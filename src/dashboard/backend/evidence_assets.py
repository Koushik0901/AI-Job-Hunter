from __future__ import annotations

from typing import Any


def _clean_text(value: Any) -> str:
    return str(value or "").replace("\x00", "").strip()


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = _clean_text(item)
        if text:
            out.append(text)
    return out


def _dedupe_preserve(values: list[str], *, limit: int | None = None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _clean_text(item)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(text)
        if limit is not None and len(out) >= limit:
            break
    return out


def _has_substance(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_has_substance(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_substance(item) for item in value)
    return bool(_clean_text(value))


def _normalize_skill_entry(item: Any) -> str:
    if isinstance(item, str):
        return _clean_text(item)
    if isinstance(item, dict):
        name = _clean_text(item.get("name"))
        if name:
            return name
        keywords = item.get("keywords")
        if isinstance(keywords, list):
            joined = ", ".join(_dedupe_preserve(_as_string_list(keywords), limit=4))
            if joined:
                return joined
        return _clean_text(item.get("category"))
    return ""


def _normalize_resume_work_item(item: dict[str, Any]) -> dict[str, Any]:
    highlights = _as_string_list(item.get("highlights"))
    summary = _clean_text(item.get("summary"))
    return {
        "company": _clean_text(item.get("name") or item.get("company")),
        "position": _clean_text(item.get("position") or item.get("role") or item.get("title")),
        "location": _clean_text(item.get("location")),
        "website": _clean_text(item.get("website")),
        "start_date": _clean_text(item.get("startDate") or item.get("start_date")),
        "end_date": _clean_text(item.get("endDate") or item.get("end_date")),
        "summary": summary,
        "highlights": highlights,
    }


def _normalize_resume_project_item(item: dict[str, Any]) -> dict[str, Any]:
    highlights = _as_string_list(item.get("highlights"))
    summary = _clean_text(item.get("summary") or item.get("description"))
    keywords_source = item.get("keywords") if isinstance(item.get("keywords"), list) else []
    keywords = [skill for skill in (_normalize_skill_entry(keyword) for keyword in keywords_source) if skill]
    return {
        "title": _clean_text(item.get("name") or item.get("title")),
        "role": _clean_text(item.get("role")),
        "summary": summary,
        "highlights": highlights,
        "keywords": keywords,
        "website": _clean_text(item.get("website")),
        "time": _clean_text(item.get("startDate") or item.get("date") or item.get("period")),
    }


def derive_fallback_evidence_assets(
    candidate_profile: dict[str, Any] | None,
    resume_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    candidate = candidate_profile if isinstance(candidate_profile, dict) else {}
    resume = resume_profile if isinstance(resume_profile, dict) else {}
    baseline = resume.get("baseline_resume_json") if isinstance(resume.get("baseline_resume_json"), dict) else {}
    basics = baseline.get("basics") if isinstance(baseline.get("basics"), dict) else {}

    candidate_skills = _as_string_list(candidate.get("skills"))
    role_families = _as_string_list(candidate.get("target_role_families"))
    education_entries = candidate.get("education") if isinstance(candidate.get("education"), list) else []

    baseline_skills_source = baseline.get("skills") if isinstance(baseline.get("skills"), list) else []
    baseline_skills = [skill for skill in (_normalize_skill_entry(item) for item in baseline_skills_source) if skill]
    merged_skills = _dedupe_preserve(candidate_skills + baseline_skills, limit=80)

    work_items_source = baseline.get("work") if isinstance(baseline.get("work"), list) else []
    work_items = [
        normalized
        for normalized in (_normalize_resume_work_item(item) for item in work_items_source if isinstance(item, dict))
        if _has_substance(normalized)
    ]

    project_items_source = baseline.get("projects") if isinstance(baseline.get("projects"), list) else []
    project_items = [
        normalized
        for normalized in (_normalize_resume_project_item(item) for item in project_items_source if isinstance(item, dict))
        if _has_substance(normalized)
    ]

    baseline_education = baseline.get("education") if isinstance(baseline.get("education"), list) else []
    normalized_education: list[dict[str, Any]] = []
    for item in education_entries:
        if not isinstance(item, dict):
            continue
        degree = _clean_text(item.get("degree"))
        field = _clean_text(item.get("field"))
        if degree:
            normalized_education.append({"degree": degree, "field": field})
    for item in baseline_education:
        if not isinstance(item, dict):
            continue
        degree = _clean_text(item.get("studyType") or item.get("degree") or item.get("area"))
        institution = _clean_text(item.get("institution"))
        if degree or institution:
            normalized_education.append({"degree": degree or institution, "field": institution if degree else ""})

    basics_summary = _clean_text(basics.get("summary"))
    basics_headline = _clean_text(basics.get("headline") or basics.get("label"))

    evidence_context = {
        "candidate_profile": {
            "years_experience": int(candidate.get("years_experience") or 0),
            "skills": merged_skills,
            "target_role_families": role_families,
            "requires_visa_sponsorship": bool(candidate.get("requires_visa_sponsorship")),
            "education": normalized_education,
        },
        "resume_basics": {
            "name": _clean_text(basics.get("name")),
            "headline": basics_headline,
            "summary": basics_summary,
            "location": _clean_text(basics.get("location")),
        },
        "work_experience": work_items,
        "projects": project_items,
        "education": normalized_education,
    }

    brag_sections: list[str] = []
    if basics_summary:
        brag_sections.append(f"Summary\n{basics_summary}")
    for item in work_items[:6]:
        header = " - ".join(part for part in [item.get("position"), item.get("company")] if part)
        bullets = [text for text in ([item.get("summary")] + list(item.get("highlights") or [])) if _clean_text(text)]
        if header and bullets:
            brag_sections.append(header + "\n" + "\n".join(f"- {bullet}" for bullet in bullets[:5]))
    for item in project_items[:6]:
        header = _clean_text(item.get("title") or item.get("role"))
        bullets = [text for text in ([item.get("summary")] + list(item.get("highlights") or [])) if _clean_text(text)]
        if header and bullets:
            brag_sections.append(header + "\n" + "\n".join(f"- {bullet}" for bullet in bullets[:4]))

    project_cards = [
        {
            "title": item.get("title") or item.get("role") or "Project",
            "role": item.get("role") or "",
            "summary": item.get("summary") or "",
            "highlights": list(item.get("highlights") or []),
            "tags": list(item.get("keywords") or []),
            "website": item.get("website") or "",
            "time": item.get("time") or "",
        }
        for item in project_items[:12]
    ]
    if not project_cards:
        project_cards = [
            {
                "title": " - ".join(part for part in [item.get("position"), item.get("company")] if part) or "Experience",
                "role": item.get("position") or "",
                "summary": item.get("summary") or "",
                "highlights": list(item.get("highlights") or []),
                "tags": [],
                "website": item.get("website") or "",
                "time": " - ".join(part for part in [item.get("start_date"), item.get("end_date")] if part),
            }
            for item in work_items[:8]
        ]

    return {
        "evidence_context": evidence_context,
        "brag_document_markdown": "\n\n".join(section for section in brag_sections if _clean_text(section)),
        "project_cards": project_cards,
        "do_not_claim": [],
    }


def prepare_candidate_evidence_assets(
    explicit_assets: dict[str, Any] | None,
    candidate_profile: dict[str, Any] | None,
    resume_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    explicit = explicit_assets if isinstance(explicit_assets, dict) else {}
    fallback = derive_fallback_evidence_assets(candidate_profile, resume_profile)

    evidence_context = explicit.get("evidence_context") if isinstance(explicit.get("evidence_context"), dict) else {}
    brag_document_markdown = _clean_text(explicit.get("brag_document_markdown"))
    project_cards = explicit.get("project_cards") if isinstance(explicit.get("project_cards"), list) else []
    do_not_claim = _as_string_list(explicit.get("do_not_claim"))

    prepared = {
        "evidence_context": evidence_context if _has_substance(evidence_context) else fallback["evidence_context"],
        "brag_document_markdown": brag_document_markdown or str(fallback.get("brag_document_markdown") or ""),
        "project_cards": project_cards if project_cards else list(fallback.get("project_cards") or []),
        "do_not_claim": do_not_claim,
    }
    updated_at = explicit.get("updated_at")
    if updated_at is not None:
        prepared["updated_at"] = updated_at
    return prepared
