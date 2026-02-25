from __future__ import annotations

from difflib import SequenceMatcher
import re
from typing import Any


_ROLE_FAMILIES = {
    "data scientist",
    "ml engineer",
    "mlops engineer",
    "data engineer",
    "research scientist",
    "analyst",
    "other",
}

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


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _norm_skill(skill: str) -> str:
    s = _norm(skill)
    # Normalize punctuation/noise so acronym and expanded form can converge.
    s = re.sub(r"[/_-]+", " ", s)
    parenthetical = re.findall(r"\(([^)]{1,32})\)", s)
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    aliases = {
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
    for raw in parenthetical:
        key = re.sub(r"[^a-z0-9]+", "", raw.lower())
        if key in aliases:
            return aliases[key]
    if s in aliases:
        return aliases[s]
    tokens = [token for token in s.split(" ") if token]
    if len(tokens) >= 2:
        acronym = "".join(token[0] for token in tokens)
        if acronym in aliases:
            return aliases[acronym]
    return s


def _skill_compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _norm_skill(value))


def _skill_acronym(value: str) -> str:
    tokens = [token for token in _norm_skill(value).split(" ") if token]
    if len(tokens) < 2:
        return ""
    return "".join(token[0] for token in tokens)


def _as_skill_set(values: Any) -> set[str]:
    if not values:
        return set()
    if not isinstance(values, list):
        return set()
    return {_norm_skill(str(v)) for v in values if _norm_skill(str(v))}


def _skill_tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", _norm_skill(value)) if token}


def _skill_similarity(left: str, right: str) -> float:
    l = _norm_skill(left)
    r = _norm_skill(right)
    if not l or not r:
        return 0.0
    if l == r:
        return 1.0

    l_compact = _skill_compact(l)
    r_compact = _skill_compact(r)
    if l_compact and l_compact == r_compact:
        return 1.0

    # Generic acronym equivalence: "ci cd" <-> "cicd", "retrieval augmented generation" <-> "rag".
    l_acronym = _skill_acronym(l)
    r_acronym = _skill_acronym(r)
    if (l_acronym and l_acronym == r_compact) or (r_acronym and r_acronym == l_compact):
        return 1.0
    if l_acronym and r_acronym and l_acronym == r_acronym:
        return 1.0

    min_len = min(len(l), len(r))
    contains_ratio = 0.0
    if min_len >= 4 and (l in r or r in l):
        contains_ratio = min_len / max(len(l), len(r))

    l_tokens = _skill_tokens(l)
    r_tokens = _skill_tokens(r)
    token_ratio = 0.0
    if l_tokens and r_tokens:
        token_ratio = len(l_tokens & r_tokens) / max(1, len(l_tokens), len(r_tokens))

    char_ratio = SequenceMatcher(None, l, r).ratio()
    return max(contains_ratio, token_ratio, char_ratio)


def _skills_match(left: str, right: str, *, threshold: float = 0.8) -> bool:
    return _skill_similarity(left, right) >= threshold


def _fuzzy_overlap_ratio(target_skills: set[str], profile_skills: set[str]) -> float:
    if not target_skills or not profile_skills:
        return 0.0
    matched = 0
    for target in target_skills:
        if any(_skills_match(target, profile) for profile in profile_skills):
            matched += 1
    return matched / max(1, len(target_skills))


def _extract_title_seniority(title: str) -> str | None:
    t = _norm(title)
    if re.search(r"\b(intern|internship)\b", t):
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


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _band(score: int) -> str:
    if score >= 80:
        return "excellent"
    if score >= 65:
        return "good"
    if score >= 45:
        return "fair"
    return "low"


def _degree_level(text: str) -> int:
    normalized = _norm(text)
    for token, level in _DEGREE_LEVELS.items():
        if token in normalized:
            return level
    return 0


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


def compute_match_score(job: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    title = str(job.get("title", ""))
    enrichment = job.get("enrichment") or {}
    if not isinstance(enrichment, dict):
        enrichment = {}

    profile_skills = _as_skill_set(profile.get("skills"))
    req_skills = _as_skill_set(enrichment.get("required_skills"))
    pref_skills = _as_skill_set(enrichment.get("preferred_skills"))

    score = 50
    breakdown: dict[str, int] = {
        "base": 50,
        "skills_required": 0,
        "skills_preferred": 0,
        "seniority_bias": 0,
        "experience_bias": 0,
        "education_alignment": 0,
        "role_family_alignment": 0,
        "eligibility_penalty": 0,
    }
    reasons: list[str] = []

    # Skills: required and preferred overlap.
    if req_skills and profile_skills:
        req_ratio = _fuzzy_overlap_ratio(req_skills, profile_skills)
        req_points = int(round(28 * req_ratio))
        breakdown["skills_required"] = req_points
        score += req_points
        reasons.append(f"Required skill overlap: {int(req_ratio * 100)}%")
    if pref_skills and profile_skills:
        pref_ratio = _fuzzy_overlap_ratio(pref_skills, profile_skills)
        pref_points = int(round(12 * pref_ratio))
        breakdown["skills_preferred"] = pref_points
        score += pref_points
        reasons.append(f"Preferred skill overlap: {int(pref_ratio * 100)}%")

    # Seniority bias.
    seniority = _norm(str(enrichment.get("seniority") or "")) or _extract_title_seniority(title)
    if seniority in {"intern", "junior"}:
        breakdown["seniority_bias"] = 20
        score += 20
        reasons.append("Junior/entry-level seniority match")
    elif seniority == "mid":
        breakdown["seniority_bias"] = 8
        score += 8
    elif seniority in {"senior", "staff", "principal"}:
        penalty = -18 if seniority == "senior" else -25
        breakdown["seniority_bias"] = penalty
        score += penalty
        reasons.append("Seniority above target")

    # Experience bias (strongly prefers <=4 years requirement).
    years_min = enrichment.get("years_exp_min")
    years_max = enrichment.get("years_exp_max")
    candidate_years = int(profile.get("years_experience", 0) or 0)
    exp_points = 0
    if isinstance(years_min, int):
        if years_min <= 4:
            exp_points += 20
            reasons.append("Experience requirement is new-grad friendly")
        elif years_min >= 7:
            exp_points -= 25
        elif years_min >= 5:
            exp_points -= 10
        if candidate_years < years_min:
            exp_points -= min(20, (years_min - candidate_years) * 5)
            reasons.append("You are below minimum experience")
    if isinstance(years_max, int) and years_max <= 4:
        exp_points += 4
    exp_points = _clamp(exp_points, -25, 20)
    breakdown["experience_bias"] = exp_points
    score += exp_points

    # Education alignment.
    minimum_degree = _norm(str(enrichment.get("minimum_degree") or ""))
    if minimum_degree:
        required_level = _degree_level(minimum_degree)
        candidate_level = _candidate_degree_level(profile)
        edu_points = 0
        if required_level > 0:
            if candidate_level >= required_level:
                edu_points = 8
                reasons.append("Education requirement aligned")
            else:
                edu_points = -16
                reasons.append("Education below minimum requirement")
        breakdown["education_alignment"] = edu_points
        score += edu_points

    # Role-family alignment.
    role_family = _norm(str(enrichment.get("role_family") or ""))
    target_families = {_norm(v) for v in (profile.get("target_role_families") or []) if _norm(str(v))}
    role_points = 0
    if role_family and role_family in _ROLE_FAMILIES and target_families:
        if role_family in target_families:
            role_points = 8
        else:
            role_points = -8
    breakdown["role_family_alignment"] = role_points
    score += role_points

    # Eligibility penalty.
    visa_required = bool(profile.get("requires_visa_sponsorship", False))
    visa_sponsorship = _norm(str(enrichment.get("visa_sponsorship") or ""))
    canada_eligible = _norm(str(enrichment.get("canada_eligible") or ""))

    if canada_eligible == "no":
        breakdown["eligibility_penalty"] -= 45
        score -= 45
        reasons.append("Role is not Canada-eligible")

    if visa_required and visa_sponsorship == "no":
        breakdown["eligibility_penalty"] -= 40
        score -= 40
        reasons.append("Visa sponsorship mismatch")

    final_score = _clamp(int(round(score)), 0, 100)
    has_enrichment = bool(enrichment)
    has_skills = bool(req_skills or pref_skills)
    confidence = "high" if (has_enrichment and has_skills) else ("medium" if has_enrichment else "low")

    return {
        "score": final_score,
        "band": _band(final_score),
        "breakdown": breakdown,
        "reasons": reasons[:4],
        "confidence": confidence,
    }
