import { useCallback, useEffect, useMemo, useRef, useState, memo } from "react";
import { motion } from "framer-motion";
import { createPortal } from "react-dom";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { EyeOff, Filter, Plus, RefreshCw } from "lucide-react";
import {
  addProfileSkill,
  createManualJob,
  deleteJob,
  getJobDetail,
  getJobEvents,
  getJobsWithParams,
  getProfile,
  getSuppressions,
  invalidateJobsListCache,
  invalidateJobDetailCache,
  invalidateJobEventsCache,
  patchTracking,
  prefetchJobDetail as apiPrefetchJobDetail,
  prefetchJobEvents as apiPrefetchJobEvents,
  retryJobProcessing,
  saveJobDecision,
  subscribeToDashboardEvents,
  suppressJob,
  unsuppressJob,
  isManualJobCreateDuplicateResponse,
  manualJobCreateResponseToDetail,
} from "../api";
import { AddJobModal } from "../components/AddJobModal";
import { SuppressionsPanel } from "../components/SuppressionsPanel";
import { ColumnSortButton } from "../components/ColumnSortButton";
import { JobCard } from "../components/JobCard";
import { ThemedLoader } from "../components/ThemedLoader";
import { ThemedSelect } from "../components/ThemedSelect";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Kanban, KanbanBoard, KanbanColumn, KanbanItem, KanbanOverlay } from "../components/ui/kanban";
import { useGlobalHotkeys } from "../hooks/useHotkeys";
import { dateValueMs, formatDateShort } from "../dateUtils";
import { normalizeSkill } from "../skillUtils";
import { useDashboardData } from "../contexts/DashboardDataContext";
import type {
  CandidateProfile,
  ColumnSortOption,
  JobDetail,
  JobEvent,
  JobSummary,
  ManualJobCreateRequest,
  Recommendation,
  SuppressedJob,
  TrackingPatchRequest,
  TrackingStatus,
} from "../types";

const STATUS_COLUMNS: Array<{ id: TrackingStatus; label: string; shortLabel: string }> = [
  { id: "staging", label: "Staging", shortLabel: "Stage" },
  { id: "applied", label: "Applied", shortLabel: "Apply" },
  { id: "interviewing", label: "Interviewing", shortLabel: "Intv" },
  { id: "offer", label: "Offer", shortLabel: "Offer" },
  { id: "rejected", label: "Rejected", shortLabel: "Rej" },
];
const VIEW_OPTIONS: Array<{ value: "kanban" | "list"; label: string }> = [
  { value: "kanban", label: "Kanban view" },
  { value: "list", label: "List view" },
];
const COLUMN_SORT_OPTIONS: Array<{ value: "stage_priority" | "match_desc" | "posted_desc" | "updated_desc" | "company_asc"; label: string }> = [
  { value: "stage_priority", label: "Stage priority" },
  { value: "match_desc", label: "Best match" },
  { value: "posted_desc", label: "Newest posted" },
  { value: "updated_desc", label: "Recently updated" },
  { value: "company_asc", label: "Company A-Z" },
];
const STATUS_FILTER_OPTIONS: Array<{ value: TrackingStatus | "all"; label: string }> = [
  { value: "all", label: "All statuses" },
  { value: "staging", label: "Staging" },
  { value: "applied", label: "Applied" },
  { value: "interviewing", label: "Interviewing" },
  { value: "offer", label: "Offer" },
  { value: "rejected", label: "Rejected" },
];
const MANUAL_STAGE_OPTIONS: Array<{ value: TrackingStatus; label: string }> = [
  { value: "staging", label: "Staging" },
  { value: "applied", label: "Applied" },
  { value: "interviewing", label: "Interviewing" },
  { value: "offer", label: "Offer" },
  { value: "rejected", label: "Rejected" },
];

const BACKLOG_PAGE_SIZE = 30;
const BACKLOG_MAX_AGE_DAYS = 21;
const BOARD_CACHE_TTL_MS = 3 * 60 * 1000;
const HOVER_PREFETCH_DELAY_MS = 150;
const BOARD_CACHE_SCHEMA_VERSION = 8;
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
  { value: "strong_match", label: "Top ranked" },
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
type FocusMode = typeof BOARD_FOCUS_OPTIONS[number]["value"];
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
  searchQuery: string;
  viewMode: BoardView;
  columnSorts: Record<TrackingStatus, ColumnSortOption>;
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
const DEFAULT_COLUMN_SORTS: Record<TrackingStatus, ColumnSortOption> = {
  not_applied: "stage_priority", // kept for type completeness, column not shown
  staging: "stage_priority",
  applied: "stage_priority",
  interviewing: "stage_priority",
  offer: "stage_priority",
  rejected: "stage_priority",
};

function buildQueryKey(
  status: TrackingStatus | "all",
  ats: string,
  company: string,
  postedAfter: string,
  postedBefore: string,
): string {
  return `${status}|${ats.trim().toLowerCase()}|${company.trim().toLowerCase()}|${postedAfter}|${postedBefore}`;
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

function parseColumnSortOption(raw: string | null | undefined): ColumnSortOption | null {
  if (!raw) return null;
  const allowed: ColumnSortOption[] = ["stage_priority", "match_desc", "posted_desc", "updated_desc", "company_asc"];
  return allowed.includes(raw as ColumnSortOption) ? (raw as ColumnSortOption) : null;
}

function parseColumnSorts(raw: string | null, fallback: Record<TrackingStatus, ColumnSortOption> = DEFAULT_COLUMN_SORTS): Record<TrackingStatus, ColumnSortOption> {
  const next = { ...DEFAULT_COLUMN_SORTS, ...fallback };
  if (!raw) return next;
  for (const entry of raw.split(",")) {
    const [status, sort] = entry.split(":");
    if (!status || !sort) continue;
    const parsedStatus = parseStatusFilter(status);
    const parsedSort = parseColumnSortOption(sort);
    if (parsedStatus === "all" || !parsedSort) continue;
    next[parsedStatus] = parsedSort;
  }
  return next;
}

function serializeColumnSorts(columnSorts: Record<TrackingStatus, ColumnSortOption>): string {
  return STATUS_COLUMNS
    .map((column) => `${column.id}:${columnSorts[column.id] ?? DEFAULT_COLUMN_SORTS[column.id]}`)
    .join(",");
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

function skeletonColumnCards(_columnId: TrackingStatus): number {
  return 3;
}

function isOlderThanDays(value: string, days: number): boolean {
  const valueMs = dateValueMs(value);
  if (valueMs === null) return false;
  const now = Date.now();
  const ageMs = now - valueMs;
  return ageMs > days * 24 * 60 * 60 * 1000;
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
  if (mode === "strong_match") return (job.match_score ?? 0) >= 85 || job.match_band === "top_band";
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
    pinned: Boolean(detail.pinned),
    updated_at: detail.tracking_updated_at ?? detail.last_seen ?? detail.first_seen ?? null,
    match_score: detail.match?.score ?? null,
    raw_score: detail.match?.raw_score ?? detail.fit_score ?? null,
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
    required_skills: detail.enrichment?.required_skills ?? [],
  };
}

function compareCompany(left: JobSummary, right: JobSummary): number {
  return left.company.localeCompare(right.company) || left.title.localeCompare(right.title);
}

function comparePostedDesc(left: JobSummary, right: JobSummary): number {
  return (dateValueMs(right.posted) ?? -Infinity) - (dateValueMs(left.posted) ?? -Infinity);
}

function compareUpdatedDesc(left: JobSummary, right: JobSummary): number {
  const rightDate = dateValueMs(right.updated_at ?? right.posted) ?? -Infinity;
  const leftDate = dateValueMs(left.updated_at ?? left.posted) ?? -Infinity;
  return rightDate - leftDate;
}

function compareMatchDesc(left: JobSummary, right: JobSummary): number {
  return (right.match_score ?? -1) - (left.match_score ?? -1);
}

function compareStagePriority(status: TrackingStatus, left: JobSummary, right: JobSummary): number {
  if (status === "staging") {
    const overdueDelta = Number(right.staging_overdue) - Number(left.staging_overdue);
    if (overdueDelta !== 0) return overdueDelta;
    const ageDelta = (right.staging_age_hours ?? -1) - (left.staging_age_hours ?? -1);
    if (ageDelta !== 0) return ageDelta;
    const matchDelta = compareMatchDesc(left, right);
    if (matchDelta !== 0) return matchDelta;
    return comparePostedDesc(left, right);
  }
  return compareUpdatedDesc(left, right);
}

function compareJobsByColumnSort(status: TrackingStatus, sortOption: ColumnSortOption, left: JobSummary, right: JobSummary): number {
  if (sortOption === "company_asc") {
    return compareCompany(left, right);
  }
  if (sortOption === "posted_desc") {
    const postedDelta = comparePostedDesc(left, right);
    return postedDelta || compareMatchDesc(left, right) || compareUpdatedDesc(left, right) || compareCompany(left, right);
  }
  if (sortOption === "updated_desc") {
    const updatedDelta = compareUpdatedDesc(left, right);
    return updatedDelta || comparePostedDesc(left, right) || compareCompany(left, right);
  }
  if (sortOption === "match_desc") {
    const matchDelta = compareMatchDesc(left, right);
    return matchDelta || comparePostedDesc(left, right) || compareUpdatedDesc(left, right) || compareCompany(left, right);
  }
  const stageDelta = compareStagePriority(status, left, right);
  return stageDelta || compareUpdatedDesc(left, right) || comparePostedDesc(left, right) || compareCompany(left, right);
}

function sortJobsForColumn(status: TrackingStatus, jobs: JobSummary[], sortOption: ColumnSortOption): JobSummary[] {
  return [...jobs].sort((left, right) => compareJobsByColumnSort(status, sortOption, left, right));
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
  if (status === "staging") {
    return {
      title: "No jobs in staging",
      body: "Move interesting roles here from your search or the Recommendations feed to start your workflow.",
    };
  }
  if (status === "applied") {
    return {
      title: "No applications sent",
      body: "Once you submit an application, move the job here to track follow-ups and next steps.",
    };
  }
  if (status === "interviewing") {
    return {
      title: "No active interviews",
      body: "When you get a recruiter reply or interview request, track your progress here.",
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
    body: "Rejected or withdrawn opportunities remain here as historical context once resolved.",
  };
}

const BoardEmptyState = memo(function BoardEmptyState({
  onAddJob,
}: {
  onAddJob: () => void;
}) {
  return (
    <motion.div 
      className="board-empty-state glass-card ambient-shadow"
      variants={sectionRevealVariants}
    >
      <div className="board-empty-icon">🏗️</div>
      <h3>Your pipeline is empty</h3>
      <p>
        AI Job Hunter works best when you start moving jobs from your discovery sources into this board.
      </p>
      <div className="board-empty-actions">
        <Button variant="primary" onClick={onAddJob}>
          Add your first job
        </Button>
        <p className="board-empty-tip">
          Tip: Use the <strong>Recommend</strong> page to find matched roles from our daily scrapes.
        </p>
      </div>
    </motion.div>
  );
});

export function BoardPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { skillAliases } = useDashboardData();
  const portalRoot = typeof document !== "undefined" ? document.body : null;
  const [searchParams, setSearchParams] = useSearchParams();
  const initialStatusFilter = parseStatusFilter(searchParams.get("status"));
  const initialAtsFilter = (searchParams.get("ats") ?? "").trim();
  const initialCompanyFilter = (searchParams.get("company") ?? "").trim();
  const initialPostedAfterFilter = parseIsoDate(searchParams.get("posted_after"));
  const initialPostedBeforeFilter = parseIsoDate(searchParams.get("posted_before"));
  const initialColumnSorts = parseColumnSorts(searchParams.get("column_sorts"), boardPageCache?.columnSorts ?? DEFAULT_COLUMN_SORTS);
  const initialQueryKey = buildQueryKey(
    initialStatusFilter,
    initialAtsFilter,
    initialCompanyFilter,
    initialPostedAfterFilter,
    initialPostedBeforeFilter,
  );
  const now = Date.now();
  const hasFreshCache =
    boardPageCache !== null &&
    boardPageCache.version === BOARD_CACHE_SCHEMA_VERSION &&
    now - boardPageCache.fetchedAt < BOARD_CACHE_TTL_MS &&
    boardPageCache.queryKey === initialQueryKey;

  const [jobs, setJobs] = useState<JobSummary[]>(() => (hasFreshCache ? boardPageCache?.jobs ?? [] : []));
  const [profile, setProfile] = useState<CandidateProfile | null>(() => (hasFreshCache ? boardPageCache?.profile ?? null : null));
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [selectedJob, setSelectedJob] = useState<JobDetail | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
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
  const [columnSorts, setColumnSorts] = useState<Record<TrackingStatus, ColumnSortOption>>(() => initialColumnSorts);
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
  const hoverPrefetchTimerRef = useRef<Record<string, number>>({});
  const manualEnrichTimerRef = useRef<Record<string, number>>({});
  const latestQueryKeyRef = useRef(initialQueryKey);
  const filterPanelRef = useRef<HTMLDivElement | null>(null);
  const browsePanelRef = useRef<HTMLDivElement | null>(null);
  const [kanbanColumnsState, setKanbanColumnsState] = useState<Record<string, JobSummary[]>>(() => {
    const seeded: Record<string, JobSummary[]> = {};
    for (const column of STATUS_COLUMNS) {
      seeded[column.id] = [];
    }
    return seeded;
  });
  const [activeDragItemId, setActiveDragItemId] = useState<string | null>(null);
  const [mobileColumnIndex, setMobileColumnIndex] = useState(0);
  const [hoveredJobId, setHoveredJobId] = useState<string | null>(null);
  const lastFetchedAtRef = useRef<number>(hasFreshCache ? boardPageCache?.fetchedAt ?? 0 : 0);
  const profileRef = useRef<CandidateProfile | null>(hasFreshCache ? boardPageCache?.profile ?? null : null);

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

  function isManualFieldMissing(field: string): boolean {
    if (field === "url") return !manualForm.url.trim();
    if (field === "company") return !manualForm.company.trim();
    if (field === "title") return !manualForm.title.trim();
    if (field === "description") return !manualForm.description.trim();
    return false;
  }

  const queryKey = buildQueryKey(statusFilter, atsFilter, companyFilter, postedAfterFilter, postedBeforeFilter);

  useEffect(() => {
    latestQueryKeyRef.current = queryKey;
  }, [queryKey]);

  useEffect(() => {
    profileRef.current = profile;
  }, [profile]);

  useEffect(() => {
    const nextColumnSorts = parseColumnSorts(searchParams.get("column_sorts"), columnSorts);
    setColumnSorts((current) => {
      const currentSerialized = serializeColumnSorts(current);
      const nextSerialized = serializeColumnSorts(nextColumnSorts);
      return currentSerialized === nextSerialized ? current : nextColumnSorts;
    });
  }, [columnSorts, searchParams]);

  const clearHoverPrefetch = useCallback((jobId: string): void => {
    const timer = hoverPrefetchTimerRef.current[jobId];
    if (!timer) return;
    window.clearTimeout(timer);
    delete hoverPrefetchTimerRef.current[jobId];
  }, []);

  const loadBoard = useCallback(async (options: { force?: boolean; silent?: boolean } = {}): Promise<void> => {
    const force = options.force ?? false;
    const silent = options.silent ?? false;
    if (!silent) {
      setLoading(true);
    } else {
      setIsRefreshingBoard(true);
    }
    setError(null);
    try {
      const loadKey = queryKey;
      const profilePromise = profileRef.current ? Promise.resolve(profileRef.current) : getProfile().catch(() => null);
      const [jobsData, profileData] = await Promise.all([
        getJobsWithParams({
          sort: "updated_desc",
          status: statusFilter,
          ats: atsFilter,
          company: companyFilter,
          posted_after: postedAfterFilter,
          posted_before: postedBeforeFilter,
          limit: BOARD_INITIAL_FETCH_LIMIT,
          offset: 0,
        }, { force }),
        profilePromise,
      ]);
      setJobs(jobsData.items);
      setProfile(profileData);
      lastFetchedAtRef.current = Date.now();
      const loadedCount = jobsData.items.length;
      const remaining = Math.min(BOARD_MAX_FETCH_LIMIT, jobsData.total) - loadedCount;
      if (remaining > 0) {
        void getJobsWithParams({
          sort: "updated_desc",
          status: statusFilter,
          ats: atsFilter,
          company: companyFilter,
          posted_after: postedAfterFilter,
          posted_before: postedBeforeFilter,
          limit: remaining,
          offset: loadedCount,
        }, { force }).then((nextPage) => {
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
  }, [atsFilter, companyFilter, postedAfterFilter, postedBeforeFilter, queryKey, statusFilter]);

  useEffect(() => {
    void loadBoard({ silent: lastFetchedAtRef.current > 0 || jobs.length > 0 });
  }, [jobs.length, loadBoard, queryKey]);

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
      searchQuery,
      viewMode,
      columnSorts,
      focusMode,
      statusFilter,
      atsFilter,
      companyFilter,
      postedAfterFilter,
      postedBeforeFilter,
      backlogVisibleCount: 0,
      fetchedAt: lastFetchedAtRef.current,
      queryKey,
    };
  }, [
    jobs,
    profile,
    searchQuery,
    viewMode,
    columnSorts,
    focusMode,
    statusFilter,
    atsFilter,
    companyFilter,
    postedAfterFilter,
    postedBeforeFilter,
    queryKey,
  ]);

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
    let cancelled = false;
    setDetailLoading(true);
    void Promise.allSettled([getJobDetail(selectedJobId), getJobEvents(selectedJobId)]).then((results) => {
      if (cancelled) return;
      const detailResult = results[0];
      const eventsResult = results[1];
      if (detailResult.status === "fulfilled") {
        const detail = detailResult.value;
        setSelectedJob(detail);
        if (hasReadyEnrichment(detail) || isProcessingResolved(detail)) {
          clearManualEnrichmentPending(detail.url);
        }
      } else {
        setSelectedJob(null);
      }
      if (eventsResult.status === "fulfilled") {
        setEvents(eventsResult.value);
      } else {
        setEvents([]);
      }
    }).finally(() => {
      if (!cancelled) {
        setDetailLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [selectedJobId]);

  useEffect(() => {
    let refreshTimer = 0;
    const unsubscribe = subscribeToDashboardEvents({
      onMessage: (payload) => {
        const scope = String(payload.scope ?? "");
        if (scope === "assistant") {
          return;
        }
        window.clearTimeout(refreshTimer);
        refreshTimer = window.setTimeout(() => {
          invalidateJobsListCache();
          void loadBoard({ force: true, silent: true });
          if (selectedJobId) {
            invalidateJobDetailCache(selectedJobId);
            invalidateJobEventsCache(selectedJobId);
            void getJobDetail(selectedJobId, { force: true }).then((detail) => {
              setSelectedJob(detail);
            }).catch(() => {});
            void getJobEvents(selectedJobId, { force: true }).then((items) => {
              setEvents(items);
            }).catch(() => {});
          }
        }, 300);
      },
    });
    return () => {
      window.clearTimeout(refreshTimer);
      unsubscribe();
    };
  }, [loadBoard, selectedJobId]);

  const scheduleJobPrefetch = useCallback((jobId: string): void => {
    clearHoverPrefetch(jobId);
    hoverPrefetchTimerRef.current[jobId] = window.setTimeout(() => {
      delete hoverPrefetchTimerRef.current[jobId];
      void apiPrefetchJobDetail(jobId);
      void apiPrefetchJobEvents(jobId);
    }, HOVER_PREFETCH_DELAY_MS);
  }, [clearHoverPrefetch]);

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
    invalidateJobDetailCache(jobId);
    void getJobDetail(jobId, { force: true })
      .then((detail) => {
        if (selectedJobId === jobId) {
          setSelectedJob(detail);
        }

        if (hasReadyEnrichment(detail) || isProcessingResolved(detail)) {
          clearManualEnrichmentPending(url);
          clearManualEnrichTimer(url);
          invalidateJobsListCache();
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
      if ((job.match_score ?? 0) >= 85 || job.match_band === "top_band") counts.strong_match += 1;
      if (job.desired_title_match) counts.desired_title_match += 1;
    }
    return counts;
  }, [searchedJobs]);

  const filteredJobs = useMemo(() => {
    return focusMode === "all" ? searchedJobs : searchedJobs.filter((job) => matchesFocusMode(job, focusMode));
  }, [focusMode, searchedJobs]);

  const listViewJobs = useMemo(() => sortJobsForColumn("applied", filteredJobs, "updated_desc"), [filteredJobs]);

  const grouped = useMemo(() => {
    const map = new Map<TrackingStatus, JobSummary[]>();
    for (const column of STATUS_COLUMNS) {
      map.set(column.id, []);
    }

    for (const job of filteredJobs) {
      // not_applied jobs are discovered via the Recommend page, not shown on the board
      if (job.status === "not_applied") continue;
      map.get(job.status)?.push(job);
    }
    for (const column of STATUS_COLUMNS) {
      const current = map.get(column.id) ?? [];
      const pinned = current.filter((job) => job.pinned);
      const unpinned = current.filter((job) => !job.pinned);
      map.set(
        column.id,
        [
          ...sortJobsForColumn(column.id, pinned, columnSorts[column.id] ?? DEFAULT_COLUMN_SORTS[column.id]),
          ...sortJobsForColumn(column.id, unpinned, columnSorts[column.id] ?? DEFAULT_COLUMN_SORTS[column.id]),
        ],
      );
    }
    return map;
  }, [columnSorts, filteredJobs]);

  useEffect(() => {
    const next: Record<string, JobSummary[]> = {};
    for (const column of STATUS_COLUMNS) {
      next[column.id] = grouped.get(column.id) ?? [];
    }
    setKanbanColumnsState(next);
  }, [grouped]);

  const applyTrackingPatch = useCallback(async (jobId: string, patch: TrackingPatchRequest): Promise<void> => {
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
    invalidateJobEventsCache(jobId);
    invalidateJobsListCache();
  }, [selectedJobId]);

  async function handleSaveDecision(jobId: string, recommendation: Recommendation): Promise<void> {
    try {
      await saveJobDecision(jobId, recommendation);
      invalidateJobsListCache();
      await loadBoard({ force: true, silent: true });
      const detail = await getJobDetail(jobId);
      if (selectedJobId === jobId) {
        setSelectedJob(detail);
      }
      toast.success(`Recommendation set to ${recommendationLabel(recommendation)}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to save decision");
    }
  }

  async function handleRetryProcessing(jobId: string): Promise<void> {
    try {
      const detail = await retryJobProcessing(jobId);
      if (selectedJobId === jobId) {
        setSelectedJob(detail);
      }
      invalidateJobsListCache();
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
    const existing = new Set((profile?.skills ?? []).map((item) => normalizeSkill(item, skillAliases)));
    if (existing.has(normalizeSkill(incoming, skillAliases))) {
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
      invalidateJobsListCache();
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
    invalidateJobDetailCache(jobId);
    invalidateJobEventsCache(jobId);
    if (selectedJobId === jobId) {
      selectJob(null);
      setSelectedJob(null);
      setEvents([]);
    }

    void deleteJob(jobId)
      .then(async () => {
        invalidateJobsListCache();
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
    invalidateJobDetailCache(jobId);
    invalidateJobEventsCache(jobId);
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
      invalidateJobsListCache();
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
        invalidateJobDetailCache(duplicateDetailId);
        if (!hasReadyEnrichment(duplicateDetail) && duplicateDetail.processing.state === "processing") {
          markManualEnrichmentPending(duplicateDetail.url);
          pollManualEnrichment(duplicateDetailId, 0, duplicateDetail.url);
        }
        toast.info(
          created.message ??
            `Kept the existing job on the board${created.duplicate_match_kind ? ` (${created.duplicate_match_kind} match)` : ""}.`,
        );
        return;
      }

      invalidateJobsListCache();
      const detail = manualJobCreateResponseToDetail(created);
      const summary = detailToSummary(detail);
      setJobs((current) => [summary, ...current.filter((item) => item.id !== summary.id)]);
      invalidateJobDetailCache(detail.id);
      invalidateJobEventsCache(detail.id);
      if (!hasReadyEnrichment(detail) && detail.processing.state === "processing") {
        markManualEnrichmentPending(detail.url);
        pollManualEnrichment(detail.id, 0, detail.url);
      }
      toast.success(
        `Saved ${detail.title}. Enrichment and formatting will continue in the background.`,
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
      invalidateJobsListCache();
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

  const kanbanColumns = useMemo(() => {
    return STATUS_COLUMNS.map((column, index) => {
      const groupedJobs = grouped.get(column.id) ?? [];
      const renderedJobs = kanbanColumnsState[column.id] ?? groupedJobs;
      return {
        column,
        index,
        groupedJobs,
        renderedJobs,
        columnCount: groupedJobs.length,
        emptyCopy: emptyColumnCopy(column.id),
      };
    });
  }, [grouped, kanbanColumnsState]);

  function openFilters(): void {
    setDraftStatusFilter(statusFilter);
    setDraftAtsFilter(atsFilter);
    setDraftCompanyFilter(companyFilter);
    setDraftPostedAfterFilter(postedAfterFilter);
    setDraftPostedBeforeFilter(postedBeforeFilter);
    setIsFilterOpen((current) => !current);
  }

  const syncFiltersToUrl = useCallback((
    nextStatus: TrackingStatus | "all",
    nextAts: string,
    nextCompany: string,
    nextPostedAfter: string,
    nextPostedBefore: string,
    nextColumnSorts: Record<TrackingStatus, ColumnSortOption>,
  ): void => {
    const params = new URLSearchParams();
    if (nextStatus !== "all") params.set("status", nextStatus);
    if (nextAts) params.set("ats", nextAts);
    if (nextCompany) params.set("company", nextCompany);
    if (nextPostedAfter) params.set("posted_after", nextPostedAfter);
    if (nextPostedBefore) params.set("posted_before", nextPostedBefore);
    params.set("column_sorts", serializeColumnSorts(nextColumnSorts));
    setSearchParams(params, { replace: true });
  }, [setSearchParams]);

  const selectJob = useCallback((jobId: string | null): void => {
    if (!jobId) {
      setSelectedJobId(null);
      return;
    }
    navigate(`/jobs/${encodeURIComponent(jobId)}`, {
      state: { from: `${location.pathname}${location.search}` },
    });
  }, [location.pathname, location.search, navigate]);

  const activeJobId = hoveredJobId;

  useGlobalHotkeys(
    {
      enter: () => {
        if (activeJobId) {
          selectJob(activeJobId);
        }
      },
      s: () => {
        if (activeJobId) {
          void applyTrackingPatch(activeJobId, { status: "staging" });
          toast.success("Job moved to Staging");
        }
      },
      a: () => {
        if (activeJobId) {
          void applyTrackingPatch(activeJobId, { status: "applied" });
          toast.success("Job moved to Applied");
        }
      },
      r: () => {
        if (activeJobId) {
          void applyTrackingPatch(activeJobId, { status: "rejected" });
          toast.success("Job moved to Rejected");
        }
      },
      p: () => {
        if (activeJobId) {
          const job = jobs.find((j) => j.id === activeJobId);
          if (job) {
            void applyTrackingPatch(job.id, { pinned: !job.pinned });
            toast.success(job.pinned ? "Job unpinned" : "Job pinned");
          }
        }
      },
    },
    [activeJobId, jobs, selectJob, applyTrackingPatch],
  );

  function updateColumnSort(status: TrackingStatus, sortOption: ColumnSortOption): void {
    setColumnSorts((current) => {
      const next = { ...current, [status]: sortOption };
      syncFiltersToUrl(statusFilter, atsFilter, companyFilter, postedAfterFilter, postedBeforeFilter, next);
      return next;
    });
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
    syncFiltersToUrl(nextStatus, nextAts, nextCompany, nextPostedAfter, nextPostedBefore, columnSorts);
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
    syncFiltersToUrl("all", "", "", "", "", columnSorts);
    setIsFilterOpen(false);
    setIsBrowsePanelOpen(false);
  }

  function applyPostedWindowPreset(days: number): void {
    const nextPostedAfter = isoDaysAgo(days);
    setPostedAfterFilter(nextPostedAfter);
    setPostedBeforeFilter("");
    setDraftPostedAfterFilter(nextPostedAfter);
    setDraftPostedBeforeFilter("");
    syncFiltersToUrl(statusFilter, atsFilter, companyFilter, nextPostedAfter, "", columnSorts);
    setIsFilterOpen(false);
    setIsBrowsePanelOpen(false);
  }

  function clearPostedWindowPreset(): void {
    setPostedAfterFilter("");
    setPostedBeforeFilter("");
    setDraftPostedAfterFilter("");
    setDraftPostedBeforeFilter("");
    syncFiltersToUrl(statusFilter, atsFilter, companyFilter, "", "", columnSorts);
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
      syncFiltersToUrl("all", atsFilter, companyFilter, postedAfterFilter, postedBeforeFilter, columnSorts);
      return;
    }
    if (key === "ats") {
      setAtsFilter("");
      setDraftAtsFilter("");
      syncFiltersToUrl(statusFilter, "", companyFilter, postedAfterFilter, postedBeforeFilter, columnSorts);
      return;
    }
    if (key === "company") {
      setCompanyFilter("");
      setDraftCompanyFilter("");
      syncFiltersToUrl(statusFilter, atsFilter, "", postedAfterFilter, postedBeforeFilter, columnSorts);
      return;
    }
    if (key === "posted_after") {
      setPostedAfterFilter("");
      setDraftPostedAfterFilter("");
      syncFiltersToUrl(statusFilter, atsFilter, companyFilter, "", postedBeforeFilter, columnSorts);
      return;
    }
    setPostedBeforeFilter("");
    setDraftPostedBeforeFilter("");
    syncFiltersToUrl(statusFilter, atsFilter, companyFilter, postedAfterFilter, "", columnSorts);
  }

  const showBoardSkeleton = loading && jobs.length === 0;

  return (
    <motion.div
      className="board-page board-page-refined"
      variants={pageRevealVariants}
      initial="hidden"
      animate="visible"
    >
      <motion.section className="board-page-rail" variants={sectionRevealVariants}>
        <div className="board-page-rail-copy">
          <p className="board-page-kicker">Board</p>
          <h2 className="board-page-title">Pipeline</h2>
        </div>
        <span className="board-page-rail-meta">{filteredJobs.length} visible</span>
      </motion.section>
      <motion.section className="board-toolbar board-toolbar--unified" variants={sectionRevealVariants}>
        <div className="board-toolbar-primary">
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
                : "Search stays pinned while board tools stay quiet"}
            </span>
          </label>
          <div className="board-toolbar-actions board-toolbar-actions--compact">
            <div className="toolbar-disclose-wrap" ref={browsePanelRef}>
              <button
                type="button"
                className={`toolbar-disclose-btn board-utility-menu-btn ${isBrowsePanelOpen ? "open" : ""}`}
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
                <span className="toolbar-disclose-label toolbar-disclose-label--desktop">View & filters</span>
                <span className="toolbar-disclose-label toolbar-disclose-label--mobile">Tools</span>
                {activeFilterCount > 0 && <span className="filter-badge">{activeFilterCount}</span>}
                <span className="toolbar-disclose-chevron" aria-hidden="true">▾</span>
              </button>
              {isBrowsePanelOpen && (
                <div className="toolbar-disclose-panel board-utility-panel">
                  <div className="board-toolbar-controls board-toolbar-controls--panel">
                    <label className="toolbar-control">
                      <span>View</span>
                      <ThemedSelect
                        value={viewMode}
                        options={VIEW_OPTIONS}
                        onChange={(value) => setViewMode(value as BoardView)}
                        ariaLabel="View mode"
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
                  <div className="board-toolbar-mobile-actions" aria-label="Board actions">
                    <button type="button" className="board-utility-action board-utility-action--ghost" onClick={() => void openSuppressionsPanel()}>
                      <EyeOff size={16} strokeWidth={2} />
                      <span>Suppressed</span>
                    </button>
                    <button type="button" className="board-utility-action board-utility-action--ghost" onClick={() => void loadBoard({ force: true })}>
                      <RefreshCw size={16} strokeWidth={2} />
                      <span>Refresh</span>
                    </button>
                    <button type="button" className="board-utility-action board-utility-action--primary" onClick={openManualCreate}>
                      <Plus size={16} strokeWidth={2.1} />
                      <span>New Track</span>
                    </button>
                  </div>
                </div>
              )}
            </div>
            <div className="board-toolbar-direct-actions" aria-label="Board actions">
              <button type="button" className="board-utility-action board-utility-action--ghost" onClick={() => void openSuppressionsPanel()}>
                <EyeOff size={16} strokeWidth={2} />
                <span>Suppressed</span>
              </button>
              <button type="button" className="board-utility-action board-utility-action--ghost" onClick={() => void loadBoard({ force: true })}>
                <RefreshCw size={16} strokeWidth={2} />
                <span>Refresh</span>
              </button>
              <button type="button" className="board-utility-action board-utility-action--primary" onClick={openManualCreate}>
                <Plus size={16} strokeWidth={2.1} />
                <span>New Track</span>
              </button>
            </div>
          </div>
        </div>
        <div className="board-toolbar-secondary">
          <div className="board-focus-inline" aria-label="Board focus">
            <p className="board-toolbar-kicker">Focus</p>
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
            {activeFilterChips.length > 0 && (
              <div className="active-filters board-toolbar-active-filters" aria-label="Active filters">
                {activeFilterChips.map((chip) => (
                  <span className="active-filter-chip" key={chip.key}>
                    <strong>{chip.label}:</strong> {chip.value}
                    <button type="button" aria-label={`Remove ${chip.label} filter`} onClick={() => removeFilterChip(chip.key)}>
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      </motion.section>

      {error && <div className="error-banner">{error}</div>}
      
      {!loading && jobs.length === 0 ? (
        <BoardEmptyState onAddJob={openManualCreate} />
      ) : (
        <motion.main className="board-layout" variants={sectionRevealVariants} layout>
          {showBoardSkeleton ? (
            <section className="board-skeleton-grid" aria-hidden="true">
              {STATUS_COLUMNS.map((column) => (
                <article key={`skeleton-${column.id}`} className="board-skeleton-column">
                  <header className="column-header skeleton">
                    <div className="column-header-top">
                      <div className="column-header-title column-header-title--sample">
                        <span className={`column-dot tone-${column.id.replaceAll("_", "-")}`} aria-hidden="true" />
                        <h3>{column.label}</h3>
                        <span className={`column-count status-${column.id}`}>--</span>
                      </div>
                    </div>
                    <p className="column-header-copy">Loading queue…</p>
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
            <div className="kanban-outer-container">
              {/* Mobile Column Tabs */}
              <nav className="kanban-mobile-tabs" aria-label="Pipeline stages">
              {STATUS_COLUMNS.map((column, index) => (
                <button
                  key={column.id}
                  type="button"
                  className={`kanban-mobile-tab ${mobileColumnIndex === index ? "active" : ""}`}
                  onClick={() => setMobileColumnIndex(index)}
                  >
                    <span className="kanban-mobile-tab-label">{column.shortLabel || column.label}</span>
                    <span className="kanban-mobile-tab-count">{(grouped.get(column.id) ?? []).length}</span>
                  </button>
                ))}
              </nav>

            <Kanban
              value={kanbanColumnsState}
              onValueChange={onKanbanValueChange}
              getItemValue={(item) => item.id}
              onItemMove={onKanbanItemMove}
              onDragStartItem={(itemId) => setActiveDragItemId(itemId)}
              onDragEndItem={() => setActiveDragItemId(null)}
            >
              <KanbanBoard className="kanban-board">
                {kanbanColumns.map(({ column, index, groupedJobs, renderedJobs, columnCount, emptyCopy }) => (
                  <motion.div
                    className={`kanban-column-wrapper ${mobileColumnIndex === index ? "mobile-active" : "mobile-hidden"}`}
                    layout="position"
                    initial={{ opacity: 0, y: 24 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.04 * index }}
                    key={column.id}
                  >
                    <KanbanColumn value={column.id} className="kanban-column">
                      <>
                      <header className="column-header">
                        <div className="column-header-top">
                          <div className="column-header-title column-header-title--sample">
                            <span className={`column-dot tone-${column.id.replaceAll("_", "-")}`} aria-hidden="true" />
                            <h3>{column.label}</h3>
                            <span className={`column-count status-${column.id}`}>{columnCount}</span>
                          </div>
                          <div className="column-header-actions">
                            <ColumnSortButton
                              value={columnSorts[column.id] ?? DEFAULT_COLUMN_SORTS[column.id]}
                              options={COLUMN_SORT_OPTIONS}
                              onChange={(value) => updateColumnSort(column.id, value as ColumnSortOption)}
                              columnLabel={column.label}
                            />
                          </div>
                        </div>
                        <p className="column-header-copy">{columnHealthCopy(column.id, groupedJobs)}</p>
                      </header>
                      <div className="column-items">
                        {renderedJobs.map((job) => (
                          <KanbanItem key={job.id} value={job.id}>
                            <JobCard
                              job={job}
                              onSelect={selectJob}
                              onPrefetchStart={(id) => {
                                setHoveredJobId(id);
                                scheduleJobPrefetch(id);
                              }}
                              onPrefetchCancel={(id) => {
                                setHoveredJobId((current) => (current === id ? null : current));
                                clearHoverPrefetch(id);
                              }}
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
                      </div>
                      </>
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
            </div>
          ) : (
            <section className="list-view">
              {listViewJobs.map((job) => (
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
        </motion.main>
      )}

      {portalRoot

        ? createPortal(
            <AddJobModal
              isOpen={isManualCreateOpen}
              onClose={() => setIsManualCreateOpen(false)}
              onSave={submitManualJob}
              form={manualForm}
              onFormChange={setManualForm}
              isSaving={isManualSaving}
              attemptedSubmit={manualAttemptedSubmit}
              isFieldMissing={isManualFieldMissing}
              duplicateCandidate={manualDuplicateCandidate}
              error={manualError}
              stageOptions={MANUAL_STAGE_OPTIONS}
            />,
            portalRoot
          )
        : null}

      {portalRoot
        ? createPortal(
            <SuppressionsPanel
              isOpen={isSuppressionPanelOpen}
              onClose={() => setIsSuppressionPanelOpen(false)}
              suppressions={suppressions}
              loading={suppressionsLoading}
              error={suppressionsError}
              onRestore={restoreSuppressedUrl}
              restoringUrl={restoringSuppressionUrl}
            />,
            portalRoot
          )
        : null}
    </motion.div>
  );
}
