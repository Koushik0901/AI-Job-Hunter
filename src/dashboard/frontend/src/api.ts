import type {
  CandidateProfile,
  JobDetail,
  JobEvent,
  JobsListResponse,
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

export function getProfile(): Promise<CandidateProfile> {
  return request<CandidateProfile>("/api/profile");
}

export function putProfile(payload: CandidateProfile): Promise<CandidateProfile> {
  return request<CandidateProfile>("/api/profile", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}
