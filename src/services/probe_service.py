from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlparse

import requests
from rich.console import Console

from fetchers import _extract_json_array_from_html

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
    (
        "recruitee",
        "https://{slug}.recruitee.com/api/offers",
        "GET",
        lambda r: r.status_code == 200 and (
            (isinstance(r.json(), dict) and "offers" in r.json()) or isinstance(r.json(), list)
        ),
    ),
]

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
}


def _probe_headers(ats_name: str, url: str) -> dict[str, str]:
    headers = dict(_DEFAULT_HEADERS)
    if ats_name == "workable":
        path_parts = [part for part in urlparse(url).path.split("/") if part]
        slug = path_parts[3] if len(path_parts) >= 4 else ""
        headers["Origin"] = "https://apply.workable.com"
        if slug:
            headers["Referer"] = f"https://apply.workable.com/{slug}/"
    return headers


def _send_probe_request(method: str, url: str, ats_name: str) -> requests.Response:
    headers = _probe_headers(ats_name, url)
    if method == "POST":
        return requests.post(url, json={}, headers=headers, timeout=15)
    return requests.get(url, headers=headers, timeout=15)


def probe_job_count(resp: requests.Response, ats_name: str) -> int:
    """Best-effort job count from a probe response."""
    try:
        data = resp.json()
        if ats_name == "greenhouse":
            return len(data.get("jobs", []))
        if ats_name == "lever":
            return len(data) if isinstance(data, list) else 0
        if ats_name == "workable":
            if not isinstance(data, dict):
                return 0
            total = data.get("total")
            if total is not None:
                try:
                    return int(total)
                except (TypeError, ValueError):
                    pass
            return len(data.get("results", []))
        if ats_name == "smartrecruiters":
            return data.get("totalFound", len(data.get("content", [])))
        if ats_name == "recruitee":
            if isinstance(data, list):
                return len(data)
            offers = data.get("offers", [])
            return len(offers) if isinstance(offers, list) else 0
    except Exception:
        pass
    if ats_name == "ashby":
        jobs = _extract_json_array_from_html(resp.text, "jobPostings")
        return len(jobs)
    return 0


def check_company(slug: str) -> None:
    """Probe each ATS to see if `slug` has a live job board."""
    console = Console()
    console.print(f"\n[bold]Checking ATS boards for slug:[/bold] [cyan]{slug}[/cyan]\n")

    found_any = False
    for ats_name, url_tmpl, method, success_test in _ATS_PROBES:
        url = url_tmpl.format(slug=slug)
        console.print(f"  {ats_name:12s} {url} ... ", end="")
        try:
            resp = _send_probe_request(method, url, ats_name)
            if success_test(resp):
                job_count = probe_job_count(resp, ats_name)
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


def probe_all(slugs: list[str], url_templates: dict[str, str]) -> list[dict[str, Any]]:
    """Probe all ATS for all slugs concurrently, returning canonical hit rows."""

    def _probe_one(slug: str, ats_name: str, url_tmpl: str, method: str, success_test) -> dict[str, Any] | None:
        url = url_tmpl.format(slug=slug)
        try:
            resp = _send_probe_request(method, url, ats_name)
            if success_test(resp):
                canonical_tmpl = url_templates.get(ats_name, url_tmpl)
                return {
                    "slug": slug,
                    "ats": ats_name,
                    "ats_url": canonical_tmpl.format(slug=slug),
                    "jobs": probe_job_count(resp, ats_name),
                }
        except requests.RequestException:
            pass
        return None

    hits: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = [
            ex.submit(_probe_one, slug, ats_name, url_tmpl, method, success_test)
            for slug in slugs
            for ats_name, url_tmpl, method, success_test in _ATS_PROBES
        ]
        for fut in as_completed(futures):
            row = fut.result()
            if row:
                hits.append(row)
    return hits
