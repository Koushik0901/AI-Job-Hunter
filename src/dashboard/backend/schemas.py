from __future__ import annotations

from pydantic import BaseModel, Field


class JobSummary(BaseModel):
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


class JobsListResponse(BaseModel):
    items: list[JobSummary]
    total: int


class JobEvent(BaseModel):
    id: int
    url: str
    event_type: str
    title: str
    body: str | None = None
    event_at: str
    created_at: str


class JobDetail(BaseModel):
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
    enrichment: "JobEnrichment | None" = None
    match: "JobMatchScore | None" = None


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


class EducationEntry(BaseModel):
    degree: str = Field(min_length=1, max_length=200)
    field: str | None = None


class CandidateProfile(BaseModel):
    years_experience: int = Field(ge=0, le=60)
    skills: list[str] = Field(default_factory=list)
    target_role_families: list[str] = Field(default_factory=list)
    requires_visa_sponsorship: bool = False
    education: list[EducationEntry] = Field(default_factory=list)
    degree: str | None = None
    degree_field: str | None = None
    updated_at: str | None = None


class AddProfileSkillRequest(BaseModel):
    skill: str = Field(min_length=1, max_length=200)


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
    description: str = Field(min_length=1)


class SuppressJobRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class SuppressedJob(BaseModel):
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
    staging_stale_7d: int
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
