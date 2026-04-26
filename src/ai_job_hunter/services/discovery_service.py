from __future__ import annotations

import re
from urllib.parse import urlparse

import requests

# Ordered: most specific first to avoid false matches
_PATH_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"boards-api\.greenhouse\.io/v1/boards/([A-Za-z0-9_-]+)/jobs"), "greenhouse"),
    (re.compile(r"job-boards\.greenhouse\.io/([A-Za-z0-9_-]+)"), "greenhouse"),
    (re.compile(r"boards\.greenhouse\.io/([A-Za-z0-9_-]+)"), "greenhouse"),
    (re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_-]+)"), "ashby"),
    (re.compile(r"jobs\.lever\.co/([A-Za-z0-9_-]+)"), "lever"),
    (re.compile(r"apply\.workable\.com/([A-Za-z0-9_-]+)"), "workable"),
]

_SUBDOMAIN_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^([a-z0-9-]+)\.recruitee\.com$"), "recruitee"),
    (re.compile(r"^([a-z0-9-]+)\.teamtailor\.com$"), "teamtailor"),
]

_DISCOVERY_ATS_SITES = [
    "site:jobs.ashbyhq.com",
    "site:job-boards.greenhouse.io",
    "site:jobs.lever.co",
]


def normalize_url(url: str) -> tuple[str, str] | None:
    """Map a job board URL to (ats_type, slug) or None if unrecognized."""
    for pattern, ats_type in _PATH_PATTERNS:
        m = pattern.search(url)
        if m:
            slug = m.group(1).rstrip("/")
            if slug:
                return (ats_type, slug)

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    for pattern, ats_type in _SUBDOMAIN_PATTERNS:
        m = pattern.match(host)
        if m:
            return (ats_type, m.group(1))

    return None


def build_discovery_queries(profile: dict) -> list[str]:
    """Generate Brave search queries from candidate profile fields."""
    titles: list[str] = profile.get("desired_job_titles") or []
    if not titles:
        return []

    role_term = " OR ".join(f'"{t}"' for t in titles)

    location_parts: list[str] = []
    country = (profile.get("country") or "").strip()
    if country:
        location_parts.append(country)
    work_mode = (profile.get("preferred_work_mode") or "").lower()
    if work_mode in ("remote", "hybrid"):
        location_parts.append("remote")
    location_term = " OR ".join(location_parts)

    queries: list[str] = []
    for site in _DISCOVERY_ATS_SITES:
        q = f"{site} {role_term}"
        if location_term:
            q += f" {location_term}"
        queries.append(q)

    return queries


def brave_search(query: str, api_key: str, count: int = 10) -> list[str]:
    """Call Brave Web Search API and return result URLs. Returns [] on any error."""
    try:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            params={"q": query, "count": count},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("web", {}).get("results", [])
        return [r["url"] for r in results if "url" in r]
    except Exception:
        return []
