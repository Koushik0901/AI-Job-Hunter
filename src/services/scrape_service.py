from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from rich import box
from rich.console import Console
from rich.table import Table

from fetchers import (
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

SENIORITY_EXCLUDE_PATTERNS = [
    r"\bsenior\b",
    r"\bsr\.?\b",
    r"\bstaff\b",
    r"\bprincipal\b",
    r"\blead\b",
]

_CA_PROVINCES = [
    "ontario", "british columbia", "alberta", "quebec", "nova scotia",
    "new brunswick", "prince edward island", "newfoundland", "labrador",
    "newfoundland and labrador", "manitoba", "saskatchewan",
    "northwest territories", "yukon", "nunavut",
]
_CA_ABBREVS = {"bc", "ab", "on", "qc", "ns", "nb", "pei", "nl", "mb", "sk", "nt", "yt", "nu"}
_CA_CITIES = [
    "vancouver", "toronto", "calgary", "edmonton", "montreal", "ottawa",
    "winnipeg", "halifax", "victoria", "waterloo", "kitchener",
]

FETCHERS = {
    "greenhouse": (fetch_greenhouse, normalize_greenhouse),
    "lever": (fetch_lever, normalize_lever),
    "ashby": (fetch_ashby, normalize_ashby),
    "workable": (fetch_workable, normalize_workable),
    "smartrecruiters": (fetch_smartrecruiters, normalize_smartrecruiters),
}


def safe_text(value: Any) -> str:
    text = str(value or "")
    try:
        text.encode("cp1252")
        return text
    except UnicodeEncodeError:
        return text.encode("cp1252", errors="replace").decode("cp1252")


def passes_title_filter(title: str) -> bool:
    t = title.lower()
    if not any(kw in t for kw in TITLE_INCLUDE):
        return False
    if any(kw in t for kw in TITLE_EXCLUDE):
        return False
    if any(re.search(pattern, t) for pattern in SENIORITY_EXCLUDE_PATTERNS):
        return False
    return True


def passes_location_filter(location: str) -> bool:
    if not location:
        return True
    loc = location.lower().strip()
    if "canada" in loc:
        return True
    if any(prov in loc for prov in _CA_PROVINCES):
        return True
    if any(city in loc for city in _CA_CITIES):
        return True
    tokens = set(re.split(r"[\s,;|()/\-]+", loc))
    if tokens & _CA_ABBREVS:
        return True
    if "remote" in loc:
        blocked = [
            "uk", "united kingdom", "europe", "eu ", "germany", "france",
            "australia", "india", "brazil", "japan", "singapore", "mexico",
        ]
        return not any(b in loc for b in blocked)
    if "anywhere" in loc:
        return True
    if loc in ("united states", "usa", "us"):
        return False
    return False


def extract_slug(ats_url: str, ats_type: str) -> str:
    parts = [p for p in urlparse(ats_url).path.strip("/").split("/") if p]
    if not parts:
        return ""
    ats = ats_type.lower()
    if ats == "greenhouse":
        return parts[-2] if len(parts) >= 2 else parts[-1]
    if ats == "workable" and "accounts" in parts:
        idx = parts.index("accounts")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    if ats == "smartrecruiters" and "companies" in parts:
        idx = parts.index("companies")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return parts[-1]


def scrape_all(
    companies: list[dict[str, Any]],
    apply_location_filter: bool = True,
    enrich: bool = True,
    title_filter_fn=None,
) -> list[dict[str, Any]]:
    title_ok = title_filter_fn if title_filter_fn is not None else passes_title_filter
    results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    raw_map: dict[str, dict[str, Any]] = {}
    console = Console(stderr=True)

    for comp in companies:
        ats_type = comp.get("ats_type", "").lower()
        name = comp.get("name", "")
        ats_url = comp.get("ats_url", "")

        if ats_type not in FETCHERS:
            console.print(f"  [yellow]Skipping {safe_text(name)}: unknown ats_type '{ats_type}'[/yellow]")
            continue

        fetcher, normalizer = FETCHERS[ats_type]
        slug = extract_slug(ats_url, ats_type)
        console.print(f"  [dim]Fetching {ats_type}:{slug} ({safe_text(name)})...[/dim]", end="")
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

            if not title_ok(job["title"]):
                continue
            if apply_location_filter and not passes_location_filter(job["location"]):
                continue
            results.append(job)

    try:
        hn_jobs = fetch_hn_jobs()
        hn_added = 0
        for job in hn_jobs:
            if not title_ok(job["title"]):
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


def render_jobs_table(jobs: list[dict[str, Any]], limit: int) -> None:
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
    table.add_column("Match", min_width=7, max_width=9, no_wrap=True)
    table.add_column("URL", min_width=20, max_width=60, no_wrap=True)

    for job in displayed:
        url = job.get("url", "")
        display_url = url if len(url) <= 60 else url[:57] + "..."
        table.add_row(
            safe_text(job.get("company", "")),
            safe_text(job.get("title", "")),
            safe_text(job.get("location", "")),
            job.get("posted", "")[:10],
            str(job.get("match_score", "-")),
            safe_text(display_url),
        )

    console.print(table)
    if len(jobs) > limit:
        console.print(f"[dim]Showing first {limit} of {len(jobs)} results. Use --limit to show more.[/dim]")
