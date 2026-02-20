"""
add_company.py — Discover which ATS platform a company uses and add it to companies.yaml.

Usage:
    uv run python src/add_company.py "Hugging Face"
    uv run python src/add_company.py "Scale AI" --slug scaleai
    uv run python src/add_company.py "OpenAI" --slug openai --add
    uv run python src/add_company.py "Toyota" --slug tri --slug toyota-research
"""
from __future__ import annotations

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml
from rich.console import Console
from rich.table import Table

# src/ is already in sys.path when running this script directly, but make it
# explicit so imports work if invoked from a different working directory.
sys.path.insert(0, str(Path(__file__).parent))

from notify import _load_dotenv
from scrape import _ATS_PROBES, _probe_job_count

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

def _probe_all(slugs: list[str]) -> list[dict]:
    """Probe all 5 ATS platforms for every slug concurrently. Returns hit dicts."""

    def _probe_one(slug: str, ats_name: str, url_tmpl: str, method: str, success_test) -> dict | None:
        url = url_tmpl.format(slug=slug)
        try:
            if method == "POST":
                resp = requests.post(url, json={}, timeout=15)
            else:
                resp = requests.get(url, timeout=15)
            if success_test(resp):
                count = _probe_job_count(resp, ats_name)
                canonical = _ATS_URL_TEMPLATES[ats_name].format(slug=slug)
                return {"slug": slug, "ats": ats_name, "ats_url": canonical, "jobs": count}
        except requests.RequestException:
            pass
        return None

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = [
            ex.submit(_probe_one, slug, ats_name, url_tmpl, method, success_test)
            for slug in slugs
            for ats_name, url_tmpl, method, success_test in _ATS_PROBES
        ]
        for fut in as_completed(futures):
            hit = fut.result()
            if hit:
                results.append(hit)

    return results


# ---------------------------------------------------------------------------
# YAML helpers
# ---------------------------------------------------------------------------

def _find_in_yaml(slug: str, ats_url: str, config_path: Path) -> str | None:
    """Return existing company name if this slug or ats_url is already in yaml, else None.

    Checks two ways:
    - Exact ats_url match (same platform, same company)
    - Slug appears as a URL path segment in any existing entry (same company, different platform)
    """
    if not config_path.exists():
        return None
    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    slug_lower = slug.lower()
    for c in data.get("companies", []):
        existing_url = c.get("ats_url", "")
        if existing_url == ats_url:
            return c.get("name", slug)
        parts = [p.lower() for p in urlparse(existing_url).path.strip("/").split("/") if p]
        if slug_lower in parts:
            return c.get("name", slug)


def _append_entry(name: str, ats_type: str, ats_url: str, config_path: Path) -> None:
    with config_path.open("a", encoding="utf-8") as f:
        f.write(f"  - name: {name}\n")
        f.write(f"    ats_type: {ats_type}\n")
        f.write(f"    ats_url: {ats_url}\n")
        f.write(f"    enabled: true\n")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover ATS platform for a company and add it to companies.yaml.",
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
    parser.add_argument(
        "--config", default=None,
        help="Path to companies.yaml (default: companies.yaml in current directory)",
    )
    args = parser.parse_args()

    _load_dotenv(Path.cwd() / ".env")

    config_path = Path(args.config) if args.config else Path.cwd() / "companies.yaml"
    console = Console()

    # 1. Build slug candidates
    candidates = _candidate_slugs(args.company)
    for s in args.slug:
        if s not in candidates:
            candidates.append(s)

    console.print(f"\n[dim]Trying slugs:[/dim] {', '.join(candidates)}\n")

    # 2. Probe concurrently
    hits = _probe_all(candidates)

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

    # 5. Filter out entries already in companies.yaml (by URL or by slug in existing URL)
    new_hits: list[dict] = []
    for h in real_hits:
        existing_name = _find_in_yaml(h["slug"], h["ats_url"], config_path)
        if existing_name:
            console.print(
                f"[dim]  Already in companies.yaml as '{existing_name}': {h['ats_url']}[/dim]"
            )
        else:
            new_hits.append(h)

    if not new_hits:
        console.print("[dim]All found entries are already in companies.yaml.[/dim]")
        return

    # 6. Decide which entries to add
    to_add: list[dict] = []

    if args.add:
        to_add = new_hits

    elif len(new_hits) == 1:
        h = new_hits[0]
        answer = console.input(
            f"\nAdd [cyan]{h['slug']}[/cyan] ([green]{h['ats']}[/green]) to companies.yaml? [y/N] "
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

    # 7. Append chosen entries to companies.yaml
    if not to_add:
        console.print("[dim]Nothing added.[/dim]")
        return

    for h in to_add:
        _append_entry(args.company, h["ats"], h["ats_url"], config_path)
        console.print(
            f"[green]Added[/green] {args.company} "
            f"([green]{h['ats']}[/green], slug=[cyan]{h['slug']}[/cyan]) "
            f"-> {config_path.name}"
        )


if __name__ == "__main__":
    main()
