from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from ai_job_hunter.db import find_company_by_url_or_slug_segment, upsert_company_source
from ai_job_hunter.services.company_source_service import preview_import_companies
from ai_job_hunter.services.probe_service import probe_all

ATS_URL_TEMPLATES: dict[str, str] = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever": "https://api.lever.co/v0/postings/{slug}",
    "ashby": "https://jobs.ashbyhq.com/{slug}",
    "workable": "https://apply.workable.com/api/v3/accounts/{slug}/jobs",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{slug}/postings",
    "recruitee": "https://{slug}.recruitee.com/api/offers",
    "teamtailor": "https://{slug}.teamtailor.com/jobs",
}

_CORPORATE_SUFFIXES = {
    "inc",
    "llc",
    "ltd",
    "corp",
    "corporation",
    "technologies",
    "technology",
    "systems",
    "solutions",
    "group",
    "labs",
    "software",
}

_LOW_SIGNAL_ZERO_JOB_ATS = frozenset({"ashby", "workable", "smartrecruiters"})
_BLOCKED_SOURCE_MARKERS = frozenset({"hiring.cafe", "hiring cafe"})


def _blocked_source_reason(*values: str) -> str | None:
    for value in values:
        lowered = str(value or "").strip().lower()
        if not lowered:
            continue
        if any(marker in lowered for marker in _BLOCKED_SOURCE_MARKERS):
            return "blocked_source"
    return None


def _path_parts(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


def candidate_slugs(name: str) -> list[str]:
    slugs: list[str] = []
    seen: set[str] = set()

    def _add(value: str) -> None:
        cleaned = value.strip("-").strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            slugs.append(cleaned)

    def _variants(base: str) -> None:
        tokens = [token for token in re.split(r"[^a-z0-9]+", base.lower()) if token]
        if not tokens:
            return
        _add(re.sub(r"[^a-z0-9]", "", "".join(tokens)))
        _add("-".join(re.sub(r"[^a-z0-9]", "", token) for token in tokens if token))
        _add(re.sub(r"[^a-z0-9]", "", tokens[0]))

    # Preserve explicit slug-like input such as "valsoft-corp" before generating
    # looser variants like "valsoftcorp".
    _add(re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"))
    _variants(name)
    tokens = [token for token in re.split(r"[^a-z0-9]+", name.lower()) if token]
    stripped = [token for token in tokens if token not in _CORPORATE_SUFFIXES]
    if stripped and stripped != tokens:
        _variants(" ".join(stripped))
    return slugs


def extract_slug_from_careers_url(value: str) -> tuple[str, str] | None:
    raw = (value or "").strip()
    if not raw.startswith(("http://", "https://")):
        return None

    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower()
    if _blocked_source_reason(host):
        return None
    parts = _path_parts(parsed.path)

    if "apply.workable.com" in host and parts:
        slug = parts[0].strip()
        if slug and slug.lower() not in {"api", "jobs"}:
            return ("workable", slug)
    if host.endswith(".recruitee.com"):
        slug = host.split(".")[0].strip().lower()
        if slug:
            return ("recruitee", slug)
    if "greenhouse.io" in host and parts:
        slug = parts[0].strip()
        if slug and slug.lower() not in {"v1", "boards", "job-boards", "boards-api"}:
            return ("greenhouse", slug)
    if host.endswith("jobs.lever.co") and parts:
        slug = parts[0].strip()
        if slug:
            return ("lever", slug)
    if host.endswith("jobs.ashbyhq.com") and parts:
        slug = parts[0].strip()
        if slug:
            return ("ashby", slug)
    if host.endswith("apply.smartrecruiters.com") and parts:
        slug = parts[0].strip()
        if slug:
            return ("smartrecruiters", slug)
    if host.endswith(".teamtailor.com"):
        slug = host.split(".")[0].strip().lower()
        if slug:
            return ("teamtailor", slug)
    return None


def classify_probe_hit(hit: dict[str, Any]) -> str:
    jobs = int(hit.get("jobs", 0) or 0)
    if jobs > 0:
        return "active"
    ats_name = str(hit.get("ats") or "").strip().lower()
    if ats_name in _LOW_SIGNAL_ZERO_JOB_ATS:
        return "low_signal_zero_jobs"
    return "zero_jobs"


def probe_company_sources(query: str, extra_slugs: list[str] | None = None) -> dict[str, Any]:
    blocked_reason = _blocked_source_reason(query)
    if blocked_reason:
        return {
            "query": query,
            "company_name": "Hiring Cafe",
            "slugs": ["hiring-cafe"],
            "matches": [],
            "zero_job_matches": [
                {
                    "name": "Hiring Cafe",
                    "slug": "hiring-cafe",
                    "ats_type": "blocked",
                    "ats_url": "https://hiring.cafe",
                    "jobs": 0,
                    "low_signal": True,
                    "suppressed_reason": blocked_reason,
                }
            ],
            "inferred": {"ats_type": "blocked", "slug": "hiring-cafe"},
        }

    inferred = extract_slug_from_careers_url(query)
    company_name = query
    url_templates = dict(ATS_URL_TEMPLATES)
    supplied_slugs = [str(value).strip() for value in (extra_slugs or []) if str(value).strip()]
    if inferred:
        inferred_ats, inferred_slug = inferred
        if inferred_slug not in supplied_slugs:
            supplied_slugs.insert(0, inferred_slug)
        url_templates = {inferred_ats: ATS_URL_TEMPLATES[inferred_ats]}
        company_name = inferred_slug.replace("-", " ").title()

    slugs = candidate_slugs(company_name)
    for slug in supplied_slugs:
        if slug not in slugs:
            slugs.append(slug)

    hits = probe_all(slugs, url_templates)
    seen_urls: set[str] = set()
    matches: list[dict[str, Any]] = []
    zero_job_matches: list[dict[str, Any]] = []
    for hit in sorted(hits, key=lambda item: (item["ats"], item["slug"])):
        if hit["ats_url"] in seen_urls:
            continue
        seen_urls.add(hit["ats_url"])
        classification = classify_probe_hit(hit)
        target = matches if classification == "active" else zero_job_matches
        target.append({
            "name": company_name,
            "slug": str(hit["slug"]),
            "ats_type": str(hit["ats"]),
            "ats_url": str(hit["ats_url"]),
            "jobs": int(hit.get("jobs", 0) or 0),
            "low_signal": classification == "low_signal_zero_jobs",
            "suppressed_reason": None if classification == "active" else classification,
        })
    return {
        "query": query,
        "company_name": company_name,
        "slugs": slugs,
        "matches": matches,
        "zero_job_matches": zero_job_matches,
        "inferred": {"ats_type": inferred[0], "slug": inferred[1]} if inferred else None,
    }


def annotate_existing_company_sources(conn: Any, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    for entry in entries:
        slug = str(entry.get("slug") or "")
        ats_url = str(entry.get("ats_url") or "")
        existing_name = find_company_by_url_or_slug_segment(conn, slug, ats_url)
        annotated.append({**entry, "exists": bool(existing_name), "existing_name": existing_name})
    return annotated


def save_company_source(conn: Any, entry: dict[str, Any]) -> dict[str, Any]:
    name = str(entry.get("name") or "").strip()
    ats_type = str(entry.get("ats_type") or "").strip().lower()
    slug = str(entry.get("slug") or "").strip()
    if not name or not ats_type or not slug:
        raise ValueError("name, ats_type, and slug are required")
    ats_url = str(entry.get("ats_url") or ATS_URL_TEMPLATES[ats_type].format(slug=slug)).strip()
    blocked_reason = _blocked_source_reason(name, slug, ats_url)
    if blocked_reason:
        raise ValueError("Hiring Cafe is blocked and cannot be added as a company source")
    source = str(entry.get("source") or "manual").strip() or "manual"
    enabled = bool(entry.get("enabled", True))
    upsert_company_source(
        conn,
        name=name,
        ats_type=ats_type,
        ats_url=ats_url,
        slug=slug,
        enabled=enabled,
        source=source,
    )
    existing_name = find_company_by_url_or_slug_segment(conn, slug, ats_url)
    return {
        "name": name,
        "ats_type": ats_type,
        "ats_url": ats_url,
        "slug": slug,
        "enabled": enabled,
        "source": source,
        "existing_name": existing_name,
    }


def preview_company_source_import(conn: Any) -> dict[str, Any]:
    preview = preview_import_companies(conn)
    new_entries = annotate_existing_company_sources(conn, list(preview.get("new_entries") or []))
    return {
        "new_entries": new_entries,
        "skipped_duplicates": int(preview.get("skipped_duplicates") or 0),
    }


def apply_company_source_import(conn: Any) -> dict[str, Any]:
    preview = preview_company_source_import(conn)
    imported = 0
    for entry in preview["new_entries"]:
        if entry.get("exists"):
            continue
        save_company_source(
            conn,
            {
                "name": entry["name"],
                "ats_type": entry["ats_type"],
                "slug": entry["slug"],
                "ats_url": entry["ats_url"],
                "enabled": True,
                "source": f"import:{entry['source']}",
            },
        )
        imported += 1
    return {
        "imported": imported,
        "skipped_duplicates": int(preview["skipped_duplicates"]),
        "new_entries": preview["new_entries"],
    }
