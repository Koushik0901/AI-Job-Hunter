"""
add_company.py — Discover which ATS platform a company uses and add it to DB.

Usage:
    uv run python src/add_company.py "Hugging Face"
    uv run python src/add_company.py "Scale AI" --slug scaleai
    uv run python src/add_company.py "OpenAI" --slug openai --add
    uv run python src/add_company.py "Toyota" --slug tri --slug toyota-research
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

# src/ is already in sys.path when running this script directly, but make it
# explicit so imports work if invoked from a different working directory.
sys.path.insert(0, str(Path(__file__).parent))

from notify import _load_dotenv
from db import find_company_by_url_or_slug_segment, init_db, upsert_company_source
from services.probe_service import probe_all

# ---------------------------------------------------------------------------
# Canonical ATS URL templates (one per platform, no query params)
# ---------------------------------------------------------------------------

_ATS_URL_TEMPLATES: dict[str, str] = {
    "greenhouse":      "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever":           "https://api.lever.co/v0/postings/{slug}",
    "ashby":           "https://jobs.ashbyhq.com/{slug}",
    "workable":        "https://apply.workable.com/api/v3/accounts/{slug}/jobs",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{slug}/postings",
}

# Common corporate suffixes to strip when generating slug candidates
_CORPORATE_SUFFIXES = {
    "inc", "llc", "ltd", "corp", "corporation",
    "technologies", "technology", "systems", "solutions",
    "group", "labs", "software",
}


# ---------------------------------------------------------------------------
# Slug candidate generation
# ---------------------------------------------------------------------------

def _candidate_slugs(name: str) -> list[str]:
    """Generate up to ~8 slug candidates from a company name."""
    slugs: list[str] = []
    seen: set[str] = set()

    def _add(s: str) -> None:
        s = s.strip("-").strip()
        if s and s not in seen:
            seen.add(s)
            slugs.append(s)

    def _variants(base: str) -> None:
        tokens = base.lower().split()
        if not tokens:
            return
        # joined — strip non-alphanumeric entirely: "hugging face" → "huggingface"
        joined = re.sub(r"[^a-z0-9]", "", "".join(tokens))
        _add(joined)
        # hyphenated — tokens with hyphens: "hugging face" → "hugging-face"
        hyphenated = "-".join(re.sub(r"[^a-z0-9]", "", t) for t in tokens if t)
        _add(hyphenated)
        # first word only: "hugging face" → "hugging"
        first = re.sub(r"[^a-z0-9]", "", tokens[0])
        _add(first)

    _variants(name)

    # Suffix-stripped form
    tokens = name.lower().split()
    stripped = [t for t in tokens if t not in _CORPORATE_SUFFIXES]
    if stripped and stripped != tokens:
        _variants(" ".join(stripped))

    return slugs


# ---------------------------------------------------------------------------
# Concurrent ATS probing
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover ATS platform for a company and add it to DB.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  uv run python src/add_company.py "Hugging Face"
  uv run python src/add_company.py "Scale AI" --slug scaleai
  uv run python src/add_company.py "OpenAI" --slug openai --add
  uv run python src/add_company.py "Toyota" --slug tri --slug toyota-research
""",
    )
    parser.add_argument("company", help="Company name to look up (e.g. 'Hugging Face')")
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

    # 1. Build slug candidates
    candidates = _candidate_slugs(args.company)
    for s in args.slug:
        if s not in candidates:
            candidates.append(s)

    console.print(f"\n[dim]Trying slugs:[/dim] {', '.join(candidates)}\n")

    # 2. Probe concurrently
    hits = probe_all(candidates, _ATS_URL_TEMPLATES)

    # 3. Deduplicate by ats_url, sort for consistent display
    seen_urls: set[str] = set()
    unique_hits: list[dict] = []
    for h in sorted(hits, key=lambda x: (x["ats"], x["slug"])):
        if h["ats_url"] not in seen_urls:
            seen_urls.add(h["ats_url"])
            unique_hits.append(h)

    # 4. Split real hits (jobs > 0) from zero-job hits (SmartRecruiters/Workable false positives)
    real_hits = [h for h in unique_hits if h["jobs"] > 0]
    zero_hits = [h for h in unique_hits if h["jobs"] == 0]

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
        table.add_row(str(i), h["slug"], h["ats"], str(h["jobs"]), h["ats_url"])
    console.print(table)

    if zero_hits:
        names = ", ".join(f"{h['ats']}:{h['slug']}" for h in zero_hits)
        console.print(
            f"[dim]  {len(zero_hits)} zero-job hit(s) hidden (false positives): {names}[/dim]"
        )

    # 5. Filter out entries already in DB (by URL or by slug in existing URL)
    new_hits: list[dict] = []
    for h in real_hits:
        existing_name = find_company_by_url_or_slug_segment(conn, h["slug"], h["ats_url"])
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
            f"\nAdd [cyan]{h['slug']}[/cyan] ([green]{h['ats']}[/green]) to DB? [y/N] "
        )
        if answer.strip().lower() == "y":
            to_add = [h]

    else:
        console.print("\n[bold]Multiple new matches found:[/bold]")
        for i, h in enumerate(new_hits, 1):
            console.print(f"  [dim]{i}.[/dim] {h['slug']} ({h['ats']})")
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
        upsert_company_source(
            conn,
            name=args.company,
            ats_type=h["ats"],
            ats_url=h["ats_url"],
            slug=h["slug"],
            enabled=True,
            source="add_company",
        )
        console.print(
            f"[green]Added[/green] {args.company} "
            f"([green]{h['ats']}[/green], slug=[cyan]{h['slug']}[/cyan]) "
            f"-> DB"
        )
    conn.close()


if __name__ == "__main__":
    main()
