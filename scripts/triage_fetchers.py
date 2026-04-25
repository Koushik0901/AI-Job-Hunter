#!/usr/bin/env python3
"""
Triage fetchers: sample up to 10 companies per ATS from DB, probe concurrently, report.

Usage:
    uv run python scripts/triage_fetchers.py
"""
from __future__ import annotations

import os
import random
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_job_hunter.env_utils import load_dotenv  # noqa: E402

load_dotenv()

from ai_job_hunter.db import init_db, list_company_sources  # noqa: E402
from ai_job_hunter.services.probe_service import (  # noqa: E402
    _ATS_PROBES,
    _send_probe_request,
    probe_job_count,
)
from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

SAMPLE_SIZE = 10
STATUS_STYLE = {"OK": "bold green", "EMPTY": "yellow", "ERROR": "bold red", "SKIP": "dim"}


def _resolve_conn():
    turso_url = os.getenv("TURSO_URL", "")
    turso_token = os.getenv("TURSO_AUTH_TOKEN", "")
    db_path = turso_url if turso_url else str(Path.cwd() / "jobs.db")
    return init_db(db_path, turso_token)


def probe_one(row: dict, probe_map: dict) -> dict:
    ats = row["ats_type"]
    slug = row["slug"]
    name = row["name"]
    params = probe_map.get(ats)
    if not params:
        return {"ats": ats, "name": name, "slug": slug, "status": "SKIP", "jobs": 0, "note": "no probe defined"}
    url_tmpl, method, success_test = params
    url = url_tmpl.format(slug=slug)
    try:
        resp = _send_probe_request(method, url, ats)
        if success_test(resp):
            jobs = probe_job_count(resp, ats)
            status = "OK" if jobs else "EMPTY"
            return {"ats": ats, "name": name, "slug": slug, "status": status, "jobs": jobs, "note": ""}
        return {"ats": ats, "name": name, "slug": slug, "status": "ERROR", "jobs": 0,
                "note": f"HTTP {resp.status_code}"}
    except Exception as exc:
        note = f"{type(exc).__name__}: {str(exc)[:60]}"
        return {"ats": ats, "name": name, "slug": slug, "status": "ERROR", "jobs": 0, "note": note}


def main() -> None:
    console = Console()
    conn = _resolve_conn()
    all_rows = list_company_sources(conn, enabled_only=False)
    conn.close()

    if not all_rows:
        console.print("[yellow]No company sources in DB. Run 'uv run ai-job-hunter sources import' first.[/yellow]")
        return

    by_ats: dict[str, list[dict]] = {}
    for row in all_rows:
        by_ats.setdefault(row["ats_type"], []).append(row)

    sample: list[dict] = []
    for ats in sorted(by_ats):
        picked = random.sample(by_ats[ats], min(SAMPLE_SIZE, len(by_ats[ats])))
        sample.extend(picked)

    probe_map = {
        ats_name: (url_tmpl, method, success_test)
        for ats_name, url_tmpl, method, success_test in _ATS_PROBES
    }

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = {ex.submit(probe_one, row, probe_map): row for row in sample}
        for fut in as_completed(futures):
            results.append(fut.result())

    results.sort(key=lambda r: (r["ats"], r["name"].lower()))

    table = Table(title=f"Fetcher triage -- {len(sample)} companies sampled", show_header=True)
    table.add_column("ATS", style="cyan")
    table.add_column("Company")
    table.add_column("Slug", style="dim")
    table.add_column("Status")
    table.add_column("Jobs", justify="right")
    table.add_column("Note", style="dim")

    for r in results:
        style = STATUS_STYLE.get(r["status"], "")
        jobs_str = str(r["jobs"]) if r["status"] in ("OK", "EMPTY") else "-"
        table.add_row(
            r["ats"], r["name"], r["slug"],
            f"[{style}]{r['status']}[/{style}]",
            jobs_str, r["note"],
        )

    console.print(table)
    console.print()

    by_ats_results: dict[str, list[dict]] = {}
    for r in results:
        by_ats_results.setdefault(r["ats"], []).append(r)

    for ats in sorted(by_ats_results):
        counts = Counter(r["status"] for r in by_ats_results[ats])
        total = len(by_ats_results[ats])
        console.print(
            f"  [cyan]{ats:<14}[/cyan] "
            f"[green]{counts.get('OK', 0)} OK[/green]  .  "
            f"[yellow]{counts.get('EMPTY', 0)} empty[/yellow]  .  "
            f"[red]{counts.get('ERROR', 0)} errors[/red]  "
            f"of {total} sampled"
        )

    console.print()
    console.print("[dim]HN ('hn_hiring') is not in company_sources -- not included above.[/dim]")


if __name__ == "__main__":
    main()
