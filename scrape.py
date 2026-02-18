"""
scrape.py — Daily ML/AI/Data Science job scraper with Telegram notifications.

Scrapes Greenhouse, Lever, Ashby, and Workable from a companies.yaml config,
filters to Canada/Remote roles, fetches full descriptions, stores results in
SQLite, and sends Telegram notifications for new postings grouped by country.

Usage:
    python scrape.py                         # standard daily run
    python scrape.py --no-location-filter    # show all title-matched jobs worldwide
    python scrape.py --no-enrich             # skip description fetching (faster)
    python scrape.py --no-notify             # skip Telegram notification
    python scrape.py --check cohere          # discover which ATS a company uses
    python scrape.py --db /path/to/jobs.db   # use a custom database path
    python scrape.py --config /path/to/companies.yaml
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import functools
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any

import requests
import yaml
from rich.console import Console
from rich.table import Table
from rich import box

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
# Retry decorator (adapted from ai-job-assist/src/jobradar/utils/retry.py)
# ---------------------------------------------------------------------------

def retry_with_backoff(max_attempts: int = 3, base_delay: float = 2.0):
    """Decorator: exponential backoff retry for requests.RequestException."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except requests.RequestException as e:
                    last_exc = e
                    if attempt == max_attempts:
                        logger.error("Final attempt %d/%d failed: %s", attempt, max_attempts, e)
                        break
                    delay = min(base_delay ** attempt, 60.0)
                    logger.warning(
                        "Attempt %d/%d failed: %s. Retrying in %.1fs...",
                        attempt, max_attempts, e, delay,
                    )
                    time.sleep(delay)
            raise last_exc or RuntimeError("Retry exhausted")
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Section A — Fetcher functions
# (adapted from ai-job-assist/src/jobradar/services/job_fetcher.py)
# ---------------------------------------------------------------------------

@retry_with_backoff(max_attempts=3)
def fetch_greenhouse(board_token: str) -> list[dict[str, Any]]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json().get("jobs", [])


@retry_with_backoff(max_attempts=3)
def fetch_lever(company_name: str) -> list[dict[str, Any]]:
    url = f"https://api.lever.co/v0/postings/{company_name}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def _extract_json_array_from_html(html_text: str, key: str) -> list[dict[str, Any]]:
    """Parse a JSON array embedded in HTML by bracket-matching (from AshbyFetcher)."""
    needle = f'"{key}":'
    index = html_text.find(needle)
    if index < 0:
        return []
    start = html_text.find("[", index)
    if start < 0:
        return []
    depth = 0
    end = -1
    for idx in range(start, len(html_text)):
        c = html_text[idx]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                end = idx
                break
    if end < 0:
        return []
    try:
        payload = json.loads(html_text[start: end + 1])
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


@retry_with_backoff(max_attempts=3)
def fetch_ashby(org_slug: str) -> list[dict[str, Any]]:
    url = f"https://jobs.ashbyhq.com/{org_slug}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    jobs = _extract_json_array_from_html(resp.text, "jobPostings")
    for job in jobs:
        if not isinstance(job, dict):
            continue
        job_id = str(job.get("id") or "").strip()
        if job_id and not job.get("jobPostingUrl"):
            job["jobPostingUrl"] = f"https://jobs.ashbyhq.com/{org_slug}/{job_id}"
    return [j for j in jobs if isinstance(j, dict)]


@retry_with_backoff(max_attempts=3)
def fetch_workable(account_slug: str) -> list[dict[str, Any]]:
    url = f"https://apply.workable.com/api/v3/accounts/{account_slug}/jobs"
    resp = requests.post(url, json={}, timeout=30)
    resp.raise_for_status()
    data = resp.json() if resp.content else {}
    jobs = data.get("results", []) if isinstance(data, dict) else []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        shortcode = str(job.get("shortcode") or "").strip()
        if shortcode and not job.get("absolute_url"):
            job["absolute_url"] = f"https://apply.workable.com/{account_slug}/j/{shortcode}"
        location = job.get("location")
        if isinstance(location, dict):
            parts = [
                str(location.get("city") or "").strip(),
                str(location.get("region") or "").strip(),
                str(location.get("country") or "").strip(),
            ]
            job["_location_str"] = ", ".join(p for p in parts if p)
    return [j for j in jobs if isinstance(j, dict)]


# ---------------------------------------------------------------------------
# Section B — Description helpers
# ---------------------------------------------------------------------------

def strip_html(html: str) -> str:
    """Strip HTML tags and decode entities, returning plain text."""
    if not html:
        return ""
    text = unescape(html)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


@retry_with_backoff(max_attempts=2)
def fetch_greenhouse_description(board_token: str, job_id: str) -> str:
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    content = resp.json().get("content", "")
    return strip_html(content)


def build_lever_description(raw: dict[str, Any]) -> str:
    """Build description from Lever list-response fields (no extra request needed)."""
    parts: list[str] = []
    desc_plain = (raw.get("descriptionPlain") or "").strip()
    if desc_plain:
        parts.append(desc_plain)
    for section in raw.get("lists") or []:
        if isinstance(section, dict):
            text = (section.get("text") or "").strip()
            content = strip_html(section.get("content") or "")
            if text:
                parts.append(text)
            if content:
                parts.append(content)
    additional = (raw.get("additionalPlain") or "").strip()
    if additional:
        parts.append(additional)
    return "\n\n".join(parts)


@retry_with_backoff(max_attempts=2)
def fetch_ashby_description(org_slug: str, job_id: str) -> str:
    url = f"https://jobs.ashbyhq.com/{org_slug}/{job_id}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            job = (data.get("props") or {}).get("pageProps", {}).get("job", {})
            desc_html = job.get("descriptionHtml", "")
            if desc_html:
                return strip_html(desc_html)
        except (json.JSONDecodeError, AttributeError):
            pass
    return ""


@retry_with_backoff(max_attempts=2)
def fetch_workable_description(account_slug: str, shortcode: str) -> str:
    url = f"https://apply.workable.com/api/v3/accounts/{account_slug}/jobs/{shortcode}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    description = data.get("full_description") or data.get("description") or ""
    return strip_html(description)


def enrich_descriptions(
    jobs: list[dict[str, Any]],
    raw_map: dict[str, dict[str, Any]],
) -> None:
    """Fetch full descriptions for all jobs concurrently. Mutates job['description']."""

    def fetch_one(job: dict[str, Any]) -> tuple[str, str]:
        url = job.get("url", "")
        ats = job.get("ats", "")
        try:
            if ats == "lever":
                return url, build_lever_description(raw_map.get(url, {}))
            elif ats == "greenhouse":
                return url, fetch_greenhouse_description(
                    job.get("_board_token", ""), job.get("_job_id", "")
                )
            elif ats == "ashby":
                return url, fetch_ashby_description(
                    job.get("_org_slug", ""), job.get("_job_id", "")
                )
            elif ats == "workable":
                return url, fetch_workable_description(
                    job.get("_account_slug", ""), job.get("_shortcode", "")
                )
        except Exception as e:
            logger.warning("Failed to fetch description for %s: %s", url, e)
        return url, ""

    url_to_job = {job["url"]: job for job in jobs if job.get("url")}
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_one, job): job for job in jobs}
        for future in as_completed(futures):
            url, desc = future.result()
            if url in url_to_job:
                url_to_job[url]["description"] = desc


# ---------------------------------------------------------------------------
# Section C — Title filter
# ---------------------------------------------------------------------------

def passes_title_filter(title: str) -> bool:
    t = title.lower()
    has_include = any(kw in t for kw in TITLE_INCLUDE)
    has_exclude = any(kw in t for kw in TITLE_EXCLUDE)
    return has_include and not has_exclude


# ---------------------------------------------------------------------------
# Section D — Location filter
# ---------------------------------------------------------------------------

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

    # Direct Canada match
    if "canada" in loc:
        return True

    # Remote patterns
    if "remote" in loc:
        # Block if it explicitly mentions a country other than US/Canada
        blocked_countries = [
            "uk", "united kingdom", "europe", "eu ", "germany", "france",
            "australia", "india", "brazil", "japan", "singapore", "mexico",
        ]
        if any(bc in loc for bc in blocked_countries):
            return False
        # Allow: "remote", "remote - canada", "remote (us)", "remote us",
        #        "united states (remote)", "anywhere", etc.
        return True

    # "anywhere"
    if "anywhere" in loc:
        return True

    # United States alone (remote-eligible from Canada sometimes)
    if loc in ("united states", "usa", "us"):
        return False  # too broad without remote — skip

    return False


# ---------------------------------------------------------------------------
# Section D — Normalise raw records into a common dict
# (adapted from ai-job-assist/src/jobradar/cli/scan.py)
# ---------------------------------------------------------------------------

def _to_iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()[:10]  # return just YYYY-MM-DD for display


def _normalize_datetime(raw: Any) -> str:
    """Convert various ATS date formats to YYYY-MM-DD string, or empty string."""
    if raw is None:
        return ""
    if isinstance(raw, (int, float)):
        ts = float(raw)
        if ts > 1_000_000_000_000:
            ts /= 1000.0
        try:
            return _to_iso_utc(datetime.fromtimestamp(ts, tz=timezone.utc))
        except (OverflowError, OSError, ValueError):
            return ""
    if isinstance(raw, str):
        value = raw.strip()
        if not value:
            return ""
        if value.isdigit():
            ts = float(value)
            if ts > 1_000_000_000_000:
                ts /= 1000.0
            try:
                return _to_iso_utc(datetime.fromtimestamp(ts, tz=timezone.utc))
            except (OverflowError, OSError, ValueError):
                return ""
        try:
            return _to_iso_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
            try:
                return _to_iso_utc(datetime.strptime(value, fmt))
            except ValueError:
                continue
    return ""


def normalize_greenhouse(raw: dict[str, Any], company: str) -> dict[str, Any]:
    loc_obj = raw.get("location") or {}
    location = loc_obj.get("name", "") if isinstance(loc_obj, dict) else str(loc_obj or "")
    return {
        "company": company,
        "title": raw.get("title", ""),
        "location": location,
        "url": raw.get("absolute_url", ""),
        "posted": _normalize_datetime(raw.get("updated_at")),
        "ats": "greenhouse",
    }


def normalize_lever(raw: dict[str, Any], company: str) -> dict[str, Any]:
    cats = raw.get("categories") or {}
    location = cats.get("location", "") if isinstance(cats, dict) else ""
    # createdAt is milliseconds epoch
    return {
        "company": company,
        "title": raw.get("text", ""),
        "location": location,
        "url": raw.get("hostedUrl", ""),
        "posted": _normalize_datetime(raw.get("createdAt")),
        "ats": "lever",
    }


def normalize_ashby(raw: dict[str, Any], company: str) -> dict[str, Any]:
    location = raw.get("locationName") or raw.get("location") or ""
    url = raw.get("jobPostingUrl") or raw.get("externalLink") or ""
    return {
        "company": company,
        "title": raw.get("title", ""),
        "location": str(location),
        "url": url,
        "posted": _normalize_datetime(raw.get("publishedDate")),
        "ats": "ashby",
    }


def normalize_workable(raw: dict[str, Any], company: str) -> dict[str, Any]:
    location = raw.get("_location_str") or raw.get("location") or ""
    if isinstance(location, dict):
        parts = [
            str(location.get("city") or "").strip(),
            str(location.get("region") or "").strip(),
            str(location.get("country") or "").strip(),
        ]
        location = ", ".join(p for p in parts if p)
    url = raw.get("absolute_url") or raw.get("url") or ""
    return {
        "company": company,
        "title": raw.get("title", ""),
        "location": str(location),
        "url": url,
        "posted": _normalize_datetime(raw.get("published")),
        "ats": "workable",
    }


# ---------------------------------------------------------------------------
# Section E — Main flow
# ---------------------------------------------------------------------------

FETCHERS = {
    "greenhouse": (fetch_greenhouse, normalize_greenhouse),
    "lever":      (fetch_lever,      normalize_lever),
    "ashby":      (fetch_ashby,      normalize_ashby),
    "workable":   (fetch_workable,   normalize_workable),
}


def _extract_slug(ats_url: str, ats_type: str) -> str:
    """Pull the board token / company slug out of an ATS API URL."""
    from urllib.parse import urlparse
    parts = [p for p in urlparse(ats_url).path.strip("/").split("/") if p]
    if not parts:
        return ""
    ats = ats_type.lower()
    if ats == "greenhouse":
        # .../boards/<token>/jobs  → second-to-last segment
        return parts[-2] if len(parts) >= 2 else parts[-1]
    if ats == "workable":
        # .../api/v3/accounts/<slug>/jobs
        if "accounts" in parts:
            idx = parts.index("accounts")
            if idx + 1 < len(parts):
                return parts[idx + 1]
    # lever: .../postings/<company>   ashby: /<org_slug>
    return parts[-1]


def load_companies(config_path: Path) -> list[dict[str, Any]]:
    """Load companies.yaml and return enabled company entries as a flat list."""
    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # New format: top-level "companies" key with list of dicts
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
    raw_map: dict[str, dict[str, Any]] = {}  # url -> raw (used for Lever descriptions)
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

            # Attach metadata needed for per-job description fetches
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

    # Sort by posted date descending (empty dates go last)
    results.sort(key=lambda j: j.get("posted") or "", reverse=True)

    if enrich and results:
        console.print(f"\n[dim]Fetching descriptions for {len(results)} jobs...[/dim]")
        enrich_descriptions(results, raw_map)

    return results


# ---------------------------------------------------------------------------
# Section F — Company discovery (--check)
# ---------------------------------------------------------------------------

# Per-ATS probe: (url_template, http_method, success_test)
# success_test receives the requests.Response and returns True if the board exists.
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
        console.print(f"  {ats_name:12s} {url} … ", end="")
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
        import json as _json
        jobs = _extract_json_array_from_html(resp.text, "jobPostings")
        return len(jobs)
    return 0


# ---------------------------------------------------------------------------
# Section G — SQLite persistence
# ---------------------------------------------------------------------------

def init_db(db_url: str) -> Any:
    """Open the jobs database (local SQLite file or SQLite Cloud URL) and ensure the schema exists."""
    if db_url.startswith("sqlitecloud://"):
        import sqlitecloud  # type: ignore[import]
        conn = sqlitecloud.connect(db_url)
    else:
        conn = sqlite3.connect(db_url)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            url         TEXT PRIMARY KEY,
            company     TEXT,
            title       TEXT,
            location    TEXT,
            posted      TEXT,
            ats         TEXT,
            description TEXT,
            first_seen  TEXT NOT NULL,
            last_seen   TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def save_jobs(
    conn: sqlite3.Connection, jobs: list[dict[str, Any]]
) -> tuple[int, int, list[dict[str, Any]]]:
    """Upsert jobs into the database. Returns (new_count, updated_count, new_jobs)."""
    now = datetime.now(timezone.utc).isoformat()[:10]
    new_count = 0
    updated_count = 0
    new_jobs: list[dict[str, Any]] = []

    for job in jobs:
        url = job.get("url", "")
        if not url:
            continue
        existing = conn.execute("SELECT 1 FROM jobs WHERE url = ?", (url,)).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO jobs (url, company, title, location, posted, ats, description, first_seen, last_seen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    url,
                    job.get("company", ""),
                    job.get("title", ""),
                    job.get("location", ""),
                    job.get("posted", ""),
                    job.get("ats", ""),
                    job.get("description", ""),
                    now,
                    now,
                ),
            )
            new_count += 1
            new_jobs.append(job)
        else:
            conn.execute(
                "UPDATE jobs SET company=?, title=?, location=?, posted=?, ats=?, description=?, last_seen=? "
                "WHERE url=?",
                (
                    job.get("company", ""),
                    job.get("title", ""),
                    job.get("location", ""),
                    job.get("posted", ""),
                    job.get("ats", ""),
                    job.get("description", ""),
                    now,
                    url,
                ),
            )
            updated_count += 1

    conn.commit()
    return new_count, updated_count, new_jobs


# ---------------------------------------------------------------------------
# Section H — Telegram notifications
# ---------------------------------------------------------------------------

def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ (values not overwritten)."""
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def bucket_country(location: str) -> str:
    """Classify a free-text location string into 'Canada', 'USA / Remote', or 'Other'."""
    loc = location.lower()
    canada_signals = (
        "canada",
        # Province abbreviations that appear after a comma (", on", ", bc" etc.)
        ", on", ", bc", ", ab", ", qc", ", mb", ", sk", ", ns", ", nb", ", nl", ", pe",
        # Major Canadian cities
        "toronto", "vancouver", "montreal", "ottawa", "calgary",
        "waterloo", "winnipeg", "halifax", "edmonton", "kitchener",
    )
    if any(sig in loc for sig in canada_signals):
        return "Canada"
    if not location.strip():
        return "USA / Remote"
    if any(sig in loc for sig in ("remote", "anywhere", "united states", "usa", "us only")):
        return "USA / Remote"
    return "Other"


_COUNTRY_ORDER = ["Canada", "USA / Remote", "Other"]
_COUNTRY_EMOJI = {"Canada": "🇨🇦", "USA / Remote": "🌐", "Other": "🌍"}


def format_telegram_message(new_jobs: list[dict[str, Any]], run_date: str) -> list[str]:
    """Return a list of ≤4096-char HTML strings ready to POST to Telegram."""
    # Group by country
    groups: dict[str, list[dict[str, Any]]] = {c: [] for c in _COUNTRY_ORDER}
    for job in new_jobs:
        groups[bucket_country(job.get("location", ""))].append(job)

    lines: list[str] = []
    lines.append(f"🔔 <b>{len(new_jobs)} new job(s) found — {run_date}</b>")

    for country in _COUNTRY_ORDER:
        bucket = groups[country]
        if not bucket:
            continue
        emoji = _COUNTRY_EMOJI[country]
        lines.append("")
        lines.append(f"{emoji} <b>{country} ({len(bucket)})</b>")
        for job in bucket:
            company = job.get("company", "")
            title = job.get("title", "")
            location = job.get("location", "")
            posted = job.get("posted", "")
            url = job.get("url", "")
            loc_part = f"📍 {location}" if location else ""
            date_part = f"🗓 {posted}" if posted else ""
            meta = " | ".join(p for p in [loc_part, date_part] if p)
            link = f'<a href="{url}">Apply →</a>' if url else ""
            lines.append("")
            lines.append(f"• <b>{company} — {title}</b>")
            if meta:
                lines.append(f"  {meta}")
            if link:
                lines.append(f"  {link}")

    # Split into ≤4096-char chunks, breaking on blank lines between jobs
    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = 0
    for line in lines:
        segment = line + "\n"
        if current_len + len(segment) > 4096 and current_parts:
            chunks.append("".join(current_parts).rstrip())
            current_parts = []
            current_len = 0
        current_parts.append(segment)
        current_len += len(segment)
    if current_parts:
        chunks.append("".join(current_parts).rstrip())
    return chunks


def send_telegram(token: str, chat_id: str, text: str) -> None:
    """Send a single HTML-formatted message via the Telegram Bot API."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=15,
    )
    resp.raise_for_status()


def notify_new_jobs(
    new_jobs: list[dict[str, Any]],
    token: str,
    chat_id: str,
    console: Any,
) -> None:
    """Format and send Telegram notifications for newly found jobs."""
    run_date = datetime.now(timezone.utc).isoformat()[:10]
    chunks = format_telegram_message(new_jobs, run_date)
    sent = 0
    for i, chunk in enumerate(chunks):
        if i > 0:
            time.sleep(1)  # avoid Telegram rate-limit between chunks
        try:
            send_telegram(token, chat_id, chunk)
            sent += 1
        except Exception as e:
            logger.error("Telegram send failed: %s", e)
            if console:
                console.print(f"  [red]Telegram error:[/red] {e}")
    if console and sent:
        console.print(
            f"  [green]Telegram:[/green] sent {sent} message(s) "
            f"for {len(new_jobs)} new job(s)"
        )


# ---------------------------------------------------------------------------
# Section I — CLI + Rich table output
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
        # Truncate long URLs
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape ML/AI/Data Science jobs from ATS platforms."
    )
    parser.add_argument(
        "--config", "-c",
        default=None,
        help="Path to companies.yaml (default: companies.yaml next to this script)",
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
        help="Local SQLite file path (default: jobs.db). Ignored if SQLITECLOUD_URL is set.",
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
    args = parser.parse_args()

    # Load .env so secrets are available via os.getenv
    _load_dotenv(Path(__file__).parent / ".env")

    # --check mode: just probe and exit
    if args.check:
        check_company(args.check)
        return

    # Resolve config path
    if args.config:
        config_path = Path(args.config)
    else:
        config_path = Path(__file__).parent / "companies.yaml"

    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    console = Console(stderr=True)
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

    # Persist to database — SQLite Cloud if env var set, otherwise local file
    cloud_url = os.getenv("SQLITECLOUD_URL", "")
    if cloud_url:
        db_url = cloud_url
        db_label = "SQLite Cloud"
    elif args.db:
        db_url = args.db
        db_label = args.db
    else:
        db_url = str(Path(__file__).parent / "jobs.db")
        db_label = db_url
    conn = init_db(db_url)
    new_count, updated_count, new_jobs = save_jobs(conn, jobs)
    conn.close()
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


if __name__ == "__main__":
    main()
