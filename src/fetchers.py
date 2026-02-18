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
