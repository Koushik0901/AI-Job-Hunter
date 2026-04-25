// Typed fetch client for the AI Job Hunter backend.
// Dev server uses Vite proxy: /api -> http://127.0.0.1:8000 (vite.config.ts).

export interface JobSummary {
  id: string;
  url: string;
  company: string;
  title: string;
  location: string;
  posted: string;
  ats: string;
  status: string;
  priority: string;
  pinned: boolean;
  updated_at: string | null;
  match_score: number | null;
  raw_score: number | null;
  match_band: string | null;
  desired_title_match: boolean;
  required_skills: string[];
  fit_score: number | null;
  interview_likelihood_score: number | null;
  urgency_score: number | null;
  friction_score: number | null;
  confidence_score: number | null;
  recommendation: string | null;
  recommendation_reasons: string[];
  guidance_title: string | null;
  guidance_summary: string | null;
  health_label: string | null;
  llm_blurb?: string | null;
}

export interface JobEnrichment {
  work_mode: string | null;
  remote_geo: string | null;
  canada_eligible: string | null;
  seniority: string | null;
  role_family: string | null;
  years_exp_min: number | null;
  years_exp_max: number | null;
  required_skills: string[];
  preferred_skills: string[];
  formatted_description: string | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
}

export interface JobMatchScore {
  score: number;
  raw_score: number | null;
  band: string;
  breakdown: Record<string, number>;
  reasons: string[];
  confidence: string;
}

export interface JobDetail extends JobSummary {
  description: string;
  first_seen: string;
  last_seen: string;
  applied_at: string | null;
  enrichment: JobEnrichment | null;
  match: JobMatchScore | null;
}

export interface EducationEntry {
  degree: string;
  field: string | null;
}

export interface CandidateProfile {
  years_experience: number;
  skills: string[];
  desired_job_titles: string[];
  target_role_families: string[];
  requires_visa_sponsorship: boolean;
  education: EducationEntry[];
  degree: string | null;
  degree_field: string | null;
  score_version: number | null;
  updated_at: string | null;
  // Identity
  full_name: string | null;
  first_name: string | null;
  last_name: string | null;
  pronouns: string | null;
  // Contact
  email: string | null;
  phone: string | null;
  // Address
  street_address: string | null;
  address_line2: string | null;
  city: string | null;
  state_province: string | null;
  postal_code: string | null;
  country: string | null;
  // Links
  linkedin_url: string | null;
  portfolio_url: string | null;
  github_url: string | null;
  // Career
  narrative_intent: string | null;
  desired_salary: string | null;
  work_authorization: string | null;
  preferred_work_mode: string | null;
  willing_to_relocate: boolean;
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

export interface ProfileGapItem {
  label: string;
  kind: string;
  count: number;
  example_job_ids: string[];
}

export interface ProfileInsightsResponse {
  top_missing_signals: ProfileGapItem[];
  roles_you_should_target_more: string[];
  roles_you_should_target_less: string[];
  suggested_profile_updates: string[];
}

export interface StatsResponse {
  total_jobs: number;
  tracked_jobs: number;
  active_pipeline: number;
  recent_activity_7d: number;
  overdue_staging_count: number;
  by_status: Record<string, number>;
}

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
  kind: string;
  source: string;
  draft: boolean;
  created_at: string;
  updated_at: string;
}

export interface InterviewTurn {
  question: string;
  answer: string;
}

export interface InterviewNextResponse {
  next_question: string | null;
  done: boolean;
  covered: string[];
  question_index: number;
}

export interface InterviewStoryDraft {
  title: string;
  narrative: string;
  kind: string;
  skills: string[];
  outcomes: string[];
  tags: string[];
  time_period: string | null;
}

export interface InterviewProfilePatch {
  skills: string[];
  desired_job_titles: string[];
  preferred_work_mode: string | null;
  narrative_intent: string | null;
}

export interface InterviewFinishResponse {
  stories: InterviewStoryDraft[];
  profile_patch: InterviewProfilePatch;
}

export interface BaseDocument {
  id: number;
  doc_type: string;
  filename: string;
  content_md: string;
  is_default: boolean;
  created_at: string;
}

export interface JobArtifact {
  id: number;
  job_id: string;
  artifact_type: string;
  content_md: string;
  base_doc_id: number | null;
  version: number;
  is_active: boolean;
  generated_by: string | null;
  created_at: string;
  updated_at: string;
  story_ids_used: number[];
}

export interface QueueItem {
  id: number;
  job_id: string;
  status: string;
  sort_order: number;
  queued_at: string;
  title: string;
  company: string;
  location: string | null;
  ats: string | null;
  match_score: number | null;
}

export interface BootstrapResponse {
  profile: CandidateProfile | null;
  stats: StatsResponse | null;
  recommended_jobs: JobSummary[];
}

export interface JobsListResponse {
  items: JobSummary[];
  total: number;
}

export interface AgentChatRequest {
  messages: { role: "user" | "assistant"; content: string }[];
  skill_invocation?: {
    name: "discover" | "resume" | "cover-letter" | "critique";
    arguments?: string;
    selected_job_id?: string | null;
    active_artifact_id?: number | null;
  };
}

export interface AgentChatResponse {
  reply: string;
  context_snapshot: string;
  response_mode: "fast" | "llm" | "llm_strong" | "tool_agent" | "fallback" | "skill";
  output_kind: "none" | "discovery" | "resume" | "cover_letter" | "critique";
  output_payload: Record<string, unknown> | null;
  operation_id: string | null;
}

export interface AtsCritiqueResponse {
  pass_likelihood: number;
  missing_keywords: string[];
  weak_sections: string[];
  suggestions: string[];
  revised_resume: string | null;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!r.ok) {
    const body = await r.text().catch(() => "");
    throw new Error(`${r.status} ${r.statusText} — ${path}${body ? ` — ${body.slice(0, 200)}` : ""}`);
  }
  if (r.status === 204) return undefined as T;
  return r.json() as Promise<T>;
}

export const api = {
  bootstrap: () => req<BootstrapResponse>("/api/bootstrap"),
  profile: () => req<CandidateProfile>("/api/profile"),
  updateProfile: (data: Partial<CandidateProfile>) =>
    req<CandidateProfile>("/api/profile", { method: "PUT", body: JSON.stringify(data) }),
  stats: () => req<StatsResponse>("/api/meta/stats"),
  conversion: () => req<ConversionResponse>("/api/meta/conversion"),
  sourceQuality: () => req<{ items: SourceQualityItem[] }>("/api/meta/source-quality"),
  profileInsights: () => req<ProfileInsightsResponse>("/api/profile/insights"),

  listJobs: (params: {
    status?: "not_applied" | "staging" | "applied" | "interviewing" | "offer" | "rejected";
    limit?: number;
    sort?: "match_desc" | "posted_desc" | "updated_desc" | "company_asc";
    q?: string;
  } = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => { if (v != null && v !== "") qs.set(k, String(v)); });
    return req<JobsListResponse>(`/api/jobs${qs.toString() ? `?${qs}` : ""}`);
  },
  job: (id: string) => req<JobDetail>(`/api/jobs/${encodeURIComponent(id)}`),
  createManualJob: (payload: {
    url: string;
    company: string;
    title: string;
    description: string;
    location?: string;
    posted?: string;
    ats?: string;
    status?: "not_applied" | "staging" | "applied" | "interviewing" | "offer" | "rejected";
  }) =>
    req<JobDetail & { duplicate_detected?: boolean; duplicate_of_job_id?: string | null }>(
      "/api/jobs/manual",
      { method: "POST", body: JSON.stringify(payload) }
    ),
  updateTracking: (
    jobId: string,
    patch: { status?: string; priority?: string; pinned?: boolean; applied_at?: string }
  ) =>
    req<JobDetail>(`/api/jobs/${encodeURIComponent(jobId)}/tracking`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  regenerateBlurb: (id: string) =>
    req<{ job_id: string; blurb: string | null; generated: boolean }>(
      `/api/jobs/${encodeURIComponent(id)}/regenerate-blurb`,
      { method: "POST" }
    ),

  interviewNext: (conversation: InterviewTurn[]) =>
    req<InterviewNextResponse>("/api/stories/interview/next", {
      method: "POST",
      body: JSON.stringify({ conversation }),
    }),
  interviewFinish: (conversation: InterviewTurn[]) =>
    req<InterviewFinishResponse>("/api/stories/interview/finish", {
      method: "POST",
      body: JSON.stringify({ conversation }),
    }),

  listStories: () => req<UserStory[]>("/api/stories"),
  storiesCount: () => req<{ count: number }>("/api/stories/count"),
  createStory: (body: Partial<UserStory> & { title: string }) =>
    req<UserStory>("/api/stories", { method: "POST", body: JSON.stringify(body) }),

  listBaseDocs: () => req<BaseDocument[]>("/api/profile/documents"),
  uploadDocument: (file: File, doc_type: string): Promise<BaseDocument> => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("doc_type", doc_type);
    return fetch("/api/profile/documents", { method: "POST", body: fd })
      .then(r => { if (!r.ok) throw new Error(`${r.status} ${r.statusText}`); return r.json(); });
  },
  deleteDocument: (id: number) =>
    req<void>(`/api/profile/documents/${id}`, { method: "DELETE" }),
  setDefaultDocument: (id: number) =>
    req<BaseDocument>(`/api/profile/documents/${id}/default`, { method: "PATCH" }),

  jobArtifacts: (jobId: string) => req<JobArtifact[]>(`/api/jobs/${encodeURIComponent(jobId)}/artifacts`),
  updateArtifact: (artifactId: number, content_md: string) =>
    req<JobArtifact>(`/api/artifacts/${artifactId}`, {
      method: "PUT",
      body: JSON.stringify({ content_md }),
    }),
  artifactPdfUrl: (artifactId: number) => `/api/artifacts/${artifactId}/pdf`,

  generateResume: (jobId: string, base_doc_id: number) =>
    req<{ id: string }>(`/api/jobs/${encodeURIComponent(jobId)}/artifacts/resume`, {
      method: "POST",
      body: JSON.stringify({ base_doc_id }),
    }),
  generateCoverLetter: (jobId: string, base_doc_id: number) =>
    req<{ id: string }>(`/api/jobs/${encodeURIComponent(jobId)}/artifacts/cover-letter`, {
      method: "POST",
      body: JSON.stringify({ base_doc_id }),
    }),
  atsCritique: (jobId: string, resume_md: string) =>
    req<AtsCritiqueResponse>(`/api/jobs/${encodeURIComponent(jobId)}/artifacts/ats-critique`, {
      method: "POST",
      body: JSON.stringify({ resume_md }),
    }),

  agentChat: (body: AgentChatRequest) =>
    req<AgentChatResponse>("/api/agent/chat", { method: "POST", body: JSON.stringify(body) }),

  listQueue: () => req<QueueItem[]>("/api/queue"),
  addToQueue: (job_id: string) =>
    req<QueueItem>("/api/queue", { method: "POST", body: JSON.stringify({ job_id }) }),
};
