from __future__ import annotations

import re
from typing import Any

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_+.#/-]{1,}")

_TECH_KEYWORDS = {
    "python", "pytorch", "tensorflow", "langchain", "langgraph", "openai", "anthropic", "gemini",
    "postgres", "mysql", "mongodb", "redis", "kafka", "spark", "airflow", "docker", "kubernetes",
    "terraform", "gcp", "aws", "azure", "huggingface", "llm", "rag", "embeddings", "vector",
    "qdrant", "pinecone", "milvus", "elasticsearch", "fastapi", "react", "typescript", "node",
    "cuda", "triton", "onnx", "xgboost", "scikit", "numpy", "pandas", "matplotlib",
}

_STRICT_SUPPORTED_PHRASES = {
    "permanent resident",
    "work permit",
    "civil engineer",
    "civil engineers",
    "geoscientist",
    "geoscientists",
    "geotechnical scientist",
    "geotechnical scientists",
    "mitacs",
    "ocr",
}


def _tokenize(value: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(value or "")]


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return " ".join(_stringify(item) for item in value)
    if isinstance(value, dict):
        return " ".join(f"{key} {_stringify(item)}" for key, item in value.items())
    return str(value)


def build_claim_policy(
    *,
    current_latex: str,
    evidence_context: dict[str, Any] | None,
    evidence_pack: dict[str, Any] | None,
    brag_document_markdown: str,
    project_cards: list[dict[str, Any]] | None,
    do_not_claim: list[str] | None,
) -> dict[str, Any]:
    evidence_text = _stringify(evidence_context) if isinstance(evidence_context, dict) else ""
    resume_text = current_latex
    lower_precedence_parts: list[str] = []
    if brag_document_markdown:
        lower_precedence_parts.append(brag_document_markdown)
    if isinstance(project_cards, list):
        for card in project_cards:
            if isinstance(card, dict):
                lower_precedence_parts.append(_stringify(card))
    lower_precedence_text = " ".join(lower_precedence_parts)

    evidence_terms = set(_tokenize(evidence_text))
    resume_terms = set(_tokenize(resume_text))
    lower_precedence_terms: set[str] = set()
    for text in lower_precedence_parts:
        lower_precedence_terms.update(_tokenize(text))

    # Truth precedence:
    # 1) evidence_context
    # 2) current_latex
    # 3) brag/project cards
    high_authority_terms = evidence_terms.union(resume_terms)
    allowed_terms = high_authority_terms.union(lower_precedence_terms)
    blocked_phrases = [str(item).strip().lower() for item in (do_not_claim or []) if str(item).strip()]
    citation_terms: dict[str, list[str]] = {}
    citation_terms["evidence_context"] = sorted(evidence_terms)
    pack = evidence_pack if isinstance(evidence_pack, dict) else {}
    selected = pack.get("selected_chunks")
    if isinstance(selected, list):
        for item in selected:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("chunk_id") or "").strip()
            text = _stringify(item.get("text"))
            if not cid or not text:
                continue
            citation_terms[cid] = sorted(set(_tokenize(text)))
    return {
        "allowed_terms": sorted(allowed_terms),
        "high_authority_terms": sorted(high_authority_terms),
        "citation_terms": citation_terms,
        "valid_citation_ids": sorted(citation_terms.keys()),
        "high_authority_text": evidence_text + " " + resume_text,
        "lower_precedence_text": lower_precedence_text,
        "term_source_summary": {
            "evidence_context_terms": len(evidence_terms),
            "resume_terms": len(resume_terms),
            "lower_precedence_terms": len(lower_precedence_terms),
        },
        "blocked_phrases": blocked_phrases,
        "precedence": [
            "evidence_context",
            "current_latex",
            "brag_document_or_project_cards",
        ],
    }


def validate_claim_text(
    new_text: str,
    policy: dict[str, Any] | None,
    *,
    old_text: str = "",
    supported_by: list[str] | None = None,
) -> tuple[bool, str | None]:
    if not policy:
        return True, None
    blocked = policy.get("blocked_phrases")
    if isinstance(blocked, list):
        lowered = new_text.lower()
        for phrase in blocked:
            if isinstance(phrase, str) and phrase and phrase in lowered:
                return False, f"blocked_phrase:{phrase}"
    else:
        lowered = new_text.lower()
    allowed_terms_raw = policy.get("allowed_terms")
    allowed_terms = set(allowed_terms_raw) if isinstance(allowed_terms_raw, list) else set()
    if not allowed_terms:
        return True, None
    old_lower = old_text.lower()
    high_authority_text = str(policy.get("high_authority_text") or "").lower()
    lower_precedence_text = str(policy.get("lower_precedence_text") or "").lower()
    high_authority_raw = policy.get("high_authority_terms")
    high_authority_terms = set(high_authority_raw) if isinstance(high_authority_raw, list) else set()
    old_tokens = set(_tokenize(old_text))
    new_tokens = set(_tokenize(new_text))
    introduced_tech = {token for token in new_tokens.difference(old_tokens) if token in _TECH_KEYWORDS}
    citation_terms_raw = policy.get("citation_terms")
    citation_terms = citation_terms_raw if isinstance(citation_terms_raw, dict) else {}
    valid_citation_ids_raw = policy.get("valid_citation_ids")
    valid_citation_ids = set(valid_citation_ids_raw) if isinstance(valid_citation_ids_raw, list) else set()
    chunk_citation_ids = {cid for cid in valid_citation_ids if cid != "evidence_context"}
    has_chunk_citations = bool(chunk_citation_ids)
    supported_ids = [str(item).strip() for item in (supported_by or []) if str(item).strip()]
    for phrase in _STRICT_SUPPORTED_PHRASES:
        if phrase not in lowered or phrase in old_lower:
            continue
        if phrase in high_authority_text:
            continue
        if phrase in lower_precedence_text and not has_chunk_citations:
            continue
        if not supported_ids:
            return False, f"unsupported_strict_phrase:{phrase}"
        phrase_supported = False
        for cid in supported_ids:
            text_terms = citation_terms.get(cid)
            if not isinstance(text_terms, list):
                continue
            citation_text = " ".join(str(term) for term in text_terms).lower()
            if phrase in citation_text:
                phrase_supported = True
                break
        if not phrase_supported:
            return False, f"unsupported_strict_phrase:{phrase}"
    for token in _tokenize(new_text):
        if token in _TECH_KEYWORDS:
            if has_chunk_citations and token not in allowed_terms:
                return False, f"unsupported_keyword:{token}"
            if has_chunk_citations and high_authority_terms and token not in high_authority_terms:
                return False, f"low_precedence_keyword:{token}"
    introduced_needing_citation = {token for token in introduced_tech if token not in high_authority_terms}
    if has_chunk_citations and introduced_needing_citation:
        if not supported_ids:
            return False, "missing_supported_by"
        for cid in supported_ids:
            if cid not in valid_citation_ids:
                return False, f"invalid_citation:{cid}"
        covered_tokens: set[str] = set()
        for cid in supported_ids:
            terms = citation_terms.get(cid)
            if isinstance(terms, list):
                covered_tokens.update(str(term) for term in terms)
        for token in introduced_needing_citation:
            if token not in covered_tokens:
                return False, f"citation_not_supporting_keyword:{token}"
    return True, None
