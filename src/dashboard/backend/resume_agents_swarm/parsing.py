from __future__ import annotations

import json
from typing import Callable, TypeVar

from pydantic import ValidationError

from dashboard.backend.resume_agents_swarm.models import (
    RankedEvidencePackModel,
    ResumeEditPlanModel,
    ResumeJDTargetSpec,
    ResumeRewriteModel,
    ResumeScoreModel,
)

T = TypeVar("T")


class JsonExtractionError(ValueError):
    pass


def extract_first_json_object(text: str) -> str:
    in_string = False
    escape = False
    depth = 0
    start = -1

    for index, char in enumerate(text):
        if start < 0:
            if char == "{":
                start = index
                depth = 1
            continue

        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    raise JsonExtractionError("No complete JSON object found in model output")


def parse_and_validate_score(output_text: str) -> ResumeScoreModel:
    raw = extract_first_json_object(output_text)
    payload = json.loads(raw)
    return ResumeScoreModel.model_validate(payload)


def parse_and_validate_rewrite(output_text: str) -> ResumeRewriteModel:
    raw = extract_first_json_object(output_text)
    payload = json.loads(raw)
    return ResumeRewriteModel.model_validate(payload)


def parse_and_validate_jd_target_spec(output_text: str) -> ResumeJDTargetSpec:
    raw = extract_first_json_object(output_text)
    payload = json.loads(raw)
    return ResumeJDTargetSpec.model_validate(payload)


def parse_and_validate_ranked_evidence_pack(output_text: str) -> RankedEvidencePackModel:
    raw = extract_first_json_object(output_text)
    payload = json.loads(raw)
    return RankedEvidencePackModel.model_validate(payload)


def parse_and_validate_edit_plan(output_text: str) -> ResumeEditPlanModel:
    raw = extract_first_json_object(output_text)
    payload = json.loads(raw)
    return ResumeEditPlanModel.model_validate(payload)


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
