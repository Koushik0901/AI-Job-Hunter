from __future__ import annotations

import os
from pathlib import Path

from rich.console import Console

from db import (
    get_candidate_profile,
    init_db,
    load_enabled_company_sources,
    load_enrichments_for_urls,
    load_jobs_for_jd_reformat,
    load_unenriched_jobs,
    save_jobs,
)
from enrich import run_description_reformat_pipeline, run_enrichment_pipeline
from match_score import compute_match_score
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


def _resolve_db():
    turso_url = os.getenv("TURSO_URL", "")
    turso_token = os.getenv("TURSO_AUTH_TOKEN", "")
    if turso_url:
        return turso_url, turso_token, "Turso"
    return str(Path.cwd() / "jobs.db"), "", str(Path.cwd() / "jobs.db")


def _env_or_default(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    cleaned = value.strip()
    return cleaned or default


def run(args) -> None:
    db_url, db_auth_token, db_label = _resolve_db()
    if args.db and not os.getenv("TURSO_URL", ""):
        db_url = args.db
        db_label = args.db
    conn = init_db(db_url, db_auth_token)
    console = Console(stderr=True)

    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model = _env_or_default("ENRICHMENT_MODEL", "openai/gpt-oss-120b")
    description_format_model = _env_or_default("DESCRIPTION_FORMAT_MODEL", "openai/gpt-oss-20b:paid")
    if not (os.getenv("DESCRIPTION_FORMAT_MODEL") or "").strip():
        console.print(
            f"[yellow]DESCRIPTION_FORMAT_MODEL missing/empty; using default: {description_format_model}[/yellow]"
        )

    if args.enrich_backfill or args.re_enrich_all or args.jd_reformat_missing or args.jd_reformat_all:
        if args.jd_reformat_missing or args.jd_reformat_all:
            jobs_to_enrich = load_jobs_for_jd_reformat(conn, missing_only=args.jd_reformat_missing)
            label = "JD reformat missing" if args.jd_reformat_missing else "JD reformat all"
            console.print(f"[bold]{label}:[/bold] {len(jobs_to_enrich)} job(s) to process in {db_label}")
            if not jobs_to_enrich:
                console.print("[dim]Nothing to process.[/dim]")
            elif not openrouter_api_key:
                console.print("[yellow]OPENROUTER_API_KEY not set - cannot run JD reformat.[/yellow]")
            else:
                run_description_reformat_pipeline(
                    jobs_to_enrich,
                    conn,
                    openrouter_api_key,
                    description_format_model,
                    console,
                )
            conn.close()
            return

        if args.re_enrich_all:
            jobs_to_enrich = load_unenriched_jobs(conn, force=True)
            label = "Re-enrich all"
        else:
            jobs_to_enrich = load_unenriched_jobs(conn, force=False)
            label = "Enrich backfill"
        console.print(f"[bold]{label}:[/bold] {len(jobs_to_enrich)} job(s) to enrich in {db_label}")
        if not jobs_to_enrich:
            console.print("[dim]Nothing to enrich.[/dim]")
        elif not openrouter_api_key:
            console.print("[yellow]OPENROUTER_API_KEY not set - cannot enrich.[/yellow]")
        else:
            run_enrichment_pipeline(
                jobs_to_enrich,
                conn,
                openrouter_api_key,
                openrouter_model,
                description_format_model,
                console,
            )
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

    profile = get_candidate_profile(conn)
    url_to_enrichment = load_enrichments_for_urls(conn, [j.get("url", "") for j in jobs if j.get("url")])
    for job in jobs:
        job_enrichment = url_to_enrichment.get(job.get("url", ""), {})
        match = compute_match_score({"title": job.get("title", ""), "enrichment": job_enrichment}, profile)
        job["match_score"] = match["score"]
        job["match_band"] = match["band"]

    if args.sort_by == "match":
        jobs.sort(key=lambda j: int(j.get("match_score", 0)), reverse=True)
    else:
        jobs.sort(key=lambda j: j.get("posted") or "", reverse=True)

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
        run_enrichment_pipeline(
            new_jobs,
            conn,
            openrouter_api_key,
            openrouter_model,
            description_format_model,
            console,
        )

    conn.close()
