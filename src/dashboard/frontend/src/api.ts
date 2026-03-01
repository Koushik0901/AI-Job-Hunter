import type {
  ArtifactSuggestion,
  ArtifactSummary,
  ArtifactStarterStatus,
  ArtifactVersion,
  CandidateProfile,
  ResumeProfile,
  ResumeImportResponse,
  CreateArtifactVersionRequest,
  FunnelAnalyticsResponse,
  GenerateArtifactSuggestionsRequest,
  JobDetail,
  JobEvent,
  JobsListResponse,
  ManualJobCreateRequest,
  SuppressedJob,
  TrackingStatus,
  ScoreRecomputeStatus,
  StatsResponse,
  TrackingPatchRequest,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function getJobs(): Promise<JobsListResponse> {
  return request<JobsListResponse>("/api/jobs?limit=200&sort=match_desc");
}

interface GetJobsParams {
  sort?: "posted_desc" | "updated_desc" | "company_asc" | "match_desc";
  status?: TrackingStatus | "all";
  q?: string;
  ats?: string;
  company?: string;
  posted_after?: string;
  posted_before?: string;
  limit?: number;
  offset?: number;
}

export function getJobsWithParams(params: GetJobsParams = {}): Promise<JobsListResponse> {
  const query = new URLSearchParams();
  query.set("limit", String(params.limit ?? 200));
  query.set("offset", String(params.offset ?? 0));
  query.set("sort", params.sort ?? "match_desc");
  if (params.status && params.status !== "all") {
    query.set("status", params.status);
  }
  if (params.q?.trim()) {
    query.set("q", params.q.trim());
  }
  if (params.ats?.trim()) {
    query.set("ats", params.ats.trim());
  }
  if (params.company?.trim()) {
    query.set("company", params.company.trim());
  }
  if (params.posted_after?.trim()) {
    query.set("posted_after", params.posted_after.trim());
  }
  if (params.posted_before?.trim()) {
    query.set("posted_before", params.posted_before.trim());
  }
  return request<JobsListResponse>(`/api/jobs?${query.toString()}`);
}

export function getStats(): Promise<StatsResponse> {
  return request<StatsResponse>("/api/meta/stats");
}

export function getScoreRecomputeStatus(): Promise<ScoreRecomputeStatus> {
  return request<ScoreRecomputeStatus>("/api/meta/scores/recompute-status");
}

export function triggerScoreRecompute(): Promise<{ scheduled: number }> {
  return request<{ scheduled: number }>("/api/meta/scores/recompute", {
    method: "POST",
  });
}

export function getJobDetail(url: string): Promise<JobDetail> {
  return request<JobDetail>(`/api/jobs/${encodeURIComponent(url)}`);
}

export function getJobArtifacts(url: string): Promise<ArtifactSummary[]> {
  return request<ArtifactSummary[]>(`/api/jobs/${encodeURIComponent(url)}/artifacts`);
}

export function generateStarterArtifacts(url: string, force = false): Promise<ArtifactSummary[]> {
  return request<ArtifactSummary[]>(`/api/jobs/${encodeURIComponent(url)}/artifacts/starter`, {
    method: "POST",
    body: JSON.stringify({ force }),
  });
}

export function getStarterArtifactsStatus(url: string): Promise<ArtifactStarterStatus> {
  return request<ArtifactStarterStatus>(`/api/jobs/${encodeURIComponent(url)}/artifacts/starter/status`);
}

export function getArtifact(artifactId: string): Promise<ArtifactSummary> {
  return request<ArtifactSummary>(`/api/artifacts/${encodeURIComponent(artifactId)}`);
}

export function deleteArtifact(artifactId: string): Promise<{ deleted: number }> {
  return request<{ deleted: number }>(`/api/artifacts/${encodeURIComponent(artifactId)}`, {
    method: "DELETE",
  });
}

export function deleteJobArtifact(url: string, artifactType: "resume" | "cover_letter"): Promise<{ deleted: number }> {
  return request<{ deleted: number }>(
    `/api/jobs/${encodeURIComponent(url)}/artifacts/${encodeURIComponent(artifactType)}`,
    { method: "DELETE" },
  );
}

export function getArtifactVersions(artifactId: string, limit = 200): Promise<ArtifactVersion[]> {
  return request<ArtifactVersion[]>(`/api/artifacts/${encodeURIComponent(artifactId)}/versions?limit=${limit}`);
}

export function createArtifactVersion(artifactId: string, payload: CreateArtifactVersionRequest): Promise<ArtifactVersion> {
  return request<ArtifactVersion>(`/api/artifacts/${encodeURIComponent(artifactId)}/versions`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getArtifactSuggestions(artifactId: string, pendingOnly = false): Promise<ArtifactSuggestion[]> {
  const query = pendingOnly ? "?pending_only=true" : "";
  return request<ArtifactSuggestion[]>(`/api/artifacts/${encodeURIComponent(artifactId)}/suggestions${query}`);
}

export function generateArtifactSuggestions(artifactId: string, payload: GenerateArtifactSuggestionsRequest): Promise<ArtifactSuggestion[]> {
  return request<ArtifactSuggestion[]>(`/api/artifacts/${encodeURIComponent(artifactId)}/suggestions/generate`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function acceptArtifactSuggestion(
  suggestionId: string,
  payload: { edited_patch_json?: Array<Record<string, unknown>>; allow_outdated?: boolean; created_by?: string } = {},
): Promise<ArtifactVersion> {
  return request<ArtifactVersion>(`/api/suggestions/${encodeURIComponent(suggestionId)}/accept`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function rejectArtifactSuggestion(suggestionId: string): Promise<{ state: string }> {
  return request<{ state: string }>(`/api/suggestions/${encodeURIComponent(suggestionId)}/reject`, {
    method: "POST",
  });
}

export async function exportArtifactPdf(artifactId: string): Promise<Blob> {
  let lastError: Error | null = null;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const response = await fetch(`${API_BASE}/api/artifacts/${encodeURIComponent(artifactId)}/export/pdf`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ format: "pdf" }),
    });
    if (response.ok) {
      return response.blob();
    }
    const text = await response.text();
    let detail = text;
    try {
      const parsed = JSON.parse(text) as { detail?: string };
      if (typeof parsed.detail === "string" && parsed.detail.trim()) {
        detail = parsed.detail;
      }
    } catch {
      // keep raw text
    }
    lastError = new Error(detail || `Export failed with status ${response.status}`);
    if (response.status === 503 && attempt === 0) {
      await new Promise((resolve) => window.setTimeout(resolve, 350));
      continue;
    }
    break;
  }
  throw (lastError ?? new Error("Export failed"));
}

export function getJobEvents(url: string): Promise<JobEvent[]> {
  return request<JobEvent[]>(`/api/jobs/${encodeURIComponent(url)}/events`);
}

export function patchTracking(url: string, payload: TrackingPatchRequest): Promise<JobDetail> {
  return request<JobDetail>(`/api/jobs/${encodeURIComponent(url)}/tracking`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteJob(url: string): Promise<{ deleted: number }> {
  return request<{ deleted: number }>(`/api/jobs/${encodeURIComponent(url)}`, {
    method: "DELETE",
  });
}

export function createManualJob(payload: ManualJobCreateRequest): Promise<JobDetail> {
  return request<JobDetail>("/api/jobs/manual", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function suppressJob(url: string, reason?: string): Promise<{ suppressed: number }> {
  return request<{ suppressed: number }>(`/api/jobs/${encodeURIComponent(url)}/suppress`, {
    method: "POST",
    body: JSON.stringify({ reason: reason?.trim() || null }),
  });
}

export function unsuppressJob(url: string): Promise<{ unsuppressed: number }> {
  return request<{ unsuppressed: number }>(`/api/jobs/${encodeURIComponent(url)}/unsuppress`, {
    method: "POST",
  });
}

export function getSuppressions(limit = 200): Promise<SuppressedJob[]> {
  return request<SuppressedJob[]>(`/api/suppressions?limit=${limit}`);
}

export function getProfile(): Promise<CandidateProfile> {
  return request<CandidateProfile>("/api/profile");
}

export function putProfile(payload: CandidateProfile): Promise<CandidateProfile> {
  return request<CandidateProfile>("/api/profile", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function addProfileSkill(skill: string): Promise<CandidateProfile> {
  return request<CandidateProfile>("/api/profile/skills", {
    method: "POST",
    body: JSON.stringify({ skill }),
  });
}

export function getResumeProfile(): Promise<ResumeProfile> {
  return request<ResumeProfile>("/api/profile/resume");
}

export function putResumeProfile(payload: ResumeProfile): Promise<ResumeProfile> {
  return request<ResumeProfile>("/api/profile/resume", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function importResumeProfile(sourcePath?: string): Promise<ResumeImportResponse> {
  return request<ResumeImportResponse>("/api/profile/resume/import", {
    method: "POST",
    body: JSON.stringify({ source_path: sourcePath ?? null }),
  });
}

export async function importResumeProfileFromFile(file: File): Promise<ResumeImportResponse> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch(`${API_BASE}/api/profile/resume/import/upload`, {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with status ${response.status}`);
  }
  return response.json() as Promise<ResumeImportResponse>;
}

interface FunnelParams {
  preset?: "30d" | "90d" | "all";
  from?: string;
  to?: string;
  status_scope?: "pipeline" | "all";
  applications_goal_target?: number;
  interviews_goal_target?: number;
  forecast_apps_per_week?: number;
}

export function getFunnelAnalytics(params: FunnelParams = {}): Promise<FunnelAnalyticsResponse> {
  const query = new URLSearchParams();
  query.set("preset", params.preset ?? "90d");
  query.set("status_scope", params.status_scope ?? "pipeline");
  if (params.from) query.set("from", params.from);
  if (params.to) query.set("to", params.to);
  if (typeof params.applications_goal_target === "number") {
    query.set("applications_goal_target", String(params.applications_goal_target));
  }
  if (typeof params.interviews_goal_target === "number") {
    query.set("interviews_goal_target", String(params.interviews_goal_target));
  }
  if (typeof params.forecast_apps_per_week === "number") {
    query.set("forecast_apps_per_week", String(params.forecast_apps_per_week));
  }
  return request<FunnelAnalyticsResponse>(`/api/analytics/funnel?${query.toString()}`);
}
