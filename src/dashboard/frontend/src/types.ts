export type TrackingStatus = "not_applied" | "staging" | "applied" | "interviewing" | "offer" | "rejected";

export type Priority = "low" | "medium" | "high";

export interface JobSummary {
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
  enrichment: JobEnrichment | null;
  match: JobMatchScore | null;
}

export interface JobMatchScore {
  score: number;
  band: string;
  breakdown: Record<string, number>;
  reasons: string[];
  confidence: string;
}

export interface CandidateProfile {
  years_experience: number;
  skills: string[];
  target_role_families: string[];
  requires_visa_sponsorship: boolean;
  education: Array<{ degree: string; field: string | null }>;
  degree: string | null;
  degree_field: string | null;
  updated_at: string | null;
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

export interface TrackingPatchRequest {
  status?: TrackingStatus;
  priority?: Priority;
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
  description: string;
}

export interface SuppressedJob {
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
  staging_stale_7d: number;
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
