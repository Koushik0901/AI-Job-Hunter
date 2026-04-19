"""
add_company.py — Discover which ATS platform a company uses and add it to DB.

Usage:
    uv run python -m ai_job_hunter.add_company "Example Company"
    uv run python -m ai_job_hunter.add_company "Acme Robotics" --slug acme-robotics
    uv run python -m ai_job_hunter.add_company "Example Company" --slug example-company --add
    uv run python -m ai_job_hunter.add_company "Example Company" --slug example-jobs --slug example-careers
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from ai_job_hunter.notify import _load_dotenv
from ai_job_hunter.db import init_db
from ai_job_hunter.services.company_registry_service import annotate_existing_company_sources, probe_company_sources, save_company_source

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover ATS platform for a company and add it to DB.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  uv run python src/add_company.py "Example Company"
  uv run python src/add_company.py "Acme Robotics" --slug acme-robotics
  uv run python src/add_company.py "Example Company" --slug example-company --add
  uv run python src/add_company.py "Example Company" --slug example-jobs --slug example-careers
""",
    )
    parser.add_argument("company", help="Company name or careers URL to look up (e.g. 'Example Company')")
    parser.add_argument(
        "--slug", action="append", default=[], metavar="SLUG",
        help="Extra slug to probe (repeatable); appended after auto-generated candidates",
    )
    parser.add_argument(
        "--add", action="store_true",
        help="Auto-add all new matches without prompting (non-interactive)",
    )
    parser.add_argument("--db", default=None, help="Local DB path (default: jobs.db in current directory)")
    args = parser.parse_args()

    _load_dotenv(Path.cwd() / ".env")

    turso_url = os.getenv("TURSO_URL", "")
    turso_token = os.getenv("TURSO_AUTH_TOKEN", "")
    if turso_url:
        db_url = turso_url
        db_token = turso_token
    elif args.db:
        db_url = args.db
        db_token = ""
    else:
        db_url = str(Path.cwd() / "jobs.db")
        db_token = ""
    conn = init_db(db_url, db_token)

    console = Console()

    probe = probe_company_sources(args.company, extra_slugs=args.slug)
    company_name_for_db = str(probe.get("company_name") or args.company)
    inferred = probe.get("inferred")
    if inferred:
        console.print(
            f"[dim]Detected careers URL -> ATS: {inferred['ats_type']}, slug: {inferred['slug']}[/dim]"
        )

    candidates = [str(slug) for slug in probe.get("slugs") or []]
    console.print(f"\n[dim]Trying slugs:[/dim] {', '.join(candidates)}\n")

    real_hits = annotate_existing_company_sources(conn, list(probe.get("matches") or []))
    zero_hits = list(probe.get("zero_job_matches") or [])

    if not real_hits:
        if zero_hits:
            console.print(
                f"[yellow]No boards with active job listings found for '{args.company}'.[/yellow]"
            )
            console.print(
                f"[dim]{len(zero_hits)} hit(s) with 0 jobs were suppressed "
                f"(likely SmartRecruiters/Workable false positives).[/dim]"
            )
        else:
            console.print(f"[yellow]No ATS board found for '{args.company}'.[/yellow]")
        console.print(
            "[dim]Try supplying a specific slug with --slug, "
            "or check the company's careers page URL.[/dim]"
        )
        conn.close()
        return

    table = Table(title=f"ATS boards found for '{args.company}'", show_header=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Slug", style="cyan")
    table.add_column("ATS", style="green")
    table.add_column("Jobs", justify="right")
    table.add_column("URL")
    for i, h in enumerate(real_hits, 1):
        table.add_row(str(i), h["slug"], h["ats_type"], str(h["jobs"]), h["ats_url"])
    console.print(table)

    if zero_hits:
        names = ", ".join(f"{h['ats_type']}:{h['slug']}" for h in zero_hits)
        console.print(
            f"[dim]  {len(zero_hits)} zero-job hit(s) hidden (false positives): {names}[/dim]"
        )

    # 5. Filter out entries already in DB (by URL or by slug in existing URL)
    new_hits: list[dict] = []
    for h in real_hits:
        existing_name = h.get("existing_name")
        if existing_name:
            console.print(
                f"[dim]  Already in DB as '{existing_name}': {h['ats_url']}[/dim]"
            )
        else:
            new_hits.append(h)

    if not new_hits:
        console.print("[dim]All found entries are already in DB.[/dim]")
        conn.close()
        return

    # 6. Decide which entries to add
    to_add: list[dict] = []

    if args.add:
        to_add = new_hits

    elif len(new_hits) == 1:
        h = new_hits[0]
        answer = console.input(
            f"\nAdd [cyan]{h['slug']}[/cyan] ([green]{h['ats_type']}[/green]) to DB? {escape('[y/N]')} "
        )
        if answer.strip().lower() == "y":
            to_add = [h]

    else:
        console.print("\n[bold]Multiple new matches found:[/bold]")
        for i, h in enumerate(new_hits, 1):
            console.print(f"  [dim]{i}.[/dim] {h['slug']} ({h['ats_type']})")
        console.print("  [dim]a.[/dim] All")
        console.print("  [dim]0.[/dim] None")
        answer = console.input("Select entries to add (comma-separated numbers, a, or 0): ").strip().lower()

        if answer == "a":
            to_add = new_hits
        elif answer == "0" or not answer:
            to_add = []
        else:
            indices: list[int] = []
            for part in re.split(r"[,\s]+", answer):
                try:
                    idx = int(part)
                    if 1 <= idx <= len(new_hits):
                        indices.append(idx - 1)
                except ValueError:
                    pass
            to_add = [new_hits[i] for i in indices]

    # 7. Insert chosen entries into DB
    if not to_add:
        console.print("[dim]Nothing added.[/dim]")
        conn.close()
        return

    for h in to_add:
        save_company_source(
            conn,
            {
                "name": company_name_for_db,
                "ats_type": h["ats_type"],
                "ats_url": h["ats_url"],
                "slug": h["slug"],
                "enabled": True,
                "source": "add_company",
            },
        )
        console.print(
            f"[green]Added[/green] {company_name_for_db} "
            f"([green]{h['ats_type']}[/green], slug=[cyan]{h['slug']}[/cyan]) "
            f"-> DB"
        )
    conn.close()


if __name__ == "__main__":
    main()
