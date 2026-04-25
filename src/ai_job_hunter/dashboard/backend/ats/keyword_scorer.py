"""
keyword_scorer.py — Deterministic, LLM-free ATS keyword gate.

The Loop B orchestrator uses this as a cheap primary gate: a tailored resume must
cover enough of the job's required skills and have the conventional resume sections
before we spend tokens on the LLM screener.

The scorer is intentionally transparent — the constants below define the rubric,
and `missing_required` / `missing_preferred` feed directly back into the next
iteration's prompt as "address these gaps" hints.

Uses the canonical `SKILL_ALIASES` + `normalize_skill` from match_score.py as the
single source of truth for skill aliasing. DO NOT duplicate that table here.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from ai_job_hunter.match_score import SKILL_ALIASES, normalize_skill


def _aliases_for(canonical: str) -> set[str]:
    """Return the canonical skill plus every alias that normalizes to it."""
    forms = {canonical}
    for alias, target in SKILL_ALIASES.items():
        if target == canonical:
            forms.add(alias)
    return forms

# ---------------------------------------------------------------------------
# Rubric constants (tune carefully — these shape the pass threshold)
# ---------------------------------------------------------------------------

# Final score is a weighted sum of three normalized-to-[0,1] components.
_REQUIRED_WEIGHT = 0.70   # how well the resume covers required skills
_PREFERRED_WEIGHT = 0.15  # partial credit for preferred skills
_SECTION_WEIGHT = 0.15    # structural check: experience + skills present

# Canonical section names to look for (lowercased substring match on headings).
_EXPERIENCE_HINTS = (
    "experience", "employment", "work history", "professional history", "career",
)
_SKILLS_HINTS = (
    "skills", "technical skills", "technologies", "tech stack", "proficiencies",
)


@dataclass
class KeywordScore:
    pass_likelihood: int
    matched_required: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    matched_preferred: list[str] = field(default_factory=list)
    missing_preferred: list[str] = field(default_factory=list)
    weak_sections: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def feedback_hints(self) -> str:
        """Human-readable feedback for the next iteration's prompt."""
        parts: list[str] = []
        if self.missing_required:
            parts.append("Missing required skills: " + ", ".join(self.missing_required))
        if self.missing_preferred:
            parts.append("Missing preferred skills: " + ", ".join(self.missing_preferred))
        if self.weak_sections:
            parts.append("Weak/missing sections: " + ", ".join(self.weak_sections))
        if not parts:
            return "Keyword gate passed — no gaps."
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _compact(text: str) -> str:
    """Lowercase, strip everything non-alphanumeric. Used for fuzzy skill matching."""
    return _ALNUM_RE.sub("", text.lower())


def _skill_present(skill: str, resume_lower: str, resume_compact: str) -> bool:
    """
    Return True if `skill` appears in the resume.

    Two-step check:
      1. Word-boundary match on the normalized skill (handles "react", "kubernetes").
      2. Compact-form match (handles "Node.js" → "nodejs", "C++" → "c", "C#" → "c").
         The compact check uses word boundaries via surrounding non-alnum in the
         original, but since resume_compact has no punctuation we just check
         substring — false positives are possible here (e.g. "go" matching "going")
         so we only use compact when the skill is ≥3 chars after compacting.
    """
    canon = normalize_skill(skill).strip()
    if not canon:
        return False

    for form in _aliases_for(canon):
        form = form.strip().lower()
        if not form:
            continue
        pattern = re.escape(form)
        if re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", resume_lower):
            return True
        compact = _compact(form)
        if len(compact) >= 3 and compact in resume_compact:
            return True

    return False


def _has_section(resume_lower: str, hints: tuple[str, ...]) -> bool:
    """Heuristic: a resume section exists if any hint appears as a heading-like line."""
    for hint in hints:
        pattern = rf"(?im)^#{{1,6}}\s*{re.escape(hint)}\b"
        if re.search(pattern, resume_lower):
            return True
        pattern = rf"(?im)^\*\*\s*{re.escape(hint)}\b"
        if re.search(pattern, resume_lower):
            return True
        pattern = rf"(?m)^\s*{re.escape(hint)}\s*:?\s*$"
        if re.search(pattern, resume_lower):
            return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_resume_keywords(
    resume_md: str,
    required_skills: list[str],
    preferred_skills: list[str],
) -> KeywordScore:
    """
    Score how well `resume_md` covers the job's required/preferred skills + checks
    that conventional resume sections are present.

    Deterministic. No LLM. Typically runs in <10ms.
    """
    if not resume_md:
        return KeywordScore(
            pass_likelihood=0,
            missing_required=list(required_skills or []),
            missing_preferred=list(preferred_skills or []),
            weak_sections=["Experience", "Skills"],
        )

    resume_lower = resume_md.lower()
    resume_compact = _compact(resume_md)

    matched_req: list[str] = []
    missing_req: list[str] = []
    for skill in required_skills or []:
        if not skill:
            continue
        if _skill_present(skill, resume_lower, resume_compact):
            matched_req.append(skill)
        else:
            missing_req.append(skill)

    matched_pref: list[str] = []
    missing_pref: list[str] = []
    for skill in preferred_skills or []:
        if not skill:
            continue
        if _skill_present(skill, resume_lower, resume_compact):
            matched_pref.append(skill)
        else:
            missing_pref.append(skill)

    weak: list[str] = []
    if not _has_section(resume_lower, _EXPERIENCE_HINTS):
        weak.append("Experience")
    if not _has_section(resume_lower, _SKILLS_HINTS):
        weak.append("Skills")

    req_total = len(matched_req) + len(missing_req)
    pref_total = len(matched_pref) + len(missing_pref)
    req_cov = (len(matched_req) / req_total) if req_total else 1.0
    pref_cov = (len(matched_pref) / pref_total) if pref_total else 1.0
    section_cov = 1.0 - (0.5 * len(weak))
    section_cov = max(0.0, min(1.0, section_cov))

    raw = (
        _REQUIRED_WEIGHT * req_cov
        + _PREFERRED_WEIGHT * pref_cov
        + _SECTION_WEIGHT * section_cov
    )
    pass_likelihood = int(round(max(0.0, min(1.0, raw)) * 100))

    return KeywordScore(
        pass_likelihood=pass_likelihood,
        matched_required=matched_req,
        missing_required=missing_req,
        matched_preferred=matched_pref,
        missing_preferred=missing_pref,
        weak_sections=weak,
    )
