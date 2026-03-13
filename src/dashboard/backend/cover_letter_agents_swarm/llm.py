from __future__ import annotations

import json
import os
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from dashboard.backend.cover_letter_agents_swarm.prompts import (
    load_cover_letter_evidence_miner_prompt,
    load_cover_letter_draft_prompt,
    load_cover_letter_jd_decomposer_prompt,
    load_cover_letter_narrative_planner_prompt,
    load_cover_letter_planner_prompt,
    load_json_repair_prompt,
    load_cover_letter_rewriter_prompt,
    load_cover_letter_scoring_prompt,
)

_OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    draft_model: str
    scoring_model: str
    rewrite_model: str
    draft_temperature: float
    scoring_temperature: float
    rewrite_temperature: float
    draft_max_tokens: int | None
    scoring_max_tokens: int | None
    rewrite_max_tokens: int | None


def _int_or_none(raw: str | None) -> int | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    return int(value)


def load_llm_config() -> LLMConfig:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required")
    return LLMConfig(
        api_key=api_key,
        draft_model=os.getenv("COVER_LETTER_SWARM_DRAFT_MODEL", "openai/gpt-oss-120b").strip() or "openai/gpt-oss-120b",
        scoring_model=os.getenv("COVER_LETTER_SWARM_SCORING_MODEL", "openai/gpt-oss-120b").strip() or "openai/gpt-oss-120b",
        rewrite_model=os.getenv("COVER_LETTER_SWARM_REWRITE_MODEL", "openai/gpt-oss-120b").strip() or "openai/gpt-oss-120b",
        draft_temperature=float(os.getenv("COVER_LETTER_SWARM_DRAFT_TEMPERATURE", "0.4")),
        scoring_temperature=float(os.getenv("COVER_LETTER_SWARM_SCORING_TEMPERATURE", "0.1")),
        rewrite_temperature=float(os.getenv("COVER_LETTER_SWARM_REWRITE_TEMPERATURE", "0.4")),
        draft_max_tokens=_int_or_none(os.getenv("COVER_LETTER_SWARM_DRAFT_MAX_TOKENS")),
        scoring_max_tokens=_int_or_none(os.getenv("COVER_LETTER_SWARM_SCORING_MAX_TOKENS")),
        rewrite_max_tokens=_int_or_none(os.getenv("COVER_LETTER_SWARM_REWRITE_MAX_TOKENS")),
    )


def build_chat_model(*, model: str, api_key: str, temperature: float, max_tokens: int | None) -> ChatOpenAI:
    kwargs: dict[str, object] = {
        "model": model,
        "api_key": api_key,
        "base_url": _OPENROUTER_BASE_URL,
        "temperature": temperature,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    return ChatOpenAI(**kwargs)


def build_draft_messages(
    *,
    job_description: str,
    resume_text: str,
    company_context: str = "",
    narrative_plan_json: str = "",
    evidence_context: dict[str, object] | None = None,
    brag_document_markdown: str = "",
    project_cards: list[dict[str, object]] | None = None,
    do_not_claim: list[str] | None = None,
    evidence_pack: dict[str, object] | None = None,
) -> list[object]:
    prompt = load_cover_letter_draft_prompt()
    evidence_json = json.dumps(evidence_context or {}, ensure_ascii=False)
    cards_json = json.dumps(project_cards or [], ensure_ascii=False)
    blocked = json.dumps(do_not_claim or [], ensure_ascii=False)
    pack_json = json.dumps(evidence_pack or {}, ensure_ascii=False)
    user_content = (
        "<JobDescription>\n"
        f"{job_description}\n"
        "</JobDescription>\n\n"
        "<ResumeText>\n"
        f"{resume_text}\n"
        "</ResumeText>\n\n"
        "<CompanyContext>\n"
        f"{company_context}\n"
        "</CompanyContext>\n\n"
        "<NarrativePlanJSON>\n"
        f"{narrative_plan_json}\n"
        "</NarrativePlanJSON>\n\n"
        "<EvidenceContext>\n"
        f"{evidence_json}\n"
        "</EvidenceContext>\n\n"
        "<BragDocumentMarkdown>\n"
        f"{brag_document_markdown}\n"
        "</BragDocumentMarkdown>\n\n"
        "<ProjectCards>\n"
        f"{cards_json}\n"
        "</ProjectCards>\n\n"
        "<DoNotClaim>\n"
        f"{blocked}\n"
        "</DoNotClaim>\n\n"
        "<EvidencePack>\n"
        f"{pack_json}\n"
        "</EvidencePack>"
    )
    return [SystemMessage(content=prompt), HumanMessage(content=user_content)]


def build_jd_decomposer_messages(*, job_description: str) -> list[object]:
    prompt = load_cover_letter_jd_decomposer_prompt()
    user_content = (
        "<JobDescription>\n"
        f"{job_description}\n"
        "</JobDescription>"
    )
    return [SystemMessage(content=prompt), HumanMessage(content=user_content)]


def build_evidence_miner_messages(
    *,
    jd_target_spec_json: str,
    evidence_pack_json: str,
    evidence_context_json: str,
) -> list[object]:
    prompt = load_cover_letter_evidence_miner_prompt()
    user_content = (
        "<JDTargetSpecJSON>\n"
        f"{jd_target_spec_json}\n"
        "</JDTargetSpecJSON>\n\n"
        "<EvidencePackJSON>\n"
        f"{evidence_pack_json}\n"
        "</EvidencePackJSON>\n\n"
        "<EvidenceContextJSON>\n"
        f"{evidence_context_json}\n"
        "</EvidenceContextJSON>"
    )
    return [SystemMessage(content=prompt), HumanMessage(content=user_content)]


def build_narrative_planner_messages(
    *,
    jd_target_spec_json: str,
    ranked_evidence_pack_json: str,
) -> list[object]:
    prompt = load_cover_letter_narrative_planner_prompt()
    user_content = (
        "<JDTargetSpecJSON>\n"
        f"{jd_target_spec_json}\n"
        "</JDTargetSpecJSON>\n\n"
        "<RankedEvidencePackJSON>\n"
        f"{ranked_evidence_pack_json}\n"
        "</RankedEvidencePackJSON>"
    )
    return [SystemMessage(content=prompt), HumanMessage(content=user_content)]


def build_planner_messages(
    *,
    jd_target_spec_json: str,
    narrative_plan_json: str,
    ranked_evidence_pack_json: str,
    recruiter_feedback_json: str,
    editable_context_json: str,
) -> list[object]:
    prompt = load_cover_letter_planner_prompt()
    user_content = (
        "<JDTargetSpecJSON>\n"
        f"{jd_target_spec_json}\n"
        "</JDTargetSpecJSON>\n\n"
        "<NarrativePlanJSON>\n"
        f"{narrative_plan_json}\n"
        "</NarrativePlanJSON>\n\n"
        "<RankedEvidencePackJSON>\n"
        f"{ranked_evidence_pack_json}\n"
        "</RankedEvidencePackJSON>\n\n"
        "<RecruiterFeedbackJSON>\n"
        f"{recruiter_feedback_json}\n"
        "</RecruiterFeedbackJSON>\n\n"
        "<EditableContextJSON>\n"
        f"{editable_context_json}\n"
        "</EditableContextJSON>"
    )
    return [SystemMessage(content=prompt), HumanMessage(content=user_content)]


def build_scorer_messages(
    *,
    job_description: str,
    cover_letter_text: str,
    evidence_context: dict[str, object] | None = None,
    brag_document_markdown: str = "",
    project_cards: list[dict[str, object]] | None = None,
    do_not_claim: list[str] | None = None,
    evidence_pack: dict[str, object] | None = None,
) -> list[object]:
    prompt = load_cover_letter_scoring_prompt()
    evidence_json = json.dumps(evidence_context or {}, ensure_ascii=False)
    cards_json = json.dumps(project_cards or [], ensure_ascii=False)
    blocked = json.dumps(do_not_claim or [], ensure_ascii=False)
    pack_json = json.dumps(evidence_pack or {}, ensure_ascii=False)
    user_content = (
        "<JobDescription>\n"
        f"{job_description}\n"
        "</JobDescription>\n\n"
        "<CoverLetterText>\n"
        f"{cover_letter_text}\n"
        "</CoverLetterText>\n\n"
        "<EvidenceContext>\n"
        f"{evidence_json}\n"
        "</EvidenceContext>\n\n"
        "<BragDocumentMarkdown>\n"
        f"{brag_document_markdown}\n"
        "</BragDocumentMarkdown>\n\n"
        "<ProjectCards>\n"
        f"{cards_json}\n"
        "</ProjectCards>\n\n"
        "<DoNotClaim>\n"
        f"{blocked}\n"
        "</DoNotClaim>\n\n"
        "<EvidencePack>\n"
        f"{pack_json}\n"
        "</EvidencePack>"
    )
    return [SystemMessage(content=prompt), HumanMessage(content=user_content)]


def build_rewriter_messages(
    *,
    job_description: str,
    jd_target_spec_json: str,
    narrative_plan_json: str,
    ranked_evidence_pack_json: str,
    edit_plan_json: str,
    recruiter_feedback_json: str,
    current_latex_cover_letter: str,
    evidence_context: dict[str, object] | None = None,
    brag_document_markdown: str = "",
    project_cards: list[dict[str, object]] | None = None,
    do_not_claim: list[str] | None = None,
    evidence_pack: dict[str, object] | None = None,
) -> list[object]:
    prompt = load_cover_letter_rewriter_prompt()
    numbered = "\n".join(f"{idx:04d}: {line}" for idx, line in enumerate(current_latex_cover_letter.splitlines()))
    evidence_json = json.dumps(evidence_context or {}, ensure_ascii=False)
    cards_json = json.dumps(project_cards or [], ensure_ascii=False)
    blocked = json.dumps(do_not_claim or [], ensure_ascii=False)
    pack_json = json.dumps(evidence_pack or {}, ensure_ascii=False)
    user_content = (
        "<JobDescription>\n"
        f"{job_description}\n"
        "</JobDescription>\n\n"
        "<JDTargetSpecJSON>\n"
        f"{jd_target_spec_json}\n"
        "</JDTargetSpecJSON>\n\n"
        "<NarrativePlanJSON>\n"
        f"{narrative_plan_json}\n"
        "</NarrativePlanJSON>\n\n"
        "<RankedEvidencePackJSON>\n"
        f"{ranked_evidence_pack_json}\n"
        "</RankedEvidencePackJSON>\n\n"
        "<EditPlanJSON>\n"
        f"{edit_plan_json}\n"
        "</EditPlanJSON>\n\n"
        "<RecruiterFeedbackJSON>\n"
        f"{recruiter_feedback_json}\n"
        "</RecruiterFeedbackJSON>\n\n"
        "<CoverLetterLatex>\n"
        f"{current_latex_cover_letter}\n"
        "</CoverLetterLatex>\n\n"
        "<CoverLetterLatexLineCandidates>\n"
        f"{numbered}\n"
        "</CoverLetterLatexLineCandidates>\n\n"
        "<EvidenceContext>\n"
        f"{evidence_json}\n"
        "</EvidenceContext>\n\n"
        "<BragDocumentMarkdown>\n"
        f"{brag_document_markdown}\n"
        "</BragDocumentMarkdown>\n\n"
        "<ProjectCards>\n"
        f"{cards_json}\n"
        "</ProjectCards>\n\n"
        "<DoNotClaim>\n"
        f"{blocked}\n"
        "</DoNotClaim>\n\n"
        "<EvidencePack>\n"
        f"{pack_json}\n"
        "</EvidencePack>\n\n"
        "Prefer legal moves with line_id/block_id when supported by the schema."
    )
    return [SystemMessage(content=prompt), HumanMessage(content=user_content)]


def build_repair_message(validation_error: str, bad_output: str) -> HumanMessage:
    template = load_json_repair_prompt()
    return HumanMessage(
        content=template.format(validation_error=validation_error, bad_output=bad_output)
    )


def invoke_model(model: ChatOpenAI, messages: list[object]) -> str:
    response = model.invoke(messages)
    content = getattr(response, "content", "")
    if isinstance(content, list):
        return "\n".join(str(part) for part in content)
    return str(content)
