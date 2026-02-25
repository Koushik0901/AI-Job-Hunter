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
