"""
scrape.py — CLI entry point for the ML/AI/DS daily job scraper.

Usage:
    uv run python src/scrape.py                        # standard daily run
    uv run python src/scrape.py --no-location-filter   # show all title-matched jobs worldwide
    uv run python src/scrape.py --no-enrich            # skip description fetching (faster)
    uv run python src/scrape.py --no-notify            # skip Telegram notification
    uv run python src/scrape.py --no-enrich-llm        # skip LLM enrichment even if API key is set
    uv run python src/scrape.py --enrich-backfill      # enrich unenriched/failed jobs in DB, then exit
    uv run python src/scrape.py --re-enrich-all        # re-enrich ALL jobs (overwrites existing), then exit
    uv run python src/scrape.py --check cohere         # discover which ATS a company uses
    uv run python src/scrape.py --db /path/to/jobs.db  # use a custom database path
    uv run python src/scrape.py --migrate-companies-from-yaml companies.yaml
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
import yaml
from rich import box
from rich.console import Console
from rich.table import Table

from db import (
    init_db,
    list_company_sources,
    load_enabled_company_sources,
    load_unenriched_jobs,
    save_jobs,
    set_company_source_enabled,
    upsert_company_source,
)
from enrich import run_enrichment_pipeline
from fetchers import (
    _extract_json_array_from_html,
    enrich_descriptions,
    fetch_ashby,
    fetch_greenhouse,
    fetch_hn_jobs,
    fetch_lever,
    fetch_smartrecruiters,
    fetch_workable,
    normalize_ashby,
    normalize_greenhouse,
    normalize_lever,
    normalize_smartrecruiters,
    normalize_workable,
)
from notify import _load_dotenv, notify_new_jobs

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _safe_text(value: Any) -> str:
    """Return a console-safe string for legacy cp1252 terminals."""
    text = str(value or "")
    try:
        text.encode("cp1252")
        return text
    except UnicodeEncodeError:
        return text.encode("cp1252", errors="replace").decode("cp1252")

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
# Canadian geography — used by the location filter below
# ---------------------------------------------------------------------------

# Full province/territory names
_CA_PROVINCES = [
    "ontario", "british columbia", "alberta", "quebec", "nova scotia",
    "new brunswick", "prince edward island", "newfoundland", "labrador",
    "newfoundland and labrador", "manitoba", "saskatchewan",
    "northwest territories", "yukon", "nunavut",
]

# Province/territory abbreviations — checked as whole tokens (not substrings)
# so "BC" doesn't match "ABC" and "ON" doesn't match "London"
_CA_ABBREVS = {"bc", "ab", "on", "qc", "ns", "nb", "pei", "nl", "mb", "sk", "nt", "yt", "nu"}

# Unambiguous Canadian cities ("london" omitted — clashes with London, UK)
_CA_CITIES = [
    "vancouver", "toronto", "calgary", "edmonton", "montreal", "ottawa",
    "winnipeg", "halifax", "victoria", "waterloo", "kitchener",
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
    - contains 'canada' or a recognizable Canadian province/city
    - contains 'remote' with no restrictive country qualifier
    - contains 'anywhere'
    """
    if not location:
        return True

    loc = location.lower().strip()

    # Explicit "Canada" mention
    if "canada" in loc:
        return True

    # Canadian province/territory full names
    if any(prov in loc for prov in _CA_PROVINCES):
        return True

    # Major Canadian cities
    if any(city in loc for city in _CA_CITIES):
        return True

    # Province/territory abbreviations — split on punctuation/whitespace so we
    # check whole tokens: "Vancouver, BC" → {"vancouver", "bc"} ✓
    #                     "ABC Corp"      → {"abc", "corp"} — no match ✓
    tokens = set(re.split(r"[\s,;|()/\-]+", loc))
    if tokens & _CA_ABBREVS:
        return True

    if "remote" in loc:
        blocked = [
            "uk", "united kingdom", "europe", "eu ", "germany", "france",
            "australia", "india", "brazil", "japan", "singapore", "mexico",
        ]
        if any(b in loc for b in blocked):
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
    "greenhouse":      (fetch_greenhouse,      normalize_greenhouse),
    "lever":           (fetch_lever,           normalize_lever),
    "ashby":           (fetch_ashby,           normalize_ashby),
    "workable":        (fetch_workable,        normalize_workable),
    "smartrecruiters": (fetch_smartrecruiters, normalize_smartrecruiters),
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
    if ats == "smartrecruiters":
        # https://api.smartrecruiters.com/v1/companies/{slug}/postings
        if "companies" in parts:
            idx = parts.index("companies")
            if idx + 1 < len(parts):
                return parts[idx + 1]
    return parts[-1]


def scrape_all(
    companies: list[dict[str, Any]],
    apply_location_filter: bool = True,
    enrich: bool = True,
    title_filter_fn=None,      # callable(title) -> bool; defaults to passes_title_filter
) -> list[dict[str, Any]]:
    _title_ok = title_filter_fn if title_filter_fn is not None else passes_title_filter
    results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    raw_map: dict[str, dict[str, Any]] = {}
    console = Console(stderr=True)

    for comp in companies:
        ats_type = comp.get("ats_type", "").lower()
        name = comp.get("name", "")
        ats_url = comp.get("ats_url", "")

        if ats_type not in FETCHERS:
            console.print(f"  [yellow]Skipping {_safe_text(name)}: unknown ats_type '{ats_type}'[/yellow]")
            continue

        fetcher, normalizer = FETCHERS[ats_type]
        slug = _extract_slug(ats_url, ats_type)

        console.print(f"  [dim]Fetching {ats_type}:{slug} ({_safe_text(name)})...[/dim]", end="")
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
            elif ats_type == "smartrecruiters":
                job["_company_slug"] = slug
                job["_job_id"] = str(raw.get("id", ""))

            url = job.get("url", "")
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
                if ats_type == "lever":
                    raw_map[url] = raw

            if not _title_ok(job["title"]):
                continue

            if apply_location_filter and not passes_location_filter(job["location"]):
                continue

            results.append(job)

    # HN "Who is Hiring" (no credentials needed — always runs)
    try:
        hn_jobs = fetch_hn_jobs()
        hn_added = 0
        for job in hn_jobs:
            if not _title_ok(job["title"]):
                continue
            if apply_location_filter and not passes_location_filter(job["location"]):
                continue
            url = job.get("url", "")
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            results.append(job)
            hn_added += 1
        console.print(f"  [green]HN Who is Hiring: {hn_added} jobs added[/green]")
    except Exception as e:
        console.print(f"  [yellow]HN fetch failed (skipping): {e}[/yellow]")

    results.sort(key=lambda j: j.get("posted") or "", reverse=True)

    if enrich and results:
        console.print(f"\n[dim]Fetching descriptions for {len(results)} jobs...[/dim]")
        enrich_descriptions(results, raw_map)

    return results


# ---------------------------------------------------------------------------
# Bulk company import (--import-companies)
# ---------------------------------------------------------------------------

# Three complementary sources:
# 1. pittcsc internships list: HTML table, many ATS URLs per row (company name in <strong>)
# 2. j-delaney easy-application: plain markdown, fewer ATS URLs but cleaner context
# 3. SimplifyJobs New Grad: HTML table, includes SmartRecruiters links
_IMPORT_SOURCES = [
    ("pittcsc", "https://raw.githubusercontent.com/pittcsc/Summer2024-Internships/dev/README.md"),
    ("j-delaney", "https://raw.githubusercontent.com/j-delaney/easy-application/master/README.md"),
    ("simplify", "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md"),
]

SIMPLIFY_NEWGRAD_URL = "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md"


def _slug_to_ats_url(slug: str, ats_type: str) -> str:
    if ats_type == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    if ats_type == "lever":
        return f"https://api.lever.co/v0/postings/{slug}"
    if ats_type == "smartrecruiters":
        return f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
    raise ValueError(f"Unknown ats_type: {ats_type}")


def _parse_companies_from_html_table(text: str) -> list[tuple[str, str, str]]:
    """
    Parse (company_name, ats_type, slug) from HTML table format used by pittcsc.
    Handles: job-boards.greenhouse.io/SLUG/jobs/ID and jobs.lever.co/SLUG
    """
    results: list[tuple[str, str, str]] = []
    seen_slugs: set[str] = set()
    for row_match in re.finditer(r'<tr>(.*?)</tr>', text, re.DOTALL):
        row = row_match.group(1)
        name_m = re.search(r'<strong><a[^>]*>([^<]+)</a></strong>', row)
        if not name_m:
            continue
        company_name = name_m.group(1).strip()
        # Greenhouse: job-boards.greenhouse.io/SLUG/ or boards.greenhouse.io/SLUG
        gh_m = re.search(
            r'(?:job-boards|boards(?:-api)?)\.greenhouse\.io/([A-Za-z0-9_-]+)', row
        )
        if gh_m:
            slug = gh_m.group(1)
            if slug not in seen_slugs:
                seen_slugs.add(slug)
                results.append((company_name, "greenhouse", slug))
        # Lever
        lv_m = re.search(r'jobs\.lever\.co/([A-Za-z0-9_-]+)', row)
        if lv_m:
            slug = lv_m.group(1)
            if slug not in seen_slugs:
                seen_slugs.add(slug)
                results.append((company_name, "lever", slug))
    return results


def _parse_companies_from_simplify(text: str) -> list[tuple[str, str, str]]:
    """
    Parse (company_name, ats_type, slug) from the SimplifyJobs New-Grad-Positions README.
    Handles Greenhouse, Lever, and SmartRecruiters links; handles '↳' sub-row continuation.
    """
    results: list[tuple[str, str, str]] = []
    seen_slugs: set[str] = set()
    last_company: str = ""

    for row_match in re.finditer(r'<tr>(.*?)</tr>', text, re.DOTALL):
        row = row_match.group(1)
        # Determine company name — strong tag or continuation arrow
        name_m = re.search(r'<strong>(?:<a[^>]*>)?([^<]+)(?:</a>)?</strong>', row)
        if name_m:
            company_name = name_m.group(1).strip()
            last_company = company_name
        else:
            # Check for continuation sub-row (↳)
            if "↳" in row or "&#8618;" in row:
                company_name = last_company
            else:
                # Try plain <a> tag in first cell
                cell_m = re.search(r'<td[^>]*>\s*<a[^>]*>([^<]{1,60})</a>', row)
                company_name = cell_m.group(1).strip() if cell_m else ""
                if company_name:
                    last_company = company_name

        if not company_name:
            continue

        # Greenhouse
        gh_m = re.search(r'(?:job-boards|boards(?:-api)?)\.greenhouse\.io/([A-Za-z0-9_-]+)', row)
        if gh_m:
            slug = gh_m.group(1)
            if slug not in seen_slugs:
                seen_slugs.add(slug)
                results.append((company_name, "greenhouse", slug))

        # Lever
        lv_m = re.search(r'jobs\.lever\.co/([A-Za-z0-9_-]+)', row)
        if lv_m:
            slug = lv_m.group(1)
            if slug not in seen_slugs:
                seen_slugs.add(slug)
                results.append((company_name, "lever", slug))

        # SmartRecruiters
        sr_m = re.search(r'apply\.smartrecruiters\.com/([A-Za-z0-9_-]+)/', row)
        if sr_m:
            slug = sr_m.group(1)
            if slug not in seen_slugs:
                seen_slugs.add(slug)
                results.append((company_name, "smartrecruiters", slug))

    return results


def _parse_companies_from_markdown(text: str) -> list[tuple[str, str, str]]:
    """
    Parse (company_name, ats_type, slug) from plain markdown format used by j-delaney.
    Guesses company name from surrounding markdown link labels.
    """
    results: list[tuple[str, str, str]] = []
    seen_slugs: set[str] = set()
    gh_pat = re.compile(r'([^\n]*boards\.greenhouse\.io/([A-Za-z0-9_-]+)[^\n]*)')
    lv_pat = re.compile(r'([^\n]*jobs\.lever\.co/([A-Za-z0-9_-]+)[^\n]*)')
    for pat, ats_type in ((gh_pat, "greenhouse"), (lv_pat, "lever")):
        for m in pat.finditer(text):
            ctx, slug = m.group(1), m.group(2)
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            name_m = re.search(r'\[([^\]]{1,60})\]', ctx)
            name = name_m.group(1).strip() if name_m else slug.replace("-", " ").title()
            results.append((name, ats_type, slug))
    return results


def cmd_import_companies(conn: Any, dry_run: bool = False) -> None:
    """Fetch community GitHub lists and upsert company sources in DB."""
    console = Console()

    # 1. Fetch all sources and collect (company_name, ats_type, slug, source) candidates
    all_candidates: list[tuple[str, str, str, str]] = []
    for source_label, source_url in _IMPORT_SOURCES:
        console.print(f"[dim]Fetching ({source_label})[/dim] {source_url}")
        try:
            resp = requests.get(source_url, timeout=30)
            resp.raise_for_status()
            text = resp.text
        except requests.RequestException as e:
            console.print(f"  [yellow]Skipped (fetch failed): {e}[/yellow]")
            continue
        # Choose parser based on source label / content
        if source_label == "simplify":
            parsed = _parse_companies_from_simplify(text)
        elif "<tr>" in text:
            parsed = _parse_companies_from_html_table(text)
        else:
            parsed = _parse_companies_from_markdown(text)
        console.print(f"  [dim]Found {len(parsed)} companies[/dim]")
        all_candidates.extend((name, ats, slug, source_label) for name, ats, slug in parsed)

    if not all_candidates:
        console.print("[yellow]No companies found from any source.[/yellow]")
        return

    # 2. Load existing company sources from DB for dedupe
    existing_companies = list_company_sources(conn, enabled_only=False)
    existing_urls: set[str] = {c.get("ats_url", "") for c in existing_companies}
    existing_slugs: set[str] = {str(c.get("slug", "")).lower() for c in existing_companies if c.get("slug")}

    # 3. Build new entries — deduplicate across sources as we go
    new_entries: list[dict[str, Any]] = []
    skipped_dupe = 0
    seen_import_slugs: set[str] = set()
    for company_name, ats_type, slug, source_label in all_candidates:
        if slug.lower() in existing_slugs or slug.lower() in seen_import_slugs:
            skipped_dupe += 1
            continue
        try:
            ats_url = _slug_to_ats_url(slug, ats_type)
        except ValueError:
            continue
        if ats_url in existing_urls:
            skipped_dupe += 1
            continue
        seen_import_slugs.add(slug.lower())
        new_entries.append({
            "name": company_name,
            "ats_type": ats_type,
            "ats_url": ats_url,
            "slug": slug,
            "enabled": True,
            "_source": source_label,
        })

    console.print(
        f"\n[bold]Import summary:[/bold] "
        f"[green]{len(new_entries)} new[/green], "
        f"[dim]{skipped_dupe} already present / duplicate[/dim]"
    )

    if not new_entries:
        console.print("[dim]Nothing to add.[/dim]")
        return

    # 4. Print preview table
    from rich.table import Table as RichTable
    preview = RichTable(title=f"Companies to import ({len(new_entries)})", show_header=True)
    preview.add_column("Name", style="cyan")
    preview.add_column("ATS", style="green")
    preview.add_column("Slug")
    preview.add_column("Source", style="dim")
    for entry in new_entries:
        # Extract slug from constructed ats_url for display
        parts = [p for p in urlparse(entry["ats_url"]).path.strip("/").split("/") if p]
        slug_display = parts[-2] if entry["ats_type"] == "greenhouse" and len(parts) >= 2 else parts[-1]
        preview.add_row(entry["name"], entry["ats_type"], slug_display, entry.get("_source", ""))
    console.print(preview)

    if dry_run:
        console.print("[yellow]Dry run — not writing to DB[/yellow]")
        return

    # 5. Upsert into DB
    for entry in new_entries:
        upsert_company_source(
            conn,
            name=entry["name"],
            ats_type=entry["ats_type"],
            ats_url=entry["ats_url"],
            slug=entry["slug"],
            enabled=True,
            source=f"import:{entry.get('_source', 'unknown')}",
        )

    console.print(
        f"[bold green]Done.[/bold green] "
        f"Upserted {len(new_entries)} company source(s) into DB"
    )


def _load_companies_from_yaml(config_path: Path) -> list[dict[str, Any]]:
    """Load company entries from YAML for one-time migration only."""
    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if "companies" in data and isinstance(data["companies"], list):
        return data["companies"]

    entries = []
    url_templates = {
        "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
        "lever": "https://api.lever.co/v0/postings/{slug}",
        "ashby": "https://jobs.ashbyhq.com/{slug}",
        "workable": "https://apply.workable.com/api/v3/accounts/{slug}/jobs",
        "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{slug}/postings",
    }
    for ats_type, slugs in data.items():
        if not isinstance(slugs, list):
            continue
        tmpl = url_templates.get(ats_type, "")
        if not tmpl:
            continue
        for slug in slugs:
            entries.append(
                {
                    "name": slug,
                    "ats_type": ats_type,
                    "ats_url": tmpl.format(slug=slug),
                    "enabled": True,
                }
            )
    return entries


def cmd_migrate_companies_from_yaml(conn: Any, config_path: Path) -> None:
    """One-time migration: import company sources from YAML into DB."""
    console = Console()
    if not config_path.exists():
        console.print(f"[red]YAML file not found:[/red] {config_path}")
        return
    rows = _load_companies_from_yaml(config_path)
    inserted = 0
    skipped = 0
    for row in rows:
        ats_type = str(row.get("ats_type", "")).lower()
        ats_url = str(row.get("ats_url", "")).strip()
        slug = _extract_slug(ats_url, ats_type)
        if not ats_type or not ats_url or not slug:
            skipped += 1
            continue
        upsert_company_source(
            conn,
            name=str(row.get("name", slug)).strip() or slug,
            ats_type=ats_type,
            ats_url=ats_url,
            slug=slug,
            enabled=bool(row.get("enabled", True)),
            source="yaml_migration",
        )
        inserted += 1
    console.print(
        f"[bold green]Migration complete.[/bold green] Upserted {inserted}, skipped {skipped} invalid row(s)."
    )


def cmd_list_companies(conn: Any) -> None:
    """Print company sources from DB."""
    console = Console()
    rows = list_company_sources(conn, enabled_only=False)
    if not rows:
        console.print("[yellow]No company sources found in DB.[/yellow]")
        return
    table = Table(title=f"Company sources ({len(rows)})", show_header=True)
    table.add_column("ID", style="dim")
    table.add_column("Enabled")
    table.add_column("ATS", style="green")
    table.add_column("Slug", style="cyan")
    table.add_column("Name")
    table.add_column("Source", style="dim")
    for row in rows:
        table.add_row(
            str(row["id"]),
            "yes" if row["enabled"] else "no",
            row["ats_type"],
            row["slug"],
            _safe_text(row["name"]),
            _safe_text(row["source"] or ""),
        )
    console.print(table)


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
    (
        "smartrecruiters",
        "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1",
        "GET",
        lambda r: r.status_code == 200 and "content" in r.json(),
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
            f"\n[dim]To add to DB, run add_company.py with this slug.[/dim]"
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
        if ats_name == "smartrecruiters":
            return data.get("totalFound", len(data.get("content", [])))
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
            _safe_text(job.get("company", "")),
            _safe_text(job.get("title", "")),
            _safe_text(job.get("location", "")),
            job.get("posted", "")[:10],
            _safe_text(display_url),
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
        help="Local SQLite file path (default: jobs.db in current directory). Ignored if TURSO_URL is set.",
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
    parser.add_argument(
        "--re-enrich-all",
        action="store_true",
        help="Re-enrich every job in the DB (overwrites existing enrichments), then exit",
    )
    parser.add_argument(
        "--import-companies",
        action="store_true",
        help="Fetch AI/ML company lists from GitHub and upsert into company_sources table",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --import-companies: print what would be added without writing to DB",
    )
    parser.add_argument(
        "--migrate-companies-from-yaml",
        metavar="PATH",
        default=None,
        help="One-time migration: import company entries from YAML into DB, then exit",
    )
    parser.add_argument(
        "--list-companies",
        action="store_true",
        help="List company source rows from DB and exit",
    )
    parser.add_argument(
        "--enable-company",
        metavar="ID_OR_SLUG",
        default=None,
        help="Enable one company source by id or slug, then exit",
    )
    parser.add_argument(
        "--disable-company",
        metavar="ID_OR_SLUG",
        default=None,
        help="Disable one company source by id or slug, then exit",
    )
    args = parser.parse_args()

    # Load .env from the current working directory (project root)
    _load_dotenv(Path.cwd() / ".env")

    if args.check:
        check_company(args.check)
        return

    # Resolve DB URL
    turso_url = os.getenv("TURSO_URL", "")
    turso_token = os.getenv("TURSO_AUTH_TOKEN", "")
    if turso_url:
        db_url = turso_url
        db_auth_token = turso_token
        db_label = "Turso"
    elif args.db:
        db_url = args.db
        db_auth_token = ""
        db_label = args.db
    else:
        db_url = str(Path.cwd() / "jobs.db")
        db_auth_token = ""
        db_label = db_url

    # LLM config
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model = os.getenv("ENRICHMENT_MODEL", "openai/gpt-oss-120b")

    console = Console(stderr=True)
    conn = init_db(db_url, db_auth_token)

    if args.migrate_companies_from_yaml:
        cmd_migrate_companies_from_yaml(conn, Path(args.migrate_companies_from_yaml))
        conn.close()
        return

    if args.list_companies:
        cmd_list_companies(conn)
        conn.close()
        return

    if args.enable_company or args.disable_company:
        target = args.enable_company or args.disable_company
        enabled = bool(args.enable_company)
        updated = set_company_source_enabled(conn, target, enabled=enabled)
        verb = "enabled" if enabled else "disabled"
        if updated:
            console.print(f"[green]Updated:[/green] {verb} '{target}'")
        else:
            console.print(f"[yellow]No company source matched '{target}'.[/yellow]")
        conn.close()
        return

    if args.import_companies:
        cmd_import_companies(conn, dry_run=args.dry_run)
        conn.close()
        return

    # --enrich-backfill / --re-enrich-all: enrich jobs, then exit
    if args.enrich_backfill or args.re_enrich_all:
        force = args.re_enrich_all
        jobs_to_enrich = load_unenriched_jobs(conn, force=force)
        label = "Re-enrich all" if force else "Backfill"
        console.print(
            f"[bold]{label}:[/bold] {len(jobs_to_enrich)} job(s) to enrich in {db_label}"
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
    companies = load_enabled_company_sources(conn)
    if not companies:
        console.print(
            "[red]No enabled company sources found in DB.[/red] "
            "Run --migrate-companies-from-yaml companies.yaml or add companies with add_company.py."
        )
        conn.close()
        sys.exit(1)
    console.print(f"[bold]Loaded {len(companies)} enabled company source(s) from DB[/bold]")
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
