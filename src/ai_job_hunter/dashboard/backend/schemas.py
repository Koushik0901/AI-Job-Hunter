from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RecommendationMixin(BaseModel):
    fit_score: int | None = None
    interview_likelihood_score: int | None = None
    urgency_score: int | None = None
    friction_score: int | None = None
    confidence_score: int | None = None
    recommendation: str | None = None
    recommendation_reasons: list[str] = Field(default_factory=list)
    guidance_mode: str | None = None
    guidance_title: str | None = None
    guidance_summary: str | None = None
    guidance_reasons: list[str] = Field(default_factory=list)
    next_best_action: str | None = None
    health_label: str | None = None


class JobProcessingState(BaseModel):
    state: str = "ready"
    step: str = "complete"
    message: str = "Job is ready."
    last_processed_at: str | None = None
    last_error: str | None = None
    retry_count: int = 0


class JobSummary(RecommendationMixin):
    id: str
    url: str
    company: str
    title: str
    location: str
    posted: str
    ats: str
    status: str
    priority: str
    pinned: bool = False
    updated_at: str | None = None
    match_score: int | None = None
    raw_score: int | None = None
    match_band: str | None = None
    desired_title_match: bool = False
    required_skills: list[str] = Field(default_factory=list)
    processing: JobProcessingState = Field(default_factory=JobProcessingState)
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
    raw_score: int | None = None
    band: str
    breakdown: dict[str, int]
    reasons: list[str] = Field(default_factory=list)
    confidence: str


class JobMatchMeta(BaseModel):
    profile_version: int
    computed_at: str | None = None
    stale: bool


class JobDetail(RecommendationMixin):
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
    pinned: bool = False
    applied_at: str | None = None
    next_step: str | None = None
    target_compensation: str | None = None
    tracking_updated_at: str | None = None
    processing: JobProcessingState = Field(default_factory=JobProcessingState)
    staging_entered_at: str | None = None
    staging_due_at: str | None = None
    staging_overdue: bool = False
    staging_age_hours: int | None = None
    enrichment: JobEnrichment | None = None
    match: JobMatchScore | None = None
    match_meta: JobMatchMeta | None = None
    desired_title_match: bool = False


class ManualJobCreateResponse(JobDetail):
    duplicate_detected: bool = False
    duplicate_of_job_id: str | None = None
    duplicate_match_kind: str | None = None


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
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    portfolio_url: str | None = None
    city: str | None = None
    country: str | None = None


class BaseDocument(BaseModel):
    id: int
    doc_type: str
    filename: str
    content_md: str
    is_default: bool
    created_at: str


class QueueItem(BaseModel):
    id: int
    job_id: str
    status: str
    sort_order: int
    queued_at: str
    title: str
    company: str
    location: str | None = None
    ats: str | None = None
    match_score: float | None = None


class JobArtifact(BaseModel):
    id: int
    job_id: str
    artifact_type: str
    content_md: str
    base_doc_id: int | None = None
    version: int
    is_active: bool
    generated_by: str | None = None
    created_at: str
    updated_at: str


class GenerateArtifactRequest(BaseModel):
    base_doc_id: int


class UpdateArtifactRequest(BaseModel):
    content_md: str = Field(min_length=1)


class AddToQueueRequest(BaseModel):
    job_id: str = Field(min_length=1)


class UpdateQueueItemRequest(BaseModel):
    status: str = Field(pattern="^(queued|processing|ready|applied|skipped)$")


class ReorderQueueRequest(BaseModel):
    ids: list[int]


class ArtifactsByUrlResponse(BaseModel):
    job_info: dict | None = None
    resume: JobArtifact | None = None
    cover_letter: JobArtifact | None = None


class AgentMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=8000)


class AgentSkillInvocation(BaseModel):
    name: str = Field(
        pattern="^(discover|resume|cover-letter|cover_letter|critique)$"
    )
    arguments: str = ""
    selected_job_id: str | None = None
    active_artifact_id: int | None = None
    active_output_kind: str | None = Field(
        default=None,
        pattern="^(none|discovery|resume|cover_letter|critique)$",
    )


class AgentChatRequest(BaseModel):
    messages: list[AgentMessage] = Field(min_length=1, max_length=40)
    skill_invocation: AgentSkillInvocation | None = None


class AgentChatResponse(BaseModel):
    reply: str
    context_snapshot: str = ""
    response_mode: str = "llm"
    output_kind: str = Field(
        default="none",
        pattern="^(none|discovery|resume|cover_letter|critique)$",
    )
    output_payload: dict[str, Any] | None = None
    operation_id: str | None = None


class AddProfileSkillRequest(BaseModel):
    skill: str = Field(min_length=1, max_length=200)


class TrackingPatchRequest(BaseModel):
    status: str | None = Field(
        default=None,
        pattern="^(not_applied|staging|applied|interviewing|offer|rejected)$",
    )
    priority: str | None = Field(default=None, pattern="^(low|medium|high)$")
    pinned: bool | None = None
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
    status: str | None = Field(
        default=None,
        pattern="^(not_applied|staging|applied|interviewing|offer|rejected)$",
    )
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
    event_type: str = Field(
        pattern="^(note|application_submitted|recruiter_screen|recruiter_reply|hiring_manager_screen|technical_interview|onsite|offer|rejection|resume_rejected|closed_no_response|withdrawn|custom)$"
    )
    title: str = Field(min_length=1, max_length=200)
    body: str | None = None
    event_at: str


class StatsResponse(BaseModel):
    total_jobs: int
    tracked_jobs: int
    active_pipeline: int
    recent_activity_7d: int
    overdue_staging_count: int = 0
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


class BootstrapCacheMeta(BaseModel):
    profile_version: int | None = None
    snapshot_ready: bool = False
    generated_at: str | None = None


class BootstrapResponse(BaseModel):
    profile: CandidateProfile | None = None
    stats: StatsResponse | None = None
    recommended_jobs: list[JobSummary] = Field(default_factory=list)
    action_queue: list[JobAction] = Field(default_factory=list)
    cache: BootstrapCacheMeta = Field(default_factory=BootstrapCacheMeta)


class ServiceHealthStatus(BaseModel):
    configured: bool
    healthy: bool
    message: str


class AppHealthResponse(BaseModel):
    status: str
    services: dict[str, ServiceHealthStatus]


class JobDecisionRequest(BaseModel):
    recommendation: str = Field(pattern="^(apply_now|review_manually|hold|archive)$")
    note: str | None = Field(default=None, max_length=1000)


class DeferActionRequest(BaseModel):
    days: int = Field(default=2, ge=1, le=14)


class JobAction(BaseModel):
    id: int
    job_id: str
    job_url: str | None = None
    company: str | None = None
    title: str | None = None
    action_type: str
    priority: str
    due_at: str
    reason: str
    status: str
    recommendation: str | None = None


class ActionQueueResponse(BaseModel):
    items: list[JobAction] = Field(default_factory=list)


class ConversionBucket(BaseModel):
    key: str
    applied: int
    responses: int
    interviews: int
    offers: int
    rejections: int


class ConversionResponse(BaseModel):
    overall: ConversionBucket
    by_ats: list[ConversionBucket] = Field(default_factory=list)
    by_role_family: list[ConversionBucket] = Field(default_factory=list)


class SourceQualityItem(BaseModel):
    ats: str
    applied: int
    positive_outcomes: int
    negative_outcomes: int
    quality_score: int


class SourceQualityResponse(BaseModel):
    items: list[SourceQualityItem] = Field(default_factory=list)


class ProfileGapItem(BaseModel):
    label: str
    kind: str
    count: int
    example_job_ids: list[str] = Field(default_factory=list)


class ProfileGapsResponse(BaseModel):
    items: list[ProfileGapItem] = Field(default_factory=list)


class ProfileInsightsResponse(BaseModel):
    top_missing_signals: list[ProfileGapItem] = Field(default_factory=list)
    roles_you_should_target_more: list[str] = Field(default_factory=list)
    roles_you_should_target_less: list[str] = Field(default_factory=list)
    suggested_profile_updates: list[str] = Field(default_factory=list)


class DailyBriefingItem(BaseModel):
    job_id: str
    job_url: str | None = None
    company: str | None = None
    title: str | None = None
    reason: str
    due_at: str | None = None
    recommendation: str | None = None
    score: int | None = None


class DailyBriefing(BaseModel):
    brief_date: str
    generated_at: str
    trigger_source: str
    telegram_sent_at: str | None = None
    summary_line: str
    quiet_day: bool = False
    apply_now: list[DailyBriefingItem] = Field(default_factory=list)
    follow_ups_due: list[DailyBriefingItem] = Field(default_factory=list)
    watchlist: list[DailyBriefingItem] = Field(default_factory=list)
    profile_gaps: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)
