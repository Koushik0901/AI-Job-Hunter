from __future__ import annotations

import re
from typing import Any

import requests
from rich.console import Console
from rich.table import Table

from db import list_company_sources, upsert_company_source
from services.scrape_service import safe_text

IMPORT_SOURCES = [
    ("pittcsc", "https://raw.githubusercontent.com/pittcsc/Summer2024-Internships/dev/README.md"),
    ("j-delaney", "https://raw.githubusercontent.com/j-delaney/easy-application/master/README.md"),
    ("simplify", "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md"),
]


def slug_to_ats_url(slug: str, ats_type: str) -> str:
    if ats_type == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    if ats_type == "lever":
        return f"https://api.lever.co/v0/postings/{slug}"
    if ats_type == "smartrecruiters":
        return f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
    if ats_type == "recruitee":
        return f"https://{slug}.recruitee.com/api/offers"
    raise ValueError(f"Unknown ats_type: {ats_type}")


def parse_companies_from_html_table(text: str) -> list[tuple[str, str, str]]:
    results: list[tuple[str, str, str]] = []
    seen_entries: set[tuple[str, str]] = set()
    for row_match in re.finditer(r"<tr>(.*?)</tr>", text, re.DOTALL):
        row = row_match.group(1)
        name_m = re.search(r"<strong><a[^>]*>([^<]+)</a></strong>", row)
        if not name_m:
            continue
        company_name = name_m.group(1).strip()
        gh_m = re.search(r"(?:job-boards|boards(?:-api)?)\.greenhouse\.io/([A-Za-z0-9_-]+)", row)
        if gh_m:
            slug = gh_m.group(1)
            key = ("greenhouse", slug.lower())
            if key not in seen_entries:
                seen_entries.add(key)
                results.append((company_name, "greenhouse", slug))
        lv_m = re.search(r"jobs\.lever\.co/([A-Za-z0-9_-]+)", row)
        if lv_m:
            slug = lv_m.group(1)
            key = ("lever", slug.lower())
            if key not in seen_entries:
                seen_entries.add(key)
                results.append((company_name, "lever", slug))
        rq_m = re.search(r"https?://([A-Za-z0-9-]+)\.recruitee\.com(?:/[^\"' <]*)?", row)
        if rq_m:
            slug = rq_m.group(1)
            key = ("recruitee", slug.lower())
            if key not in seen_entries:
                seen_entries.add(key)
                results.append((company_name, "recruitee", slug))
    return results


def parse_companies_from_simplify(text: str) -> list[tuple[str, str, str]]:
    results: list[tuple[str, str, str]] = []
    seen_entries: set[tuple[str, str]] = set()
    last_company = ""
    for row_match in re.finditer(r"<tr>(.*?)</tr>", text, re.DOTALL):
        row = row_match.group(1)
        name_m = re.search(r"<strong>(?:<a[^>]*>)?([^<]+)(?:</a>)?</strong>", row)
        if name_m:
            company_name = name_m.group(1).strip()
            last_company = company_name
        else:
            if "↳" in row or "&#8618;" in row:
                company_name = last_company
            else:
                cell_m = re.search(r"<td[^>]*>\s*<a[^>]*>([^<]{1,60})</a>", row)
                company_name = cell_m.group(1).strip() if cell_m else ""
                if company_name:
                    last_company = company_name
        if not company_name:
            continue

        gh_m = re.search(r"(?:job-boards|boards(?:-api)?)\.greenhouse\.io/([A-Za-z0-9_-]+)", row)
        if gh_m:
            slug = gh_m.group(1)
            key = ("greenhouse", slug.lower())
            if key not in seen_entries:
                seen_entries.add(key)
                results.append((company_name, "greenhouse", slug))
        lv_m = re.search(r"jobs\.lever\.co/([A-Za-z0-9_-]+)", row)
        if lv_m:
            slug = lv_m.group(1)
            key = ("lever", slug.lower())
            if key not in seen_entries:
                seen_entries.add(key)
                results.append((company_name, "lever", slug))
        sr_m = re.search(r"apply\.smartrecruiters\.com/([A-Za-z0-9_-]+)/", row)
        if sr_m:
            slug = sr_m.group(1)
            key = ("smartrecruiters", slug.lower())
            if key not in seen_entries:
                seen_entries.add(key)
                results.append((company_name, "smartrecruiters", slug))
        rq_m = re.search(r"https?://([A-Za-z0-9-]+)\.recruitee\.com(?:/[^\"' <]*)?", row)
        if rq_m:
            slug = rq_m.group(1)
            key = ("recruitee", slug.lower())
            if key not in seen_entries:
                seen_entries.add(key)
                results.append((company_name, "recruitee", slug))
    return results


def parse_companies_from_markdown(text: str) -> list[tuple[str, str, str]]:
    results: list[tuple[str, str, str]] = []
    seen_entries: set[tuple[str, str]] = set()
    gh_pat = re.compile(r"([^\n]*boards\.greenhouse\.io/([A-Za-z0-9_-]+)[^\n]*)")
    lv_pat = re.compile(r"([^\n]*jobs\.lever\.co/([A-Za-z0-9_-]+)[^\n]*)")
    rq_pat = re.compile(r"([^\n]*https?://([A-Za-z0-9-]+)\.recruitee\.com(?:/[^\s\)]*)?[^\n]*)")
    for pat, ats_type in ((gh_pat, "greenhouse"), (lv_pat, "lever"), (rq_pat, "recruitee")):
        for m in pat.finditer(text):
            ctx, slug = m.group(1), m.group(2)
            key = (ats_type, slug.lower())
            if key in seen_entries:
                continue
            seen_entries.add(key)
            name_m = re.search(r"\[([^\]]{1,60})\]", ctx)
            name = name_m.group(1).strip() if name_m else slug.replace("-", " ").title()
            results.append((name, ats_type, slug))
    return results


def fetch_import_candidates(console: Console | None = None) -> list[tuple[str, str, str, str]]:
    all_candidates: list[tuple[str, str, str, str]] = []
    for source_label, source_url in IMPORT_SOURCES:
        if console:
            console.print(f"[dim]Fetching ({source_label})[/dim] {source_url}")
        try:
            resp = requests.get(source_url, timeout=30)
            resp.raise_for_status()
            text = resp.text
        except requests.RequestException as e:
            if console:
                console.print(f"  [yellow]Skipped (fetch failed): {e}[/yellow]")
            continue
        if source_label == "simplify":
            parsed = parse_companies_from_simplify(text)
        elif "<tr>" in text:
            parsed = parse_companies_from_html_table(text)
        else:
            parsed = parse_companies_from_markdown(text)
        if console:
            console.print(f"  [dim]Found {len(parsed)} companies[/dim]")
        all_candidates.extend((name, ats, slug, source_label) for name, ats, slug in parsed)
    return all_candidates


def preview_import_companies(conn: Any, console: Console | None = None) -> dict[str, Any]:
    all_candidates = fetch_import_candidates(console=console)
    if not all_candidates:
        if console:
            console.print("[yellow]No companies found from any source.[/yellow]")
        return {"new_entries": [], "skipped_duplicates": 0}
    existing = list_company_sources(conn, enabled_only=False)
    existing_urls = {row.get("ats_url", "") for row in existing}
    existing_slugs = {str(row.get("slug", "")).lower() for row in existing if row.get("slug")}

    new_entries: list[dict[str, Any]] = []
    skipped_dupe = 0
    seen_import_slugs: set[str] = set()
    for name, ats_type, slug, source_label in all_candidates:
        if slug.lower() in existing_slugs or slug.lower() in seen_import_slugs:
            skipped_dupe += 1
            continue
        try:
            ats_url = slug_to_ats_url(slug, ats_type)
        except ValueError:
            continue
        if ats_url in existing_urls:
            skipped_dupe += 1
            continue
        seen_import_slugs.add(slug.lower())
        new_entries.append({
            "name": name,
            "ats_type": ats_type,
            "ats_url": ats_url,
            "slug": slug,
            "source": source_label,
        })
    return {"new_entries": new_entries, "skipped_duplicates": skipped_dupe}


def import_companies(conn: Any, dry_run: bool = False) -> None:
    console = Console()
    preview = preview_import_companies(conn, console=console)
    new_entries = preview["new_entries"]
    skipped_dupe = int(preview["skipped_duplicates"])
    console.print(
        f"\n[bold]Import summary:[/bold] [green]{len(new_entries)} new[/green], "
        f"[dim]{skipped_dupe} already present / duplicate[/dim]"
    )
    if not new_entries:
        return

    preview = Table(title=f"Companies to import ({len(new_entries)})", show_header=True)
    preview.add_column("Name", style="cyan")
    preview.add_column("ATS", style="green")
    preview.add_column("Slug")
    preview.add_column("Source", style="dim")
    for entry in new_entries:
        preview.add_row(entry["name"], entry["ats_type"], entry["slug"], entry["source"])
    console.print(preview)

    if dry_run:
        console.print("[yellow]Dry run — not writing to DB[/yellow]")
        return

    for entry in new_entries:
        upsert_company_source(
            conn,
            name=entry["name"],
            ats_type=entry["ats_type"],
            ats_url=entry["ats_url"],
            slug=entry["slug"],
            enabled=True,
            source=f"import:{entry['source']}",
        )
    console.print(f"[bold green]Done.[/bold green] Upserted {len(new_entries)} company source(s) into DB")


def list_companies_table(conn: Any) -> None:
    rows = list_company_sources(conn, enabled_only=False)
    console = Console()
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
            safe_text(row["name"]),
            safe_text(row["source"] or ""),
        )
    console.print(table)
