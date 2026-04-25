#!/usr/bin/env python3
"""
Record ATS API response fixtures for regression tests.

For each ATS, finds the first enabled company in DB with >= 1 job and saves
the raw HTTP response body to tests/fixtures/<ats>_<slug>.(json|html).

Run after fixing fetchers. Re-run any time to refresh fixtures.

Usage:
    uv run python scripts/record_fixtures.py
"""
from __future__ import annotations

import os
import sys
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

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
HTML_ATS = {"ashby", "teamtailor"}


def _resolve_conn():
    turso_url = os.getenv("TURSO_URL", "")
    turso_token = os.getenv("TURSO_AUTH_TOKEN", "")
    db_path = turso_url if turso_url else str(Path.cwd() / "jobs.db")
    return init_db(db_path, turso_token)


def main() -> None:
    console = Console()
    FIXTURES_DIR.mkdir(exist_ok=True)

    conn = _resolve_conn()
    all_rows = list_company_sources(conn, enabled_only=True)
    conn.close()

    by_ats: dict[str, list[dict]] = {}
    for row in all_rows:
        by_ats.setdefault(row["ats_type"], []).append(row)

    probe_url_map = {
        ats_name: (url_tmpl, method)
        for ats_name, url_tmpl, method, _ in _ATS_PROBES
    }
    probe_check_map = {
        ats_name: success_test
        for ats_name, _, _, success_test in _ATS_PROBES
    }

    for ats in sorted(by_ats):
        if ats not in probe_url_map:
            console.print(f"[dim]skip {ats} -- no probe defined[/dim]")
            continue

        url_tmpl, method = probe_url_map[ats]
        success_test = probe_check_map[ats]
        found = False

        for row in by_ats[ats]:
            slug = row["slug"]
            url = url_tmpl.format(slug=slug)
            try:
                resp = _send_probe_request(method, url, ats)
                if not success_test(resp):
                    continue
                if probe_job_count(resp, ats) == 0:
                    continue
                ext = "html" if ats in HTML_ATS else "json"
                filename = f"{ats}_{slug}.{ext}"
                FIXTURES_DIR.joinpath(filename).write_text(resp.text, encoding="utf-8")
                console.print(
                    f"[green]Recorded[/green]  {filename}"
                    f"  ({probe_job_count(resp, ats)} jobs)  -- {row['name']}"
                )
                found = True
                break
            except Exception as exc:
                console.print(f"  [dim]skip {slug}: {type(exc).__name__}: {exc}[/dim]")

        if not found:
            console.print(
                f"[yellow]No OK slug found for {ats}[/yellow] "
                "-- fix the fetcher first, then re-run"
            )


if __name__ == "__main__":
    main()
