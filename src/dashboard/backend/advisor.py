from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def clamp(value: int | float, lower: int = 0, upper: int = 100) -> int:
    return max(lower, min(upper, int(round(value))))


def normalize_skill(value: str) -> str:
    normalized = value.strip().lower()
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
    compact = "".join(ch for ch in normalized if ch.isalnum())
    return aliases.get(compact, normalized)


def overlap_skills(left: list[str], right: list[str]) -> tuple[list[str], list[str]]:
    normalized_right = {normalize_skill(item): item for item in right if item.strip()}
    matched: list[str] = []
    missing: list[str] = []
    for item in left:
        key = normalize_skill(item)
        if key in normalized_right:
            matched.append(item.strip())
        else:
            missing.append(item.strip())
    return matched, missing


def _evaluation_guidance(
    *,
    recommendation: str,
    fit_score: int,
    urgency_score: int,
    friction_score: int,
    confidence_score: int,
    reasons: list[str],
) -> dict[str, Any]:
    if recommendation == "apply_now":
        return {
            "guidance_mode": "evaluation",
            "guidance_title": "Strong candidate to apply",
            "guidance_summary": "The fit and urgency are strong enough to move this role into the apply queue.",
            "guidance_reasons": reasons[:4] or [
                "The role has enough signal to justify moving it into the apply queue.",
            ],
            "next_best_action": "Apply now.",
            "health_label": "ready",
        }
    if recommendation == "review_manually":
        return {
            "guidance_mode": "evaluation",
            "guidance_title": "Worth a closer review",
            "guidance_summary": "The signals are mixed, so give the posting a quick manual check before you commit.",
            "guidance_reasons": reasons[:4] or [
                "The role has mixed signals and should be reviewed before acting.",
            ],
            "next_best_action": "Review the posting details before applying.",
            "health_label": "watch",
        }
    if recommendation == "hold":
        hold_reasons = reasons[:4] or [
            "The role is not urgent enough to move forward right now.",
        ]
        if fit_score >= 60 and urgency_score < 50:
            hold_reasons.insert(0, "The fit is acceptable, but the posting no longer looks urgent.")
        return {
            "guidance_mode": "evaluation",
            "guidance_title": "Worth holding for now",
            "guidance_summary": "This role looks more like a future option than an immediate move.",
            "guidance_reasons": hold_reasons[:4],
            "next_best_action": "Hold it and revisit later.",
            "health_label": "hold",
        }
    archive_reasons = reasons[:4] or [
        "The fit or friction profile is too weak to keep this role in active rotation.",
    ]
    if friction_score >= 50:
        archive_reasons.insert(0, "Application friction is high enough to make this a poor use of time.")
    elif confidence_score < 45:
        archive_reasons.insert(0, "The model confidence is too low to justify active attention.")
    return {
        "guidance_mode": "evaluation",
        "guidance_title": "Archive candidate",
        "guidance_summary": "The role is too weak or too costly to keep in the active queue.",
        "guidance_reasons": archive_reasons[:4],
        "next_best_action": "Archive it.",
        "health_label": "archive",
    }


def _stage_guidance(
    *,
    status: str,
    recommendation: str,
    fit_score: int,
    urgency_score: int,
    friction_score: int,
    confidence_score: int,
    reasons: list[str],
) -> dict[str, Any]:
    normalized_status = status.strip().lower()

    def _confidence_reason() -> str | None:
        if confidence_score < 50:
            return "Treat the scoring model as directional and lean on the concrete job facts."
        return None

    if normalized_status == "applied":
        stage_reasons = ["The application is already submitted."]
        if fit_score >= 75:
            stage_reasons.append("Your profile overlap is still strong enough to justify keeping the role warm.")
        elif fit_score < 55:
            stage_reasons.append("Use the response window to decide whether this is still worth proactive follow-up.")
        if urgency_score >= 70:
            stage_reasons.append("The posting is still fresh enough to justify a timely follow-up.")
        elif urgency_score < 45:
            stage_reasons.append("The posting is aging, so the next touchpoint matters more.")
        confidence_reason = _confidence_reason()
        if confidence_reason:
            stage_reasons.append(confidence_reason)
        return {
            "guidance_mode": "stage_narrative",
            "guidance_title": "Application in flight",
            "guidance_summary": "Keep a light follow-up cadence and stay ready to respond if the role moves forward.",
            "guidance_reasons": stage_reasons[:4],
            "next_best_action": "Follow up when the role goes quiet.",
            "health_label": "in_process",
        }
    if normalized_status == "interviewing":
        stage_reasons = ["The role is already in an active interview loop."]
        if fit_score >= 75:
            stage_reasons.append("Use your strongest evidence and matched skills as the center of interview prep.")
        elif fit_score < 55:
            stage_reasons.append("Use the drawer as a prep checklist for the areas that still need tighter examples.")
        if friction_score >= 50:
            stage_reasons.append("There are still some friction points worth preparing for.")
        confidence_reason = _confidence_reason()
        if confidence_reason:
            stage_reasons.append(confidence_reason)
        return {
            "guidance_mode": "stage_narrative",
            "guidance_title": "Interview loop active",
            "guidance_summary": "Use the remaining requirements as prep prompts and keep notes ready for the next round.",
            "guidance_reasons": stage_reasons[:4],
            "next_best_action": "Prepare for the next round and capture follow-up questions.",
            "health_label": "active",
        }
    if normalized_status == "offer":
        stage_reasons = ["This role is in decision mode now."]
        if fit_score >= 75:
            stage_reasons.append("The original fit looked strong enough to make the offer worth comparing seriously.")
        elif fit_score < 55:
            stage_reasons.append("The fit was only moderate, so focus on scope and compensation trade-offs.")
        if friction_score >= 50:
            stage_reasons.append("There may still be friction points to weigh before accepting.")
        confidence_reason = _confidence_reason()
        if confidence_reason:
            stage_reasons.append(confidence_reason)
        return {
            "guidance_mode": "stage_narrative",
            "guidance_title": "Offer stage",
            "guidance_summary": "Compare compensation, scope, timing, and any remaining risk before you decide.",
            "guidance_reasons": stage_reasons[:4],
            "next_best_action": "Review the terms and decide whether to accept or negotiate.",
            "health_label": "decision_time",
        }
    return _evaluation_guidance(
        recommendation=recommendation,
        fit_score=fit_score,
        urgency_score=urgency_score,
        friction_score=friction_score,
        confidence_score=confidence_score,
        reasons=reasons,
    )


def build_recommendation(
    *,
    profile: dict[str, Any],
    job: dict[str, Any],
    source_quality_score: int = 50,
    role_quality_score: int = 50,
    override: str | None = None,
    override_note: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    posted_raw = str(job.get("posted") or "").strip()
    age_days = 14
    try:
        if posted_raw:
            posted_dt = datetime.fromisoformat(posted_raw).replace(tzinfo=timezone.utc)
            age_days = max(0, (now - posted_dt).days)
    except Exception:
        age_days = 14

    match_score = int(job.get("match_score") or 0)
    fit_score = clamp(match_score)
    urgency = 85 - (age_days * 5)
    if str(job.get("status") or "") == "staging":
        urgency += 12
    if bool(job.get("staging_overdue")):
        urgency += 18
    urgency_score = clamp(urgency, 10, 100)

    friction = 12
    enrichment = job.get("enrichment") if isinstance(job.get("enrichment"), dict) else {}
    red_flags = list(enrichment.get("red_flags") or [])
    friction += min(len(red_flags) * 9, 27)
    if not enrichment or str(enrichment.get("enrichment_status") or "").lower() != "ok":
        friction += 12
    if bool(profile.get("requires_visa_sponsorship")) and str(enrichment.get("visa_sponsorship") or "").strip().lower() in {"no", "not available"}:
        friction += 20
    years_min = enrichment.get("years_exp_min")
    years_exp = int(profile.get("years_experience") or 0)
    try:
        if years_min is not None and int(years_min) > years_exp + 2:
            friction += 18
    except Exception:
        pass
    friction_score = clamp(friction)

    confidence = 38
    if match_score > 0:
        confidence += 18
    if enrichment:
        confidence += 18
    if str(enrichment.get("enrichment_status") or "").lower() == "ok":
        confidence += 12
    if job.get("desired_title_match"):
        confidence += 10
    if source_quality_score != 50 or role_quality_score != 50:
        confidence += 6
    confidence_score = clamp(confidence)

    likelihood = (
        (fit_score * 0.58)
        + (urgency_score * 0.22)
        + (confidence_score * 0.12)
        + ((source_quality_score - 50) * 0.22)
        + ((role_quality_score - 50) * 0.10)
        - (friction_score * 0.35)
    )
    interview_likelihood_score = clamp(likelihood)

    recommendation = None
    status = str(job.get("status") or job.get("tracking_status") or "")
    if override:
        recommendation = override
    elif status in {"offer", "interviewing", "applied"}:
        recommendation = "hold"
    elif status == "rejected":
        recommendation = "archive"
    elif interview_likelihood_score >= 78:
        recommendation = "apply_now"
    elif interview_likelihood_score >= 55:
        recommendation = "review_manually"
    elif interview_likelihood_score >= 35:
        recommendation = "hold"
    else:
        recommendation = "archive"

    reasons: list[str] = []
    if override:
        reasons.append(f"Manual override: {override.replace('_', ' ')}.")
        if override_note:
            reasons.append(override_note.strip())
    else:
        if fit_score >= 80:
            reasons.append("Strong fit based on current profile and enrichment.")
        elif fit_score >= 60:
            reasons.append("Moderate fit worth a closer review.")
        else:
            reasons.append("Fit signals are weak relative to your target profile.")
        if age_days <= 3:
            reasons.append("Fresh posting with a higher chance of active review.")
        elif age_days >= 14:
            reasons.append("Older posting reduces urgency and likely response rate.")
        if job.get("desired_title_match"):
            reasons.append("Title aligns with your desired job titles.")
        if source_quality_score >= 60:
            reasons.append("This ATS/source has converted relatively well for you.")
        elif source_quality_score <= 40:
            reasons.append("This ATS/source has underperformed in your history.")
        if friction_score >= 50:
            reasons.append("Application friction is elevated because of missing evidence or role constraints.")
        elif red_flags:
            reasons.append("There are some red flags to review before applying.")

    guidance = _stage_guidance(
        status=status,
        recommendation=str(recommendation or "archive"),
        fit_score=fit_score,
        urgency_score=urgency_score,
        friction_score=friction_score,
        confidence_score=confidence_score,
        reasons=reasons,
    )

    return {
        "fit_score": fit_score,
        "interview_likelihood_score": interview_likelihood_score,
        "urgency_score": urgency_score,
        "friction_score": friction_score,
        "confidence_score": confidence_score,
        "recommendation": recommendation,
        "recommendation_reasons": reasons[:4],
        **guidance,
    }


def build_application_brief(*, profile: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    enrichment = job.get("enrichment") if isinstance(job.get("enrichment"), dict) else {}
    profile_skills = [str(item).strip() for item in profile.get("skills", []) if str(item).strip()]
    required = [str(item).strip() for item in enrichment.get("required_skills", []) if str(item).strip()]
    preferred = [str(item).strip() for item in enrichment.get("preferred_skills", []) if str(item).strip()]
    matched_required, missing_required = overlap_skills(required, profile_skills)
    matched_preferred, _ = overlap_skills(preferred, profile_skills)

    emphasis: list[str] = []
    role_family = str(enrichment.get("role_family") or job.get("title") or "this role").strip()
    if profile.get("years_experience"):
        emphasis.append(f"Lead with your {int(profile['years_experience'])}+ years of experience that map to {role_family}.")
    skill_bullets = (matched_required + matched_preferred)[:3]
    for skill in skill_bullets:
        emphasis.append(f"Highlight concrete outcomes where you used {skill}.")
    if job.get("desired_title_match"):
        emphasis.append("Make the title alignment explicit in your summary and top bullets.")
    if not emphasis:
        emphasis.append("Lead with the closest relevant project or accomplishment before generic skills.")
    while len(emphasis) < 3:
        emphasis.append("Use quantified impact and execution ownership rather than tool-only bullets.")

    why_apply = []
    for reason in list(job.get("recommendation_reasons") or [])[:2]:
        why_apply.append(str(reason))
    if not why_apply:
        why_apply.append("The role sits near the top of your current priority queue.")

    summary = (
        f"{job.get('company', 'This company')} looks worth applying to because the role scores "
        f"{job.get('interview_likelihood_score', 'n/a')} for interview likelihood and aligns with "
        f"{len(matched_required)}/{max(1, len(required))} required skills."
    )
    narrative_angle = (
        f"Position yourself as a candidate who can ramp quickly into {role_family} work, "
        f"with credible overlap in {', '.join(skill_bullets) if skill_bullets else 'core role requirements'}."
    )
    return {
        "summary": summary,
        "why_apply": " ".join(why_apply),
        "matched_skills": matched_required + [item for item in matched_preferred if item not in matched_required],
        "missing_skills": missing_required[:5],
        "resume_points": emphasis[:5],
        "narrative_angle": narrative_angle,
    }
