import type {
  ActionQueueResponse,
  AppHealthResponse,
  CandidateProfile,
  ConversionResponse,
  DailyBriefing,
  ProfileGapsResponse,
  ProfileInsightsResponse,
  JobDetail,
  JobAction,
  JobEvent,
  JobsListResponse,
  ManualJobCreateRequest,
  ManualJobCreateResponse,
  ScoreRecomputeStatus,
  SourceQualityResponse,
  StatsResponse,
  SuppressedJob,
  TrackingPatchRequest,
  TrackingStatus,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";
const CLIENT_ID_KEY = "dashboard_client_id";

function getClientId(): string {
  try {
    const existing = window.localStorage.getItem(CLIENT_ID_KEY);
    if (existing && existing.trim()) return existing.trim();
    const created = window.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    window.localStorage.setItem(CLIENT_ID_KEY, created);
    return created;
  } catch {
    return "anonymous";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Client-Id": getClientId(),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function parseAttachmentFilename(header: string | null, fallback: string): string {
  const value = header ?? "";
  const utf8Match = value.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {
      return fallback;
    }
  }
  const quotedMatch = value.match(/filename="([^"]+)"/i);
  if (quotedMatch?.[1]) {
    return quotedMatch[1];
  }
  const plainMatch = value.match(/filename=([^;]+)/i);
  if (plainMatch?.[1]) {
    return plainMatch[1].trim();
  }
  return fallback;
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
  if (params.status && params.status !== "all") query.set("status", params.status);
  if (params.q?.trim()) query.set("q", params.q.trim());
  if (params.ats?.trim()) query.set("ats", params.ats.trim());
  if (params.company?.trim()) query.set("company", params.company.trim());
  if (params.posted_after?.trim()) query.set("posted_after", params.posted_after.trim());
  if (params.posted_before?.trim()) query.set("posted_before", params.posted_before.trim());
  return request<JobsListResponse>(`/api/jobs?${query.toString()}`);
}

export function getStats(): Promise<StatsResponse> {
  return request<StatsResponse>("/api/meta/stats");
}

export function getDailyBriefingLatest(): Promise<DailyBriefing> {
  return request<DailyBriefing>("/api/meta/daily-briefing/latest");
}

export function refreshDailyBriefing(): Promise<DailyBriefing> {
  return request<DailyBriefing>("/api/meta/daily-briefing/refresh", {
    method: "POST",
  });
}

export function sendDailyBriefing(): Promise<DailyBriefing> {
  return request<DailyBriefing>("/api/meta/daily-briefing/send", {
    method: "POST",
  });
}

export function getActionQueue(): Promise<ActionQueueResponse> {
  return request<ActionQueueResponse>("/api/meta/action-queue");
}

export function completeAction(actionId: number): Promise<JobAction> {
  return request<JobAction>(`/api/actions/${actionId}/complete`, {
    method: "POST",
  });
}

export function deferAction(actionId: number, days = 2): Promise<JobAction> {
  return request<JobAction>(`/api/actions/${actionId}/defer`, {
    method: "POST",
    body: JSON.stringify({ days }),
  });
}

export function getHealth(): Promise<AppHealthResponse> {
  return request<AppHealthResponse>("/api/health");
}

export function getScoreRecomputeStatus(): Promise<ScoreRecomputeStatus> {
  return request<ScoreRecomputeStatus>("/api/meta/scores/recompute-status");
}

export function triggerScoreRecompute(): Promise<{ scheduled: number }> {
  return request<{ scheduled: number }>("/api/meta/scores/recompute", { method: "POST" });
}

export function getJobDetail(jobId: string): Promise<JobDetail> {
  return request<JobDetail>(`/api/jobs/${encodeURIComponent(jobId)}`);
}

export function retryJobProcessing(jobId: string): Promise<JobDetail> {
  return request<JobDetail>(`/api/jobs/${encodeURIComponent(jobId)}/retry-processing`, {
    method: "POST",
  });
}

export function saveJobDecision(jobId: string, recommendation: "apply_now" | "review_manually" | "hold" | "archive", note?: string): Promise<{ job_id: string; recommendation: string; note: string | null; updated_at: string }> {
  return request<{ job_id: string; recommendation: string; note: string | null; updated_at: string }>(`/api/jobs/${encodeURIComponent(jobId)}/decision`, {
    method: "POST",
    body: JSON.stringify({ recommendation, note: note?.trim() || null }),
  });
}

export async function fetchJobDescriptionPdf(jobId: string, fallbackFilename = "job-description.pdf"): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}/description/pdf`, {
    headers: { "X-Client-Id": getClientId() },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with status ${response.status}`);
  }
  return {
    blob: await response.blob(),
    filename: parseAttachmentFilename(response.headers.get("Content-Disposition"), fallbackFilename),
  };
}

export function getJobEvents(jobId: string): Promise<JobEvent[]> {
  return request<JobEvent[]>(`/api/jobs/${encodeURIComponent(jobId)}/events`);
}

export function patchTracking(jobId: string, payload: TrackingPatchRequest): Promise<JobDetail> {
  return request<JobDetail>(`/api/jobs/${encodeURIComponent(jobId)}/tracking`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteJob(jobId: string): Promise<{ deleted: number }> {
  return request<{ deleted: number }>(`/api/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function isManualJobCreateDuplicateResponse(value: ManualJobCreateResponse | unknown): value is ManualJobCreateResponse {
  if (!isRecord(value)) return false;
  return value.duplicate_detected === true || typeof value.duplicate_of_job_id === "string";
}

export function manualJobCreateResponseToDetail(value: ManualJobCreateResponse): JobDetail {
  return value;
}

export function createManualJob(payload: ManualJobCreateRequest): Promise<ManualJobCreateResponse> {
  return request<ManualJobCreateResponse>("/api/jobs/manual", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function suppressJob(jobId: string, reason?: string): Promise<{ suppressed: number }> {
  return request<{ suppressed: number }>(`/api/jobs/${encodeURIComponent(jobId)}/suppress`, {
    method: "POST",
    body: JSON.stringify({ reason: reason?.trim() || null }),
  });
}

export function unsuppressJob(jobId: string): Promise<{ unsuppressed: number }> {
  return request<{ unsuppressed: number }>(`/api/jobs/${encodeURIComponent(jobId)}/unsuppress`, { method: "POST" });
}

export function getSuppressions(limit = 200): Promise<SuppressedJob[]> {
  return request<SuppressedJob[]>(`/api/suppressions?limit=${limit}`);
}

export function getConversion(): Promise<ConversionResponse> {
  return request<ConversionResponse>("/api/meta/conversion");
}

export function getSourceQuality(): Promise<SourceQualityResponse> {
  return request<SourceQualityResponse>("/api/meta/source-quality");
}

export function getProfileGaps(): Promise<ProfileGapsResponse> {
  return request<ProfileGapsResponse>("/api/meta/profile-gaps");
}

export function getProfileInsights(): Promise<ProfileInsightsResponse> {
  return request<ProfileInsightsResponse>("/api/profile/insights");
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
