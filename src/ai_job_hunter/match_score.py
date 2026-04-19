from __future__ import annotations

from bisect import bisect_left, bisect_right
from difflib import SequenceMatcher
import math
import re
from typing import Any

from ai_job_hunter.config import get_roles


_DEFAULT_ROLE_FAMILIES = {
    "data scientist",
    "ml engineer",
    "mlops engineer",
    "data engineer",
    "research scientist",
    "analyst",
    "other",
}


def _role_families() -> set[str]:
    configured = get_roles().get("families")
    if not configured:
        return set(_DEFAULT_ROLE_FAMILIES)
    return {str(v).strip().lower() for v in configured if str(v).strip()}


# Backwards-compatible alias; most callers use _role_families() now.
_ROLE_FAMILIES = _role_families()

_DEGREE_LEVELS: dict[str, int] = {
    "high school": 1,
    "diploma": 2,
    "associate": 3,
    "bachelor": 4,
    "masters": 5,
    "master": 5,
    "phd": 6,
    "doctorate": 6,
}

_SENIORITY_RANKS: dict[str, int] = {
    "intern": 0,
    "junior": 1,
    "mid": 2,
    "senior": 3,
    "staff": 4,
    "principal": 5,
}

_PERCENTILE_ANCHORS: list[tuple[float, int]] = [
    (0.0, 12),
    (0.10, 25),
    (0.50, 55),
    (0.85, 80),
    (0.97, 92),
    (1.0, 97),
]

SKILL_ALIASES: dict[str, str] = {
    "js": "javascript",
    "ts": "typescript",
    "k8s": "kubernetes",
    "tf": "tensorflow",
    "torch": "pytorch",
    "rag": "retrieval augmented generation",
    "llm": "large language model",
    "llms": "large language model",
    "nlp": "natural language processing",
    "cv": "computer vision",
    "ml": "machine learning",
    "genai": "generative ai",
    "cicd": "ci cd",
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _norm_title(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", _norm(text))
    return re.sub(r"\s+", " ", cleaned).strip()


def _norm_skill(skill: str) -> str:
    s = _norm(skill)
    s = re.sub(r"[/_-]+", " ", s)
    parenthetical = re.findall(r"\(([^)]{1,32})\)", s)
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for raw in parenthetical:
        key = re.sub(r"[^a-z0-9]+", "", raw.lower())
        if key in SKILL_ALIASES:
            return SKILL_ALIASES[key]
    if s in SKILL_ALIASES:
        return SKILL_ALIASES[s]
    tokens = [token for token in s.split(" ") if token]
    if len(tokens) >= 2:
        acronym = "".join(token[0] for token in tokens)
        if acronym in SKILL_ALIASES:
            return SKILL_ALIASES[acronym]
    return s


def normalize_skill(skill: str) -> str:
    return _norm_skill(skill)


def _skill_compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _norm_skill(value))


def _skill_acronym(value: str) -> str:
    tokens = [token for token in _norm_skill(value).split(" ") if token]
    if len(tokens) < 2:
        return ""
    return "".join(token[0] for token in tokens)


def _as_skill_set(values: Any) -> set[str]:
    if not values or not isinstance(values, list):
        return set()
    return {_norm_skill(str(v)) for v in values if _norm_skill(str(v))}


def _skill_tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", _norm_skill(value)) if token}


def _skill_similarity(left: str, right: str) -> float:
    a = _norm_skill(left)
    b = _norm_skill(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    a_compact = _skill_compact(a)
    b_compact = _skill_compact(b)
    if a_compact and a_compact == b_compact:
        return 1.0

    a_acronym = _skill_acronym(a)
    b_acronym = _skill_acronym(b)
    if (a_acronym and a_acronym == b_compact) or (b_acronym and b_acronym == a_compact):
        return 1.0
    if a_acronym and b_acronym and a_acronym == b_acronym:
        return 1.0

    min_len = min(len(a), len(b))
    contains_ratio = 0.0
    if min_len >= 4 and (a in b or b in a):
        contains_ratio = min_len / max(len(a), len(b))

    a_tokens = _skill_tokens(a)
    b_tokens = _skill_tokens(b)
    token_ratio = 0.0
    if a_tokens and b_tokens:
        token_ratio = len(a_tokens & b_tokens) / max(1, len(a_tokens), len(b_tokens))

    chab_ratio = SequenceMatcher(None, a, b).ratio()
    return max(contains_ratio, token_ratio, chab_ratio)


def _extract_title_seniority(title: str) -> str | None:
    t = _norm(title)
    if re.search(r"\b(intern|internship|co[\s-]?op)\b", t):
        return "intern"
    if re.search(r"\b(junior|entry|associate)\b", t):
        return "junior"
    if re.search(r"\b(mid|ii|level 2)\b", t):
        return "mid"
    if re.search(r"\b(senior|sr\.?)\b", t):
        return "senior"
    if re.search(r"\b(staff)\b", t):
        return "staff"
    if re.search(r"\b(principal|lead)\b", t):
        return "principal"
    return None


def _clamp(value: int | float, low: int, high: int) -> int:
    return max(low, min(high, int(round(value))))


def _band(score: int) -> str:
    if score >= 85:
        return "top_band"
    if score >= 70:
        return "strong"
    if score >= 50:
        return "viable"
    return "low"


def _degree_level(text: str) -> int:
    normalized = _norm(text)
    for token, level in _DEGREE_LEVELS.items():
        if token in normalized:
            return level
    return 0


def _title_similarity(left: str, right: str) -> float:
    a = _norm_title(left)
    b = _norm_title(right)
    if not a or not b:
        return 0.0
    a_seniority = _extract_title_seniority(left)
    b_seniority = _extract_title_seniority(right)
    if a_seniority and b_seniority and a_seniority != b_seniority:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return min(len(a), len(b)) / max(len(a), len(b))
    a_tokens = {token for token in a.split(" ") if token}
    b_tokens = {token for token in b.split(" ") if token}
    token_ratio = 0.0
    if a_tokens and b_tokens:
        token_ratio = len(a_tokens & b_tokens) / max(1, len(a_tokens), len(b_tokens))
    return max(token_ratio, SequenceMatcher(None, a, b).ratio())


def _candidate_degree_level(profile: dict[str, Any]) -> int:
    education = profile.get("education")
    levels: list[int] = []
    if isinstance(education, list):
        for item in education:
            if isinstance(item, dict):
                levels.append(_degree_level(str(item.get("degree") or "")))
    if not levels:
        levels.append(_degree_level(str(profile.get("degree") or "")))
    return max(levels) if levels else 0


def _best_overlap(skills: set[str], profile_skills: set[str]) -> float:
    if not skills or not profile_skills:
        return 0.0
    total = 0.0
    for target in skills:
        total += max((_skill_similarity(target, profile) for profile in profile_skills), default=0.0)
    return total / max(1, len(skills))


def _coverage_component(skills: set[str], profile_skills: set[str], missing_default: int) -> tuple[int, float]:
    if not skills:
        return missing_default, 0.0
    overlap = _best_overlap(skills, profile_skills)
    curved = math.pow(overlap, 0.9) if overlap > 0 else 0.0
    return _clamp(18 + (curved * 82), 0, 100), overlap


def _candidate_target_rank(profile: dict[str, Any]) -> int:
    desired_titles = profile.get("desired_job_titles") or []
    title_ranks = [
        _SENIORITY_RANKS[level]
        for value in desired_titles
        for level in [_extract_title_seniority(str(value))]
        if level in _SENIORITY_RANKS
    ]
    if title_ranks:
        return int(round(sum(title_ranks) / len(title_ranks)))
    years = int(profile.get("years_experience", 0) or 0)
    if years <= 1:
        return _SENIORITY_RANKS["junior"]
    if years <= 4:
        return _SENIORITY_RANKS["mid"]
    if years <= 7:
        return _SENIORITY_RANKS["senior"]
    return _SENIORITY_RANKS["staff"]


def _seniority_component(title: str, enrichment: dict[str, Any], profile: dict[str, Any]) -> tuple[int, int | None, bool]:
    seniority = _norm(str(enrichment.get("seniority") or "")) or _extract_title_seniority(title)
    if seniority not in _SENIORITY_RANKS:
        return 45, None, False

    job_rank = _SENIORITY_RANKS[seniority]
    target_rank = _candidate_target_rank(profile)
    distance = abs(job_rank - target_rank)
    score = _clamp(96 - (distance * 28), 8, 100)
    severe = seniority == "intern" or job_rank >= target_rank + 2
    return score, job_rank, severe


def _experience_component(enrichment: dict[str, Any], profile: dict[str, Any]) -> int:
    years_min = enrichment.get("years_exp_min")
    years_max = enrichment.get("years_exp_max")
    if years_min is None and years_max is None:
        return 45

    candidate_years = int(profile.get("years_experience", 0) or 0)
    score = 92
    try:
        if years_min is not None:
            years_min = int(years_min)
            if candidate_years < years_min:
                score -= min(70, (years_min - candidate_years) * 16)
            else:
                score -= min(12, max(0, candidate_years - years_min) * 2)
        if years_max is not None:
            years_max = int(years_max)
            if candidate_years > years_max:
                score -= min(35, (candidate_years - years_max) * 7)
    except Exception:
        return 45
    return _clamp(score, 8, 100)


def _desired_title_component(job_title: str, desired_titles: Any) -> tuple[int, float]:
    titles = [str(value).strip() for value in (desired_titles or []) if str(value).strip()]
    if not job_title.strip() or not titles:
        return 50, 0.0
    best = max((_title_similarity(job_title, title) for title in titles), default=0.0)
    return _clamp(20 + (best * 80), 0, 100), best


def _education_component(enrichment: dict[str, Any], profile: dict[str, Any]) -> int:
    minimum_degree = _norm(str(enrichment.get("minimum_degree") or ""))
    if not minimum_degree:
        return 50
    required_level = _degree_level(minimum_degree)
    candidate_level = _candidate_degree_level(profile)
    if required_level <= 0:
        return 50
    if candidate_level >= required_level:
        return 88
    gap = required_level - candidate_level
    return _clamp(50 - (gap * 22), 4, 88)


def _role_family_component(enrichment: dict[str, Any], profile: dict[str, Any]) -> int:
    role_family = _norm(str(enrichment.get("role_family") or ""))
    target_families = {
        _norm(str(v))
        for v in (profile.get("target_role_families") or [])
        if _norm(str(v))
    }
    if not role_family or role_family not in _role_families():
        return 50
    if not target_families:
        return 55
    return 88 if role_family in target_families else 28


def compute_match_score(job: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    title = str(job.get("title", ""))
    enrichment = job.get("enrichment") or {}
    if not isinstance(enrichment, dict):
        enrichment = {}

    profile_skills = _as_skill_set(profile.get("skills"))
    req_skills = _as_skill_set(enrichment.get("required_skills"))
    pref_skills = _as_skill_set(enrichment.get("preferred_skills"))

    required_score, required_overlap = _coverage_component(req_skills, profile_skills, 38)
    preferred_score, preferred_overlap = _coverage_component(pref_skills, profile_skills, 45)
    title_score, title_alignment = _desired_title_component(title, profile.get("desired_job_titles"))
    experience_score = _experience_component(enrichment, profile)
    seniority_score, seniority_rank, severe_seniority_mismatch = _seniority_component(title, enrichment, profile)
    education_score = _education_component(enrichment, profile)
    role_family_score = _role_family_component(enrichment, profile)

    weighted = (
        (required_score * 0.40)
        + (preferred_score * 0.08)
        + (title_score * 0.12)
        + (experience_score * 0.14)
        + (seniority_score * 0.12)
        + (role_family_score * 0.08)
        + (education_score * 0.06)
    )

    has_enrichment = bool(enrichment)
    has_structured_signals = bool(
        req_skills
        or pref_skills
        or enrichment.get("years_exp_min") is not None
        or enrichment.get("role_family")
        or enrichment.get("seniority")
    )
    if not has_enrichment:
        weighted *= 0.74
    elif not has_structured_signals:
        weighted *= 0.84

    eligibility_block = False
    visa_required = bool(profile.get("requires_visa_sponsorship", False))
    visa_sponsorship = _norm(str(enrichment.get("visa_sponsorship") or ""))
    canada_eligible = _norm(str(enrichment.get("canada_eligible") or ""))
    suppressor_cap = 100
    reasons: list[str] = []

    if canada_eligible == "no":
        eligibility_block = True
        suppressor_cap = min(suppressor_cap, 22)
        reasons.append("Role is not Canada eligible")
    if visa_required and visa_sponsorship in {"no", "not available"}:
        eligibility_block = True
        suppressor_cap = min(suppressor_cap, 26)
        reasons.append("Visa sponsorship does not match your profile needs")
    if severe_seniority_mismatch:
        suppressor_cap = min(suppressor_cap, 34)
        reasons.append("Role seniority sits well outside your current target range")

    raw_score = _clamp(weighted, 0, 100)
    if suppressor_cap < 100:
        raw_score = min(raw_score, suppressor_cap)

    breakdown: dict[str, int] = {
        "skills_required": required_score,
        "skills_preferred": preferred_score,
        "desired_title_alignment": title_score,
        "experience_fit": experience_score,
        "seniority_fit": seniority_score,
        "education_alignment": education_score,
        "role_family_alignment": role_family_score,
        "required_skill_overlap": _clamp(required_overlap * 100, 0, 100),
        "preferred_skill_overlap": _clamp(preferred_overlap * 100, 0, 100),
        "title_similarity": _clamp(title_alignment * 100, 0, 100),
        "suppressor_eligibility": 1 if eligibility_block else 0,
        "suppressor_seniority": 1 if severe_seniority_mismatch else 0,
        "suppressed_score_cap": suppressor_cap if suppressor_cap < 100 else 0,
        "job_seniority_rank": seniority_rank if seniority_rank is not None else -1,
    }

    if required_overlap >= 0.7:
        reasons.insert(0, f"Strong required-skill coverage ({_clamp(required_overlap * 100, 0, 100)}%)")
    elif req_skills:
        reasons.append(f"Required-skill coverage is only {_clamp(required_overlap * 100, 0, 100)}%")

    if title_alignment >= 0.75:
        reasons.append("Job title lines up well with your target titles")
    if experience_score >= 80:
        reasons.append("Experience requirement is close to your background")
    elif experience_score <= 35:
        reasons.append("Experience requirement is materially above your current background")
    if role_family_score >= 80:
        reasons.append("Role family aligns with your target track")

    confidence = "low"
    if has_enrichment and has_structured_signals and req_skills:
        confidence = "high"
    elif has_enrichment:
        confidence = "medium"

    return {
        "score": raw_score,
        "raw_score": raw_score,
        "band": _band(raw_score),
        "breakdown": breakdown,
        "reasons": reasons[:4],
        "confidence": confidence,
        "suppressed": suppressor_cap < 100,
    }


def _quantile(values: list[int], percentile: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    position = percentile * (len(values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(values[lower])
    lower_value = values[lower]
    upper_value = values[upper]
    return lower_value + ((upper_value - lower_value) * (position - lower))


def _interpolate_anchors(position: float, anchors: list[tuple[float, int]]) -> float:
    if position <= anchors[0][0]:
        return float(anchors[0][1])
    for index in range(1, len(anchors)):
        left_pos, left_value = anchors[index - 1]
        right_pos, right_value = anchors[index]
        if position <= right_pos:
            span = max(1e-9, right_pos - left_pos)
            ratio = (position - left_pos) / span
            return left_value + ((right_value - left_value) * ratio)
    return float(anchors[-1][1])


def calibrate_match_scores(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items:
        return []

    cohort_values = sorted(
        int(item.get("raw_score", item.get("score", 0)) or 0)
        for item in items
        if not bool(item.get("suppressed")) and str(item.get("status") or "") != "rejected"
    )
    if not cohort_values:
        cohort_values = sorted(int(item.get("raw_score", item.get("score", 0)) or 0) for item in items)

    median = _quantile(cohort_values, 0.5)
    q10 = _quantile(cohort_values, 0.10)
    q90 = _quantile(cohort_values, 0.90)
    spread = max(8.0, q90 - q10)

    calibrated: list[dict[str, Any]] = []
    for item in items:
        raw_score = int(item.get("raw_score", item.get("score", 0)) or 0)
        left = bisect_left(cohort_values, raw_score)
        right = bisect_right(cohort_values, raw_score)
        midpoint = (left + right - 1) / 2 if right > left else left
        percentile = midpoint / max(1, len(cohort_values) - 1) if len(cohort_values) > 1 else 1.0
        percentile_score = _interpolate_anchors(percentile, _PERCENTILE_ANCHORS)
        distance_bonus = ((raw_score - median) / spread) * 8.0
        rank_score = _clamp(percentile_score + distance_bonus, 8, 99)
        if bool(item.get("suppressed")):
            cap = int((item.get("breakdown") or {}).get("suppressed_score_cap") or 34)
            rank_score = min(rank_score, max(18, cap + 8))

        item["score"] = rank_score
        item["band"] = _band(rank_score)
        calibrated.append(item)
    return calibrated
