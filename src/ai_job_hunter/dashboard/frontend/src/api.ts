import type {
  ActionQueueResponse,
  AgentChatResponse,
  AgentSkillInvocation,
  AgentMessage,
  AppHealthResponse,
  BaseDocument,
  BootstrapResponse,
  CandidateProfile,
  ConversionResponse,
  DailyBriefing,
  JobArtifact,
  ProfileGapsResponse,
  ProfileInsightsResponse,
  JobDetail,
  JobAction,
  JobEvent,
  JobsListResponse,
  ManualJobCreateRequest,
  ManualJobCreateResponse,
  QueueItem,
  ScoreRecomputeStatus,
  SourceQualityResponse,
  StatsResponse,
  SuppressedJob,
  TrackingPatchRequest,
  TrackingStatus,
  WorkspaceOperation,
} from "./types";

const RAW_API_BASE = (import.meta.env.VITE_API_BASE ?? "").trim();
const API_BASE = RAW_API_BASE.replace(/\/+$/, "");
const RAW_AGENT_API_BASE = (import.meta.env.VITE_AGENT_API_BASE ?? "").trim();
const AGENT_API_BASE = RAW_AGENT_API_BASE.replace(/\/+$/, "");
const CLIENT_ID_KEY = "dashboard_client_id";
const CLIENT_CACHE_TTL = {
  bootstrap: 20_000,
  jobsList: 20_000,
  stats: 20_000,
  actionQueue: 20_000,
  jobDetail: 45_000,
  jobEvents: 30_000,
  queue: 20_000,
  artifacts: 20_000,
} as const;
type CacheEntry<T> = { value: T; expiresAt: number };
const responseCache = new Map<string, CacheEntry<unknown>>();

export function buildApiUrl(path: string): string {
  return API_BASE ? `${API_BASE}${path}` : path;
}

function buildAgentApiUrl(path: string): string {
  return AGENT_API_BASE ? `${AGENT_API_BASE}${path}` : buildApiUrl(path);
}

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
  const response = await fetch(buildApiUrl(path), {
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
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

async function agentRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(buildAgentApiUrl(path), {
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
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

function getCachedValue<T>(key: string): T | null {
  const existing = responseCache.get(key);
  if (!existing) return null;
  if (existing.expiresAt <= Date.now()) {
    responseCache.delete(key);
    return null;
  }
  return existing.value as T;
}

function setCachedValue<T>(key: string, value: T, ttlMs: number): T {
  responseCache.set(key, { value, expiresAt: Date.now() + ttlMs });
  return value;
}

function invalidateCache(key: string): void {
  responseCache.delete(key);
}

function invalidateCachePrefix(prefix: string): void {
  for (const key of responseCache.keys()) {
    if (key.startsWith(prefix)) {
      responseCache.delete(key);
    }
  }
}

async function cachedRequest<T>(key: string, ttlMs: number, path: string): Promise<T> {
  const cached = getCachedValue<T>(key);
  if (cached !== null) return cached;
  const value = await request<T>(path);
  return setCachedValue(key, value, ttlMs);
}

export function invalidateJobDetailCache(jobId: string): void {
  invalidateCache(`job-detail:${jobId}`);
}

export function invalidateJobEventsCache(jobId: string): void {
  invalidateCache(`job-events:${jobId}`);
}

export function invalidateQueueCache(): void {
  invalidateCache("queue");
}

export function invalidateJobArtifactsCache(jobId: string): void {
  invalidateCache(`job-artifacts:${jobId}`);
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

function jobsListCacheKey(params: GetJobsParams): string {
  const normalized = {
    sort: params.sort ?? "match_desc",
    status: params.status ?? "all",
    q: params.q?.trim() ?? "",
    ats: params.ats?.trim() ?? "",
    company: params.company?.trim() ?? "",
    posted_after: params.posted_after?.trim() ?? "",
    posted_before: params.posted_before?.trim() ?? "",
    limit: params.limit ?? 200,
    offset: params.offset ?? 0,
  };
  return `jobs-list:${JSON.stringify(normalized)}`;
}

export function invalidateJobsListCache(): void {
  invalidateCachePrefix("jobs-list:");
}

export function getJobsWithParams(
  params: GetJobsParams = {},
  options: { force?: boolean } = {},
): Promise<JobsListResponse> {
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
  const cacheKey = jobsListCacheKey(params);
  if (options.force) {
    invalidateCache(cacheKey);
  }
  return cachedRequest<JobsListResponse>(
    cacheKey,
    CLIENT_CACHE_TTL.jobsList,
    `/api/jobs?${query.toString()}`,
  );
}

export function getStats(options: { force?: boolean } = {}): Promise<StatsResponse> {
  if (options.force) {
    invalidateCache("stats");
  }
  return cachedRequest<StatsResponse>("stats", CLIENT_CACHE_TTL.stats, "/api/meta/stats");
}

export function getBootstrap(options: { force?: boolean } = {}): Promise<BootstrapResponse> {
  if (options.force) {
    invalidateCache("bootstrap");
  }
  return cachedRequest<BootstrapResponse>("bootstrap", CLIENT_CACHE_TTL.bootstrap, "/api/bootstrap");
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

export function getActionQueue(options: { force?: boolean } = {}): Promise<ActionQueueResponse> {
  if (options.force) {
    invalidateCache("action-queue");
  }
  return cachedRequest<ActionQueueResponse>(
    "action-queue",
    CLIENT_CACHE_TTL.actionQueue,
    "/api/meta/action-queue",
  );
}

export function completeAction(actionId: number): Promise<JobAction> {
  return request<JobAction>(`/api/actions/${actionId}/complete`, {
    method: "POST",
  }).then((value) => {
    invalidateCache("action-queue");
    invalidateCache("stats");
    invalidateJobsListCache();
    invalidateCachePrefix("bootstrap");
    return value;
  });
}

export function deferAction(actionId: number, days = 2): Promise<JobAction> {
  return request<JobAction>(`/api/actions/${actionId}/defer`, {
    method: "POST",
    body: JSON.stringify({ days }),
  }).then((value) => {
    invalidateCache("action-queue");
    invalidateJobsListCache();
    invalidateCachePrefix("bootstrap");
    return value;
  });
}

export function getHealth(): Promise<AppHealthResponse> {
  return request<AppHealthResponse>("/api/health");
}

export function getScoreRecomputeStatus(): Promise<ScoreRecomputeStatus> {
  return request<ScoreRecomputeStatus>("/api/meta/scores/recompute-status");
}

export function getSkillAliases(): Promise<Record<string, string>> {
  return request<Record<string, string>>("/api/meta/skill-aliases");
}

export function triggerScoreRecompute(): Promise<{ scheduled: number }> {
  return request<{ scheduled: number }>("/api/meta/scores/recompute", { method: "POST" });
}

export function getJobDetail(jobId: string, options: { force?: boolean } = {}): Promise<JobDetail> {
  if (options.force) {
    invalidateJobDetailCache(jobId);
  }
  return cachedRequest<JobDetail>(
    `job-detail:${jobId}`,
    CLIENT_CACHE_TTL.jobDetail,
    `/api/jobs/${encodeURIComponent(jobId)}`,
  );
}

export async function prefetchJobDetail(jobId: string): Promise<void> {
  if (!jobId || getCachedValue<JobDetail>(`job-detail:${jobId}`) !== null) return;
  try {
    await getJobDetail(jobId);
  } catch {
    // ignore prefetch failures
  }
}

export function retryJobProcessing(jobId: string): Promise<JobDetail> {
  return request<JobDetail>(`/api/jobs/${encodeURIComponent(jobId)}/retry-processing`, {
    method: "POST",
  }).then((value) => {
    invalidateCache(`job-detail:${jobId}`);
    invalidateJobsListCache();
    invalidateCachePrefix("bootstrap");
    return value;
  });
}

export function saveJobDecision(jobId: string, recommendation: "apply_now" | "review_manually" | "hold" | "archive", note?: string): Promise<{ job_id: string; recommendation: string; note: string | null; updated_at: string }> {
  return request<{ job_id: string; recommendation: string; note: string | null; updated_at: string }>(`/api/jobs/${encodeURIComponent(jobId)}/decision`, {
    method: "POST",
    body: JSON.stringify({ recommendation, note: note?.trim() || null }),
  }).then((value) => {
    invalidateCache(`job-detail:${jobId}`);
    invalidateJobsListCache();
    invalidateCachePrefix("bootstrap");
    return value;
  });
}

export async function fetchJobDescriptionPdf(jobId: string, fallbackFilename = "job-description.pdf"): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(buildApiUrl(`/api/jobs/${encodeURIComponent(jobId)}/description/pdf`), {
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

export function getJobEvents(jobId: string, options: { force?: boolean } = {}): Promise<JobEvent[]> {
  if (options.force) {
    invalidateJobEventsCache(jobId);
  }
  return cachedRequest<JobEvent[]>(
    `job-events:${jobId}`,
    CLIENT_CACHE_TTL.jobEvents,
    `/api/jobs/${encodeURIComponent(jobId)}/events`,
  );
}

export async function prefetchJobEvents(jobId: string): Promise<void> {
  if (!jobId || getCachedValue<JobEvent[]>(`job-events:${jobId}`) !== null) return;
  try {
    await getJobEvents(jobId);
  } catch {
    // ignore prefetch failures
  }
}

export function patchTracking(jobId: string, payload: TrackingPatchRequest): Promise<JobDetail> {
  return request<JobDetail>(`/api/jobs/${encodeURIComponent(jobId)}/tracking`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  }).then((value) => {
    invalidateCache(`job-detail:${jobId}`);
    invalidateJobsListCache();
    invalidateCachePrefix("bootstrap");
    return value;
  });
}

export function deleteJob(jobId: string): Promise<{ deleted: number }> {
  return request<{ deleted: number }>(`/api/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" }).then((value) => {
    invalidateCache(`job-detail:${jobId}`);
    invalidateCache(`job-events:${jobId}`);
    invalidateJobsListCache();
    invalidateCachePrefix("bootstrap");
    return value;
  });
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
  }).then((value) => {
    invalidateJobsListCache();
    invalidateCachePrefix("bootstrap");
    return value;
  });
}

export function suppressJob(jobId: string, reason?: string): Promise<{ suppressed: number }> {
  return request<{ suppressed: number }>(`/api/jobs/${encodeURIComponent(jobId)}/suppress`, {
    method: "POST",
    body: JSON.stringify({ reason: reason?.trim() || null }),
  }).then((value) => {
    invalidateCache(`job-detail:${jobId}`);
    invalidateJobsListCache();
    invalidateCachePrefix("bootstrap");
    return value;
  });
}

export function unsuppressJob(jobId: string): Promise<{ unsuppressed: number }> {
  return request<{ unsuppressed: number }>(`/api/jobs/${encodeURIComponent(jobId)}/unsuppress`, { method: "POST" }).then((value) => {
    invalidateCache(`job-detail:${jobId}`);
    invalidateJobsListCache();
    invalidateCachePrefix("bootstrap");
    return value;
  });
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
  }).then((value) => {
    invalidateJobsListCache();
    invalidateCachePrefix("bootstrap");
    invalidateCache("stats");
    invalidateCache("action-queue");
    return value;
  });
}

export function addProfileSkill(skill: string): Promise<CandidateProfile> {
  return request<CandidateProfile>("/api/profile/skills", {
    method: "POST",
    body: JSON.stringify({ skill }),
  }).then((value) => {
    invalidateJobsListCache();
    invalidateCachePrefix("bootstrap");
    invalidateCache("stats");
    invalidateCache("action-queue");
    return value;
  });
}

export function agentChat(
  messages: AgentMessage[],
  skillInvocation?: AgentSkillInvocation | null,
): Promise<AgentChatResponse> {
  return agentRequest<AgentChatResponse>("/api/agent/chat", {
    method: "POST",
    body: JSON.stringify({ messages, skill_invocation: skillInvocation ?? null }),
  });
}

export function getOperation(id: string): Promise<WorkspaceOperation> {
  return request<WorkspaceOperation>(`/api/operations/${encodeURIComponent(id)}`);
}

export function subscribeToDashboardEvents(
  handlers: {
    onMessage: (payload: Record<string, unknown>) => void;
    onError?: () => void;
  },
): () => void {
  const source = new EventSource(buildApiUrl("/api/events/stream"));
  source.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data) as Record<string, unknown>;
      handlers.onMessage(payload);
    } catch {
      // ignore malformed frames
    }
  };
  source.onerror = () => {
    handlers.onError?.();
  };
  return () => source.close();
}

export function subscribeToOperation(
  id: string,
  handlers: {
    onMessage: (operation: WorkspaceOperation) => void;
    onError?: () => void;
  },
): () => void {
  const url = buildApiUrl(`/api/operations/${encodeURIComponent(id)}/events`);
  const source = new EventSource(url);
  source.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data) as WorkspaceOperation;
      handlers.onMessage(payload);
      if (payload.status === "completed" || payload.status === "failed") {
        source.close();
      }
    } catch {
      // ignore malformed frames
    }
  };
  source.onerror = () => {
    handlers.onError?.();
  };
  return () => source.close();
}

export function getAutofillExport(): Promise<Record<string, string | null>> {
  return request<Record<string, string | null>>("/api/profile/autofill-export");
}

// ---------------------------------------------------------------------------
// Base documents
// ---------------------------------------------------------------------------

export function listBaseDocuments(): Promise<BaseDocument[]> {
  return request<BaseDocument[]>("/api/profile/documents");
}

export async function uploadBaseDocument(file: File, doc_type: "resume" | "cover_letter"): Promise<BaseDocument> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("doc_type", doc_type);
  const resp = await fetch(buildApiUrl("/api/profile/documents"), {
    method: "POST",
    body: formData,
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`Upload failed: ${resp.status} ${text}`);
  }
  return resp.json();
}

export function deleteBaseDocument(id: number): Promise<void> {
  return request<void>(`/api/profile/documents/${id}`, { method: "DELETE" });
}

export function setDefaultBaseDocument(id: number): Promise<BaseDocument> {
  return request<BaseDocument>(`/api/profile/documents/${id}/default`, { method: "PATCH" });
}

// ---------------------------------------------------------------------------
// Story bank
// ---------------------------------------------------------------------------

export function listStories(options: { includeDrafts?: boolean } = {}): Promise<import("./types").UserStory[]> {
  const qs = options.includeDrafts === false ? "?include_drafts=false" : "";
  return request<import("./types").UserStory[]>(`/api/stories${qs}`);
}

export function getStoryCount(): Promise<import("./types").StoryCount> {
  return request<import("./types").StoryCount>("/api/stories/count");
}

export function createStory(data: import("./types").UserStoryCreate): Promise<import("./types").UserStory> {
  return request<import("./types").UserStory>("/api/stories", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateStory(id: number, data: import("./types").UserStoryUpdate): Promise<import("./types").UserStory> {
  return request<import("./types").UserStory>(`/api/stories/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export function deleteStory(id: number): Promise<void> {
  return request<void>(`/api/stories/${id}`, { method: "DELETE" });
}

export function bulkAcceptStories(
  storyIds: number[],
  profileDelta?: import("./types").ExtractedProfileDelta | null,
): Promise<{ accepted: number }> {
  return request<{ accepted: number }>("/api/stories/bulk-accept", {
    method: "POST",
    body: JSON.stringify({ story_ids: storyIds, profile_delta: profileDelta ?? null }),
  });
}

export function extractStoriesFromResume(baseDocId: number): Promise<import("./types").WorkspaceOperation> {
  return request<import("./types").WorkspaceOperation>(
    `/api/stories/extract-from-resume?base_doc_id=${baseDocId}`,
    { method: "POST" },
  );
}

export function getRelevantStories(jobId: string, topK = 5): Promise<import("./types").RelevantStory[]> {
  return request<import("./types").RelevantStory[]>(
    `/api/jobs/${encodeURIComponent(jobId)}/relevant-stories?top_k=${topK}`,
  );
}

export function triggerStoryEmbedding(): Promise<{ embedded: number }> {
  return request<{ embedded: number }>("/api/stories/embed", { method: "POST" });
}

export function triggerJobEmbedding(limit = 200): Promise<{ embedded: number }> {
  return request<{ embedded: number }>(`/api/jobs/embed?limit=${limit}`, { method: "POST" });
}

// ---------------------------------------------------------------------------
// Application queue
// ---------------------------------------------------------------------------

export function getQueue(options: { force?: boolean } = {}): Promise<QueueItem[]> {
  if (options.force) {
    invalidateCache("queue");
  }
  return cachedRequest<QueueItem[]>("queue", CLIENT_CACHE_TTL.queue, "/api/queue");
}

export async function prefetchQueue(): Promise<void> {
  if (getCachedValue<QueueItem[]>("queue") !== null) return;
  try {
    await getQueue();
  } catch {
    // ignore prefetch failures
  }
}

export function addToQueue(job_id: string): Promise<QueueItem> {
  return request<QueueItem>("/api/queue", {
    method: "POST",
    body: JSON.stringify({ job_id }),
  }).then((value) => {
    invalidateCache("queue");
    invalidateCachePrefix("bootstrap");
    return value;
  });
}

export function removeFromQueue(id: number): Promise<void> {
  return request<void>(`/api/queue/${id}`, { method: "DELETE" }).then((value) => {
    invalidateCache("queue");
    invalidateCachePrefix("bootstrap");
    return value;
  });
}

export function updateQueueItem(id: number, status: string): Promise<QueueItem> {
  return request<QueueItem>(`/api/queue/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  }).then((value) => {
    invalidateCache("queue");
    invalidateCachePrefix("bootstrap");
    return value;
  });
}

export function reorderQueue(ids: number[]): Promise<void> {
  return request<void>("/api/queue/reorder", {
    method: "POST",
    body: JSON.stringify({ ids }),
  }).then((value) => {
    invalidateCache("queue");
    return value;
  });
}

// ---------------------------------------------------------------------------
// Job artifacts
// ---------------------------------------------------------------------------

export function getJobArtifacts(job_id: string, options: { force?: boolean } = {}): Promise<JobArtifact[]> {
  if (options.force) {
    invalidateCache(`job-artifacts:${job_id}`);
  }
  return cachedRequest<JobArtifact[]>(
    `job-artifacts:${job_id}`,
    CLIENT_CACHE_TTL.artifacts,
    `/api/jobs/${encodeURIComponent(job_id)}/artifacts`,
  );
}

export async function prefetchJobArtifacts(job_id: string): Promise<void> {
  if (!job_id || getCachedValue<JobArtifact[]>(`job-artifacts:${job_id}`) !== null) return;
  try {
    await getJobArtifacts(job_id);
  } catch {
    // ignore prefetch failures
  }
}

export function generateResume(job_id: string, base_doc_id: number): Promise<WorkspaceOperation> {
  return request<WorkspaceOperation>(`/api/jobs/${encodeURIComponent(job_id)}/artifacts/resume`, {
    method: "POST",
    body: JSON.stringify({ base_doc_id }),
  }).then((value) => {
    invalidateCache(`job-artifacts:${job_id}`);
    return value;
  });
}

export function generateCoverLetter(job_id: string, base_doc_id: number): Promise<WorkspaceOperation> {
  return request<WorkspaceOperation>(`/api/jobs/${encodeURIComponent(job_id)}/artifacts/cover-letter`, {
    method: "POST",
    body: JSON.stringify({ base_doc_id }),
  }).then((value) => {
    invalidateCache(`job-artifacts:${job_id}`);
    return value;
  });
}

export function streamArtifact(
  job_id: string,
  artifact_type: "resume" | "cover_letter",
  base_doc_id: number,
  handlers: {
    onChunk: (token: string) => void;
    onArtifact: (artifact: JobArtifact) => void;
    onError: (detail: string) => void;
    onDone: () => void;
  },
): () => void {
  const slug = artifact_type === "resume" ? "resume" : "cover-letter";
  const url = buildApiUrl(
    `/api/jobs/${encodeURIComponent(job_id)}/artifacts/${slug}/stream?base_doc_id=${base_doc_id}`,
  );
  const source = new EventSource(url);

  source.addEventListener("chunk", (event: MessageEvent) => {
    try {
      const token = JSON.parse(event.data) as string;
      handlers.onChunk(token);
    } catch {
      // ignore malformed frames
    }
  });

  source.addEventListener("artifact", (event: MessageEvent) => {
    try {
      const artifact = JSON.parse(event.data) as JobArtifact;
      invalidateCache(`job-artifacts:${job_id}`);
      handlers.onArtifact(artifact);
    } catch {
      // ignore malformed frames
    }
  });

  source.addEventListener("error", (event: MessageEvent) => {
    try {
      const payload = JSON.parse(event.data) as { detail?: string };
      handlers.onError(payload.detail ?? "Generation failed");
    } catch {
      handlers.onError("Generation failed");
    }
    source.close();
  });

  source.addEventListener("done", () => {
    handlers.onDone();
    source.close();
  });

  // Network-level error (connection refused, etc.)
  source.onerror = () => {
    handlers.onError("Connection error during generation");
    source.close();
  };

  return () => source.close();
}

export function updateArtifact(id: number, content_md: string): Promise<JobArtifact> {
  return request<JobArtifact>(`/api/artifacts/${id}`, {
    method: "PUT",
    body: JSON.stringify({ content_md }),
  }).then((value) => {
    invalidateCache(`job-artifacts:${value.job_id}`);
    return value;
  });
}

export function getArtifactPdfUrl(id: number): string {
  return buildApiUrl(`/api/artifacts/${id}/pdf`);
}
