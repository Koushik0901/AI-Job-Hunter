import type {
  ArtifactSummary,
  AppHealthResponse,
  ArtifactStarterStatus,
  ArtifactVersion,
  ArtifactsHubResponse,
  CandidateEvidenceAssets,
  CandidateEvidenceIndexStatus,
  CandidateProfile,
  CompanySource,
  CompanySourceImportResponse,
  CompanySourceProbeResponse,
  ArtifactLatexDocument,
  ResumeLatexDocument,
  ResumeProfile,
  ResumeSwarmOptimizeResponse,
  ResumeSwarmRunStartResponse,
  ResumeSwarmRunStatusResponse,
  TemplateSettings,
  TemplateValidationResult,
  ResumeImportResponse,
  CreateArtifactVersionRequest,
  FunnelAnalyticsResponse,
  JobDetail,
  JobEvent,
  JobsListResponse,
  ManualJobCreateRequest,
  SuppressedJob,
  TrackingStatus,
  ScoreRecomputeStatus,
  StatsResponse,
  TrackingPatchRequest,
  WorkspaceOperation,
  WorkspaceOverview,
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
  const clientId = getClientId();
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Client-Id": clientId,
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

export function getHealth(): Promise<AppHealthResponse> {
  return request<AppHealthResponse>("/api/health");
}

export function getWorkspaceOverview(): Promise<WorkspaceOverview> {
  return request<WorkspaceOverview>("/api/workspace/overview");
}

export function getCompanySources(): Promise<CompanySource[]> {
  return request<CompanySource[]>("/api/company-sources");
}

export function probeCompanySources(payload: { query: string; extra_slugs?: string[] }): Promise<CompanySourceProbeResponse> {
  return request<CompanySourceProbeResponse>("/api/company-sources/probe", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createCompanySource(payload: {
  name: string;
  ats_type: string;
  slug: string;
  ats_url?: string | null;
  enabled?: boolean;
  source?: string;
}): Promise<CompanySource> {
  return request<CompanySource>("/api/company-sources", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateCompanySource(
  sourceId: number,
  payload: { enabled?: boolean; name?: string; source?: string },
): Promise<CompanySource> {
  return request<CompanySource>(`/api/company-sources/${encodeURIComponent(String(sourceId))}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function previewCompanySourceImport(): Promise<CompanySourceImportResponse> {
  return request<CompanySourceImportResponse>("/api/company-sources/import-preview", {
    method: "POST",
  });
}

export function importCompanySources(): Promise<CompanySourceImportResponse> {
  return request<CompanySourceImportResponse>("/api/company-sources/import", {
    method: "POST",
  });
}

export function getWorkspaceOperations(limit = 20): Promise<WorkspaceOperation[]> {
  return request<WorkspaceOperation[]>(`/api/workspace/operations?limit=${limit}`);
}

export function getWorkspaceOperation(operationId: string): Promise<WorkspaceOperation> {
  return request<WorkspaceOperation>(`/api/workspace/operations/${encodeURIComponent(operationId)}`);
}

export function runWorkspaceScrape(payload: {
  no_location_filter?: boolean;
  no_enrich?: boolean;
  no_enrich_llm?: boolean;
  sort_by?: "match" | "posted";
} = {}): Promise<WorkspaceOperation> {
  return request<WorkspaceOperation>("/api/workspace/operations/scrape", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function runWorkspaceEnrichBackfill(): Promise<WorkspaceOperation> {
  return request<WorkspaceOperation>("/api/workspace/operations/enrich-backfill", {
    method: "POST",
  });
}

export function runWorkspaceReEnrichAll(): Promise<WorkspaceOperation> {
  return request<WorkspaceOperation>("/api/workspace/operations/re-enrich-all", {
    method: "POST",
  });
}

export function runWorkspaceJdReformat(payload: { missing_only?: boolean } = {}): Promise<WorkspaceOperation> {
  return request<WorkspaceOperation>("/api/workspace/operations/jd-reformat", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function previewWorkspacePrune(days: number): Promise<WorkspaceOperation> {
  return request<WorkspaceOperation>("/api/workspace/operations/prune-preview", {
    method: "POST",
    body: JSON.stringify({ days }),
  });
}

export function runWorkspacePrune(days: number): Promise<WorkspaceOperation> {
  return request<WorkspaceOperation>("/api/workspace/operations/prune", {
    method: "POST",
    body: JSON.stringify({ days }),
  });
}

export function getScoreRecomputeStatus(): Promise<ScoreRecomputeStatus> {
  return request<ScoreRecomputeStatus>("/api/meta/scores/recompute-status");
}

export function triggerScoreRecompute(): Promise<{ scheduled: number }> {
  return request<{ scheduled: number }>("/api/meta/scores/recompute", {
    method: "POST",
  });
}

export function getJobDetail(jobId: string): Promise<JobDetail> {
  return request<JobDetail>(`/api/jobs/${encodeURIComponent(jobId)}`);
}

export function getJobArtifacts(jobId: string): Promise<ArtifactSummary[]> {
  return request<ArtifactSummary[]>(`/api/jobs/${encodeURIComponent(jobId)}/artifacts`);
}

export function prewarmJobCache(jobId: string): Promise<{ ok: boolean; warmed: string[] }> {
  return request<{ ok: boolean; warmed: string[] }>(`/api/jobs/${encodeURIComponent(jobId)}/cache/prewarm`, {
    method: "POST",
  });
}

export function generateStarterArtifacts(jobId: string, force = false): Promise<ArtifactSummary[]> {
  return request<ArtifactSummary[]>(`/api/jobs/${encodeURIComponent(jobId)}/artifacts/starter`, {
    method: "POST",
    body: JSON.stringify({ force }),
  });
}

export function getStarterArtifactsStatus(jobId: string): Promise<ArtifactStarterStatus> {
  return request<ArtifactStarterStatus>(`/api/jobs/${encodeURIComponent(jobId)}/artifacts/starter/status`);
}

interface GetArtifactsHubParams {
  q?: string;
  status?: TrackingStatus | "all";
  sort?: "updated_desc" | "company_asc";
  limit?: number;
  offset?: number;
}

export function getArtifactsHub(params: GetArtifactsHubParams = {}): Promise<ArtifactsHubResponse> {
  const query = new URLSearchParams();
  query.set("limit", String(params.limit ?? 200));
  query.set("offset", String(params.offset ?? 0));
  query.set("sort", params.sort ?? "updated_desc");
  if (params.status && params.status !== "all") {
    query.set("status", params.status);
  }
  if (params.q?.trim()) {
    query.set("q", params.q.trim());
  }
  return request<ArtifactsHubResponse>(`/api/artifacts?${query.toString()}`);
}

export function getArtifact(artifactId: string): Promise<ArtifactSummary> {
  return request<ArtifactSummary>(`/api/artifacts/${encodeURIComponent(artifactId)}`);
}

export function getResumeTemplates(): Promise<Array<{ id: string; name: string }>> {
  return request<Array<{ id: string; name: string }>>("/api/resume-templates");
}

export function getCoverLetterTemplates(): Promise<Array<{ id: string; name: string }>> {
  return request<Array<{ id: string; name: string }>>("/api/cover-letter-templates");
}

export function getTemplatesByType(artifactType: "resume" | "cover_letter"): Promise<Array<{ id: string; name: string }>> {
  return request<Array<{ id: string; name: string }>>(`/api/templates/${encodeURIComponent(artifactType)}`);
}

export function getTemplateSource(
  artifactType: "resume" | "cover_letter",
  templateId: string,
): Promise<{ template_id: string; artifact_type: string; source_text: string }> {
  return request<{ template_id: string; artifact_type: string; source_text: string }>(
    `/api/templates/${encodeURIComponent(artifactType)}/${encodeURIComponent(templateId)}/source`,
  );
}

export function validateTemplate(artifactType: "resume" | "cover_letter", templateId: string): Promise<TemplateValidationResult> {
  return request<TemplateValidationResult>(
    `/api/templates/${encodeURIComponent(artifactType)}/${encodeURIComponent(templateId)}/validate`,
  );
}

export function deleteArtifact(artifactId: string): Promise<{ deleted: number }> {
  return request<{ deleted: number }>(`/api/artifacts/${encodeURIComponent(artifactId)}`, {
    method: "DELETE",
  });
}

export function deleteJobArtifact(jobId: string, artifactType: "resume" | "cover_letter"): Promise<{ deleted: number }> {
  return request<{ deleted: number }>(
    `/api/jobs/${encodeURIComponent(jobId)}/artifacts/${encodeURIComponent(artifactType)}`,
    { method: "DELETE" },
  );
}

export function getArtifactVersions(artifactId: string, limit = 200): Promise<ArtifactVersion[]> {
  return request<ArtifactVersion[]>(`/api/artifacts/${encodeURIComponent(artifactId)}/versions?limit=${limit}`);
}

export function getResumeLatexDocument(artifactId: string): Promise<ResumeLatexDocument> {
  return request<ResumeLatexDocument>(`/api/artifacts/${encodeURIComponent(artifactId)}/resume-latex`);
}

export function getArtifactLatexDocument(artifactId: string): Promise<ArtifactLatexDocument> {
  return request<ArtifactLatexDocument>(`/api/artifacts/${encodeURIComponent(artifactId)}/latex`);
}

export function saveResumeLatexDocument(
  artifactId: string,
  payload: { source_text: string; template_id: string; label?: "draft" | "tailored" | "final"; created_by?: string },
): Promise<ArtifactVersion> {
  return request<ArtifactVersion>(`/api/artifacts/${encodeURIComponent(artifactId)}/resume-latex/save`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function saveArtifactLatexDocument(
  artifactId: string,
  payload: { source_text: string; template_id: string; label?: "draft" | "tailored" | "final"; created_by?: string },
): Promise<ArtifactVersion> {
  return request<ArtifactVersion>(`/api/artifacts/${encodeURIComponent(artifactId)}/latex/save`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function recompileResumeLatexDocument(
  artifactId: string,
  payload: { source_text?: string; template_id?: string; created_by?: string } = {},
): Promise<ResumeLatexDocument> {
  return request<ResumeLatexDocument>(`/api/artifacts/${encodeURIComponent(artifactId)}/resume-latex/recompile`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function recompileArtifactLatexDocument(
  artifactId: string,
  payload: { source_text?: string; template_id?: string; created_by?: string } = {},
): Promise<ArtifactLatexDocument> {
  return request<ArtifactLatexDocument>(`/api/artifacts/${encodeURIComponent(artifactId)}/latex/recompile`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function optimizeResumeWithSwarm(
  artifactId: string,
  payload: { cycles?: number; created_by?: string } = {},
): Promise<ResumeSwarmOptimizeResponse> {
  return request<ResumeSwarmOptimizeResponse>(`/api/artifacts/${encodeURIComponent(artifactId)}/resume-latex/swarm-optimize`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function startResumeSwarmRun(
  artifactId: string,
  payload: { cycles?: number; source_text?: string; template_id?: string } = {},
): Promise<ResumeSwarmRunStartResponse> {
  return request<ResumeSwarmRunStartResponse>(`/api/artifacts/${encodeURIComponent(artifactId)}/resume-latex/swarm-runs`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getResumeSwarmRunStatus(artifactId: string, runId: string): Promise<ResumeSwarmRunStatusResponse> {
  return request<ResumeSwarmRunStatusResponse>(
    `/api/artifacts/${encodeURIComponent(artifactId)}/resume-latex/swarm-runs/${encodeURIComponent(runId)}`,
  );
}

export function cancelResumeSwarmRun(artifactId: string, runId: string): Promise<ResumeSwarmRunStatusResponse> {
  return request<ResumeSwarmRunStatusResponse>(
    `/api/artifacts/${encodeURIComponent(artifactId)}/resume-latex/swarm-runs/${encodeURIComponent(runId)}/cancel`,
    { method: "POST" },
  );
}

export function confirmResumeSwarmRunSave(
  artifactId: string,
  runId: string,
  payload: { created_by?: string; label?: "draft" | "tailored" | "final" } = {},
): Promise<ResumeSwarmOptimizeResponse> {
  return request<ResumeSwarmOptimizeResponse>(
    `/api/artifacts/${encodeURIComponent(artifactId)}/resume-latex/swarm-runs/${encodeURIComponent(runId)}/confirm-save`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function startCoverLetterSwarmRun(
  artifactId: string,
  payload: { cycles?: number; source_text?: string; template_id?: string } = {},
): Promise<ResumeSwarmRunStartResponse> {
  return request<ResumeSwarmRunStartResponse>(`/api/artifacts/${encodeURIComponent(artifactId)}/cover-letter-latex/swarm-runs`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getCoverLetterSwarmRunStatus(artifactId: string, runId: string): Promise<ResumeSwarmRunStatusResponse> {
  return request<ResumeSwarmRunStatusResponse>(
    `/api/artifacts/${encodeURIComponent(artifactId)}/cover-letter-latex/swarm-runs/${encodeURIComponent(runId)}`,
  );
}

export function cancelCoverLetterSwarmRun(artifactId: string, runId: string): Promise<ResumeSwarmRunStatusResponse> {
  return request<ResumeSwarmRunStatusResponse>(
    `/api/artifacts/${encodeURIComponent(artifactId)}/cover-letter-latex/swarm-runs/${encodeURIComponent(runId)}/cancel`,
    { method: "POST" },
  );
}

export function confirmCoverLetterSwarmRunSave(
  artifactId: string,
  runId: string,
  payload: { created_by?: string; label?: "draft" | "tailored" | "final" } = {},
): Promise<ResumeSwarmOptimizeResponse> {
  return request<ResumeSwarmOptimizeResponse>(
    `/api/artifacts/${encodeURIComponent(artifactId)}/cover-letter-latex/swarm-runs/${encodeURIComponent(runId)}/confirm-save`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export async function fetchResumeLatexPdf(artifactId: string): Promise<Blob> {
  const response = await fetch(`${API_BASE}/api/artifacts/${encodeURIComponent(artifactId)}/resume-latex/pdf`);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with status ${response.status}`);
  }
  return response.blob();
}

export async function fetchArtifactLatexPdf(artifactId: string): Promise<Blob> {
  const response = await fetch(`${API_BASE}/api/artifacts/${encodeURIComponent(artifactId)}/latex/pdf`);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with status ${response.status}`);
  }
  return response.blob();
}

export function getTemplateSettings(): Promise<TemplateSettings> {
  return request<TemplateSettings>("/api/profile/templates");
}

export function putTemplateSettings(payload: TemplateSettings): Promise<TemplateSettings> {
  return request<TemplateSettings>("/api/profile/templates", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function createArtifactVersion(artifactId: string, payload: CreateArtifactVersionRequest): Promise<ArtifactVersion> {
  return request<ArtifactVersion>(`/api/artifacts/${encodeURIComponent(artifactId)}/versions`, {
    method: "POST",
    body: JSON.stringify(payload),
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
  return request<{ deleted: number }>(`/api/jobs/${encodeURIComponent(jobId)}`, {
    method: "DELETE",
  });
}

export function createManualJob(payload: ManualJobCreateRequest): Promise<JobDetail> {
  return request<JobDetail>("/api/jobs/manual", {
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
  return request<{ unsuppressed: number }>(`/api/jobs/${encodeURIComponent(jobId)}/unsuppress`, {
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

export function getEvidenceAssets(): Promise<CandidateEvidenceAssets> {
  return request<CandidateEvidenceAssets>("/api/profile/evidence-assets");
}

export function putEvidenceAssets(payload: CandidateEvidenceAssets): Promise<CandidateEvidenceAssets> {
  return request<CandidateEvidenceAssets>("/api/profile/evidence-assets", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function getEvidenceIndexStatus(): Promise<CandidateEvidenceIndexStatus> {
  return request<CandidateEvidenceIndexStatus>("/api/profile/evidence/index-status");
}

export function reindexEvidenceAssets(): Promise<CandidateEvidenceIndexStatus> {
  return request<CandidateEvidenceIndexStatus>("/api/profile/evidence/reindex", {
    method: "POST",
  });
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
