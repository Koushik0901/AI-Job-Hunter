from __future__ import annotations

import json
from typing import Callable, TypeVar

from pydantic import ValidationError

from dashboard.backend.cover_letter_agents_swarm.models import (
    CoverLetterEditPlanModel,
    CoverLetterJDTargetSpec,
    CoverLetterNarrativePlanModel,
    CoverLetterRankedEvidencePackModel,
    CoverLetterRewriteModel,
    CoverLetterScoreModel,
    DraftOutputModel,
)
from dashboard.backend.resume_agents_swarm.parsing import JsonExtractionError, extract_first_json_object

T = TypeVar("T")


def parse_and_validate_draft(output_text: str) -> DraftOutputModel:
    raw = extract_first_json_object(output_text)
    payload = json.loads(raw)
    return DraftOutputModel.model_validate(payload)


def parse_and_validate_score(output_text: str) -> CoverLetterScoreModel:
    raw = extract_first_json_object(output_text)
    payload = json.loads(raw)
    return CoverLetterScoreModel.model_validate(payload)


def parse_and_validate_rewrite(output_text: str) -> CoverLetterRewriteModel:
    raw = extract_first_json_object(output_text)
    payload = json.loads(raw)
    return CoverLetterRewriteModel.model_validate(payload)


def parse_and_validate_jd_target_spec(output_text: str) -> CoverLetterJDTargetSpec:
    raw = extract_first_json_object(output_text)
    payload = json.loads(raw)
    return CoverLetterJDTargetSpec.model_validate(payload)


def parse_and_validate_ranked_evidence_pack(output_text: str) -> CoverLetterRankedEvidencePackModel:
    raw = extract_first_json_object(output_text)
    payload = json.loads(raw)
    return CoverLetterRankedEvidencePackModel.model_validate(payload)


def parse_and_validate_narrative_plan(output_text: str) -> CoverLetterNarrativePlanModel:
    raw = extract_first_json_object(output_text)
    payload = json.loads(raw)
    return CoverLetterNarrativePlanModel.model_validate(payload)


def parse_and_validate_edit_plan(output_text: str) -> CoverLetterEditPlanModel:
    raw = extract_first_json_object(output_text)
    payload = json.loads(raw)
    return CoverLetterEditPlanModel.model_validate(payload)


def call_with_json_retries(
    *,
    invoke: Callable[[list[object]], str],
    base_messages: list[object],
    parser: Callable[[str], T],
    build_repair_message: Callable[[str, str], object],
    max_retries: int,
    before_attempt: Callable[[], None] | None = None,
) -> tuple[T, list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    messages = list(base_messages)

    for attempt in range(max_retries + 1):
        if before_attempt is not None:
            before_attempt()
        output = invoke(messages)
        try:
            parsed = parser(output)
            return parsed, errors
        except (JsonExtractionError, json.JSONDecodeError, ValidationError, ValueError) as error:
            errors.append(
                {
                    "attempt": str(attempt + 1),
                    "error": str(error),
                    "raw_output": output,
                }
            )
            if attempt >= max_retries:
                raise
            if before_attempt is not None:
                before_attempt()
            messages.append(build_repair_message(str(error), output))

    raise RuntimeError("unreachable")
