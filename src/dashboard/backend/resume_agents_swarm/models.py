from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ScoreCategory = Literal[
    "First_Pass_Clarity",
    "Impact_Specificity",
    "JD_Alignment",
    "Hard_Skills_Keywords",
    "Action_Language",
]

EvidenceQuality = Literal["Strong", "Weak", "None"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Breakdown(StrictModel):
    First_Pass_Clarity: int = Field(ge=0, le=15)
    Impact_Specificity: int = Field(ge=0, le=25)
    JD_Alignment: int = Field(ge=0, le=30)
    Hard_Skills_Keywords: int = Field(ge=0, le=20)
    Action_Language: int = Field(ge=0, le=10)


class Pass7sSummary(StrictModel):
    Target_Role_Clear: bool
    Core_Stack_Clear: bool
    Top_Impact_Clear: bool
    What_Recruiter_Notices_First: list[str] = Field(default_factory=list, max_length=3)
    What_Should_Be_Obvious_But_Isnt: list[str] = Field(default_factory=list, max_length=3)


class JobRequirementMap(StrictModel):
    Must_Have_Skills: list[str] = Field(default_factory=list)
    Nice_To_Have_Skills: list[str] = Field(default_factory=list)
    Top_Responsibilities: list[str] = Field(default_factory=list)
    Role_Signals: list[str] = Field(default_factory=list)
    Repeated_Keywords: list[str] = Field(default_factory=list)


class EvidenceCoverageItem(StrictModel):
    skill: str | None = None
    responsibility: str | None = None
    covered: bool
    evidence_spans: list[str] = Field(default_factory=list)
    evidence_quality: EvidenceQuality


class EvidenceBlock(StrictModel):
    Must_Haves_Coverage: list[EvidenceCoverageItem] = Field(default_factory=list)
    Responsibilities_Coverage: list[EvidenceCoverageItem] = Field(default_factory=list)


class ContradictionRisk(StrictModel):
    issue: str
    evidence_spans: list[str] = Field(default_factory=list)


class HighLeverageSection(StrictModel):
    section_hint: str
    why: str
    goal: str


class ResumeJDTargetSpec(StrictModel):
    role_title_hint: str = ""
    must_have_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    top_outcomes: list[str] = Field(default_factory=list)
    role_signals: list[str] = Field(default_factory=list)
    company_signals: list[str] = Field(default_factory=list)
    risk_signals: list[str] = Field(default_factory=list)


EvidenceSupportLevel = Literal["strong", "medium", "weak"]


class StoryCandidate(StrictModel):
    story_id: str = Field(min_length=1)
    label: str
    why_relevant: str
    supporting_citations: list[str] = Field(default_factory=list)


class KeywordSupportItem(StrictModel):
    keyword: str
    supporting_citations: list[str] = Field(default_factory=list)
    support_level: EvidenceSupportLevel


class RankedEvidencePackModel(StrictModel):
    selected_chunk_ids: list[str] = Field(default_factory=list)
    top_story_candidates: list[StoryCandidate] = Field(default_factory=list)
    keyword_support_map: list[KeywordSupportItem] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


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


class ResumeEditPlanModel(StrictModel):
    selected_fixes: list[PlannedFixItem] = Field(default_factory=list)
    deferred_fix_ids: list[str] = Field(default_factory=list)
    edit_budget_summary: EditBudgetSummary
    planner_notes: list[str] = Field(default_factory=list)


class FixPlanItem(StrictModel):
    fix_id: str = Field(min_length=1)
    priority: int = Field(ge=1)
    expected_score_gain: int = Field(ge=1, le=10)
    category: ScoreCategory
    location_hint: str
    problem: str
    required_evidence: str
    rewrite_goal: str


class ResumeScoreModel(StrictModel):
    Total_Score: int = Field(ge=0, le=100)
    Breakdown: Breakdown
    Pass_7s_Summary: Pass7sSummary
    Job_Requirement_Map: JobRequirementMap
    Evidence: EvidenceBlock
    Critical_Feedback: list[str] = Field(default_factory=list)
    Fluff_Detected: list[str] = Field(default_factory=list)
    Stuffed_Keywords: list[str] = Field(default_factory=list)
    Weak_Evidence_Keywords: list[str] = Field(default_factory=list)
    Missing_Keywords: list[str] = Field(default_factory=list)
    Contradictions_Or_Risks: list[ContradictionRisk] = Field(default_factory=list)
    High_Leverage_Sections_To_Edit: list[HighLeverageSection] = Field(default_factory=list)
    Fix_Plan: list[FixPlanItem] = Field(default_factory=list)
    Non_Negotiables: list[str] = Field(default_factory=list, max_length=3)


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
    targets: list[ScoreCategory] = Field(default_factory=list)
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


class ResumeRewriteModel(StrictModel):
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
