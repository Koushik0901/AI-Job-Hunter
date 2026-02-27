import type {
  CandidateProfile,
  FunnelAnalyticsResponse,
  JobDetail,
  JobEvent,
  JobsListResponse,
  ManualJobCreateRequest,
  SuppressedJob,
  TrackingStatus,
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
  return request<JobsListResponse>("/api/jobs?limit=500&sort=match_desc");
}

interface GetJobsParams {
  sort?: "posted_desc" | "updated_desc" | "company_asc" | "match_desc";
  status?: TrackingStatus | "all";
  q?: string;
  ats?: string;
  company?: string;
  posted_after?: string;
  posted_before?: string;
}

export function getJobsWithParams(params: GetJobsParams = {}): Promise<JobsListResponse> {
  const query = new URLSearchParams();
  query.set("limit", "500");
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

export function getJobDetail(url: string): Promise<JobDetail> {
  return request<JobDetail>(`/api/jobs/${encodeURIComponent(url)}`);
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
