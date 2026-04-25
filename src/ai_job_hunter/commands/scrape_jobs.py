from __future__ import annotations

import os
from pathlib import Path

from rich.console import Console

from ai_job_hunter.db import init_db, list_overdue_staging_jobs
from ai_job_hunter.env_utils import env_or_default
from ai_job_hunter.notify import notify_new_jobs, notify_overdue_staging_jobs
from ai_job_hunter.services.scrape_service import render_jobs_table
from ai_job_hunter.services.workspace_operation_service import execute_workspace_operation


def register(subparsers) -> None:
    parser = subparsers.add_parser("scrape", help="Run job scraping pipeline")
    parser.add_argument("--db", default=None, metavar="PATH", help="Local SQLite path (default: jobs.db). Ignored if TURSO_URL is set.")
    parser.add_argument("--no-location-filter", action="store_true", help="Skip location filtering")
    parser.add_argument("--limit", type=int, default=50, metavar="N", help="Max rows to display (default: 50)")
    parser.add_argument("--no-enrich", action="store_true", help="Skip fetching full job descriptions")
    parser.add_argument("--no-notify", action="store_true", help="Skip Telegram notification")
    parser.add_argument("--no-enrich-llm", action="store_true", help="Skip LLM enrichment")
    parser.add_argument("--enrich-backfill", action="store_true", help="Enrich unenriched/failed jobs in DB and exit")
    parser.add_argument("--re-enrich-all", action="store_true", help="Re-enrich all jobs with descriptions and exit")
    parser.add_argument(
        "--jd-reformat-missing",
        action="store_true",
        help="Reformat job descriptions for enriched rows missing formatted_description, then exit",
    )
    parser.add_argument(
        "--jd-reformat-all",
        action="store_true",
        help="Reformat job descriptions for all enriched rows (enrichment_status=ok), then exit",
    )
    parser.add_argument("--sort-by", choices=("match", "posted"), default="match", help="Display ordering for scraped jobs")
    parser.add_argument(
        "--blurb-backfill",
        action="store_true",
        help="Generate LLM 'Kenji's read' blurbs for the top viable unapplied jobs missing them, then exit",
    )
    parser.add_argument(
        "--blurb-force",
        action="store_true",
        help="With --blurb-backfill: regenerate even if a blurb already exists",
    )
    parser.add_argument(
        "--blurb-top-n",
        type=int,
        default=150,
        metavar="N",
        help="With --blurb-backfill: cap the number of jobs to blurb (default: 150)",
    )


def _resolve_db():
    turso_url = os.getenv("TURSO_URL", "")
    turso_token = os.getenv("TURSO_AUTH_TOKEN", "")
    if turso_url:
        return turso_url, turso_token, "Turso"
    return str(Path.cwd() / "jobs.db"), "", str(Path.cwd() / "jobs.db")


def run(args) -> None:
    db_url, db_auth_token, db_label = _resolve_db()
    if args.db and not os.getenv("TURSO_URL", ""):
        db_url = args.db
        db_label = args.db
    conn = init_db(db_url, db_auth_token)
    console = Console(stderr=True)
    if not (os.getenv("DESCRIPTION_FORMAT_MODEL") or "").strip():
        console.print(
            f"[yellow]DESCRIPTION_FORMAT_MODEL missing/empty; using default: {env_or_default('DESCRIPTION_FORMAT_MODEL', 'openai/gpt-oss-120b')}[/yellow]"
        )

    try:
        if args.jd_reformat_missing or args.jd_reformat_all:
            summary = execute_workspace_operation(
                conn,
                "jd_reformat",
                {"missing_only": args.jd_reformat_missing},
                console=console,
            )
            console.print(
                f"[bold]{'JD reformat missing' if args.jd_reformat_missing else 'JD reformat all'}:[/bold] "
                f"{int(summary.get('jobs_processed', 0) or 0)} job(s) processed in {db_label}"
            )
            conn.close()
            return

        if args.blurb_backfill:
            summary = execute_workspace_operation(
                conn,
                "blurb_backfill",
                {"force": bool(args.blurb_force), "top_n": int(args.blurb_top_n)},
                console=console,
            )
            console.print(
                f"[bold]Blurb backfill:[/bold] generated "
                f"{int(summary.get('blurbs_generated', 0) or 0)} blurb(s) in {db_label}"
            )
            conn.close()
            return

        if args.enrich_backfill or args.re_enrich_all:
            summary = execute_workspace_operation(
                conn,
                "re_enrich_all" if args.re_enrich_all else "enrich_backfill",
                {},
                console=console,
            )
            console.print(
                f"[bold]{'Re-enrich all' if args.re_enrich_all else 'Enrich backfill'}:[/bold] "
                f"{int(summary.get('jobs_processed', 0) or 0)} job(s) processed in {db_label}"
            )
            conn.close()
            return

        summary = execute_workspace_operation(
            conn,
            "scrape",
            {
                "no_location_filter": args.no_location_filter,
                "no_enrich": args.no_enrich,
                "no_enrich_llm": args.no_enrich_llm,
                "sort_by": args.sort_by,
                "include_jobs": True,
            },
            console=console,
        )
    except RuntimeError as error:
        console.print(f"[red]{error}[/red]")
        conn.close()
        raise SystemExit(1) from error

    jobs = list(summary.get("jobs") or [])
    new_jobs = list(summary.get("new_jobs") or [])
    overdue_staging_jobs = list_overdue_staging_jobs(conn)
    console.print(f"\n[bold green]Done.[/bold green] Found {len(jobs)} matching jobs.\n")
    if jobs:
        render_jobs_table(jobs, limit=args.limit)
    else:
        console.print("[yellow]No jobs matched the filters.[/yellow]")
    console.print(
        f"\n[bold]Database:[/bold] {db_label}  "
        f"[green]{int(summary.get('new_count', 0) or 0)} new[/green], "
        f"[dim]{int(summary.get('updated_count', 0) or 0)} updated[/dim]"
    )

    if not args.no_notify:
        token = os.getenv("TELEGRAM_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if token and chat_id:
            if new_jobs:
                notify_new_jobs(new_jobs, token, chat_id, console)
            else:
                console.print("[dim]No new jobs - no Telegram notification sent.[/dim]")
            if overdue_staging_jobs:
                notify_overdue_staging_jobs(overdue_staging_jobs, token, chat_id, console)
            else:
                console.print("[dim]No overdue staging jobs - no Telegram notification sent.[/dim]")
        else:
            console.print("[dim]Telegram not configured - set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID[/dim]")

    conn.close()
