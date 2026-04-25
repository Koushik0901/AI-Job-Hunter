"""
fetchers.py — ATS fetchers, normalizers, description helpers, and retry logic.
"""
from __future__ import annotations

import functools
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Retry decorator
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
# ATS fetchers
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
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    }
    resp = requests.get(url, headers=headers, timeout=30)
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
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "Origin": "https://apply.workable.com",
        "Referer": f"https://apply.workable.com/{account_slug}/",
        "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    }
    jobs: list[dict[str, Any]] = []
    seen_shortcodes: set[str] = set()
    token: str | None = None

    while True:
        payload: dict[str, str] = {}
        if token:
            payload["token"] = token
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json() if resp.content else {}
        page_jobs = data.get("results", []) if isinstance(data, dict) else []

        for job in page_jobs:
            if not isinstance(job, dict):
                continue
            shortcode = str(job.get("shortcode") or "").strip()
            if shortcode and shortcode in seen_shortcodes:
                continue
            if shortcode:
                seen_shortcodes.add(shortcode)
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
            jobs.append(job)

        next_token = str(data.get("nextPage") or "").strip() if isinstance(data, dict) else ""
        if not next_token or next_token == token:
            break
        token = next_token

    return jobs


@retry_with_backoff(max_attempts=3)
def fetch_recruitee(company_slug: str) -> list[dict[str, Any]]:
    base = f"https://{company_slug}.recruitee.com/api/offers"
    urls = (base, base + "/")
    last_error: Exception | None = None
    for url in urls:
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                offers = data.get("offers", [])
                return offers if isinstance(offers, list) else []
            if isinstance(data, list):
                return data
            return []
        except requests.RequestException as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    return []


def _extract_teamtailor_job_urls(base_url: str, html_text: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for match in re.finditer(r'href=["\']([^"\']*/jobs/\d+(?:-[^"\']+)?)["\']', html_text, re.I):
        href = str(match.group(1) or "").strip()
        if not href:
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        if "/jobs/" not in parsed.path:
            continue
        cleaned = absolute.split("#", 1)[0]
        cleaned = cleaned.split("?", 1)[0]
        if cleaned in seen:
            continue
        seen.add(cleaned)
        urls.append(cleaned)
    return urls


def _extract_teamtailor_job_posting(html_text: str) -> dict[str, Any]:
    def _job_posting_candidate(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        raw_type = value.get("@type")
        if isinstance(raw_type, str) and raw_type.strip().lower() == "jobposting":
            return value
        if isinstance(raw_type, list):
            for item in raw_type:
                if str(item or "").strip().lower() == "jobposting":
                    return value
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                candidate = _job_posting_candidate(item)
                if candidate:
                    return candidate
        return None

    for match in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html_text,
        re.I | re.S,
    ):
        raw = str(match.group(1) or "").strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        candidates: list[Any]
        if isinstance(parsed, list):
            candidates = parsed
        else:
            candidates = [parsed]
        for item in candidates:
            candidate = _job_posting_candidate(item)
            if candidate:
                return candidate
    return {}


def _extract_teamtailor_meta_fields(html_text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for label_raw, value_raw in re.findall(
        r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>",
        html_text,
        re.I | re.S,
    ):
        label = strip_html(label_raw).strip().lower()
        value = strip_html(value_raw).strip()
        if label and value and label not in fields:
            fields[label] = value
    return fields


def _teamtailor_location_from_job_posting(job_posting: dict[str, Any]) -> str:
    raw_locations = job_posting.get("jobLocation")
    if not raw_locations:
        return ""
    places = raw_locations if isinstance(raw_locations, list) else [raw_locations]
    seen: set[str] = set()
    locations: list[str] = []
    for place in places:
        if not isinstance(place, dict):
            continue
        address = place.get("address") or {}
        if not isinstance(address, dict):
            continue
        parts = [
            str(address.get("addressLocality") or "").strip(),
            str(address.get("addressRegion") or "").strip(),
            str(address.get("addressCountry") or "").strip(),
        ]
        location = ", ".join(part for part in parts if part)
        if location and location not in seen:
            seen.add(location)
            locations.append(location)
    return " | ".join(locations)


@retry_with_backoff(max_attempts=3)
def _fetch_teamtailor_job_detail(job_url: str) -> dict[str, Any]:
    resp = requests.get(job_url, timeout=30)
    resp.raise_for_status()
    job_posting = _extract_teamtailor_job_posting(resp.text)
    fields = _extract_teamtailor_meta_fields(resp.text)
    location = fields.get("location") or fields.get("locations") or _teamtailor_location_from_job_posting(job_posting)
    remote_status = fields.get("remote status") or fields.get("remote")
    if remote_status:
        remote_lower = remote_status.lower()
        if location:
            if remote_lower not in location.lower():
                location = f"{location} ({remote_status})"
        else:
            location = remote_status
    return {
        **job_posting,
        "url": job_posting.get("url") or job_url,
        "location": location,
        "employmentType": job_posting.get("employmentType") or fields.get("employment type") or "",
    }


@retry_with_backoff(max_attempts=3)
def fetch_teamtailor(company_slug: str) -> list[dict[str, Any]]:
    list_url = f"https://{company_slug}.teamtailor.com/jobs"
    resp = requests.get(list_url, timeout=30)
    resp.raise_for_status()
    job_urls = _extract_teamtailor_job_urls(list_url, resp.text)
    if not job_urls:
        return []

    detail_by_url: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(job_urls))) as executor:
        future_map = {executor.submit(_fetch_teamtailor_job_detail, job_url): job_url for job_url in job_urls}
        for future in as_completed(future_map):
            job_url = future_map[future]
            try:
                detail_by_url[job_url] = future.result()
            except requests.RequestException as exc:
                logger.warning("Failed to fetch Teamtailor job detail for %s: %s", job_url, exc)

    return [detail_by_url[job_url] for job_url in job_urls if job_url in detail_by_url]


# ---------------------------------------------------------------------------
# Description helpers
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
    url = f"https://apply.workable.com/api/v2/accounts/{account_slug}/jobs/{shortcode}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    description = data.get("full_description") or data.get("description") or ""
    return strip_html(description)


@retry_with_backoff(max_attempts=2)
def fetch_recruitee_description(company_slug: str, offer_id: str) -> str:
    if not company_slug or not offer_id:
        return ""
    url = f"https://{company_slug}.recruitee.com/api/offers/{offer_id}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    offer = data.get("offer", data) if isinstance(data, dict) else {}
    if not isinstance(offer, dict):
        return ""
    description = (
        offer.get("description")
        or offer.get("description_html")
        or offer.get("content")
        or ""
    )
    return strip_html(str(description))


def enrich_descriptions(
    jobs: list[dict[str, Any]],
    raw_map: dict[str, dict[str, Any]],
) -> None:
    """Fetch full descriptions for all jobs concurrently. Mutates job['description']."""

    def fetch_one(job: dict[str, Any]) -> tuple[str, str]:
        url = job.get("url", "")
        if job.get("description"):          # already provided (e.g. Adzuna)
            return url, job["description"]
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
            elif ats == "smartrecruiters":
                slug = job.get("_company_slug", "")
                job_id = job.get("_job_id", "")
                if slug and job_id:
                    return url, fetch_smartrecruiters_description(slug, job_id)
            elif ats == "recruitee":
                raw_desc = (
                    job.get("description")
                    or (raw_map.get(url, {}) if url else {}).get("description")
                    or (raw_map.get(url, {}) if url else {}).get("description_html")
                )
                if raw_desc:
                    return url, strip_html(str(raw_desc))
                slug = job.get("_company_slug", "")
                offer_id = job.get("_offer_id", "")
                if slug and offer_id:
                    return url, fetch_recruitee_description(slug, offer_id)
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
# Normalizers
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


def normalize_recruitee(raw: dict[str, Any], company: str) -> dict[str, Any]:
    location = raw.get("location") or {}
    location_str = ""
    if isinstance(location, dict):
        parts = [
            str(location.get("city") or "").strip(),
            str(location.get("region") or "").strip(),
            str(location.get("country") or "").strip(),
        ]
        location_str = ", ".join(p for p in parts if p)
    elif isinstance(location, str):
        location_str = location.strip()

    careers_url = (
        raw.get("careers_url")
        or raw.get("url")
        or raw.get("job_url")
        or ""
    )
    slug = str(raw.get("company_slug") or raw.get("company") or "").strip()
    offer_id = str(raw.get("id") or raw.get("offer_id") or "").strip()
    offer_slug = str(raw.get("slug") or "").strip()
    if not careers_url and slug and offer_slug:
        careers_url = f"https://{slug}.recruitee.com/o/{offer_slug}"
    elif not careers_url and slug and offer_id:
        careers_url = f"https://{slug}.recruitee.com/o/{offer_id}"

    posted_raw = (
        raw.get("created_at")
        or raw.get("published_at")
        or raw.get("updated_at")
        or raw.get("open_at")
    )
    description = raw.get("description") or raw.get("description_html") or ""
    return {
        "company": company,
        "title": raw.get("title", ""),
        "location": location_str,
        "url": str(careers_url),
        "posted": _normalize_datetime(posted_raw),
        "ats": "recruitee",
        "description": strip_html(str(description)) if description else "",
        "_company_slug": slug,
        "_offer_id": offer_id,
    }


def normalize_teamtailor(raw: dict[str, Any], company: str) -> dict[str, Any]:
    description = raw.get("description") or ""
    return {
        "company": company,
        "title": raw.get("title", ""),
        "location": str(raw.get("location") or ""),
        "url": str(raw.get("url") or ""),
        "posted": _normalize_datetime(raw.get("datePosted")),
        "ats": "teamtailor",
        "description": strip_html(str(description)) if description else "",
    }


# ---------------------------------------------------------------------------
# SmartRecruiters API
# ---------------------------------------------------------------------------

@retry_with_backoff(max_attempts=3)
def fetch_smartrecruiters(company_slug: str) -> list[dict[str, Any]]:
    url = f"https://api.smartrecruiters.com/v1/companies/{company_slug}/postings"
    resp = requests.get(url, params={"limit": 100, "offset": 0}, timeout=30)
    resp.raise_for_status()
    return resp.json().get("content", [])


def normalize_smartrecruiters(raw: dict[str, Any], company: str) -> dict[str, Any]:
    loc = raw.get("location") or {}
    city = str(loc.get("city") or "").strip()
    region = str(loc.get("region") or "").strip()
    country = str(loc.get("country") or "").strip()
    remote = loc.get("remote", False)
    loc_parts = [p for p in [city, region, country] if p]
    if remote:
        location = "Remote, " + ", ".join(loc_parts) if loc_parts else "Remote"
    else:
        location = ", ".join(loc_parts)
    return {
        "company": company,
        "title": raw.get("name", ""),
        "location": location,
        "url": raw.get("ref", ""),
        "posted": _normalize_datetime(raw.get("releasedDate", "")),
        "ats": "smartrecruiters",
        "_job_id": str(raw.get("id", "")),
    }


@retry_with_backoff(max_attempts=2)
def fetch_smartrecruiters_description(company_slug: str, job_id: str) -> str:
    url = f"https://api.smartrecruiters.com/v1/companies/{company_slug}/postings/{job_id}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    sections = (data.get("jobAd") or {}).get("sections") or {}
    parts: list[str] = []
    for key in ("companyDescription", "jobDescription", "otherDetails"):
        html = sections.get(key, {})
        if isinstance(html, dict):
            html = html.get("text", "") or html.get("html", "") or ""
        if html:
            text = strip_html(str(html))
            if text:
                parts.append(text)
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# HN "Who is Hiring" via Algolia API
# ---------------------------------------------------------------------------

_HN_ML_KEYWORDS = frozenset([
    "machine learning", "data scientist", "data science", "ai engineer",
    "ml engineer", "nlp", "llm", "deep learning", "mlops", "data engineer",
    "artificial intelligence",
])

_HN_LOCATION_PATTERNS = (
    r"\bremote\b",
    r"\bhybrid\b",
    r"\bonsite\b",
    r"\bon-site\b",
    r"\bcanada\b",
    r"\bunited states\b",
    r"\busa\b",
    r"\bus\b",
    r"\bnew york\b",
    r"\bsan francisco\b",
    r"\btoronto\b",
    r"\bvancouver\b",
    r"\bmontreal\b",
    r"\blondon\b",
    r"\bberlin\b",
    r"\beurope\b",
    r"\buk\b",
)

_HN_METADATA_HINTS = (
    "full-time",
    "full time",
    "part-time",
    "part time",
    "contract",
    "internship",
    "intern",
)

_HN_GENERIC_TITLES = {"multiple roles", "multiple openings", "various"}


def _find_hn_hiring_thread() -> int | None:
    """Return the objectID of the most recent 'Ask HN: Who is Hiring?' thread."""
    try:
        resp = requests.get(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={
                "query": "Ask HN: Who is hiring?",
                "tags": "story,author_whoishiring",
                "hitsPerPage": 20,
            },
            timeout=15,
        )
        resp.raise_for_status()
        for hit in resp.json().get("hits", []):
            title = str(hit.get("title") or "")
            if (
                hit.get("author") == "whoishiring"
                and "Who is hiring?" in title
                and "Who wants to be hired?" not in title
            ):
                return int(hit["objectID"])
    except Exception as e:
        logger.warning("HN thread lookup failed: %s", e)
    return None


def fetch_hn_jobs() -> list[dict[str, Any]]:
    """Fetch ML/AI job comments from the latest HN 'Who is Hiring?' thread."""
    thread_id = _find_hn_hiring_thread()
    if thread_id is None:
        logger.warning("HN: could not find 'Who is Hiring?' thread")
        return []

    jobs: list[dict[str, Any]] = []
    page = 0
    while True:
        try:
            resp = requests.get(
                "https://hn.algolia.com/api/v1/search",
                params={
                    "tags": f"comment,story_{thread_id}",
                    "hitsPerPage": 1000,
                    "page": page,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("HN page %d fetch failed: %s", page, e)
            break

        hits = data.get("hits", [])
        for hit in hits:
            text = _hn_plain_text(hit.get("comment_text") or "").lower()
            if any(kw in text for kw in _HN_ML_KEYWORDS):
                jobs.append(normalize_hn(hit))

        nb_pages = data.get("nbPages", 1)
        page += 1
        if page >= nb_pages:
            break

    return jobs


def normalize_hn(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize an HN comment into a standard job dict."""
    text = _hn_plain_text(raw.get("comment_text") or "")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    first_line_plain = lines[0] if lines else ""
    segments = _hn_split_segments(first_line_plain)

    company, location = _hn_company_and_location(segments[0] if segments else "")
    company = company or "Unknown"

    location = _hn_extract_location(segments, location)
    title = _hn_extract_title(segments)

    return {
        "company": company,
        "title": title,
        "location": location,
        "url": f"https://news.ycombinator.com/item?id={raw['objectID']}",
        "posted": (raw.get("created_at") or "")[:10],
        "ats": "hn_hiring",
        "description": strip_html(text),
    }


def _hn_plain_text(html_text: str) -> str:
    if not html_text:
        return ""
    text = unescape(html_text)
    text = re.sub(r"(?i)<\s*(p|br|div|li)\b[^>]*>", "\n", text)
    text = re.sub(r"(?i)</\s*(p|div|li)\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ")
    lines = [re.sub(r"\s+", " ", line).strip(" \t|") for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _hn_split_segments(first_line_plain: str) -> list[str]:
    parts = re.split(r"\s+\|\s+|\s+[—–]\s+|\s+-\s+", first_line_plain)
    cleaned = [part.strip(" |") for part in parts if part.strip(" |")]
    return cleaned if cleaned else ([first_line_plain.strip()] if first_line_plain.strip() else [])


def _hn_is_location_segment(segment: str) -> bool:
    lowered = segment.lower()
    return any(re.search(pattern, lowered) for pattern in _HN_LOCATION_PATTERNS)


def _hn_is_metadata_segment(segment: str) -> bool:
    lowered = segment.lower()
    if any(hint in lowered for hint in _HN_METADATA_HINTS):
        return True
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return True
    if re.search(r"\$\d", lowered):
        return True
    return False


def _hn_company_and_location(segment: str) -> tuple[str, str]:
    cleaned = re.sub(r"^\s*hiring:\s*", "", segment, flags=re.I).strip()
    location = ""
    match = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", cleaned)
    if match:
        candidate_company = match.group(1).strip()
        candidate_location = match.group(2).strip()
        if _hn_is_location_segment(candidate_location):
            cleaned = candidate_company
            location = candidate_location
    return cleaned, location


def _hn_trim_title_context(segment: str) -> str:
    value = re.split(r"\bapply\b\s*:?", segment, maxsplit=1, flags=re.I)[0]
    value = re.split(r"https?://\S+", value, maxsplit=1)[0]
    return value.strip(" |-–—")


def _hn_extract_location(segments: list[str], initial_location: str) -> str:
    if initial_location:
        return initial_location
    for segment in segments[1:]:
        trimmed = _hn_trim_title_context(segment)
        if trimmed and _hn_is_location_segment(trimmed):
            return trimmed
    return ""


def _hn_extract_title(segments: list[str]) -> str:
    title = ""
    context = ""

    for segment in segments[1:]:
        trimmed = _hn_trim_title_context(segment)
        if not trimmed:
            continue
        if _hn_is_location_segment(trimmed):
            continue
        if _hn_is_metadata_segment(trimmed):
            continue
        if not title:
            title = trimmed
            continue
        if not context:
            context = trimmed
            break

    if title and context:
        context_lower = context.lower()
        if (
            len(context) <= 80
            and (
                any(keyword in context_lower for keyword in _HN_ML_KEYWORDS)
                or re.search(r"\b(ai|ml|llm|nlp|data)\b", context_lower)
            )
        ):
            title = f"{title} - {context}"

    if not title:
        fallback = segments[1] if len(segments) > 1 else (segments[0] if segments else "")
        title = _hn_trim_title_context(fallback) or "HN opportunity"

    return title[:120] if title else "HN opportunity"
