export type TrackingStatus = "not_applied" | "staging" | "applied" | "interviewing" | "offer" | "rejected";

export type Priority = "low" | "medium" | "high";
export type Recommendation = "apply_now" | "review_manually" | "hold" | "archive";
export type RecommendationGuidanceMode = "evaluation" | "stage_narrative";
export type ColumnSortOption = "stage_priority" | "match_desc" | "posted_desc" | "updated_desc" | "company_asc";

export interface JobProcessingState {
  state: "processing" | "ready" | "failed";
  step: string;
  message: string;
  last_processed_at: string | null;
  last_error: string | null;
  retry_count: number;
}

export interface JobSummary {
  id: string;
  url: string;
  company: string;
  title: string;
  location: string;
  posted: string;
  ats: string;
  status: TrackingStatus;
  priority: Priority;
  pinned: boolean;
  updated_at: string | null;
  match_score: number | null;
  raw_score: number | null;
  match_band: string | null;
  desired_title_match: boolean;
  required_skills: string[];
  processing: JobProcessingState;
  staging_entered_at: string | null;
  staging_due_at: string | null;
  staging_overdue: boolean;
  staging_age_hours: number | null;
  fit_score: number | null;
  interview_likelihood_score: number | null;
  urgency_score: number | null;
  friction_score: number | null;
  confidence_score: number | null;
  recommendation: Recommendation | null;
  recommendation_reasons: string[];
  guidance_mode: RecommendationGuidanceMode | null;
  guidance_title: string | null;
  guidance_summary: string | null;
  guidance_reasons: string[];
  next_best_action: string | null;
  health_label: string | null;
  semantic_score?: number | null;
  matched_story_ids?: number[];
  matched_story_titles?: string[];
}

export interface JobsListResponse {
  items: JobSummary[];
  total: number;
}

export interface JobEnrichment {
  work_mode: string | null;
  remote_geo: string | null;
  canada_eligible: string | null;
  seniority: string | null;
  role_family: string | null;
  years_exp_min: number | null;
  years_exp_max: number | null;
  minimum_degree: string | null;
  required_skills: string[];
  preferred_skills: string[];
  formatted_description: string | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  visa_sponsorship: string | null;
  red_flags: string[];
  enriched_at: string | null;
  enrichment_status: string | null;
  enrichment_model: string | null;
}

export interface JobMatchScore {
  score: number;
  raw_score: number | null;
  band: string;
  breakdown: Record<string, number>;
  reasons: string[];
  confidence: string;
}

export interface JobMatchMeta {
  profile_version: number;
  computed_at: string | null;
  stale: boolean;
}

export interface JobDetail {
  id: string;
  url: string;
  company: string;
  title: string;
  location: string;
  posted: string;
  ats: string;
  description: string;
  first_seen: string;
  last_seen: string;
  application_status: string | null;
  tracking_status: TrackingStatus;
  priority: Priority;
  pinned: boolean;
  applied_at: string | null;
  next_step: string | null;
  target_compensation: string | null;
  tracking_updated_at: string | null;
  staging_entered_at: string | null;
  staging_due_at: string | null;
  staging_overdue: boolean;
  staging_age_hours: number | null;
  processing: JobProcessingState;
  enrichment: JobEnrichment | null;
  match: JobMatchScore | null;
  match_meta: JobMatchMeta | null;
  desired_title_match: boolean;
  fit_score: number | null;
  interview_likelihood_score: number | null;
  urgency_score: number | null;
  friction_score: number | null;
  confidence_score: number | null;
  recommendation: Recommendation | null;
  recommendation_reasons: string[];
  guidance_mode: RecommendationGuidanceMode | null;
  guidance_title: string | null;
  guidance_summary: string | null;
  guidance_reasons: string[];
  next_best_action: string | null;
  health_label: string | null;
  semantic_score?: number | null;
  matched_story_ids?: number[];
  matched_story_titles?: string[];
}

export interface CandidateProfile {
  years_experience: number;
  skills: string[];
  desired_job_titles: string[];
  target_role_families: string[];
  requires_visa_sponsorship: boolean;
  education: Array<{ degree: string; field: string | null }>;
  degree: string | null;
  degree_field: string | null;
  score_version?: number;
  updated_at: string | null;
  full_name: string | null;
  email: string | null;
  phone: string | null;
  linkedin_url: string | null;
  portfolio_url: string | null;
  city: string | null;
  country: string | null;
}

export interface BaseDocument {
  id: number;
  doc_type: "resume" | "cover_letter";
  filename: string;
  content_md: string;
  is_default: boolean;
  created_at: string;
}

export interface QueueItem {
  id: number;
  job_id: string;
  status: "queued" | "processing" | "ready" | "applied" | "skipped";
  sort_order: number;
  queued_at: string;
  processed_at: string | null;
  title: string;
  company: string;
  location: string | null;
  ats: string | null;
  match_score: number | null;
}

export interface JobArtifact {
  id: number;
  job_id: string;
  artifact_type: "resume" | "cover_letter";
  content_md: string;
  base_doc_id: number | null;
  version: number;
  is_active: boolean;
  generated_by: string | null;
  created_at: string;
  updated_at: string;
  story_ids_used: number[];
}

export interface AgentMessage {
  role: "user" | "assistant";
  content: string;
}

export type AgentSkillName = "discover" | "resume" | "cover_letter" | "critique";
export type AgentOutputKind = "none" | "discovery" | "resume" | "cover_letter" | "critique";

export interface AgentSkillInvocation {
  name: AgentSkillName;
  arguments?: string;
  selected_job_id?: string | null;
  active_artifact_id?: number | null;
  active_output_kind?: AgentOutputKind | null;
}

export interface AgentChatRequest {
  messages: AgentMessage[];
  skill_invocation?: AgentSkillInvocation | null;
}

export interface AgentChatResponse {
  reply: string;
  context_snapshot: string;
  response_mode: "fast" | "llm" | "fallback" | "skill";
  output_kind: AgentOutputKind;
  output_payload?: Record<string, unknown> | null;
  operation_id?: string | null;
}

export interface JobEvent {
  id: number;
  job_id: string;
  url: string;
  event_type: string;
  title: string;
  body: string | null;
  event_at: string;
  created_at: string;
}

export interface JobAction {
  id: number;
  job_id: string;
  job_url: string | null;
  company: string | null;
  title: string | null;
  action_type: string;
  priority: Priority;
  due_at: string;
  reason: string;
  status: string;
  recommendation: Recommendation | null;
}

export interface ActionQueueResponse {
  items: JobAction[];
}

export interface ConversionBucket {
  key: string;
  applied: number;
  responses: number;
  interviews: number;
  offers: number;
  rejections: number;
}

export interface ConversionResponse {
  overall: ConversionBucket;
  by_ats: ConversionBucket[];
  by_role_family: ConversionBucket[];
}

export interface SourceQualityItem {
  ats: string;
  applied: number;
  positive_outcomes: number;
  negative_outcomes: number;
  quality_score: number;
}

export interface SourceQualityResponse {
  items: SourceQualityItem[];
}

export interface ProfileGapItem {
  label: string;
  kind: string;
  count: number;
  example_job_ids: string[];
}

export interface ProfileGapsResponse {
  items: ProfileGapItem[];
}

export interface ProfileInsightsResponse {
  top_missing_signals: ProfileGapItem[];
  roles_you_should_target_more: string[];
  roles_you_should_target_less: string[];
  suggested_profile_updates: string[];
}

export interface DailyBriefingItem {
  job_id: string;
  job_url: string | null;
  company: string | null;
  title: string | null;
  reason: string;
  due_at: string | null;
  recommendation: Recommendation | null;
  score: number | null;
}

export interface DailyBriefing {
  brief_date: string;
  generated_at: string;
  trigger_source: string;
  telegram_sent_at: string | null;
  summary_line: string;
  quiet_day: boolean;
  apply_now: DailyBriefingItem[];
  follow_ups_due: DailyBriefingItem[];
  watchlist: DailyBriefingItem[];
  profile_gaps: string[];
  signals: string[];
}

export interface AppHealthResponse {
  status: string;
  services: Record<string, { configured: boolean; healthy: boolean; message: string }>;
}

export interface StatsResponse {
  total_jobs: number;
  tracked_jobs: number;
  active_pipeline: number;
  recent_activity_7d: number;
  overdue_staging_count: number;
  by_status: Record<string, number>;
}

export interface ScoreRecomputeStatus {
  running: boolean;
  queued_while_running: number;
  last_started_at: string | null;
  last_finished_at: string | null;
  last_duration_ms: number | null;
  last_total: number | null;
  last_processed: number | null;
  last_scope: string | null;
  last_error: string | null;
}

export interface WorkspaceOperation {
  id: string;
  kind: string;
  status: "queued" | "running" | "completed" | "failed";
  params: Record<string, unknown>;
  summary: Record<string, unknown>;
  log_tail: string;
  started_at: string;
  finished_at: string | null;
  error: string | null;
}

export interface BootstrapCacheMeta {
  profile_version: number | null;
  snapshot_ready: boolean;
  generated_at: string | null;
}

export interface BootstrapResponse {
  profile: CandidateProfile | null;
  stats: StatsResponse | null;
  recommended_jobs: JobSummary[];
  action_queue: JobAction[];
  cache: BootstrapCacheMeta;
}

export interface TrackingPatchRequest {
  status?: TrackingStatus;
  priority?: Priority;
  pinned?: boolean;
  applied_at?: string | null;
  next_step?: string | null;
  target_compensation?: string | null;
}

export interface ManualJobCreateRequest {
  url: string;
  company: string;
  title: string;
  location?: string | null;
  posted?: string | null;
  ats?: string | null;
  status?: TrackingStatus | null;
  description: string;
}

export interface ManualJobCreateResponse extends JobDetail {
  duplicate_detected: boolean;
  duplicate_of_job_id: string | null;
  duplicate_match_kind: "url" | "content" | null;
  message?: string | null;
}

export interface SuppressedJob {
  job_id: string;
  url: string;
  company: string;
  reason: string | null;
  created_at: string;
  updated_at: string;
  created_by: string;
}

export type StoryKind = "role" | "project" | "aspiration" | "strength";
export type StorySource = "user" | "resume_extracted" | "wizard";

export interface UserStory {
  id: number;
  title: string;
  narrative: string;
  role_context: string | null;
  skills: string[];
  outcomes: string[];
  tags: string[];
  importance: number;
  time_period: string | null;
  kind: StoryKind;
  source: StorySource;
  draft: boolean;
  created_at: string;
  updated_at: string;
}

export interface UserStoryCreate {
  title: string;
  narrative?: string;
  role_context?: string | null;
  skills?: string[];
  outcomes?: string[];
  tags?: string[];
  importance?: number;
  time_period?: string | null;
  kind?: StoryKind;
  source?: StorySource;
  draft?: boolean;
}

export interface UserStoryUpdate {
  title?: string;
  narrative?: string;
  role_context?: string | null;
  skills?: string[];
  outcomes?: string[];
  tags?: string[];
  importance?: number;
  time_period?: string | null;
  kind?: StoryKind;
  draft?: boolean;
}

export interface ExtractedProfileDelta {
  full_name?: string | null;
  email?: string | null;
  phone?: string | null;
  linkedin_url?: string | null;
  portfolio_url?: string | null;
  city?: string | null;
  country?: string | null;
  years_experience?: number | null;
  skills?: string[];
  desired_job_titles?: string[];
  degree?: string | null;
  degree_field?: string | null;
}

export interface StoryCount {
  total: number;
  accepted: number;
  drafts: number;
}

export interface RelevantStory {
  id: number;
  title: string;
  kind: StoryKind;
  narrative: string;
  role_context: string | null;
  skills: string[];
  importance: number;
  similarity: number;
}
