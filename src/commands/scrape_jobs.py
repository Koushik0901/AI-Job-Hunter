from __future__ import annotations

import os
from pathlib import Path

from rich.console import Console

from db import init_db, load_enabled_company_sources, load_unenriched_jobs, save_jobs
from enrich import run_enrichment_pipeline
from notify import notify_new_jobs
from services.scrape_service import render_jobs_table, scrape_all


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

    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model = os.getenv("ENRICHMENT_MODEL", "openai/gpt-oss-120b")

    if args.enrich_backfill or args.re_enrich_all:
        force = args.re_enrich_all
        jobs_to_enrich = load_unenriched_jobs(conn, force=force)
        label = "Re-enrich all" if force else "Backfill"
        console.print(f"[bold]{label}:[/bold] {len(jobs_to_enrich)} job(s) to enrich in {db_label}")
        if not jobs_to_enrich:
            console.print("[dim]Nothing to enrich.[/dim]")
        elif not openrouter_api_key:
            console.print("[yellow]OPENROUTER_API_KEY not set - cannot enrich.[/yellow]")
        else:
            run_enrichment_pipeline(jobs_to_enrich, conn, openrouter_api_key, openrouter_model, console)
        conn.close()
        return

    companies = load_enabled_company_sources(conn)
    if not companies:
        console.print(
            "[red]No enabled company sources found in DB.[/red] "
            "Add companies with `uv run python src/add_company.py \"Company Name\"` "
            "or import from community lists via `uv run python src/cli.py sources import`."
        )
        conn.close()
        raise SystemExit(1)

    ats_counts = {}
    for c in companies:
        ats_counts[c.get("ats_type", "unknown")] = ats_counts.get(c.get("ats_type", "unknown"), 0) + 1
    console.print(
        f"[bold]Scraping {len(companies)} companies across {len(ats_counts)} ATS platforms...[/bold]\n"
    )

    jobs = scrape_all(
        companies,
        apply_location_filter=not args.no_location_filter,
        enrich=not args.no_enrich,
    )

    console.print(f"\n[bold green]Done.[/bold green] Found {len(jobs)} matching jobs.\n")
    if not jobs:
        console.print("[yellow]No jobs matched the filters.[/yellow]")
        conn.close()
        return

    render_jobs_table(jobs, limit=args.limit)
    new_count, updated_count, new_jobs = save_jobs(conn, jobs)
    console.print(
        f"\n[bold]Database:[/bold] {db_label}  [green]{new_count} new[/green], [dim]{updated_count} updated[/dim]"
    )

    if not args.no_notify and new_jobs:
        token = os.getenv("TELEGRAM_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if token and chat_id:
            notify_new_jobs(new_jobs, token, chat_id, console)
        else:
            console.print("[dim]Telegram not configured - set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID[/dim]")
    elif not new_jobs:
        console.print("[dim]No new jobs - no Telegram notification sent.[/dim]")

    if new_jobs and not args.no_enrich_llm and openrouter_api_key:
        run_enrichment_pipeline(new_jobs, conn, openrouter_api_key, openrouter_model, console)

    conn.close()
