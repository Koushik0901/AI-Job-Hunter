"""
scrape.py — CLI entry point for the ML/AI/DS daily job scraper.

Usage:
    uv run python src/scrape.py                        # standard daily run
    uv run python src/scrape.py --no-location-filter   # show all title-matched jobs worldwide
    uv run python src/scrape.py --no-enrich            # skip description fetching (faster)
    uv run python src/scrape.py --no-notify            # skip Telegram notification
    uv run python src/scrape.py --no-enrich-llm        # skip LLM enrichment even if API key is set
    uv run python src/scrape.py --enrich-backfill      # enrich unenriched/failed jobs in DB, then exit
    uv run python src/scrape.py --check cohere         # discover which ATS a company uses
    uv run python src/scrape.py --db /path/to/jobs.db  # use a custom database path
    uv run python src/scrape.py --config /path/to/companies.yaml
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
import yaml
from rich import box
from rich.console import Console
from rich.table import Table

from db import init_db, load_unenriched_jobs, save_jobs
from enrich import run_enrichment_pipeline
from fetchers import (
    _extract_json_array_from_html,
    enrich_descriptions,
    fetch_ashby,
    fetch_greenhouse,
    fetch_lever,
    fetch_workable,
    normalize_ashby,
    normalize_greenhouse,
    normalize_lever,
    normalize_workable,
)
from notify import _load_dotenv, notify_new_jobs

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Title filter keywords
# ---------------------------------------------------------------------------
TITLE_INCLUDE = [
    "machine learning",
    "ml engineer",
    "mlops",
    "ml ops",
    "applied ml",
    "ai engineer",
    "applied scientist",
    "data scientist",
    "data science",
    "research scientist",
    "nlp",
    "llm",
    "computer vision",
    "generative ai",
]

TITLE_EXCLUDE = [
    "sales",
    "recruiter",
    "marketing",
    "legal",
    "hr ",
    "designer",
    "customer success",
    "director",
    "vp ",
    "principal staff",
]

# ---------------------------------------------------------------------------
# Title / location filters
# ---------------------------------------------------------------------------

def passes_title_filter(title: str) -> bool:
    t = title.lower()
    has_include = any(kw in t for kw in TITLE_INCLUDE)
    has_exclude = any(kw in t for kw in TITLE_EXCLUDE)
    return has_include and not has_exclude


def passes_location_filter(location: str) -> bool:
    """
    Accept if:
    - location is empty/null (unknown → let through)
    - contains 'canada'
    - contains 'remote' with no restrictive country qualifier (or with CA/US qualifier)
    - common remote-friendly patterns
    """
    if not location:
        return True

    loc = location.lower().strip()

    if "canada" in loc:
        return True

    if "remote" in loc:
        blocked_countries = [
            "uk", "united kingdom", "europe", "eu ", "germany", "france",
            "australia", "india", "brazil", "japan", "singapore", "mexico",
        ]
        if any(bc in loc for bc in blocked_countries):
            return False
        return True

    if "anywhere" in loc:
        return True

    if loc in ("united states", "usa", "us"):
        return False

    return False


# ---------------------------------------------------------------------------
# ATS dispatch table
# ---------------------------------------------------------------------------

FETCHERS = {
    "greenhouse": (fetch_greenhouse, normalize_greenhouse),
    "lever":      (fetch_lever,      normalize_lever),
    "ashby":      (fetch_ashby,      normalize_ashby),
    "workable":   (fetch_workable,   normalize_workable),
}


def _extract_slug(ats_url: str, ats_type: str) -> str:
    """Pull the board token / company slug out of an ATS API URL."""
    parts = [p for p in urlparse(ats_url).path.strip("/").split("/") if p]
    if not parts:
        return ""
    ats = ats_type.lower()
    if ats == "greenhouse":
        return parts[-2] if len(parts) >= 2 else parts[-1]
    if ats == "workable":
        if "accounts" in parts:
            idx = parts.index("accounts")
            if idx + 1 < len(parts):
                return parts[idx + 1]
    return parts[-1]


def load_companies(config_path: Path) -> list[dict[str, Any]]:
    """Load companies.yaml and return enabled company entries as a flat list."""
    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if "companies" in data and isinstance(data["companies"], list):
        return [c for c in data["companies"] if c.get("enabled", True)]

    # Legacy format: {greenhouse: [slug, ...], lever: [...], ...}
    entries = []
    url_templates = {
        "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
        "lever":      "https://api.lever.co/v0/postings/{slug}",
        "ashby":      "https://jobs.ashbyhq.com/{slug}",
        "workable":   "https://apply.workable.com/api/v3/accounts/{slug}/jobs",
    }
    for ats_type, slugs in data.items():
        if not isinstance(slugs, list):
            continue
        tmpl = url_templates.get(ats_type, "")
        for slug in slugs:
            entries.append({
                "name": slug,
                "ats_type": ats_type,
                "ats_url": tmpl.format(slug=slug),
                "enabled": True,
            })
    return entries


def scrape_all(
    companies: list[dict[str, Any]],
    apply_location_filter: bool = True,
    enrich: bool = True,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    raw_map: dict[str, dict[str, Any]] = {}
    console = Console(stderr=True)

    for comp in companies:
        ats_type = comp.get("ats_type", "").lower()
        name = comp.get("name", "")
        ats_url = comp.get("ats_url", "")

        if ats_type not in FETCHERS:
            console.print(f"  [yellow]Skipping {name}: unknown ats_type '{ats_type}'[/yellow]")
            continue

        fetcher, normalizer = FETCHERS[ats_type]
        slug = _extract_slug(ats_url, ats_type)

        console.print(f"  [dim]Fetching {ats_type}:{slug} ({name})...[/dim]", end="")
        try:
            raw_jobs = fetcher(slug)
            console.print(f" [green]{len(raw_jobs)} jobs[/green]")
        except Exception as e:
            console.print(f" [red]ERROR: {e}[/red]")
            continue

        for raw in raw_jobs:
            job = normalizer(raw, name)

            if ats_type == "greenhouse":
                job["_board_token"] = slug
                job["_job_id"] = str(raw.get("id", ""))
            elif ats_type == "ashby":
                job["_org_slug"] = slug
                job["_job_id"] = str(raw.get("id", ""))
            elif ats_type == "workable":
                job["_account_slug"] = slug
                job["_shortcode"] = str(raw.get("shortcode", ""))

            url = job.get("url", "")
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
                if ats_type == "lever":
                    raw_map[url] = raw

            if not passes_title_filter(job["title"]):
                continue

            if apply_location_filter and not passes_location_filter(job["location"]):
                continue

            results.append(job)

    results.sort(key=lambda j: j.get("posted") or "", reverse=True)

    if enrich and results:
        console.print(f"\n[dim]Fetching descriptions for {len(results)} jobs...[/dim]")
        enrich_descriptions(results, raw_map)

    return results


# ---------------------------------------------------------------------------
# Company discovery (--check)
# ---------------------------------------------------------------------------

_ATS_PROBES: list[tuple[str, str, str, Any]] = [
    (
        "greenhouse",
        "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
        "GET",
        lambda r: r.status_code == 200 and "jobs" in r.json(),
    ),
    (
        "lever",
        "https://api.lever.co/v0/postings/{slug}",
        "GET",
        lambda r: r.status_code == 200 and isinstance(r.json(), list),
    ),
    (
        "ashby",
        "https://jobs.ashbyhq.com/{slug}",
        "GET",
        lambda r: r.status_code == 200 and "jobPostings" in r.text,
    ),
    (
        "workable",
        "https://apply.workable.com/api/v3/accounts/{slug}/jobs",
        "POST",
        lambda r: r.status_code == 200,
    ),
]


def check_company(slug: str) -> None:
    """Probe each ATS to see if `slug` has a live job board."""
    console = Console()
    console.print(f"\n[bold]Checking ATS boards for slug:[/bold] [cyan]{slug}[/cyan]\n")

    found_any = False
    for ats_name, url_tmpl, method, success_test in _ATS_PROBES:
        url = url_tmpl.format(slug=slug)
        console.print(f"  {ats_name:12s} {url} ... ", end="")
        try:
            if method == "POST":
                resp = requests.post(url, json={}, timeout=15)
            else:
                resp = requests.get(url, timeout=15)

            if success_test(resp):
                job_count = _probe_job_count(resp, ats_name)
                console.print(f"[bold green]FOUND[/bold green] ({job_count} jobs)")
                found_any = True
            else:
                console.print(f"[dim]not found[/dim] (HTTP {resp.status_code})")
        except requests.RequestException as e:
            console.print(f"[red]error[/red] ({e})")

    if not found_any:
        console.print(
            f"\n[yellow]No ATS board found for slug '{slug}'.[/yellow] "
            "Try a different spelling or check the company's careers page."
        )
    else:
        console.print(
            f"\n[dim]To add to companies.yaml, copy the matching entry above.[/dim]"
        )


def _probe_job_count(resp: requests.Response, ats_name: str) -> int:
    """Best-effort job count from a probe response."""
    try:
        data = resp.json()
        if ats_name == "greenhouse":
            return len(data.get("jobs", []))
        if ats_name == "lever":
            return len(data) if isinstance(data, list) else 0
        if ats_name == "workable":
            return len(data.get("results", [])) if isinstance(data, dict) else 0
    except Exception:
        pass
    if ats_name == "ashby":
        jobs = _extract_json_array_from_html(resp.text, "jobPostings")
        return len(jobs)
    return 0


# ---------------------------------------------------------------------------
# Rich table output
# ---------------------------------------------------------------------------

def render_table(jobs: list[dict[str, Any]], limit: int) -> None:
    console = Console()
    displayed = jobs[:limit]

    table = Table(
        title=f"ML/AI/DS Job Listings ({len(displayed)} shown of {len(jobs)} matched)",
        box=box.ROUNDED,
        show_lines=False,
        highlight=True,
    )
    table.add_column("Company", style="green", no_wrap=True, min_width=12)
    table.add_column("Title", style="cyan", min_width=25, max_width=45)
    table.add_column("Location", min_width=14, max_width=28)
    table.add_column("Posted", min_width=10, max_width=10, no_wrap=True)
    table.add_column("URL", min_width=20, max_width=60, no_wrap=True)

    for job in displayed:
        url = job.get("url", "")
        display_url = url if len(url) <= 60 else url[:57] + "..."
        table.add_row(
            job.get("company", ""),
            job.get("title", ""),
            job.get("location", ""),
            job.get("posted", "")[:10],
            display_url,
        )

    console.print(table)
    if len(jobs) > limit:
        console.print(
            f"[dim]Showing first {limit} of {len(jobs)} results. "
            f"Use --limit to show more.[/dim]"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape ML/AI/Data Science jobs from ATS platforms."
    )
    parser.add_argument(
        "--config", "-c",
        default=None,
        help="Path to companies.yaml (default: companies.yaml in the current directory)",
    )
    parser.add_argument(
        "--no-location-filter",
        action="store_true",
        help="Skip location filtering — show all title-matched jobs",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        metavar="N",
        help="Maximum rows to display (default: 50)",
    )
    parser.add_argument(
        "--check",
        metavar="SLUG",
        default=None,
        help=(
            "Probe each ATS platform for the given slug and report which "
            "boards have a live job page (e.g. --check cohere)"
        ),
    )
    parser.add_argument(
        "--db",
        default=None,
        metavar="PATH",
        help="Local SQLite file path (default: jobs.db in current directory). Ignored if SQLITECLOUD_URL is set.",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip fetching full job descriptions (faster, no description stored)",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="Skip Telegram notification even if TELEGRAM_TOKEN/TELEGRAM_CHAT_ID are set",
    )
    parser.add_argument(
        "--no-enrich-llm",
        action="store_true",
        help="Skip LLM enrichment even if OPENROUTER_API_KEY is set",
    )
    parser.add_argument(
        "--enrich-backfill",
        action="store_true",
        help="Enrich all unenriched/failed jobs in the DB, then exit (no scraping)",
    )
    args = parser.parse_args()

    # Load .env from the current working directory (project root)
    _load_dotenv(Path.cwd() / ".env")

    if args.check:
        check_company(args.check)
        return

    # Resolve DB URL
    cloud_url = os.getenv("SQLITECLOUD_URL", "")
    if cloud_url:
        db_url = cloud_url
        db_label = "SQLite Cloud"
    elif args.db:
        db_url = args.db
        db_label = args.db
    else:
        db_url = str(Path.cwd() / "jobs.db")
        db_label = db_url

    # LLM config
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model = os.getenv("ENRICHMENT_MODEL", "google/gemma-3-12b-it")

    console = Console(stderr=True)

    # --enrich-backfill: enrich unenriched/failed jobs, then exit
    if args.enrich_backfill:
        conn = init_db(db_url)
        jobs_to_enrich = load_unenriched_jobs(conn)
        console.print(
            f"[bold]Backfill:[/bold] {len(jobs_to_enrich)} job(s) to enrich in {db_label}"
        )
        if not jobs_to_enrich:
            console.print("[dim]Nothing to enrich.[/dim]")
        elif not openrouter_api_key:
            console.print("[yellow]OPENROUTER_API_KEY not set — cannot enrich.[/yellow]")
        else:
            run_enrichment_pipeline(jobs_to_enrich, conn, openrouter_api_key, openrouter_model, console)
        conn.close()
        return

    # Normal daily scrape flow
    if args.config:
        config_path = Path(args.config)
    else:
        config_path = Path.cwd() / "companies.yaml"

    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    console.print(f"[bold]Loading companies from[/bold] {config_path}")

    companies = load_companies(config_path)
    ats_counts = {}
    for c in companies:
        ats_counts[c.get("ats_type", "unknown")] = ats_counts.get(c.get("ats_type", "unknown"), 0) + 1
    console.print(
        f"[bold]Scraping {len(companies)} companies across "
        f"{len(ats_counts)} ATS platforms...[/bold]\n"
    )

    apply_loc = not args.no_location_filter
    if not apply_loc:
        console.print("[yellow]Location filter disabled — showing all title-matched jobs[/yellow]\n")

    jobs = scrape_all(
        companies,
        apply_location_filter=apply_loc,
        enrich=not args.no_enrich,
    )

    console.print(f"\n[bold green]Done.[/bold green] Found {len(jobs)} matching jobs.\n")

    if not jobs:
        console.print("[yellow]No jobs matched the filters.[/yellow]")
        return

    render_table(jobs, limit=args.limit)

    conn = init_db(db_url)
    new_count, updated_count, new_jobs = save_jobs(conn, jobs)
    console.print(
        f"\n[bold]Database:[/bold] {db_label}  "
        f"[green]{new_count} new[/green], [dim]{updated_count} updated[/dim]"
    )

    # Telegram notification
    if not args.no_notify and new_jobs:
        token = os.getenv("TELEGRAM_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if token and chat_id:
            notify_new_jobs(new_jobs, token, chat_id, console)
        else:
            console.print(
                "[dim]Telegram not configured — set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID in .env[/dim]"
            )
    elif not new_jobs:
        console.print("[dim]No new jobs — no Telegram notification sent.[/dim]")

    # LLM enrichment on new jobs only
    if new_jobs and not args.no_enrich_llm and openrouter_api_key:
        run_enrichment_pipeline(new_jobs, conn, openrouter_api_key, openrouter_model, console)

    conn.close()


if __name__ == "__main__":
    main()
