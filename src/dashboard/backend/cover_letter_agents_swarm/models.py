from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CoverLetterCategory = Literal[
    "Personalization_Intent",
    "Narrative_Fit",
    "Evidence_Credibility",
    "Tone_Clarity_Human",
    "Structure_Skimmability",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftOutputModel(StrictModel):
    cover_letter_text: str = Field(min_length=1)
    notes_for_reviewer: list[str] = Field(default_factory=list)


class CoverLetterBreakdown(StrictModel):
    Personalization_Intent: int = Field(ge=0, le=25)
    Narrative_Fit: int = Field(ge=0, le=25)
    Evidence_Credibility: int = Field(ge=0, le=20)
    Tone_Clarity_Human: int = Field(ge=0, le=20)
    Structure_Skimmability: int = Field(ge=0, le=10)


class CoverLetterSuccessMap(StrictModel):
    Top_Role_Outcomes: list[str] = Field(default_factory=list)
    Fit_Signals_To_Demonstrate: list[str] = Field(default_factory=list)
    Company_Signals_From_JD: list[str] = Field(default_factory=list)
    Potential_Risks_To_Address: list[str] = Field(default_factory=list)


class CoverLetterEvidenceBlock(StrictModel):
    Why_Company_Evidence: list[str] = Field(default_factory=list)
    Why_Role_Evidence: list[str] = Field(default_factory=list)
    Proof_Examples_Evidence: list[str] = Field(default_factory=list)
    Tone_Voice_Evidence: list[str] = Field(default_factory=list)


class HighLeverageSection(StrictModel):
    section_hint: str
    why: str
    goal: str


class CoverLetterJDTargetSpec(StrictModel):
    role_title_hint: str = ""
    top_outcomes: list[str] = Field(default_factory=list)
    fit_signals: list[str] = Field(default_factory=list)
    company_signals: list[str] = Field(default_factory=list)
    tone_signals: list[str] = Field(default_factory=list)
    risk_signals: list[str] = Field(default_factory=list)


class StoryCandidate(StrictModel):
    story_id: str = Field(min_length=1)
    label: str
    why_relevant: str
    supporting_citations: list[str] = Field(default_factory=list)


class CoverLetterRankedEvidencePackModel(StrictModel):
    selected_chunk_ids: list[str] = Field(default_factory=list)
    story_candidates: list[StoryCandidate] = Field(default_factory=list)
    why_company_evidence: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


class NarrativeStory(StrictModel):
    label: str = ""
    goal: str = ""
    supporting_citations: list[str] = Field(default_factory=list)


class CoverLetterNarrativePlanModel(StrictModel):
    opening_angle: str = ""
    proof_story_1: NarrativeStory = Field(default_factory=NarrativeStory)
    proof_story_2: NarrativeStory = Field(default_factory=NarrativeStory)
    why_company_angle: str = ""
    closing_intent: str = ""
    tone_guardrails: list[str] = Field(default_factory=list)


TargetKind = Literal["section", "block", "line_range"]


class EditBudgetSummary(StrictModel):
    max_fixes_this_cycle: int = Field(ge=0, le=20)
    max_ops_this_cycle: int = Field(ge=0, le=20)
    max_changed_lines: int = Field(ge=0, le=200)


class PlannedFixItem(StrictModel):
    fix_id: str = Field(min_length=1)
    priority: int = Field(ge=1)
    expected_gain: int = Field(ge=0, le=20)
    location_hint: str
    target_kind: TargetKind
    section_id: str = ""
    block_id: str = ""
    start_line_id: int | None = Field(default=None, ge=0)
    end_line_id: int | None = Field(default=None, ge=0)
    allowed_ops: list[str] = Field(default_factory=list)
    required_citations: list[str] = Field(default_factory=list)
    rationale: str


class CoverLetterEditPlanModel(StrictModel):
    selected_fixes: list[PlannedFixItem] = Field(default_factory=list)
    deferred_fix_ids: list[str] = Field(default_factory=list)
    edit_budget_summary: EditBudgetSummary
    planner_notes: list[str] = Field(default_factory=list)


class CoverLetterFixPlanItem(StrictModel):
    fix_id: str = Field(min_length=1)
    priority: int = Field(ge=1)
    expected_score_gain: int = Field(ge=1, le=10)
    category: CoverLetterCategory
    location_hint: str
    problem: str
    required_evidence: str
    rewrite_goal: str


class CoverLetterScoreModel(StrictModel):
    Total_Score: int = Field(ge=0, le=100)
    Breakdown: CoverLetterBreakdown
    Cover_Letter_Success_Map: CoverLetterSuccessMap
    Evidence: CoverLetterEvidenceBlock
    Critical_Feedback: list[str] = Field(default_factory=list)
    Fluff_Detected: list[str] = Field(default_factory=list)
    Generic_Template_Signals: list[str] = Field(default_factory=list)
    Resume_Rehash_Sections: list[str] = Field(default_factory=list)
    Missing_Elements: list[str] = Field(default_factory=list)
    High_Leverage_Sections_To_Edit: list[HighLeverageSection] = Field(default_factory=list)
    Fix_Plan: list[CoverLetterFixPlanItem] = Field(default_factory=list)
    Non_Negotiables: list[str] = Field(default_factory=list)


class SkippedFixItem(StrictModel):
    fix_id: str = Field(min_length=1)
    why: str

LegalMoveOp = Literal[
    "replace_range",
    "insert_after",
    "delete_range",
]


class LegalMove(StrictModel):
    move_id: str = Field(min_length=1)
    fix_id: str = Field(min_length=1)
    op: LegalMoveOp
    reason: str
    targets: list[CoverLetterCategory] = Field(default_factory=list)
    supported_by: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("targets", mode="before")
    @classmethod
    def _normalize_targets(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            cleaned = [item.strip() for item in re.split(r"[,\s]+", value) if item.strip()]
            return cleaned
        return value


class CoverLetterRewriteModel(StrictModel):
    applied_fix_ids: list[str] = Field(default_factory=list)
    skipped_fix_ids: list[SkippedFixItem] = Field(default_factory=list)
    moves: list[LegalMove] = Field(default_factory=list, max_length=20)


class ApplyFailure(StrictModel):
    fix_id: str
    reason: str
    old_latex: str


class ApplyApplied(StrictModel):
    fix_id: str
    line_index: int
    old_latex: str
    new_latex: str
    warnings: list[str] = Field(default_factory=list)


class ApplyNoOp(StrictModel):
    fix_id: str
    reason: str


class ApplyReport(StrictModel):
    applied: list[ApplyApplied] = Field(default_factory=list)
    failed: list[ApplyFailure] = Field(default_factory=list)
    no_op: list[ApplyNoOp] = Field(default_factory=list)
    applied_moves: list[dict[str, Any]] = Field(default_factory=list)
    failed_moves: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    doc_version_hash_before: str = ""
    doc_version_hash_after: str = ""
    updated_latex: str
