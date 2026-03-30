import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { createPortal } from "react-dom";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import {
  addProfileSkill,
  createManualJob,
  deleteJob,
  getJobDetail,
  getJobEvents,
  getJobsWithParams,
  getProfile,
  getSuppressions,
  patchTracking,
  retryJobProcessing,
  saveJobDecision,
  suppressJob,
  unsuppressJob,
  isManualJobCreateDuplicateResponse,
  manualJobCreateResponseToDetail,
} from "../api";
import { DetailDrawer } from "../components/DetailDrawer";
import { JobCard } from "../components/JobCard";
import { ThemedLoader } from "../components/ThemedLoader";
import { ThemedSelect } from "../components/ThemedSelect";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Kanban, KanbanBoard, KanbanColumn, KanbanItem, KanbanOverlay } from "../components/ui/kanban";
import { dateValueMs, formatDateShort } from "../dateUtils";
import type {
  CandidateProfile,
  JobDetail,
  JobEvent,
  JobSummary,
  ManualJobCreateRequest,
  Recommendation,
  SuppressedJob,
  TrackingPatchRequest,
  TrackingStatus,
} from "../types";

const STATUS_COLUMNS: Array<{ id: TrackingStatus; label: string }> = [
  { id: "not_applied", label: "Backlog" },
  { id: "staging", label: "Staging" },
  { id: "applied", label: "Applied" },
  { id: "interviewing", label: "Interviewing" },
  { id: "offer", label: "Offer" },
  { id: "rejected", label: "Rejected" },
];
const VIEW_OPTIONS: Array<{ value: "kanban" | "list"; label: string }> = [
  { value: "kanban", label: "Kanban view" },
  { value: "list", label: "List view" },
];
const SORT_OPTIONS: Array<{ value: "match_desc" | "posted_desc" | "updated_desc" | "company_asc"; label: string }> = [
  { value: "match_desc", label: "Best match" },
  { value: "posted_desc", label: "Newest posted" },
  { value: "updated_desc", label: "Recently updated" },
  { value: "company_asc", label: "Company A-Z" },
];
const STATUS_FILTER_OPTIONS: Array<{ value: TrackingStatus | "all"; label: string }> = [
  { value: "all", label: "All statuses" },
  { value: "not_applied", label: "Backlog" },
  { value: "staging", label: "Staging" },
  { value: "applied", label: "Applied" },
  { value: "interviewing", label: "Interviewing" },
  { value: "offer", label: "Offer" },
  { value: "rejected", label: "Rejected" },
];
const MANUAL_STAGE_OPTIONS: Array<{ value: TrackingStatus; label: string }> = [
  { value: "staging", label: "Staging" },
  { value: "not_applied", label: "Backlog" },
  { value: "applied", label: "Applied" },
  { value: "interviewing", label: "Interviewing" },
  { value: "offer", label: "Offer" },
  { value: "rejected", label: "Rejected" },
];

const BACKLOG_PAGE_SIZE = 30;
const BACKLOG_MAX_AGE_DAYS = 21;
const BOARD_CACHE_TTL_MS = 3 * 60 * 1000;
const DETAIL_CACHE_TTL_MS = 10 * 60 * 1000;
const EVENTS_CACHE_TTL_MS = 5 * 60 * 1000;
const JOBS_QUERY_CACHE_CAP = 4;
const DETAIL_CACHE_CAP = 12;
const EVENTS_CACHE_CAP = 8;
const HOVER_PREFETCH_DELAY_MS = 150;
const BOARD_CACHE_SCHEMA_VERSION = 7;
const BOARD_INITIAL_FETCH_LIMIT = 200;
const BOARD_MAX_FETCH_LIMIT = 500;
const MANUAL_ENRICH_POLL_INTERVAL_MS = 3500;
const MANUAL_ENRICH_POLL_MAX_ATTEMPTS = 34;
const POSTED_WINDOW_PRESETS: Array<{ label: string; days: number }> = [
  { label: "24h", days: 1 },
  { label: "5d", days: 5 },
  { label: "7d", days: 7 },
  { label: "14d", days: 14 },
  { label: "30d", days: 30 },
];
const BOARD_FOCUS_OPTIONS = [
  { value: "all", label: "All" },
  { value: "overdue", label: "Overdue" },
  { value: "staging", label: "Staging" },
  { value: "high_priority", label: "High priority" },
  { value: "strong_match", label: "Strong match" },
  { value: "desired_title_match", label: "Matches my titles" },
] as const;

const pageEase = [0.22, 0.84, 0.24, 1] as [number, number, number, number];

const MANUAL_REQUIRED_FIELDS = [
  { key: "url", label: "Job URL" },
  { key: "company", label: "Company" },
  { key: "title", label: "Title" },
  { key: "description", label: "Description" },
] as const;

const pageRevealVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.05,
      delayChildren: 0.04,
    },
  },
};

const sectionRevealVariants = {
  hidden: { opacity: 0, y: 18 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.38, ease: pageEase },
  },
};

type BoardView = "kanban" | "list";
type SortOption = "match_desc" | "posted_desc" | "updated_desc" | "company_asc";
type FocusMode = typeof BOARD_FOCUS_OPTIONS[number]["value"];
type MemoryCacheEntry<T> = { value: T; fetchedAt: number; touchedAt: number };
type MemoryCacheRecord<T> = Record<string, MemoryCacheEntry<T>>;
type ManualDuplicateCandidate = {
  jobId: string;
  title: string;
  company: string;
  location: string;
  posted: string;
  matchKind: "url" | "content";
};

type BoardPageCache = {
  version: number;
  jobs: JobSummary[];
  profile: CandidateProfile | null;
  detailCache: MemoryCacheRecord<JobDetail>;
  eventsCache: MemoryCacheRecord<JobEvent[]>;
  searchQuery: string;
  viewMode: BoardView;
  sortOption: SortOption;
  focusMode: FocusMode;
  statusFilter: TrackingStatus | "all";
  atsFilter: string;
  companyFilter: string;
  postedAfterFilter: string;
  postedBeforeFilter: string;
  backlogVisibleCount: number;
  fetchedAt: number;
  queryKey: string;
};

let boardPageCache: BoardPageCache | null = null;
const jobsQueryCache = new Map<string, { items: JobSummary[]; fetchedAt: number }>();

function buildQueryKey(
  status: TrackingStatus | "all",
  ats: string,
  company: string,
  postedAfter: string,
  postedBefore: string,
  sort: SortOption,
): string {
  return `${status}|${ats.trim().toLowerCase()}|${company.trim().toLowerCase()}|${postedAfter}|${postedBefore}|${sort}`;
}

function normalizeManualDuplicateText(raw: string | null | undefined): string {
  return (raw ?? "")
    .trim()
    .toLowerCase()
    .replace(/\u00a0/g, " ")
    .replace(/&nbsp;|&#160;/g, " ")
    .replace(/[^a-z0-9]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeManualDuplicateUrl(raw: string | null | undefined): string {
  const trimmed = (raw ?? "").trim();
  if (!trimmed) return "";
  try {
    const parsed = new URL(trimmed);
    parsed.hash = "";
    parsed.pathname = parsed.pathname.replace(/\/+$/, "") || "/";
    return parsed.toString().toLowerCase().replace(/\/+$/, "");
  } catch {
    return trimmed.toLowerCase().replace(/\/+$/, "");
  }
}

function normalizeManualDuplicateMonth(raw: string | null | undefined): string {
  const trimmed = (raw ?? "").trim();
  return /^\d{4}-\d{2}/.test(trimmed) ? trimmed.slice(0, 7) : "";
}

function findManualDuplicateCandidate(form: ManualJobCreateRequest, jobs: JobSummary[]): ManualDuplicateCandidate | null {
  const normalizedUrl = normalizeManualDuplicateUrl(form.url);
  if (normalizedUrl) {
    for (const job of jobs) {
      if (normalizeManualDuplicateUrl(job.url) === normalizedUrl) {
        return {
          jobId: job.id,
          title: job.title,
          company: job.company,
          location: job.location,
          posted: job.posted,
          matchKind: "url",
        };
      }
    }
  }

  const normalizedTitle = normalizeManualDuplicateText(form.title);
  const normalizedCompany = normalizeManualDuplicateText(form.company);
  const normalizedLocation = normalizeManualDuplicateText(form.location ?? "");
  const normalizedPostedMonth = normalizeManualDuplicateMonth(form.posted);
  if (!normalizedTitle || !normalizedCompany || !normalizedLocation || !normalizedPostedMonth) {
    return null;
  }

  for (const job of jobs) {
    if (
      normalizeManualDuplicateText(job.title) === normalizedTitle &&
      normalizeManualDuplicateText(job.company) === normalizedCompany &&
      normalizeManualDuplicateText(job.location) === normalizedLocation &&
      normalizeManualDuplicateMonth(job.posted) === normalizedPostedMonth
    ) {
      return {
        jobId: job.id,
        title: job.title,
        company: job.company,
        location: job.location,
        posted: job.posted,
        matchKind: "content",
      };
    }
  }

  return null;
}

function getJobsQueryCache(key: string): JobSummary[] | null {
  const cached = jobsQueryCache.get(key);
  if (!cached) return null;
  if (Date.now() - cached.fetchedAt >= BOARD_CACHE_TTL_MS) {
    jobsQueryCache.delete(key);
    return null;
  }
  // LRU touch
  jobsQueryCache.delete(key);
  jobsQueryCache.set(key, cached);
  return cached.items;
}

function setJobsQueryCache(key: string, items: JobSummary[]): void {
  if (jobsQueryCache.has(key)) {
    jobsQueryCache.delete(key);
  }
  jobsQueryCache.set(key, { items, fetchedAt: Date.now() });
  while (jobsQueryCache.size > JOBS_QUERY_CACHE_CAP) {
    const oldestKey = jobsQueryCache.keys().next().value as string | undefined;
    if (!oldestKey) break;
    jobsQueryCache.delete(oldestKey);
  }
}

function pruneRecordCache<T>(cache: MemoryCacheRecord<T>, ttlMs: number, cap: number): MemoryCacheRecord<T> {
  const now = Date.now();
  const freshEntries = Object.entries(cache)
    .filter(([, entry]) => now - entry.fetchedAt < ttlMs)
    .sort((left, right) => right[1].touchedAt - left[1].touchedAt)
    .slice(0, cap);
  return Object.fromEntries(freshEntries);
}

function getRecordCacheValue<T>(cache: MemoryCacheRecord<T>, key: string, ttlMs: number): T | null {
  const entry = cache[key];
  if (!entry) return null;
  if (Date.now() - entry.fetchedAt >= ttlMs) {
    return null;
  }
  return entry.value;
}

function upsertRecordCache<T>(cache: MemoryCacheRecord<T>, key: string, value: T, ttlMs: number, cap: number): MemoryCacheRecord<T> {
  const now = Date.now();
  return pruneRecordCache(
    {
      ...cache,
      [key]: {
        value,
        fetchedAt: now,
        touchedAt: now,
      },
    },
    ttlMs,
    cap,
  );
}

function removeRecordCacheValue<T>(cache: MemoryCacheRecord<T>, key: string): MemoryCacheRecord<T> {
  if (!cache[key]) {
    return cache;
  }
  const next = { ...cache };
  delete next[key];
  return next;
}

function skeletonColumnCards(columnId: TrackingStatus): number {
  return columnId === "not_applied" ? 5 : 3;
}

function isOlderThanDays(value: string, days: number): boolean {
  const valueMs = dateValueMs(value);
  if (valueMs === null) return false;
  const now = Date.now();
  const ageMs = now - valueMs;
  return ageMs > days * 24 * 60 * 60 * 1000;
}

function normalizeSkill(value: string): string {
  const normalized = value.trim().toLowerCase();
  const parenthetical = [...normalized.matchAll(/\(([^)]{1,32})\)/g)].map((match) => match[1] ?? "");
  const stripped = normalized
    .replace(/[/_-]+/g, " ")
    .replace(/\([^)]*\)/g, " ")
    .replace(/[^a-z0-9\s]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  const aliases: Record<string, string> = {
    js: "javascript",
    ts: "typescript",
    k8s: "kubernetes",
    tf: "tensorflow",
    torch: "pytorch",
    rag: "retrieval augmented generation",
    llm: "large language model",
    llms: "large language model",
    nlp: "natural language processing",
    cv: "computer vision",
    ml: "machine learning",
    genai: "generative ai",
    cicd: "ci cd",
  };
  for (const raw of parenthetical) {
    const key = raw.replace(/[^a-z0-9]+/g, "");
    if (aliases[key]) {
      return aliases[key];
    }
  }
  if (aliases[stripped]) {
    return aliases[stripped];
  }
  const tokens = stripped.split(" ").filter(Boolean);
  if (tokens.length >= 2) {
    const acronym = tokens.map((token) => token[0]).join("");
    if (aliases[acronym]) {
      return aliases[acronym];
    }
  }
  return stripped;
}

function parseStatusFilter(raw: string | null): TrackingStatus | "all" {
  if (!raw) {
    return "all";
  }
  const allowed: Array<TrackingStatus | "all"> = ["all", "not_applied", "staging", "applied", "interviewing", "offer", "rejected"];
  return allowed.includes(raw as TrackingStatus | "all") ? (raw as TrackingStatus | "all") : "all";
}

function parseIsoDate(raw: string | null): string {
  if (!raw) return "";
  return /^\d{4}-\d{2}-\d{2}$/.test(raw) ? raw : "";
}

function toLocalIsoDate(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function isoDaysAgo(days: number): string {
  const date = new Date();
  date.setHours(0, 0, 0, 0);
  date.setDate(date.getDate() - days);
  return toLocalIsoDate(date);
}

function postedWindowChipLabel(postedAfter: string, postedBefore: string): string | null {
  if (!postedAfter || postedBefore) return null;
  const preset = POSTED_WINDOW_PRESETS.find((item) => isoDaysAgo(item.days) === postedAfter);
  return preset ? `Last ${preset.label}` : null;
}

function focusModeLabel(mode: FocusMode): string {
  return BOARD_FOCUS_OPTIONS.find((option) => option.value === mode)?.label ?? "All";
}

function recommendationLabel(value: Recommendation | string | null | undefined): string {
  if (!value) return "Unrated";
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function matchesFocusMode(job: JobSummary, mode: FocusMode): boolean {
  if (mode === "all") return true;
  if (mode === "overdue") return Boolean(job.staging_overdue);
  if (mode === "staging") return job.status === "staging";
  if (mode === "high_priority") return job.priority === "high";
  if (mode === "strong_match") return (job.match_score ?? 0) >= 80;
  if (mode === "desired_title_match") return Boolean(job.desired_title_match);
  return true;
}

function detailToSummary(detail: JobDetail): JobSummary {
  return {
    id: detail.id,
    url: detail.url,
    company: detail.company,
    title: detail.title,
    location: detail.location,
    posted: detail.posted,
    ats: detail.ats,
    status: detail.tracking_status,
    priority: detail.priority,
    updated_at: detail.tracking_updated_at ?? detail.last_seen ?? detail.first_seen ?? null,
    match_score: detail.match?.score ?? null,
    match_band: detail.match?.band ?? null,
    desired_title_match: Boolean(detail.desired_title_match),
    staging_entered_at: detail.staging_entered_at,
    staging_due_at: detail.staging_due_at,
    staging_overdue: detail.staging_overdue,
    staging_age_hours: detail.staging_age_hours,
    fit_score: detail.fit_score,
    interview_likelihood_score: detail.interview_likelihood_score,
    urgency_score: detail.urgency_score,
    friction_score: detail.friction_score,
    confidence_score: detail.confidence_score,
    recommendation: detail.recommendation,
    recommendation_reasons: detail.recommendation_reasons,
    guidance_mode: detail.guidance_mode,
    guidance_title: detail.guidance_title,
    guidance_summary: detail.guidance_summary,
    guidance_reasons: detail.guidance_reasons,
    next_best_action: detail.next_best_action,
    health_label: detail.health_label,
    processing: detail.processing,
  };
}

function hasReadyEnrichment(detail: JobDetail): boolean {
  const enrichment = detail.enrichment;
  if (!enrichment) return false;
  const status = (enrichment.enrichment_status ?? "").trim().toLowerCase();
  if (status === "ok" || status === "success") return true;
  return Boolean((enrichment.formatted_description ?? "").trim());
}

function isProcessingResolved(detail: JobDetail): boolean {
  return detail.processing.state === "ready" || detail.processing.state === "failed";
}

function stagingSlaLabel(job: JobSummary): string | null {
  if (job.status !== "staging" || typeof job.staging_age_hours !== "number") return null;
  if (job.staging_overdue) return `Overdue by ${Math.max(0, job.staging_age_hours - 48)}h`;
  return `Due in ${Math.max(0, 48 - job.staging_age_hours)}h`;
}

function columnHealthCopy(status: TrackingStatus, jobs: JobSummary[]): string {
  if (status === "not_applied") return "Recent roles";
  if (status === "staging") {
    const overdueCount = jobs.filter((job) => job.staging_overdue).length;
    return overdueCount > 0 ? `${overdueCount} overdue` : (jobs.length > 0 ? "Within SLA" : "48h review lane");
  }
  if (status === "applied") return jobs.length > 0 ? "Awaiting response" : "Application queue";
  if (status === "interviewing") return jobs.length > 0 ? "Active loop" : "Interview cycle";
  if (status === "offer") return jobs.length > 0 ? "Decision window" : "Offer stage";
  return jobs.length > 0 ? "Closed outcomes" : "Archived outcomes";
}

function emptyColumnCopy(status: TrackingStatus): { title: string; body: string } {
  if (status === "not_applied") {
    return {
      title: "No backlog roles",
      body: "Newly discovered roles will land here when they are still fresh enough to review. Add or enable company sources if this stays empty.",
    };
  }
  if (status === "staging") {
    return {
      title: "No roles in review",
      body: "Move strong candidates here when you want a short, focused decision window.",
    };
  }
  if (status === "applied") {
    return {
      title: "No submitted applications",
      body: "Roles you actively apply to will form the live follow-up queue here.",
    };
  }
  if (status === "interviewing") {
    return {
      title: "No interview loops",
      body: "This column becomes the operational center once conversations start moving.",
    };
  }
  if (status === "offer") {
    return {
      title: "No offers yet",
      body: "Offers and final-stage negotiations will stay visible here for quick comparison.",
    };
  }
  return {
    title: "No closed roles",
    body: "Rejected opportunities remain here as historical context once they are resolved.",
  };
}

export function BoardPage() {
  const portalRoot = typeof document !== "undefined" ? document.body : null;
  const [searchParams, setSearchParams] = useSearchParams();
  const initialStatusFilter = parseStatusFilter(searchParams.get("status"));
  const initialAtsFilter = (searchParams.get("ats") ?? "").trim();
  const initialCompanyFilter = (searchParams.get("company") ?? "").trim();
  const initialPostedAfterFilter = parseIsoDate(searchParams.get("posted_after"));
  const initialPostedBeforeFilter = parseIsoDate(searchParams.get("posted_before"));
  const initialSelectedJobId = (searchParams.get("job") ?? "").trim() || null;
  const initialSortOption = boardPageCache?.sortOption ?? "match_desc";
  const initialQueryKey = buildQueryKey(
    initialStatusFilter,
    initialAtsFilter,
    initialCompanyFilter,
    initialPostedAfterFilter,
    initialPostedBeforeFilter,
    initialSortOption,
  );
  const now = Date.now();
  const hasFreshCache =
    boardPageCache !== null &&
    boardPageCache.version === BOARD_CACHE_SCHEMA_VERSION &&
    now - boardPageCache.fetchedAt < BOARD_CACHE_TTL_MS &&
    boardPageCache.queryKey === initialQueryKey;
  const initialDetailCache = hasFreshCache ? pruneRecordCache(boardPageCache?.detailCache ?? {}, DETAIL_CACHE_TTL_MS, DETAIL_CACHE_CAP) : {};
  const initialEventsCache = hasFreshCache ? pruneRecordCache(boardPageCache?.eventsCache ?? {}, EVENTS_CACHE_TTL_MS, EVENTS_CACHE_CAP) : {};

  const [jobs, setJobs] = useState<JobSummary[]>(() => (hasFreshCache ? boardPageCache?.jobs ?? [] : []));
  const [profile, setProfile] = useState<CandidateProfile | null>(() => (hasFreshCache ? boardPageCache?.profile ?? null : null));
  const [selectedJobId, setSelectedJobId] = useState<string | null>(initialSelectedJobId);
  const [selectedJob, setSelectedJob] = useState<JobDetail | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailCache, setDetailCache] = useState<MemoryCacheRecord<JobDetail>>(() => initialDetailCache);
  const [eventsCache, setEventsCache] = useState<MemoryCacheRecord<JobEvent[]>>(() => initialEventsCache);
  const [pendingEnrichmentByUrl, setPendingEnrichmentByUrl] = useState<Record<string, true>>({});
  const [loading, setLoading] = useState<boolean>(() => !hasFreshCache);
  const [isRefreshingBoard, setIsRefreshingBoard] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [manualError, setManualError] = useState<string | null>(null);
  const [manualAttemptedSubmit, setManualAttemptedSubmit] = useState(false);
  const [isManualCreateOpen, setIsManualCreateOpen] = useState(false);
  const [isManualSaving, setIsManualSaving] = useState(false);
  const [isSuppressionPanelOpen, setIsSuppressionPanelOpen] = useState(false);
  const [suppressions, setSuppressions] = useState<SuppressedJob[]>([]);
  const [suppressionsLoading, setSuppressionsLoading] = useState(false);
  const [suppressionsError, setSuppressionsError] = useState<string | null>(null);
  const [restoringSuppressionUrl, setRestoringSuppressionUrl] = useState<string | null>(null);
  const [manualForm, setManualForm] = useState<ManualJobCreateRequest>({
    url: "",
    company: "",
    title: "",
    location: "",
    posted: "",
    ats: "manual",
    status: "staging",
    description: "",
  });
  const [searchQuery, setSearchQuery] = useState(() => (hasFreshCache ? boardPageCache?.searchQuery ?? "" : ""));
  const [viewMode, setViewMode] = useState<BoardView>(() => (hasFreshCache ? boardPageCache?.viewMode ?? "kanban" : "kanban"));
  const [sortOption, setSortOption] = useState<SortOption>(() => (hasFreshCache ? boardPageCache?.sortOption ?? "match_desc" : "match_desc"));
  const [focusMode, setFocusMode] = useState<FocusMode>(() => (hasFreshCache ? boardPageCache?.focusMode ?? "all" : "all"));
  const [statusFilter, setStatusFilter] = useState<TrackingStatus | "all">(() => (
    hasFreshCache ? parseStatusFilter((boardPageCache?.statusFilter as string | null | undefined) ?? null) : initialStatusFilter
  ));
  const [atsFilter, setAtsFilter] = useState(() => (hasFreshCache ? boardPageCache?.atsFilter ?? "" : initialAtsFilter));
  const [companyFilter, setCompanyFilter] = useState(() => (hasFreshCache ? boardPageCache?.companyFilter ?? "" : initialCompanyFilter));
  const [postedAfterFilter, setPostedAfterFilter] = useState(() => (hasFreshCache ? boardPageCache?.postedAfterFilter ?? "" : initialPostedAfterFilter));
  const [postedBeforeFilter, setPostedBeforeFilter] = useState(() => (hasFreshCache ? boardPageCache?.postedBeforeFilter ?? "" : initialPostedBeforeFilter));
  const [isBrowsePanelOpen, setIsBrowsePanelOpen] = useState(false);
  const [isFilterOpen, setIsFilterOpen] = useState(false);
  const [draftStatusFilter, setDraftStatusFilter] = useState<TrackingStatus | "all">(() => (
    hasFreshCache ? parseStatusFilter((boardPageCache?.statusFilter as string | null | undefined) ?? null) : initialStatusFilter
  ));
  const [draftAtsFilter, setDraftAtsFilter] = useState(() => (hasFreshCache ? boardPageCache?.atsFilter ?? "" : initialAtsFilter));
  const [draftCompanyFilter, setDraftCompanyFilter] = useState(() => (hasFreshCache ? boardPageCache?.companyFilter ?? "" : initialCompanyFilter));
  const [draftPostedAfterFilter, setDraftPostedAfterFilter] = useState(() => (hasFreshCache ? boardPageCache?.postedAfterFilter ?? "" : initialPostedAfterFilter));
  const [draftPostedBeforeFilter, setDraftPostedBeforeFilter] = useState(() => (hasFreshCache ? boardPageCache?.postedBeforeFilter ?? "" : initialPostedBeforeFilter));
  const detailInflightRef = useRef(new Set<string>());
  const hoverPrefetchTimerRef = useRef<Record<string, number>>({});
  const manualEnrichTimerRef = useRef<Record<string, number>>({});
  const latestQueryKeyRef = useRef(initialQueryKey);
  const filterPanelRef = useRef<HTMLDivElement | null>(null);
  const browsePanelRef = useRef<HTMLDivElement | null>(null);
  const [backlogVisibleCount, setBacklogVisibleCount] = useState<number>(
    () => (hasFreshCache ? boardPageCache?.backlogVisibleCount ?? BACKLOG_PAGE_SIZE : BACKLOG_PAGE_SIZE),
  );
  const [kanbanColumnsState, setKanbanColumnsState] = useState<Record<string, JobSummary[]>>(() => {
    const seeded: Record<string, JobSummary[]> = {};
    for (const column of STATUS_COLUMNS) {
      seeded[column.id] = [];
    }
    return seeded;
  });
  const [activeDragItemId, setActiveDragItemId] = useState<string | null>(null);
  const lastFetchedAtRef = useRef<number>(hasFreshCache ? boardPageCache?.fetchedAt ?? 0 : 0);
  const selectedSummary = useMemo(() => {
    if (!selectedJobId) return null;
    return jobs.find((job) => job.id === selectedJobId) ?? null;
  }, [jobs, selectedJobId]);
  const selectedUrl = useMemo(() => {
    if (!selectedJobId) return null;
    if (selectedSummary?.url) return selectedSummary.url;
    if (selectedJob?.id === selectedJobId) return selectedJob.url;
    return null;
  }, [selectedSummary, selectedJob, selectedJobId]);
  const manualMissingRequiredFields = useMemo(() => {
    return MANUAL_REQUIRED_FIELDS.filter((field) => {
      if (field.key === "url") return !manualForm.url.trim();
      if (field.key === "company") return !manualForm.company.trim();
      if (field.key === "title") return !manualForm.title.trim();
      return !manualForm.description.trim();
    }).map((field) => field.label);
  }, [manualForm.company, manualForm.description, manualForm.title, manualForm.url]);
  const manualDuplicateCandidate = useMemo(() => findManualDuplicateCandidate(manualForm, jobs), [manualForm, jobs]);

  function isManualFieldMissing(field: (typeof MANUAL_REQUIRED_FIELDS)[number]["key"]): boolean {
    if (field === "url") return !manualForm.url.trim();
    if (field === "company") return !manualForm.company.trim();
    if (field === "title") return !manualForm.title.trim();
    return !manualForm.description.trim();
  }

  const queryKey = buildQueryKey(statusFilter, atsFilter, companyFilter, postedAfterFilter, postedBeforeFilter, sortOption);

  useEffect(() => {
    latestQueryKeyRef.current = queryKey;
  }, [queryKey]);

  useEffect(() => {
    const nextSelectedJobId = (searchParams.get("job") ?? "").trim() || null;
    setSelectedJobId((current) => (current === nextSelectedJobId ? current : nextSelectedJobId));
  }, [searchParams]);

  function rememberDetail(detail: JobDetail): void {
    setDetailCache((current) => upsertRecordCache(current, detail.url, detail, DETAIL_CACHE_TTL_MS, DETAIL_CACHE_CAP));
  }

  function rememberEvents(url: string, timeline: JobEvent[]): void {
    setEventsCache((current) => upsertRecordCache(current, url, timeline, EVENTS_CACHE_TTL_MS, EVENTS_CACHE_CAP));
  }

  function forgetCachedUrl(url: string): void {
    setDetailCache((current) => removeRecordCacheValue(current, url));
    setEventsCache((current) => removeRecordCacheValue(current, url));
  }

  function clearHoverPrefetch(jobId: string): void {
    const timer = hoverPrefetchTimerRef.current[jobId];
    if (!timer) return;
    window.clearTimeout(timer);
    delete hoverPrefetchTimerRef.current[jobId];
  }

  async function loadBoard(options: { force?: boolean; silent?: boolean } = {}): Promise<void> {
    const force = options.force ?? false;
    const silent = options.silent ?? false;
    const cachedItems = !force ? getJobsQueryCache(queryKey) : null;
    if (cachedItems) {
      setJobs(cachedItems);
      if (!silent) {
        setLoading(false);
      }
      setIsRefreshingBoard(false);
      return;
    }

    if (!silent) {
      setLoading(true);
    } else {
      setIsRefreshingBoard(true);
    }
    setError(null);
    try {
      const loadKey = queryKey;
      const profilePromise = profile ? Promise.resolve(profile) : getProfile().catch(() => null);
      const [jobsData, profileData] = await Promise.all([
        getJobsWithParams({
          sort: "match_desc",
          status: statusFilter,
          ats: atsFilter,
          company: companyFilter,
          posted_after: postedAfterFilter,
          posted_before: postedBeforeFilter,
          limit: BOARD_INITIAL_FETCH_LIMIT,
          offset: 0,
        }),
        profilePromise,
      ]);
      setJobs(jobsData.items);
      setJobsQueryCache(queryKey, jobsData.items);
      setProfile(profileData);
      lastFetchedAtRef.current = Date.now();
      const loadedCount = jobsData.items.length;
      const remaining = Math.min(BOARD_MAX_FETCH_LIMIT, jobsData.total) - loadedCount;
      if (remaining > 0) {
        void getJobsWithParams({
          sort: "match_desc",
          status: statusFilter,
          ats: atsFilter,
          company: companyFilter,
          posted_after: postedAfterFilter,
          posted_before: postedBeforeFilter,
          limit: remaining,
          offset: loadedCount,
        }).then((nextPage) => {
          if (loadKey !== latestQueryKeyRef.current) {
            return;
          }
          setJobs((current) => {
            const seen = new Set(current.map((job) => job.id));
            const merged = [...current];
            for (const item of nextPage.items) {
              if (!seen.has(item.id)) {
                merged.push(item);
              }
            }
            setJobsQueryCache(loadKey, merged);
            return merged;
          });
        }).catch(() => {
          // Keep the initial result when background pagination fails.
        });
      }
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : "Unknown error");
    } finally {
      if (!silent) {
        setLoading(false);
      }
      setIsRefreshingBoard(false);
    }
  }

  useEffect(() => {
    const cachedItems = getJobsQueryCache(queryKey);
    if (cachedItems) {
      setJobs(cachedItems);
      setLoading(false);
      return;
    }
    void loadBoard({ silent: lastFetchedAtRef.current > 0 || jobs.length > 0 });
  }, [queryKey]);

  useEffect(() => {
    return () => {
      for (const timer of Object.values(hoverPrefetchTimerRef.current)) {
        window.clearTimeout(timer);
      }
      hoverPrefetchTimerRef.current = {};
      for (const timer of Object.values(manualEnrichTimerRef.current)) {
        window.clearTimeout(timer);
      }
      manualEnrichTimerRef.current = {};
    };
  }, []);

  useEffect(() => {
    boardPageCache = {
      version: BOARD_CACHE_SCHEMA_VERSION,
      jobs,
      profile,
      detailCache: pruneRecordCache(detailCache, DETAIL_CACHE_TTL_MS, DETAIL_CACHE_CAP),
      eventsCache: pruneRecordCache(eventsCache, EVENTS_CACHE_TTL_MS, EVENTS_CACHE_CAP),
      searchQuery,
      viewMode,
      sortOption,
      focusMode,
      statusFilter,
      atsFilter,
      companyFilter,
      postedAfterFilter,
      postedBeforeFilter,
      backlogVisibleCount,
      fetchedAt: lastFetchedAtRef.current,
      queryKey,
    };
  }, [
    jobs,
    profile,
    detailCache,
    eventsCache,
    searchQuery,
    viewMode,
    sortOption,
    focusMode,
    statusFilter,
    atsFilter,
    companyFilter,
    postedAfterFilter,
    postedBeforeFilter,
    backlogVisibleCount,
    queryKey,
  ]);

  useEffect(() => {
    setBacklogVisibleCount(BACKLOG_PAGE_SIZE);
  }, [queryKey, searchQuery, sortOption, focusMode]);

  useEffect(() => {
    if (!isFilterOpen && !isBrowsePanelOpen) {
      return;
    }
    function onDocumentMouseDown(event: MouseEvent): void {
      const target = event.target as Node;
      const targetElement = event.target as Element | null;
      const clickedInDropdown = Boolean(targetElement?.closest(".ui-dropdown-content, .themed-select-menu"));
      if (clickedInDropdown) {
        return;
      }
      const clickedInsideFilter = Boolean(filterPanelRef.current?.contains(target));
      const clickedInsideBrowse = Boolean(browsePanelRef.current?.contains(target));
      if (!clickedInsideFilter && !clickedInsideBrowse) {
        setIsFilterOpen(false);
        setIsBrowsePanelOpen(false);
      }
    }
    window.addEventListener("mousedown", onDocumentMouseDown);
    return () => window.removeEventListener("mousedown", onDocumentMouseDown);
  }, [isFilterOpen, isBrowsePanelOpen]);

  useEffect(() => {
    if (!selectedJobId) {
      setSelectedJob(null);
      setEvents([]);
      setDetailLoading(false);
      return;
    }

    const jobUrl = selectedSummary?.url ?? (selectedJob?.id === selectedJobId ? selectedJob.url : null);
    if (!jobUrl) {
      setDetailLoading(true);
      void Promise.all([getJobDetail(selectedJobId), getJobEvents(selectedJobId)])
        .then(([detail, timeline]) => {
          rememberDetail(detail);
          rememberEvents(detail.url, timeline);
          setSelectedJob(detail);
          setEvents(timeline);
        })
        .catch(() => {
          setSelectedJob(null);
          setEvents([]);
        })
        .finally(() => {
          setDetailLoading(false);
        });
      return;
    }

    const cachedDetail = getRecordCacheValue(detailCache, jobUrl, DETAIL_CACHE_TTL_MS);
    const cachedEvents = getRecordCacheValue(eventsCache, jobUrl, EVENTS_CACHE_TTL_MS);

    if (cachedDetail) {
      setSelectedJob(cachedDetail);
      if (hasReadyEnrichment(cachedDetail)) {
        setPendingEnrichmentByUrl((current) => {
          if (!current[cachedDetail.url]) return current;
          const { [cachedDetail.url]: _, ...rest } = current;
          return rest;
        });
      }
    } else {
      setSelectedJob(null);
    }

    if (cachedEvents) {
      setEvents(cachedEvents);
    } else {
      setEvents([]);
    }

    if (cachedDetail && cachedEvents) {
      setDetailLoading(false);
      return;
    }

    setDetailLoading(true);
    const requests: Array<Promise<void>> = [];

    if (!cachedDetail) {
      requests.push(
        getJobDetail(selectedJobId).then((detail) => {
          rememberDetail(detail);
          setSelectedJob(detail);
          if (hasReadyEnrichment(detail) || isProcessingResolved(detail)) {
            setPendingEnrichmentByUrl((current) => {
              if (!current[detail.url]) return current;
              const { [detail.url]: _, ...rest } = current;
              return rest;
            });
          }
        }),
      );
    }

    if (!cachedEvents) {
      requests.push(
        getJobEvents(selectedJobId).then((timeline) => {
          rememberEvents(jobUrl, timeline);
          setEvents(timeline);
        }),
      );
    }

    void Promise.allSettled(requests).finally(() => {
      setDetailLoading(false);
    });
  }, [selectedSummary, selectedJob, selectedJobId, jobs, detailCache, eventsCache]);

  async function prefetchJobDetail(jobId: string): Promise<void> {
    const summary = jobs.find((job) => job.id === jobId);
    if (!summary?.url || getRecordCacheValue(detailCache, summary.url, DETAIL_CACHE_TTL_MS) || detailInflightRef.current.has(summary.url)) {
      return;
    }
    detailInflightRef.current.add(summary.url);
    try {
      const detail = await getJobDetail(jobId);
      rememberDetail(detail);
      if (hasReadyEnrichment(detail) || isProcessingResolved(detail)) {
        setPendingEnrichmentByUrl((current) => {
          if (!current[detail.url]) return current;
          const { [detail.url]: _, ...rest } = current;
          return rest;
        });
      }
    } catch {
      // Ignore background prefetch failures (e.g., record removed mid-flight).
    } finally {
      detailInflightRef.current.delete(summary.url);
    }
  }

  function scheduleJobPrefetch(jobId: string): void {
    const summary = jobs.find((job) => job.id === jobId);
    if (!summary?.url || getRecordCacheValue(detailCache, summary.url, DETAIL_CACHE_TTL_MS)) {
      return;
    }
    clearHoverPrefetch(jobId);
    hoverPrefetchTimerRef.current[jobId] = window.setTimeout(() => {
      delete hoverPrefetchTimerRef.current[jobId];
      void prefetchJobDetail(jobId);
    }, HOVER_PREFETCH_DELAY_MS);
  }

  function clearManualEnrichTimer(url: string): void {
    const timer = manualEnrichTimerRef.current[url];
    if (!timer) return;
    window.clearTimeout(timer);
    delete manualEnrichTimerRef.current[url];
  }

  function markManualEnrichmentPending(url: string): void {
    setPendingEnrichmentByUrl((current) => ({ ...current, [url]: true }));
  }

  function clearManualEnrichmentPending(url: string): void {
    setPendingEnrichmentByUrl((current) => {
      if (!current[url]) return current;
      const { [url]: _, ...rest } = current;
      return rest;
    });
  }

  function pollManualEnrichment(jobId: string, attempt = 0, fallbackUrl?: string): void {
    const summary = jobs.find((job) => job.id === jobId) ?? (selectedJob?.id === jobId ? detailToSummary(selectedJob) : null);
    const url = summary?.url ?? fallbackUrl ?? "";
    if (!url) {
      return;
    }
    clearManualEnrichTimer(url);
    void getJobDetail(jobId)
      .then((detail) => {
        rememberDetail(detail);
        if (selectedJobId === jobId) {
          setSelectedJob(detail);
        }

        if (hasReadyEnrichment(detail) || isProcessingResolved(detail)) {
          clearManualEnrichmentPending(url);
          clearManualEnrichTimer(url);
          jobsQueryCache.clear();
          void loadBoard({ force: true, silent: true });
          return;
        }

        if (attempt >= MANUAL_ENRICH_POLL_MAX_ATTEMPTS) {
          clearManualEnrichmentPending(url);
          return;
        }

        manualEnrichTimerRef.current[url] = window.setTimeout(
          () => pollManualEnrichment(jobId, attempt + 1, url),
          MANUAL_ENRICH_POLL_INTERVAL_MS,
        );
      })
      .catch(() => {
        if (attempt >= MANUAL_ENRICH_POLL_MAX_ATTEMPTS) {
          clearManualEnrichmentPending(url);
          return;
        }
        manualEnrichTimerRef.current[url] = window.setTimeout(
          () => pollManualEnrichment(jobId, attempt + 1, url),
          MANUAL_ENRICH_POLL_INTERVAL_MS,
        );
      });
  }

  const searchedJobs = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return !query ? jobs : jobs.filter((job) => {
      const haystack = `${job.title} ${job.company} ${job.location}`.toLowerCase();
      return haystack.includes(query);
    });
  }, [jobs, searchQuery]);

  const focusCounts = useMemo<Record<FocusMode, number>>(() => {
    const counts: Record<FocusMode, number> = {
      all: searchedJobs.length,
      overdue: 0,
      staging: 0,
      high_priority: 0,
      strong_match: 0,
      desired_title_match: 0,
    };
    for (const job of searchedJobs) {
      if (job.staging_overdue) counts.overdue += 1;
      if (job.status === "staging") counts.staging += 1;
      if (job.priority === "high") counts.high_priority += 1;
      if ((job.match_score ?? 0) >= 80) counts.strong_match += 1;
      if (job.desired_title_match) counts.desired_title_match += 1;
    }
    return counts;
  }, [searchedJobs]);

  const filteredJobs = useMemo(() => {
    const subset = focusMode === "all" ? searchedJobs : searchedJobs.filter((job) => matchesFocusMode(job, focusMode));
    const sorted = [...subset];
    if (sortOption === "company_asc") {
      sorted.sort((left, right) => left.company.localeCompare(right.company));
      return sorted;
    }
    if (sortOption === "posted_desc") {
      sorted.sort((left, right) => (dateValueMs(right.posted) ?? -Infinity) - (dateValueMs(left.posted) ?? -Infinity));
      return sorted;
    }
    if (sortOption === "updated_desc") {
      sorted.sort((left, right) => {
        const rightDate = dateValueMs(right.updated_at ?? right.posted) ?? -Infinity;
        const leftDate = dateValueMs(left.updated_at ?? left.posted) ?? -Infinity;
        return rightDate - leftDate;
      });
      return sorted;
    }
    // match_desc default
    sorted.sort((left, right) => (right.match_score ?? 0) - (left.match_score ?? 0));
    return sorted;
  }, [focusMode, searchedJobs, sortOption]);

  const grouped = useMemo(() => {
    const map = new Map<TrackingStatus, JobSummary[]>();
    for (const column of STATUS_COLUMNS) {
      map.set(column.id, []);
    }

    for (const job of filteredJobs) {
      if (job.status === "not_applied" && isOlderThanDays(job.posted, BACKLOG_MAX_AGE_DAYS)) {
        continue;
      }
      const bucket = map.get(job.status) ?? map.get("not_applied");
      bucket?.push(job);
    }
    const stagingBucket = map.get("staging");
    stagingBucket?.sort((left, right) => {
      const overdueDelta = Number(right.staging_overdue) - Number(left.staging_overdue);
      if (overdueDelta !== 0) return overdueDelta;
      return (right.staging_age_hours ?? -1) - (left.staging_age_hours ?? -1);
    });
    return map;
  }, [filteredJobs]);

  useEffect(() => {
    const next: Record<string, JobSummary[]> = {};
    for (const column of STATUS_COLUMNS) {
      const rows = grouped.get(column.id) ?? [];
      next[column.id] = column.id === "not_applied" ? rows.slice(0, backlogVisibleCount) : rows;
    }
    setKanbanColumnsState(next);
  }, [backlogVisibleCount, grouped]);

  async function applyTrackingPatch(jobId: string, patch: TrackingPatchRequest): Promise<void> {
    const detail = await patchTracking(jobId, patch);
    const nextSummary = detailToSummary(detail);
    setJobs((current) => current.map((job) => {
      if (job.id !== jobId) {
        return job;
      }
      return { ...job, ...nextSummary };
    }));

    if (selectedJobId === jobId) {
      setSelectedJob(detail);
    }
    rememberDetail(detail);
    jobsQueryCache.clear();
  }

  async function handleSaveDecision(jobId: string, recommendation: Recommendation): Promise<void> {
    try {
      await saveJobDecision(jobId, recommendation);
      jobsQueryCache.clear();
      await loadBoard({ force: true, silent: true });
      const detail = await getJobDetail(jobId);
      if (selectedJobId === jobId) {
        setSelectedJob(detail);
      }
      rememberDetail(detail);
      toast.success(`Recommendation set to ${recommendationLabel(recommendation)}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to save decision");
    }
  }

  async function handleRetryProcessing(jobId: string): Promise<void> {
    try {
      const detail = await retryJobProcessing(jobId);
      rememberDetail(detail);
      if (selectedJobId === jobId) {
        setSelectedJob(detail);
      }
      jobsQueryCache.clear();
      if (!hasReadyEnrichment(detail) && detail.processing.state === "processing") {
        markManualEnrichmentPending(detail.url);
        pollManualEnrichment(detail.id, 0, detail.url);
      } else {
        clearManualEnrichmentPending(detail.url);
        clearManualEnrichTimer(detail.url);
      }
      toast.success(detail.processing.message || "Background processing restarted.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to retry job processing");
    }
  }

  async function addSkillToProfile(skill: string): Promise<void> {
    const incoming = skill.trim();
    if (!incoming) {
      return;
    }
    const existing = new Set((profile?.skills ?? []).map((item) => normalizeSkill(item)));
    if (existing.has(normalizeSkill(incoming))) {
      return;
    }

    if (profile) {
      const optimistic: CandidateProfile = {
        ...profile,
        skills: [...profile.skills, incoming],
      };
      setProfile(optimistic);
    }

    try {
      const saved = await addProfileSkill(incoming);
      setProfile(saved);
      jobsQueryCache.clear();
    } catch (error) {
      try {
        const fresh = await getProfile();
        setProfile(fresh);
      } catch {
        if (profile) {
          setProfile(profile);
        }
      }
      throw error;
    }
  }

  async function removeJob(jobId: string): Promise<void> {
    const removedJob = jobs.find((item) => item.id === jobId) ?? null;
    if (!removedJob) {
      return;
    }
    const url = removedJob.url;
    const wasEnrichmentPending = Boolean(pendingEnrichmentByUrl[url] || manualEnrichTimerRef.current[url]);
    clearManualEnrichTimer(url);
    clearManualEnrichmentPending(url);

    setJobs((current) => current.filter((job) => job.id !== jobId));
    forgetCachedUrl(url);
    if (selectedJobId === jobId) {
      selectJob(null);
      setSelectedJob(null);
      setEvents([]);
    }

    void deleteJob(jobId)
      .then(async () => {
        jobsQueryCache.clear();
      })
      .catch((err) => {
        if (wasEnrichmentPending) {
          markManualEnrichmentPending(url);
        }
        setJobs((current) => [removedJob, ...current]);
        setError(err instanceof Error ? err.message : "Failed to delete job");
      });
  }

  async function suppressJobFromBoard(jobId: string, reason?: string): Promise<void> {
    const removedJob = jobs.find((item) => item.id === jobId) ?? null;
    if (!removedJob) {
      return;
    }
    const url = removedJob.url;
    const wasEnrichmentPending = Boolean(pendingEnrichmentByUrl[url] || manualEnrichTimerRef.current[url]);
    clearManualEnrichTimer(url);
    clearManualEnrichmentPending(url);

    setJobs((current) => current.filter((job) => job.id !== jobId));
    forgetCachedUrl(url);
    if (selectedJobId === jobId) {
      selectJob(null);
      setSelectedJob(null);
      setEvents([]);
    }

    try {
      await suppressJob(jobId, reason);
      if (isSuppressionPanelOpen) {
        const rows = await getSuppressions(300);
        setSuppressions(rows);
      }
      jobsQueryCache.clear();
    } catch (err) {
      if (wasEnrichmentPending) {
        markManualEnrichmentPending(url);
      }
      setJobs((current) => [removedJob, ...current]);
      throw err;
    }
  }

  function resetManualForm(): void {
    setManualAttemptedSubmit(false);
    setManualForm({
      url: "",
      company: "",
      title: "",
      location: "",
      posted: "",
      ats: "manual",
      status: "staging",
      description: "",
    });
  }

  function openManualCreate(): void {
    setManualError(null);
    resetManualForm();
    setIsManualCreateOpen(true);
  }

  async function submitManualJob(): Promise<void> {
    setManualError(null);
    setManualAttemptedSubmit(true);
    const payload: ManualJobCreateRequest = {
      url: manualForm.url.trim(),
      company: manualForm.company.trim(),
      title: manualForm.title.trim(),
      location: manualForm.location?.trim() || null,
      posted: manualForm.posted?.trim() || null,
      ats: manualForm.ats?.trim() || "manual",
      status: (manualForm.status ?? "staging") as TrackingStatus,
      description: manualForm.description.trim(),
    };
    if (manualMissingRequiredFields.length > 0) {
      setManualError("Fill the required fields before saving.");
      return;
    }

    setIsManualSaving(true);
    try {
      const created = await createManualJob(payload);
      setIsManualCreateOpen(false);
      resetManualForm();

      if (isManualJobCreateDuplicateResponse(created)) {
        const duplicateDetail = manualJobCreateResponseToDetail(created);
        const existingJobId = duplicateDetail.id ?? created.duplicate_of_job_id;
        if (!existingJobId) {
          throw new Error("Duplicate job response did not include an existing job id.");
        }
        const duplicateDetailId = duplicateDetail.id || existingJobId;
        selectJob(existingJobId);
        rememberDetail(duplicateDetail);
        setSelectedJob(duplicateDetail);
        if (!hasReadyEnrichment(duplicateDetail) && duplicateDetail.processing.state === "processing") {
          markManualEnrichmentPending(duplicateDetail.url);
          pollManualEnrichment(duplicateDetailId, 0, duplicateDetail.url);
        }
        setEvents([]);
        toast.info(
          created.message ??
            `Opened the existing job${created.duplicate_match_kind ? ` (${created.duplicate_match_kind} match)` : ""}.`,
        );
        return;
      }

      jobsQueryCache.clear();
      const detail = manualJobCreateResponseToDetail(created);
      const summary = detailToSummary(detail);
      setJobs((current) => [summary, ...current.filter((item) => item.id !== summary.id)]);
      rememberDetail(detail);
      rememberEvents(detail.url, []);
      selectJob(detail.id);
      setSelectedJob(detail);
      setEvents([]);
      if (!hasReadyEnrichment(detail) && detail.processing.state === "processing") {
        markManualEnrichmentPending(detail.url);
        pollManualEnrichment(detail.id, 0, detail.url);
      }
      toast.success(
        `Saved ${detail.title}. Opening the drawer now while enrichment and formatting continue in the background.`,
      );
      window.setTimeout(() => {
        void loadBoard({ force: true, silent: true });
      }, 0);
    } catch (fetchError) {
      setManualError(fetchError instanceof Error ? fetchError.message : "Failed to create manual job");
    } finally {
      setIsManualSaving(false);
    }
  }

  async function openSuppressionsPanel(): Promise<void> {
    setIsSuppressionPanelOpen(true);
    setSuppressionsLoading(true);
    setSuppressionsError(null);
    try {
      const rows = await getSuppressions(300);
      setSuppressions(rows);
    } catch (fetchError) {
      setSuppressionsError(fetchError instanceof Error ? fetchError.message : "Failed to load suppressed jobs");
    } finally {
      setSuppressionsLoading(false);
    }
  }

  async function restoreSuppressedUrl(jobId: string, url: string): Promise<void> {
    if (restoringSuppressionUrl) return;
    setRestoringSuppressionUrl(url);
    setSuppressionsError(null);
    try {
      await unsuppressJob(jobId);
      setSuppressions((current) => current.filter((item) => item.url !== url));
      jobsQueryCache.clear();
      await loadBoard({ force: true });
    } catch (fetchError) {
      setSuppressionsError(fetchError instanceof Error ? fetchError.message : "Failed to restore suppressed job");
    } finally {
      setRestoringSuppressionUrl(null);
    }
  }

  async function onDropJob(status: string, jobId: string): Promise<void> {
    const nextStatus = status as TrackingStatus;
    const existing = jobs.find((job) => job.id === jobId);
    if (!existing || existing.status === nextStatus) {
      return;
    }

    setJobs((current) => current.map((job) => (job.id === jobId ? { ...job, status: nextStatus } : job)));
    try {
      await applyTrackingPatch(jobId, { status: nextStatus });
    } catch {
      setJobs((current) => current.map((job) => (job.id === jobId ? { ...job, status: existing.status } : job)));
    }
  }

  function onKanbanValueChange(next: Record<string, JobSummary[]>): void {
    setKanbanColumnsState(next);
  }

  function onKanbanItemMove(meta: { itemId: string; fromColumn: string; toColumn: string }): void {
    if (meta.fromColumn === meta.toColumn) {
      return;
    }
    void onDropJob(meta.toColumn, meta.itemId);
  }

  const activeDragJob = useMemo(() => {
    if (!activeDragItemId) return null;
    for (const jobsInColumn of Object.values(kanbanColumnsState)) {
      const match = jobsInColumn.find((job) => job.id === activeDragItemId);
      if (match) return match;
    }
    return null;
  }, [activeDragItemId, kanbanColumnsState]);

  function loadMoreBacklog(total: number): void {
    setBacklogVisibleCount((current) => (current >= total ? current : current + BACKLOG_PAGE_SIZE));
  }

  function openFilters(): void {
    setDraftStatusFilter(statusFilter);
    setDraftAtsFilter(atsFilter);
    setDraftCompanyFilter(companyFilter);
    setDraftPostedAfterFilter(postedAfterFilter);
    setDraftPostedBeforeFilter(postedBeforeFilter);
    setIsFilterOpen((current) => !current);
  }

  function syncFiltersToUrl(
    nextStatus: TrackingStatus | "all",
    nextAts: string,
    nextCompany: string,
    nextPostedAfter: string,
    nextPostedBefore: string,
    nextJobId: string | null = selectedJobId,
  ): void {
    const params = new URLSearchParams();
    if (nextStatus !== "all") params.set("status", nextStatus);
    if (nextAts) params.set("ats", nextAts);
    if (nextCompany) params.set("company", nextCompany);
    if (nextPostedAfter) params.set("posted_after", nextPostedAfter);
    if (nextPostedBefore) params.set("posted_before", nextPostedBefore);
    if (nextJobId) params.set("job", nextJobId);
    setSearchParams(params, { replace: true });
  }

  function selectJob(jobId: string | null): void {
    setSelectedJobId(jobId);
    syncFiltersToUrl(statusFilter, atsFilter, companyFilter, postedAfterFilter, postedBeforeFilter, jobId);
  }

  function applyFilters(): void {
    const nextStatus = draftStatusFilter;
    const nextAts = draftAtsFilter.trim();
    const nextCompany = draftCompanyFilter.trim();
    const nextPostedAfter = draftPostedAfterFilter.trim();
    const nextPostedBefore = draftPostedBeforeFilter.trim();
    setStatusFilter(nextStatus);
    setAtsFilter(nextAts);
    setCompanyFilter(nextCompany);
    setPostedAfterFilter(nextPostedAfter);
    setPostedBeforeFilter(nextPostedBefore);
    syncFiltersToUrl(nextStatus, nextAts, nextCompany, nextPostedAfter, nextPostedBefore);
    setIsFilterOpen(false);
    setIsBrowsePanelOpen(false);
  }

  function clearFilters(): void {
    setStatusFilter("all");
    setAtsFilter("");
    setCompanyFilter("");
    setPostedAfterFilter("");
    setPostedBeforeFilter("");
    setDraftStatusFilter("all");
    setDraftAtsFilter("");
    setDraftCompanyFilter("");
    setDraftPostedAfterFilter("");
    setDraftPostedBeforeFilter("");
    syncFiltersToUrl("all", "", "", "", "");
    setIsFilterOpen(false);
    setIsBrowsePanelOpen(false);
  }

  function applyPostedWindowPreset(days: number): void {
    const nextPostedAfter = isoDaysAgo(days);
    setPostedAfterFilter(nextPostedAfter);
    setPostedBeforeFilter("");
    setDraftPostedAfterFilter(nextPostedAfter);
    setDraftPostedBeforeFilter("");
    syncFiltersToUrl(statusFilter, atsFilter, companyFilter, nextPostedAfter, "");
    setIsFilterOpen(false);
    setIsBrowsePanelOpen(false);
  }

  function clearPostedWindowPreset(): void {
    setPostedAfterFilter("");
    setPostedBeforeFilter("");
    setDraftPostedAfterFilter("");
    setDraftPostedBeforeFilter("");
    syncFiltersToUrl(statusFilter, atsFilter, companyFilter, "", "");
    setIsFilterOpen(false);
    setIsBrowsePanelOpen(false);
  }

  const activeFilterCount =
    (focusMode !== "all" ? 1 : 0) +
    (statusFilter !== "all" ? 1 : 0) +
    (atsFilter ? 1 : 0) +
    (companyFilter ? 1 : 0) +
    (postedAfterFilter ? 1 : 0) +
    (postedBeforeFilter ? 1 : 0);
  const postedWindowLabel = postedWindowChipLabel(postedAfterFilter, postedBeforeFilter);
  const activeFilterChips: Array<{ key: "focus" | "status" | "ats" | "company" | "posted_after" | "posted_before"; label: string; value: string }> = [
    ...(focusMode !== "all" ? [{ key: "focus" as const, label: "Focus", value: focusModeLabel(focusMode) }] : []),
    ...(statusFilter && statusFilter !== "all" ? [{ key: "status" as const, label: "Status", value: statusFilter.replaceAll("_", " ") }] : []),
    ...(atsFilter ? [{ key: "ats" as const, label: "ATS", value: atsFilter }] : []),
    ...(companyFilter ? [{ key: "company" as const, label: "Company", value: companyFilter }] : []),
    ...(postedAfterFilter ? [{ key: "posted_after" as const, label: postedWindowLabel ? "Time" : "Posted after", value: postedWindowLabel ?? postedAfterFilter }] : []),
    ...(postedBeforeFilter ? [{ key: "posted_before" as const, label: "Posted before", value: postedBeforeFilter }] : []),
  ];

  function removeFilterChip(key: "focus" | "status" | "ats" | "company" | "posted_after" | "posted_before"): void {
    if (key === "focus") {
      setFocusMode("all");
      return;
    }
    if (key === "status") {
      setStatusFilter("all");
      setDraftStatusFilter("all");
      syncFiltersToUrl("all", atsFilter, companyFilter, postedAfterFilter, postedBeforeFilter);
      return;
    }
    if (key === "ats") {
      setAtsFilter("");
      setDraftAtsFilter("");
      syncFiltersToUrl(statusFilter, "", companyFilter, postedAfterFilter, postedBeforeFilter);
      return;
    }
    if (key === "company") {
      setCompanyFilter("");
      setDraftCompanyFilter("");
      syncFiltersToUrl(statusFilter, atsFilter, "", postedAfterFilter, postedBeforeFilter);
      return;
    }
    if (key === "posted_after") {
      setPostedAfterFilter("");
      setDraftPostedAfterFilter("");
      syncFiltersToUrl(statusFilter, atsFilter, companyFilter, "", postedBeforeFilter);
      return;
    }
    setPostedBeforeFilter("");
    setDraftPostedBeforeFilter("");
    syncFiltersToUrl(statusFilter, atsFilter, companyFilter, postedAfterFilter, "");
  }

  const showBoardSkeleton = loading && jobs.length === 0;
  const manualCreateModal = (
    <div
      className="confirm-modal-layer"
      role="presentation"
      onClick={() => {
        if (!isManualSaving) {
          setIsManualCreateOpen(false);
        }
      }}
    >
      <section
        className="confirm-modal confirm-modal--manual"
        role="dialog"
        aria-modal="true"
        aria-labelledby="manual-create-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="confirm-modal-head confirm-modal-head--manual">
          <div>
            <h4 id="manual-create-title">Add job</h4>
          </div>
        </header>
        {manualDuplicateCandidate ? (
          <div className="manual-modal-warning manual-modal-warning--duplicate">
            <strong>Already on the board</strong>
            <span>
              {manualDuplicateCandidate.title} · {manualDuplicateCandidate.company} · {manualDuplicateCandidate.location} ·{" "}
              {formatDateShort(manualDuplicateCandidate.posted, "Unknown date")} · saving will open the existing record.
            </span>
          </div>
        ) : null}
        <div className="drawer-grid">
          <label className="full-width">
            <span>Job URL *</span>
            <input
              type="url"
              className={manualAttemptedSubmit && isManualFieldMissing("url") ? "field-invalid" : undefined}
              aria-invalid={manualAttemptedSubmit && isManualFieldMissing("url")}
              value={manualForm.url}
              onChange={(event) => setManualForm((current) => ({ ...current, url: event.target.value }))}
              placeholder="https://company.com/careers/job/123"
            />
          </label>
          <label>
            <span>Company *</span>
            <input
              type="text"
              className={manualAttemptedSubmit && isManualFieldMissing("company") ? "field-invalid" : undefined}
              aria-invalid={manualAttemptedSubmit && isManualFieldMissing("company")}
              value={manualForm.company}
              onChange={(event) => setManualForm((current) => ({ ...current, company: event.target.value }))}
              placeholder="Company name"
            />
          </label>
          <label>
            <span>Title *</span>
            <input
              type="text"
              className={manualAttemptedSubmit && isManualFieldMissing("title") ? "field-invalid" : undefined}
              aria-invalid={manualAttemptedSubmit && isManualFieldMissing("title")}
              value={manualForm.title}
              onChange={(event) => setManualForm((current) => ({ ...current, title: event.target.value }))}
              placeholder="Role title"
            />
          </label>
          <label>
            <span>Location</span>
            <input
              type="text"
              value={manualForm.location ?? ""}
              onChange={(event) => setManualForm((current) => ({ ...current, location: event.target.value }))}
              placeholder="City, Country / Remote"
            />
          </label>
          <label>
            <span>Posted Date</span>
            <input
              type="date"
              value={manualForm.posted ?? ""}
              onChange={(event) => setManualForm((current) => ({ ...current, posted: event.target.value }))}
            />
          </label>
          <label>
            <span>Stage</span>
            <ThemedSelect
              value={(manualForm.status ?? "staging") as TrackingStatus}
              options={MANUAL_STAGE_OPTIONS}
              onChange={(value) => setManualForm((current) => ({ ...current, status: value as TrackingStatus }))}
              ariaLabel="Manual job stage"
            />
          </label>
          <label className="full-width">
            <span>Description *</span>
            <textarea
              className={`manual-job-textarea ${manualAttemptedSubmit && isManualFieldMissing("description") ? "field-invalid" : ""}`.trim()}
              aria-invalid={manualAttemptedSubmit && isManualFieldMissing("description")}
              value={manualForm.description}
              onChange={(event) => setManualForm((current) => ({ ...current, description: event.target.value }))}
              placeholder="Paste the full job description."
            />
          </label>
        </div>
        {manualError ? <p className="confirm-modal-error">{manualError}</p> : null}
        <div className="confirm-modal-footer">
          <div className="confirm-modal-actions">
            <Button
              type="button"
              variant="default"
              size="compact"
              data-icon="↗"
              onClick={() => setIsManualCreateOpen(false)}
              disabled={isManualSaving}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              data-icon="✓"
              onClick={() => void submitManualJob()}
              disabled={isManualSaving}
            >
              {isManualSaving ? "Saving..." : manualDuplicateCandidate ? "Open existing" : "Save"}
            </Button>
          </div>
        </div>
      </section>
    </div>
  );

  return (
    <motion.div
      className={`board-page board-page-refined ${selectedJobId ? "board-page--drawer-open" : ""}`}
      variants={pageRevealVariants}
      initial="hidden"
      animate="visible"
    >
      <motion.section className="board-toolbar" variants={sectionRevealVariants}>
        <div className="board-toolbar-primary">
          <div className="board-toolbar-intro">
            <p className="board-toolbar-kicker">Board controls</p>
            <h3 className="board-title">Search, filter, move jobs</h3>
          </div>
          <label className="board-search-panel">
            <span className="board-search-label">Quick find</span>
            <div className="board-search-shell">
              <span className="board-search-icon" aria-hidden="true">⌕</span>
              <input
                type="search"
                className="board-search"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Search title, company, location, or ATS"
                aria-label="Search jobs"
              />
              <span className="board-search-count">{filteredJobs.length}</span>
            </div>
            <span className="board-search-caption">
              {isRefreshingBoard
                ? "Refreshing results from cached board snapshot..."
                : activeFilterCount > 0
                ? `${activeFilterCount} active filter${activeFilterCount === 1 ? "" : "s"} shaping results`
                : "Search stays pinned while browse controls stay compact"}
            </span>
          </label>
        </div>
        <div className="board-toolbar-actions">
          <section className="toolbar-band toolbar-band-controls" aria-label="Browse controls">
            <p className="toolbar-band-label">Browse</p>
            <div className="toolbar-disclose-wrap" ref={browsePanelRef}>
              <button
                type="button"
                className={`toolbar-disclose-btn ${isBrowsePanelOpen ? "open" : ""}`}
                onClick={() => {
                  setIsBrowsePanelOpen((current) => {
                    const next = !current;
                    if (!next) {
                      setIsFilterOpen(false);
                    }
                    return next;
                  });
                }}
                aria-expanded={isBrowsePanelOpen}
                aria-label="Toggle browse controls"
                aria-haspopup="dialog"
              >
                <span className="toolbar-disclose-label">Controls</span>
                {activeFilterCount > 0 && <span className="filter-badge">{activeFilterCount}</span>}
                <span className="toolbar-disclose-chevron" aria-hidden="true">▾</span>
              </button>
              {isBrowsePanelOpen && (
                <div className="toolbar-disclose-panel">
                  <div className="board-toolbar-controls">
                    <label className="toolbar-control">
                      <span>View</span>
                      <ThemedSelect
                        value={viewMode}
                        options={VIEW_OPTIONS}
                        onChange={(value) => setViewMode(value as BoardView)}
                        ariaLabel="View mode"
                      />
                    </label>
                    <label className="toolbar-control">
                      <span>Sort</span>
                      <ThemedSelect
                        value={sortOption}
                        options={SORT_OPTIONS}
                        onChange={(value) => setSortOption(value as SortOption)}
                        ariaLabel="Sort jobs"
                      />
                    </label>
                    <div className="filter-anchor" ref={filterPanelRef}>
                      <button
                        type="button"
                        className={`filter-disclose-btn ${isFilterOpen ? "open" : ""}`}
                        onClick={openFilters}
                        aria-haspopup="dialog"
                        aria-expanded={isFilterOpen}
                      >
                        <span className="filter-disclose-label">Filters</span>
                        <span className="filter-disclose-meta">
                          {activeFilterCount > 0 && <span className="filter-badge">{activeFilterCount}</span>}
                          <span className="toolbar-disclose-chevron" aria-hidden="true">▾</span>
                        </span>
                      </button>
                      {isFilterOpen && (
                        <div className="filter-popover">
                          <div className="filter-presets">
                            <div className="filter-presets-head">
                              <span>Quick time</span>
                              {(postedAfterFilter || postedBeforeFilter) && (
                                <button type="button" className="filter-preset-clear" onClick={clearPostedWindowPreset}>
                                  Clear time
                                </button>
                              )}
                            </div>
                            <div className="filter-preset-row">
                              {POSTED_WINDOW_PRESETS.map((preset) => {
                                const active = postedAfterFilter === isoDaysAgo(preset.days) && !postedBeforeFilter;
                                return (
                                  <button
                                    key={preset.label}
                                    type="button"
                                    className={`filter-preset-chip ${active ? "active" : ""}`}
                                    onClick={() => applyPostedWindowPreset(preset.days)}
                                  >
                                    Last {preset.label}
                                  </button>
                                );
                              })}
                            </div>
                          </div>
                          <div className="filter-grid">
                            <label>
                              <span>Status</span>
                              <ThemedSelect
                                value={draftStatusFilter}
                                options={STATUS_FILTER_OPTIONS}
                                onChange={(value) => setDraftStatusFilter(value as TrackingStatus | "all")}
                                ariaLabel="Filter by status"
                              />
                            </label>
                            <label>
                              <span>ATS</span>
                              <input
                                type="text"
                                value={draftAtsFilter}
                                onChange={(event) => setDraftAtsFilter(event.target.value)}
                              />
                            </label>
                            <label>
                              <span>Company</span>
                              <input
                                type="text"
                                value={draftCompanyFilter}
                                onChange={(event) => setDraftCompanyFilter(event.target.value)}
                              />
                            </label>
                            <label>
                              <span>Posted After</span>
                              <input
                                type="date"
                                value={draftPostedAfterFilter}
                                onChange={(event) => setDraftPostedAfterFilter(event.target.value)}
                              />
                            </label>
                            <label>
                              <span>Posted Before</span>
                              <input
                                type="date"
                                value={draftPostedBeforeFilter}
                                onChange={(event) => setDraftPostedBeforeFilter(event.target.value)}
                              />
                            </label>
                          </div>
                          <div className="filter-actions">
                            <Button type="button" variant="default" size="compact" data-icon="⟲" onClick={clearFilters}>Clear</Button>
                            <Button type="button" variant="primary" data-icon="✓" onClick={applyFilters}>Apply</Button>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </section>
          <section className="toolbar-band toolbar-band-actions" aria-label="Quick actions">
            <p className="toolbar-band-label">Actions</p>
            <div className="board-toolbar-cta-row">
              <button type="button" className="delete-cta toolbar-cta toolbar-cta-suppressed" onClick={() => void openSuppressionsPanel()}>
                <span className="delete-cta__text">Suppressed</span>
                <span className="delete-cta__icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" className="delete-cta__svg delete-cta__svg-slim">
                    <path d="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6Z" />
                    <path d="M9.6 9.6a3.5 3.5 0 0 0 4.95 4.95" />
                    <path d="M4 20 20 4" />
                  </svg>
                </span>
              </button>
              <button type="button" className="delete-cta toolbar-cta toolbar-cta-add" onClick={openManualCreate}>
                <span className="delete-cta__text">Add Job</span>
                <span className="delete-cta__icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" className="delete-cta__svg delete-cta__svg-slim">
                    <path d="M12 5v14M5 12h14" />
                  </svg>
                </span>
              </button>
              <button type="button" onClick={() => void loadBoard({ force: true })} className="delete-cta toolbar-cta toolbar-cta-refresh">
                <span className="delete-cta__text">Refresh</span>
                <span className="delete-cta__icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" className="delete-cta__svg delete-cta__svg-slim">
                    <path d="M20 12a8 8 0 1 1-2.34-5.66" />
                    <path d="M20 4v6h-6" />
                  </svg>
                </span>
              </button>
            </div>
          </section>
        </div>
      </motion.section>
      <motion.section className="board-focus-strip" aria-label="Board focus" variants={sectionRevealVariants}>
        <div className="board-focus-copy">
          <p className="board-focus-kicker">Focus</p>
          <p className="board-focus-note">
            {focusMode === "all"
              ? "Jump into a specific work queue without changing your search or filter setup."
              : `${focusModeLabel(focusMode)} mode narrows the board to the jobs that need attention in this pass.`}
          </p>
        </div>
        <div className="board-focus-actions">
          {BOARD_FOCUS_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={`board-focus-chip ${focusMode === option.value ? "active" : ""}`}
              onClick={() => setFocusMode(option.value)}
            >
              <span>{option.label}</span>
              <strong>{focusCounts[option.value]}</strong>
            </button>
          ))}
        </div>
      </motion.section>
      {activeFilterChips.length > 0 && (
        <motion.section className="active-filters" aria-label="Active filters" variants={sectionRevealVariants}>
          {activeFilterChips.map((chip) => (
            <span className="active-filter-chip" key={chip.key}>
              <strong>{chip.label}:</strong> {chip.value}
              <button type="button" aria-label={`Remove ${chip.label} filter`} onClick={() => removeFilterChip(chip.key)}>
                ×
              </button>
            </span>
          ))}
        </motion.section>
      )}

      <motion.section className="board-flow-strip" aria-label="Pipeline stage distribution" variants={sectionRevealVariants}>
        {STATUS_COLUMNS.map((column) => {
          const count = grouped.get(column.id)?.length ?? 0;
          const total = Math.max(1, filteredJobs.length);
          const ratio = Math.max(6, Math.round((count / total) * 100));
          return (
            <article key={`flow-${column.id}`} className={`board-flow-item status-${column.id}`}>
              <div className="board-flow-head">
                <p>{column.label}</p>
                <strong>{count}</strong>
              </div>
              <span className="board-flow-copy">{columnHealthCopy(column.id, grouped.get(column.id) ?? [])}</span>
              <div className="board-flow-bar" role="presentation">
                <span style={{ width: `${ratio}%` }} />
              </div>
            </article>
          );
        })}
      </motion.section>

      {error && <div className="error-banner">{error}</div>}
      <motion.main className="board-layout" variants={sectionRevealVariants}>
          <p className="board-note">
            Backlog only shows jobs posted in the last 3 weeks; all other stages show full history.
          </p>
          {showBoardSkeleton ? (
            <section className="board-skeleton-grid" aria-hidden="true">
              {STATUS_COLUMNS.map((column) => (
                <article key={`skeleton-${column.id}`} className="board-skeleton-column">
                  <header className="column-header skeleton">
                    <div className="column-header-top">
                      <div className="column-header-title">
                        <span className={`column-tone tone-${column.id.replaceAll("_", "-")}`} aria-hidden="true" />
                        <div className="column-heading">
                          <h3>{column.label}</h3>
                          <p>Loading queue…</p>
                        </div>
                      </div>
                    </div>
                  </header>
                  <div className="column-items">
                    {Array.from({ length: skeletonColumnCards(column.id) }, (_, index) => (
                      <div key={`${column.id}-skeleton-card-${index}`} className="job-card-skeleton">
                        <span className="skeleton-line short" />
                        <span className="skeleton-line medium" />
                        <span className="skeleton-line medium" />
                        <span className="skeleton-line long" />
                      </div>
                    ))}
                  </div>
                </article>
              ))}
            </section>
          ) : viewMode === "kanban" ? (
            <Kanban
              value={kanbanColumnsState}
              onValueChange={onKanbanValueChange}
              getItemValue={(item) => item.id}
              onItemMove={onKanbanItemMove}
              onDragStartItem={(itemId) => setActiveDragItemId(itemId)}
              onDragEndItem={() => setActiveDragItemId(null)}
            >
              <KanbanBoard className="kanban-board">
                {STATUS_COLUMNS.map((column, index) => (
                  <motion.div
                    initial={{ opacity: 0, y: 24 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.04 * index }}
                    key={column.id}
                  >
                    <KanbanColumn value={column.id} className="kanban-column">
                      {(() => {
                        const jobsInColumn = grouped.get(column.id) ?? [];
                        const emptyCopy = emptyColumnCopy(column.id);
                        const columnCount = jobsInColumn.length;
                        return (
                          <>
                      <header className="column-header">
                        <div className="column-header-top">
                          <div className="column-header-title">
                            <span className={`column-tone tone-${column.id.replaceAll("_", "-")}`} aria-hidden="true" />
                            <div className="column-heading">
                              <h3>{column.label}</h3>
                              <p>{columnHealthCopy(column.id, jobsInColumn)}</p>
                            </div>
                          </div>
                          <span className={`column-count status-${column.id.replaceAll("_", "-")}`}>{columnCount}</span>
                        </div>
                      </header>
                      <div className="column-items">
                        {(kanbanColumnsState[column.id] ?? []).map((job) => (
                          <KanbanItem key={job.id} value={job.id}>
                            <JobCard
                              job={job}
                              onSelect={selectJob}
                              onPrefetchStart={scheduleJobPrefetch}
                              onPrefetchCancel={clearHoverPrefetch}
                              selected={selectedJobId === job.id}
                            />
                          </KanbanItem>
                        ))}
                        {columnCount === 0 && (
                          <div className={`column-empty status-${column.id.replaceAll("_", "-")}`}>
                            <strong>{emptyCopy.title}</strong>
                            <p>{emptyCopy.body}</p>
                          </div>
                        )}
                        {column.id === "not_applied" && (grouped.get(column.id)?.length ?? 0) > backlogVisibleCount && (
                          <Button
                            type="button"
                            variant="default"
                            size="compact"
                            data-icon="↓"
                            onClick={() => loadMoreBacklog(grouped.get(column.id)?.length ?? 0)}
                          >
                            Load More
                          </Button>
                        )}
                      </div>
                          </>
                        );
                      })()}
                    </KanbanColumn>
                  </motion.div>
                ))}
              </KanbanBoard>
              <KanbanOverlay>
                {activeDragJob ? (
                  <JobCard job={activeDragJob} onSelect={() => {}} preview />
                ) : (
                  <div className="kanban-overlay-card" />
                )}
              </KanbanOverlay>
            </Kanban>
          ) : (
            <section className="list-view">
              {filteredJobs.map((job) => (
                <article key={job.id} className="list-row">
                  <button type="button" className="list-row-main" onClick={() => selectJob(job.id)}>
                    <h4>{job.title}</h4>
                    <p>{job.company} • {job.location || "-"}</p>
                  </button>
                  <div className="list-row-meta">
                    <Badge>{(job.status ?? "not_applied").replaceAll("_", " ")}</Badge>
                    {stagingSlaLabel(job) ? (
                      <span className={`job-sla-chip ${job.staging_overdue ? "overdue" : "due-soon"}`}>{stagingSlaLabel(job)}</span>
                    ) : null}
                    <Badge>{job.ats || "ATS"}</Badge>
                    <Badge>Posted {formatDateShort(job.posted, "-")}</Badge>
                  </div>
                </article>
              ))}
            </section>
          )}

          {portalRoot
            ? createPortal(
                <DetailDrawer
                  open={Boolean(selectedJobId)}
                  loading={detailLoading}
                  job={selectedJob}
                  summaryJob={selectedSummary}
                  profile={profile}
                  events={events}
                  enrichmentPending={Boolean(selectedUrl && pendingEnrichmentByUrl[selectedUrl])}
                  onClose={() => selectJob(null)}
                    onAddSkillToProfile={addSkillToProfile}
                    onDeleteJob={removeJob}
                    onSuppressJob={suppressJobFromBoard}
                    onRetryProcessing={handleRetryProcessing}
                    onSaveDecision={handleSaveDecision}
                  onChangeTracking={async (patch) => {
                    if (!selectedJobId) {
                      return;
                    }
                    await applyTrackingPatch(selectedJobId, patch);
                  }}
                />,
                portalRoot,
              )
            : (
                <DetailDrawer
                  open={Boolean(selectedJobId)}
                  loading={detailLoading}
                  job={selectedJob}
                  summaryJob={selectedSummary}
                  profile={profile}
                  events={events}
                  enrichmentPending={Boolean(selectedUrl && pendingEnrichmentByUrl[selectedUrl])}
                  onClose={() => selectJob(null)}
                    onAddSkillToProfile={addSkillToProfile}
                    onDeleteJob={removeJob}
                    onSuppressJob={suppressJobFromBoard}
                    onRetryProcessing={handleRetryProcessing}
                    onSaveDecision={handleSaveDecision}
                  onChangeTracking={async (patch) => {
                    if (!selectedJobId) {
                      return;
                    }
                    await applyTrackingPatch(selectedJobId, patch);
                  }}
                />
              )}
        </motion.main>

      {isManualCreateOpen && (portalRoot ? createPortal(manualCreateModal, portalRoot) : manualCreateModal)}

      {isSuppressionPanelOpen && (portalRoot
        ? createPortal(
            <div
              className="confirm-modal-layer"
              role="presentation"
              onClick={() => {
                if (!restoringSuppressionUrl) {
                  setIsSuppressionPanelOpen(false);
                }
              }}
            >
              <section
                className="confirm-modal suppression-modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="suppression-list-title"
                onClick={(event) => event.stopPropagation()}
              >
                <header className="confirm-modal-head">
                  <h4 id="suppression-list-title">Suppressed Jobs</h4>
                </header>
                <p className="confirm-modal-message">
                  These jobs are hidden and blocked from future scrape ingestion. Restore any URL to allow it again.
                </p>
                {suppressionsError && <p className="confirm-modal-error">{suppressionsError}</p>}
                {suppressionsLoading ? (
                  <div className="suppression-loading">
                    <ThemedLoader label="Loading suppressions" />
                  </div>
                ) : suppressions.length === 0 ? (
                  <p className="empty-text">No suppressed jobs.</p>
                ) : (
                  <div className="suppression-list">
                    {suppressions.map((item) => (
                      <article key={item.job_id || item.url} className="suppression-item">
                        <div className="suppression-copy">
                          <p>{item.company || "Unknown company"}</p>
                          <small>{item.reason || "No reason provided"}</small>
                          <code>{item.url}</code>
                        </div>
                        <Button
                          type="button"
                          variant="default"
                          size="compact"
                          data-icon="⟲"
                          disabled={restoringSuppressionUrl === item.url}
                          onClick={() => void restoreSuppressedUrl(item.job_id, item.url)}
                        >
                          {restoringSuppressionUrl === item.url ? "Restoring..." : "Restore"}
                        </Button>
                      </article>
                    ))}
                  </div>
                )}
                <div className="confirm-modal-actions">
                  <Button
                    type="button"
                    variant="default"
                    size="compact"
                    data-icon="↩"
                    onClick={() => setIsSuppressionPanelOpen(false)}
                    disabled={Boolean(restoringSuppressionUrl)}
                  >
                    Close
                  </Button>
                </div>
              </section>
            </div>,
            portalRoot,
          )
        : (
            <div
              className="confirm-modal-layer"
              role="presentation"
              onClick={() => {
                if (!restoringSuppressionUrl) {
                  setIsSuppressionPanelOpen(false);
                }
              }}
            >
              <section
                className="confirm-modal suppression-modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="suppression-list-title"
                onClick={(event) => event.stopPropagation()}
              >
                <header className="confirm-modal-head">
                  <h4 id="suppression-list-title">Suppressed Jobs</h4>
                </header>
                <p className="confirm-modal-message">
                  These jobs are hidden and blocked from future scrape ingestion. Restore any URL to allow it again.
                </p>
                {suppressionsError && <p className="confirm-modal-error">{suppressionsError}</p>}
                {suppressionsLoading ? (
                  <div className="suppression-loading">
                    <ThemedLoader label="Loading suppressions" />
                  </div>
                ) : suppressions.length === 0 ? (
                  <p className="empty-text">No suppressed jobs.</p>
                ) : (
                  <div className="suppression-list">
                    {suppressions.map((item) => (
                      <article key={item.job_id || item.url} className="suppression-item">
                        <div className="suppression-copy">
                          <p>{item.company || "Unknown company"}</p>
                          <small>{item.reason || "No reason provided"}</small>
                          <code>{item.url}</code>
                        </div>
                        <Button
                          type="button"
                          variant="default"
                          size="compact"
                          data-icon="⟲"
                          disabled={restoringSuppressionUrl === item.url}
                          onClick={() => void restoreSuppressedUrl(item.job_id, item.url)}
                        >
                          {restoringSuppressionUrl === item.url ? "Restoring..." : "Restore"}
                        </Button>
                      </article>
                    ))}
                  </div>
                )}
                <div className="confirm-modal-actions">
                  <Button
                    type="button"
                    variant="default"
                    size="compact"
                    data-icon="↩"
                    onClick={() => setIsSuppressionPanelOpen(false)}
                    disabled={Boolean(restoringSuppressionUrl)}
                  >
                    Close
                  </Button>
                </div>
              </section>
            </div>
          ))}
    </motion.div>
  );
}
