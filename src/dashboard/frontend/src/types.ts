export type TrackingStatus = "not_applied" | "staging" | "applied" | "interviewing" | "offer" | "rejected";

export type Priority = "low" | "medium" | "high";

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
  updated_at: string | null;
  match_score: number | null;
  match_band: string | null;
  desired_title_match: boolean;
  staging_entered_at: string | null;
  staging_due_at: string | null;
  staging_overdue: boolean;
  staging_age_hours: number | null;
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
  applied_at: string | null;
  next_step: string | null;
  target_compensation: string | null;
  tracking_updated_at: string | null;
  staging_entered_at: string | null;
  staging_due_at: string | null;
  staging_overdue: boolean;
  staging_age_hours: number | null;
  enrichment: JobEnrichment | null;
  match: JobMatchScore | null;
  match_meta: JobMatchMeta | null;
  desired_title_match: boolean;
}

export interface JobMatchScore {
  score: number;
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
}

export interface ResumeProfile {
  baseline_resume_json: Record<string, unknown>;
  template_id: string;
  use_template_typography: boolean;
  document_typography_override: Record<string, unknown>;
  updated_at: string | null;
}

export interface CandidateEvidenceAssets {
  evidence_context: Record<string, unknown>;
  brag_document_markdown: string;
  project_cards: Array<Record<string, unknown>>;
  do_not_claim: string[];
  updated_at: string | null;
}

export interface CandidateEvidenceIndexStatus {
  enabled: boolean;
  backend: string;
  status: string;
  indexed_count: number;
  message: string;
  updated_at: number | null;
  collection: string | null;
}

export interface ServiceHealthStatus {
  configured: boolean;
  healthy: boolean;
  message: string;
  collection?: string | null;
  collection_exists?: boolean;
}

export interface AppHealthResponse {
  status: string;
  services: {
    redis: ServiceHealthStatus;
    qdrant: ServiceHealthStatus;
  };
}

export interface CompanySource {
  id: number;
  name: string;
  ats_type: string;
  ats_url: string;
  slug: string;
  enabled: boolean;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface CompanySourceProbeResult {
  name: string;
  slug: string;
  ats_type: string;
  ats_url: string;
  jobs: number;
  exists: boolean;
  existing_name: string | null;
  source?: string | null;
  low_signal?: boolean;
  suppressed_reason?: string | null;
}

export interface CompanySourceProbeResponse {
  query: string;
  company_name: string;
  slugs: string[];
  inferred: Record<string, string> | null;
  matches: CompanySourceProbeResult[];
  zero_job_matches: CompanySourceProbeResult[];
}

export interface CompanySourceImportResponse {
  new_entries: CompanySourceProbeResult[];
  skipped_duplicates: number;
  imported: number | null;
}

export interface WorkspaceOperation {
  id: string;
  kind: string;
  status: string;
  params: Record<string, unknown>;
  summary: Record<string, unknown>;
  log_tail: string;
  started_at: string;
  finished_at: string | null;
  error: string | null;
}

export interface WorkspaceOverview {
  total_jobs: number;
  enabled_company_sources: number;
  total_company_sources: number;
  desired_job_titles_count: number;
  has_profile_basics: boolean;
  services: AppHealthResponse["services"];
  recent_operations: WorkspaceOperation[];
}

export interface ResumeImportResponse {
  source_path: string;
  baseline_resume_json: Record<string, unknown>;
}

export interface JobEvent {
  id: number;
  url: string;
  event_type: string;
  title: string;
  body: string | null;
  event_at: string;
  created_at: string;
}

export interface StatsResponse {
  total_jobs: number;
  tracked_jobs: number;
  active_pipeline: number;
  recent_activity_7d: number;
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

export interface ArtifactVersion {
  id: string;
  artifact_id: string;
  version: number;
  label: "draft" | "tailored" | "final" | string;
  content_json: Record<string, unknown> | null;
  content_text: string | null;
  meta_json: Record<string, unknown>;
  created_at: string;
  created_by: string;
  supersedes_version_id: string | null;
  base_version_id: string | null;
}

export interface ResumeLatexDocument {
  artifact_id: string;
  version_id: string | null;
  version: number | null;
  source_text: string;
  template_id: string;
  compile_status: string;
  compile_error: string | null;
  pdf_available: boolean;
  compiled_at: string | null;
  log_tail: string | null;
  diagnostics?: Array<Record<string, unknown>>;
}

export interface ArtifactLatexDocument {
  artifact_id: string;
  artifact_type: "resume" | "cover_letter" | string;
  version_id: string | null;
  version: number | null;
  source_text: string;
  template_id: string;
  compile_status: string;
  compile_error: string | null;
  pdf_available: boolean;
  compiled_at: string | null;
  log_tail: string | null;
  diagnostics: Array<Record<string, unknown>>;
}

export interface ResumeSwarmOptimizeResponse {
  artifact_id: string;
  version_id: string;
  version: number;
  final_score: Record<string, unknown>;
  history: Array<Record<string, unknown>>;
}

export interface ResumeSwarmRunStartResponse {
  run_id: string;
  status: string;
}

export interface ResumeSwarmRunStatusResponse {
  run_id: string;
  artifact_id: string;
  status: string;
  current_stage: string;
  stage_index: number;
  started_at: string;
  updated_at: string;
  cycles_target: number;
  cycles_done: number;
  events: Array<Record<string, unknown>>;
  latest_score: Record<string, unknown> | null;
  latest_rewrite: Record<string, unknown> | null;
  latest_apply_report: Record<string, unknown> | null;
  final_score: Record<string, unknown> | null;
  candidate_latex: string | null;
  error: string | null;
}

export interface TemplateSettings {
  resume_template_id: string;
  cover_letter_template_id: string;
  updated_at: string | null;
}

export interface TemplateValidationResult {
  ok: boolean;
  warnings: string[];
  missing_required_sections: string[];
  missing_required_placeholders: string[];
  detected_sections: string[];
  detected_items: string[];
}

export interface ArtifactSummary {
  id: string;
  job_id: string;
  job_url: string;
  artifact_type: "resume" | "cover_letter" | string;
  active_version_id: string | null;
  active_version: ArtifactVersion | null;
  created_at: string;
}

export interface ArtifactStarterStatus {
  job_id: string;
  job_url: string;
  stage: string;
  progress_percent: number;
  running: boolean;
  updated_at: string | null;
}

export interface ArtifactsHubItem {
  job_id: string;
  job_url: string;
  company: string;
  title: string;
  tracking_status: TrackingStatus | string;
  tracking_updated_at: string | null;
  latest_artifact_updated_at: string | null;
  resume: ArtifactSummary | null;
  cover_letter: ArtifactSummary | null;
}

export interface ArtifactsHubResponse {
  items: ArtifactsHubItem[];
  total: number;
}

export interface TrackingPatchRequest {
  status?: TrackingStatus;
  priority?: Priority;
  applied_at?: string | null;
  next_step?: string | null;
  target_compensation?: string | null;
}

export interface CreateArtifactVersionRequest {
  label: "draft" | "tailored" | "final";
  content_json: Record<string, unknown>;
  meta_json?: Record<string, unknown>;
  created_by?: string;
  base_version_id?: string | null;
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

export interface SuppressedJob {
  job_id: string;
  url: string;
  company: string;
  reason: string | null;
  created_at: string;
  updated_at: string;
  created_by: string;
}

export interface FunnelWindow {
  from: string | null;
  to: string | null;
  preset: "30d" | "90d" | "all" | string;
}

export interface FunnelStage {
  status: TrackingStatus | "rejected";
  count: number;
}

export interface FunnelConversions {
  backlog_to_staging: number;
  staging_to_applied: number;
  applied_to_interviewing: number;
  interviewing_to_offer: number;
  backlog_to_offer: number;
}

export interface FunnelTotals {
  tracked_total: number;
  active_total: number;
  offer_total: number;
}

export interface FunnelComparisonWindow {
  from: string | null;
  to: string | null;
  days: number;
}

export interface FunnelDeltaSummary {
  tracked_total: number;
  active_total: number;
  offer_total: number;
  conversions: FunnelConversions;
  comparison_window: FunnelComparisonWindow | null;
}

export interface WeeklyGoalMetric {
  target: number;
  actual: number;
  progress: number;
}

export interface FunnelWeeklyGoals {
  window_start: string;
  window_end: string;
  applications: WeeklyGoalMetric;
  interviews: WeeklyGoalMetric;
}

export interface FunnelAlerts {
  staging_overdue_48h: number;
  interviewing_no_activity_5d: number;
  backlog_expiring_soon: number;
}

export interface CohortFunnelRow {
  week_start: string;
  stages: FunnelStage[];
  tracked_total: number;
  offer_rate: number;
}

export interface SourceQualityItem {
  name: string;
  tracked_total: number;
  active_total: number;
  offers: number;
  offer_rate: number;
  interview_rate: number;
}

export interface SourceQualitySummary {
  ats: SourceQualityItem[];
  companies: SourceQualityItem[];
}

export interface ForecastWindow {
  days: number;
  projected_interviews: number;
  projected_offers: number;
  interviews_low: number;
  interviews_high: number;
  offers_low: number;
  offers_high: number;
}

export interface ForecastSummary {
  applications_per_week: number;
  interview_rate: number;
  offer_rate_from_interview: number;
  confidence_band: "low" | "medium" | "high" | string;
  confidence_margin: number;
  windows: ForecastWindow[];
}

export interface FunnelAnalyticsResponse {
  window: FunnelWindow;
  stages: FunnelStage[];
  conversions: FunnelConversions;
  totals: FunnelTotals;
  deltas: FunnelDeltaSummary;
  weekly_goals: FunnelWeeklyGoals;
  alerts: FunnelAlerts;
  cohorts: CohortFunnelRow[];
  source_quality: SourceQualitySummary;
  forecast: ForecastSummary;
}
