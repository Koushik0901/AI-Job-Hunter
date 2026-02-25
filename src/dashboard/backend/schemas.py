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


class TrackingPatchRequest(BaseModel):
    status: str | None = Field(default=None, pattern="^(not_applied|staging|applied|interviewing|offer|rejected)$")
    priority: str | None = Field(default=None, pattern="^(low|medium|high)$")
    applied_at: str | None = None
    next_step: str | None = None
    target_compensation: str | None = None


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
