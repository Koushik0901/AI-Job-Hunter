from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, field_validator


class JobSummary(BaseModel):
    id: str
    url: str
    company: str
    title: str
    location: str
    posted: str
    ats: str
    status: str
    priority: str
    updated_at: str | None = None
    match_score: int | None = None
    match_band: str | None = None
    desired_title_match: bool = False
    staging_entered_at: str | None = None
    staging_due_at: str | None = None
    staging_overdue: bool = False
    staging_age_hours: int | None = None


class JobsListResponse(BaseModel):
    items: list[JobSummary]
    total: int


class JobEvent(BaseModel):
    id: int
    job_id: str
    url: str
    event_type: str
    title: str
    body: str | None = None
    event_at: str
    created_at: str


class JobDetail(BaseModel):
    id: str
    url: str
    company: str
    title: str
    location: str
    posted: str
    ats: str
    description: str
    first_seen: str
    last_seen: str
    application_status: str | None = None
    tracking_status: str
    priority: str
    applied_at: str | None = None
    next_step: str | None = None
    target_compensation: str | None = None
    tracking_updated_at: str | None = None
    staging_entered_at: str | None = None
    staging_due_at: str | None = None
    staging_overdue: bool = False
    staging_age_hours: int | None = None
    enrichment: "JobEnrichment | None" = None
    match: "JobMatchScore | None" = None
    match_meta: "JobMatchMeta | None" = None
    desired_title_match: bool = False


class JobEnrichment(BaseModel):
    work_mode: str | None = None
    remote_geo: str | None = None
    canada_eligible: str | None = None
    seniority: str | None = None
    role_family: str | None = None
    years_exp_min: int | None = None
    years_exp_max: int | None = None
    minimum_degree: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    formatted_description: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    visa_sponsorship: str | None = None
    red_flags: list[str] = Field(default_factory=list)
    enriched_at: str | None = None
    enrichment_status: str | None = None
    enrichment_model: str | None = None


class JobMatchScore(BaseModel):
    score: int
    band: str
    breakdown: dict[str, int]
    reasons: list[str] = Field(default_factory=list)
    confidence: str


class JobMatchMeta(BaseModel):
    profile_version: int
    computed_at: str | None = None
    stale: bool


class EducationEntry(BaseModel):
    degree: str = Field(min_length=1, max_length=200)
    field: str | None = None


class CandidateProfile(BaseModel):
    years_experience: int = Field(ge=0, le=60)
    skills: list[str] = Field(default_factory=list)
    desired_job_titles: list[str] = Field(default_factory=list)
    target_role_families: list[str] = Field(default_factory=list)
    requires_visa_sponsorship: bool = False
    education: list[EducationEntry] = Field(default_factory=list)
    degree: str | None = None
    degree_field: str | None = None
    score_version: int | None = None
    updated_at: str | None = None


class ResumeProfile(BaseModel):
    baseline_resume_json: dict[str, object] = Field(default_factory=dict)
    template_id: str = "classic"
    use_template_typography: bool = True
    document_typography_override: dict[str, object] = Field(default_factory=dict)
    updated_at: str | None = None


class CandidateEvidenceAssets(BaseModel):
    evidence_context: dict[str, object] = Field(default_factory=dict)
    brag_document_markdown: str = ""
    project_cards: list[dict[str, object]] = Field(default_factory=list)
    do_not_claim: list[str] = Field(default_factory=list)
    updated_at: str | None = None

    @field_validator("brag_document_markdown")
    @classmethod
    def _validate_brag_doc(cls, value: str) -> str:
        cleaned = (value or "").replace("\x00", "")
        if len(cleaned) > 200_000:
            raise ValueError("brag_document_markdown exceeds 200000 characters")
        return cleaned

    @field_validator("evidence_context")
    @classmethod
    def _validate_evidence_context(cls, value: dict[str, object]) -> dict[str, object]:
        payload = json.dumps(value or {}, ensure_ascii=False)
        if len(payload) > 300_000:
            raise ValueError("evidence_context payload exceeds 300000 characters")
        return value

    @field_validator("project_cards")
    @classmethod
    def _validate_project_cards(cls, value: list[dict[str, object]]) -> list[dict[str, object]]:
        if len(value or []) > 200:
            raise ValueError("project_cards exceeds 200 items")
        payload = json.dumps(value or [], ensure_ascii=False)
        if len(payload) > 400_000:
            raise ValueError("project_cards payload exceeds 400000 characters")
        cleaned_cards: list[dict[str, object]] = []
        for card in value or []:
            if not isinstance(card, dict):
                continue
            normalized: dict[str, Any] = {}
            for key, item in card.items():
                if isinstance(item, str):
                    normalized[str(key)] = item.replace("\x00", "")
                else:
                    normalized[str(key)] = item
            cleaned_cards.append(normalized)
        return cleaned_cards

    @field_validator("do_not_claim")
    @classmethod
    def _validate_do_not_claim(cls, value: list[str]) -> list[str]:
        cleaned = [str(item).replace("\x00", "").strip() for item in (value or []) if str(item).strip()]
        if len(cleaned) > 200:
            raise ValueError("do_not_claim exceeds 200 entries")
        return cleaned


class CandidateEvidenceIndexStatus(BaseModel):
    enabled: bool = False
    backend: str = "disabled"
    status: str = "idle"
    indexed_count: int = 0
    message: str = ""
    updated_at: float | None = None
    collection: str | None = None


class ServiceHealthStatus(BaseModel):
    configured: bool
    healthy: bool
    message: str
    collection: str | None = None
    collection_exists: bool | None = None


class AppHealthResponse(BaseModel):
    status: str
    services: dict[str, ServiceHealthStatus]


class CompanySource(BaseModel):
    id: int
    name: str
    ats_type: str
    ats_url: str
    slug: str
    enabled: bool = True
    source: str = ""
    created_at: str
    updated_at: str


class CompanySourceProbeResult(BaseModel):
    name: str
    slug: str
    ats_type: str
    ats_url: str
    jobs: int = 0
    exists: bool = False
    existing_name: str | None = None
    source: str | None = None
    low_signal: bool = False
    suppressed_reason: str | None = None


class CompanySourceProbeRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    extra_slugs: list[str] = Field(default_factory=list)


class CompanySourceProbeResponse(BaseModel):
    query: str
    company_name: str
    slugs: list[str] = Field(default_factory=list)
    inferred: dict[str, str] | None = None
    matches: list[CompanySourceProbeResult] = Field(default_factory=list)
    zero_job_matches: list[CompanySourceProbeResult] = Field(default_factory=list)


class CreateCompanySourceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    ats_type: str = Field(min_length=2, max_length=80)
    slug: str = Field(min_length=1, max_length=200)
    ats_url: str | None = None
    enabled: bool = True
    source: str = Field(default="manual", max_length=120)


class UpdateCompanySourceRequest(BaseModel):
    enabled: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=300)
    source: str | None = Field(default=None, max_length=120)


class CompanySourceImportResponse(BaseModel):
    new_entries: list[CompanySourceProbeResult] = Field(default_factory=list)
    skipped_duplicates: int = 0
    imported: int | None = None


class WorkspaceOperation(BaseModel):
    id: str
    kind: str
    status: str
    params: dict[str, object] = Field(default_factory=dict)
    summary: dict[str, object] = Field(default_factory=dict)
    log_tail: str = ""
    started_at: str
    finished_at: str | None = None
    error: str | None = None


class WorkspaceOverview(BaseModel):
    total_jobs: int
    enabled_company_sources: int
    total_company_sources: int
    desired_job_titles_count: int
    has_profile_basics: bool
    services: dict[str, ServiceHealthStatus]
    recent_operations: list[WorkspaceOperation] = Field(default_factory=list)


class TemplateSettings(BaseModel):
    resume_template_id: str = "classic"
    cover_letter_template_id: str = "classic"
    updated_at: str | None = None


class ResumeImportRequest(BaseModel):
    source_path: str | None = None


class ResumeImportResponse(BaseModel):
    source_path: str
    baseline_resume_json: dict[str, object] = Field(default_factory=dict)


class AddProfileSkillRequest(BaseModel):
    skill: str = Field(min_length=1, max_length=200)


class WorkspaceScrapeRequest(BaseModel):
    no_location_filter: bool = False
    no_enrich: bool = False
    no_enrich_llm: bool = False
    sort_by: str = Field(default="match", pattern="^(match|posted)$")


class WorkspaceJdReformatRequest(BaseModel):
    missing_only: bool = True


class WorkspacePruneRequest(BaseModel):
    days: int = Field(default=28, ge=1, le=365)


class TrackingPatchRequest(BaseModel):
    status: str | None = Field(default=None, pattern="^(not_applied|staging|applied|interviewing|offer|rejected)$")
    priority: str | None = Field(default=None, pattern="^(low|medium|high)$")
    applied_at: str | None = None
    next_step: str | None = None
    target_compensation: str | None = None


class ManualJobCreateRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    company: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=400)
    location: str | None = None
    posted: str | None = None
    ats: str | None = None
    status: str | None = Field(default=None, pattern="^(not_applied|staging|applied|interviewing|offer|rejected)$")
    description: str = Field(min_length=1)


class SuppressJobRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class SuppressedJob(BaseModel):
    job_id: str
    url: str
    company: str
    reason: str | None = None
    created_at: str
    updated_at: str
    created_by: str


class CreateEventRequest(BaseModel):
    event_type: str = Field(pattern="^(note|application_submitted|recruiter_screen|technical_interview|onsite|offer|rejection|withdrawn|custom)$")
    title: str = Field(min_length=1, max_length=200)
    body: str | None = None
    event_at: str


class StatsResponse(BaseModel):
    total_jobs: int
    tracked_jobs: int
    active_pipeline: int
    recent_activity_7d: int
    by_status: dict[str, int]


class ScoreRecomputeStatus(BaseModel):
    running: bool
    queued_while_running: int
    last_started_at: str | None = None
    last_finished_at: str | None = None
    last_duration_ms: int | None = None
    last_total: int | None = None
    last_processed: int | None = None
    last_scope: str | None = None
    last_error: str | None = None


class ArtifactSummary(BaseModel):
    id: str
    job_id: str
    job_url: str
    artifact_type: str
    active_version_id: str | None = None
    active_version: "ArtifactVersion | None" = None
    created_at: str


class ArtifactVersion(BaseModel):
    id: str
    artifact_id: str
    version: int
    label: str
    content_json: dict[str, object] | None = None
    content_text: str | None = None
    meta_json: dict[str, object] = Field(default_factory=dict)
    created_at: str
    created_by: str
    supersedes_version_id: str | None = None
    base_version_id: str | None = None


class GenerateStarterArtifactsRequest(BaseModel):
    force: bool = False


class ArtifactStarterStatus(BaseModel):
    job_id: str
    job_url: str
    stage: str
    progress_percent: int = Field(ge=0, le=100)
    running: bool = False
    updated_at: str | None = None


class CreateArtifactVersionRequest(BaseModel):
    label: str = Field(default="draft", pattern="^(draft|tailored|final)$")
    content_json: dict[str, object]
    meta_json: dict[str, object] = Field(default_factory=dict)
    created_by: str = Field(default="ui", min_length=1, max_length=80)
    base_version_id: str | None = None


class ArtifactExportRequest(BaseModel):
    format: str = Field(default="pdf", pattern="^(pdf)$")


class ResumeLatexDocument(BaseModel):
    artifact_id: str
    version_id: str | None = None
    version: int | None = None
    source_text: str
    template_id: str = "classic"
    compile_status: str = "never"
    compile_error: str | None = None
    pdf_available: bool = False
    compiled_at: str | None = None
    log_tail: str | None = None
    diagnostics: list[dict[str, object]] = Field(default_factory=list)


class ArtifactLatexDocument(BaseModel):
    artifact_id: str
    artifact_type: str
    version_id: str | None = None
    version: int | None = None
    source_text: str
    template_id: str = "classic"
    compile_status: str = "never"
    compile_error: str | None = None
    pdf_available: bool = False
    compiled_at: str | None = None
    log_tail: str | None = None
    diagnostics: list[dict[str, object]] = Field(default_factory=list)


class SaveResumeLatexRequest(BaseModel):
    source_text: str
    template_id: str = Field(default="classic", min_length=1, max_length=80)
    label: str = Field(default="draft", pattern="^(draft|tailored|final)$")
    created_by: str = Field(default="ui", min_length=1, max_length=80)


class RecompileResumeLatexRequest(BaseModel):
    source_text: str | None = None
    template_id: str | None = Field(default=None, min_length=1, max_length=80)
    created_by: str = Field(default="ui", min_length=1, max_length=80)


class SaveArtifactLatexRequest(BaseModel):
    source_text: str
    template_id: str = Field(default="classic", min_length=1, max_length=80)
    label: str = Field(default="draft", pattern="^(draft|tailored|final)$")
    created_by: str = Field(default="ui", min_length=1, max_length=80)


class RecompileArtifactLatexRequest(BaseModel):
    source_text: str | None = None
    template_id: str | None = Field(default=None, min_length=1, max_length=80)
    created_by: str = Field(default="ui", min_length=1, max_length=80)


class ResumeSwarmOptimizeRequest(BaseModel):
    cycles: int = Field(default=2, ge=1, le=5)
    created_by: str = Field(default="ui", min_length=1, max_length=80)


class ResumeSwarmOptimizeResponse(BaseModel):
    artifact_id: str
    version_id: str
    version: int
    final_score: dict[str, object] = Field(default_factory=dict)
    history: list[dict[str, object]] = Field(default_factory=list)


class ResumeSwarmRunStartRequest(BaseModel):
    cycles: int = Field(default=2, ge=1, le=5)
    source_text: str | None = None
    template_id: str | None = Field(default=None, min_length=1, max_length=80)


class ResumeSwarmRunStartResponse(BaseModel):
    run_id: str
    status: str


class ResumeSwarmConfirmSaveRequest(BaseModel):
    created_by: str = Field(default="ui", min_length=1, max_length=80)
    label: str = Field(default="draft", pattern="^(draft|tailored|final)$")


class ResumeSwarmRunStatusResponse(BaseModel):
    run_id: str
    artifact_id: str
    status: str
    current_stage: str
    stage_index: int
    started_at: str
    updated_at: str
    cycles_target: int
    cycles_done: int
    events: list[dict[str, object]] = Field(default_factory=list)
    latest_score: dict[str, object] | None = None
    latest_rewrite: dict[str, object] | None = None
    latest_apply_report: dict[str, object] | None = None
    final_score: dict[str, object] | None = None
    candidate_latex: str | None = None
    error: str | None = None


class TemplateValidationResult(BaseModel):
    ok: bool = True
    warnings: list[str] = Field(default_factory=list)
    missing_required_sections: list[str] = Field(default_factory=list)
    missing_required_placeholders: list[str] = Field(default_factory=list)
    detected_sections: list[str] = Field(default_factory=list)
    detected_items: list[str] = Field(default_factory=list)


class ArtifactsHubItem(BaseModel):
    job_id: str
    job_url: str
    company: str
    title: str
    tracking_status: str
    tracking_updated_at: str | None = None
    latest_artifact_updated_at: str | None = None
    resume: ArtifactSummary | None = None
    cover_letter: ArtifactSummary | None = None


class ArtifactsHubResponse(BaseModel):
    items: list[ArtifactsHubItem] = Field(default_factory=list)
    total: int


class FunnelWindow(BaseModel):
    from_date: str | None = Field(default=None, alias="from")
    to_date: str | None = Field(default=None, alias="to")
    preset: str

    model_config = {"populate_by_name": True}


class FunnelStage(BaseModel):
    status: str
    count: int


class FunnelConversions(BaseModel):
    backlog_to_staging: float
    staging_to_applied: float
    applied_to_interviewing: float
    interviewing_to_offer: float
    backlog_to_offer: float


class FunnelTotals(BaseModel):
    tracked_total: int
    active_total: int
    offer_total: int


class FunnelComparisonWindow(BaseModel):
    from_date: str | None = Field(default=None, alias="from")
    to_date: str | None = Field(default=None, alias="to")
    days: int

    model_config = {"populate_by_name": True}


class FunnelConversionDeltas(BaseModel):
    backlog_to_staging: float
    staging_to_applied: float
    applied_to_interviewing: float
    interviewing_to_offer: float
    backlog_to_offer: float


class FunnelDeltaSummary(BaseModel):
    tracked_total: int
    active_total: int
    offer_total: int
    conversions: FunnelConversionDeltas
    comparison_window: FunnelComparisonWindow | None = None


class WeeklyGoalMetric(BaseModel):
    target: int
    actual: int
    progress: float


class FunnelWeeklyGoals(BaseModel):
    window_start: str
    window_end: str
    applications: WeeklyGoalMetric
    interviews: WeeklyGoalMetric


class FunnelAlerts(BaseModel):
    staging_overdue_48h: int
    interviewing_no_activity_5d: int
    backlog_expiring_soon: int


class CohortFunnelRow(BaseModel):
    week_start: str
    stages: list[FunnelStage]
    tracked_total: int
    offer_rate: float


class SourceQualityItem(BaseModel):
    name: str
    tracked_total: int
    active_total: int
    offers: int
    offer_rate: float
    interview_rate: float


class SourceQualitySummary(BaseModel):
    ats: list[SourceQualityItem] = Field(default_factory=list)
    companies: list[SourceQualityItem] = Field(default_factory=list)


class ForecastWindow(BaseModel):
    days: int
    projected_interviews: float
    projected_offers: float
    interviews_low: float
    interviews_high: float
    offers_low: float
    offers_high: float


class ForecastSummary(BaseModel):
    applications_per_week: int
    interview_rate: float
    offer_rate_from_interview: float
    confidence_band: str
    confidence_margin: float
    windows: list[ForecastWindow] = Field(default_factory=list)


class FunnelAnalyticsResponse(BaseModel):
    window: FunnelWindow
    stages: list[FunnelStage]
    conversions: FunnelConversions
    totals: FunnelTotals
    deltas: FunnelDeltaSummary
    weekly_goals: FunnelWeeklyGoals
    alerts: FunnelAlerts
    cohorts: list[CohortFunnelRow] = Field(default_factory=list)
    source_quality: SourceQualitySummary
    forecast: ForecastSummary
