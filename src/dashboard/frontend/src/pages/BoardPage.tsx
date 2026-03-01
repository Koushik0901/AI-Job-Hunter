import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { addProfileSkill, createManualJob, deleteJob, generateArtifactSuggestions, generateStarterArtifacts, getJobArtifacts, getJobDetail, getJobEvents, getJobsWithParams, getProfile, getStarterArtifactsStatus, getStats, getSuppressions, patchTracking, suppressJob, unsuppressJob } from "../api";
import { DetailDrawer } from "../components/DetailDrawer";
import { JobCard } from "../components/JobCard";
import { ScoreRecomputeStatus } from "../components/ScoreRecomputeStatus";
import { ThemedLoader } from "../components/ThemedLoader";
import { ThemedSelect } from "../components/ThemedSelect";
import { SpotlightSurface } from "../components/reactbits/SpotlightSurface";
import { Badge } from "../components/ui/badge";
import { Kanban, KanbanBoard, KanbanColumn, KanbanItem, KanbanOverlay } from "../components/ui/kanban";
import type { ArtifactStarterStatus, ArtifactSummary, CandidateProfile, JobDetail, JobEvent, JobSummary, ManualJobCreateRequest, StatsResponse, SuppressedJob, TrackingPatchRequest, TrackingStatus } from "../types";

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

const BACKLOG_PAGE_SIZE = 30;
const BACKLOG_MAX_AGE_DAYS = 21;
const BOARD_CACHE_TTL_MS = 3 * 60 * 1000;
const JOBS_QUERY_CACHE_CAP = 4;
const BOARD_CACHE_SCHEMA_VERSION = 3;
const BOARD_INITIAL_FETCH_LIMIT = 200;
const BOARD_MAX_FETCH_LIMIT = 500;
const MANUAL_ENRICH_POLL_INTERVAL_MS = 3500;
const MANUAL_ENRICH_POLL_MAX_ATTEMPTS = 34;

type BoardView = "kanban" | "list";
type SortOption = "match_desc" | "posted_desc" | "updated_desc" | "company_asc";

type BoardPageCache = {
  version: number;
  jobs: JobSummary[];
  stats: StatsResponse | null;
  profile: CandidateProfile | null;
  detailCache: Record<string, JobDetail>;
  eventsCache: Record<string, JobEvent[]>;
  artifactCache: Record<string, ArtifactSummary[]>;
  searchQuery: string;
  viewMode: BoardView;
  sortOption: SortOption;
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
): string {
  return `${status}|${ats.trim().toLowerCase()}|${company.trim().toLowerCase()}|${postedAfter}|${postedBefore}`;
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

function isOlderThanDays(value: string, days: number): boolean {
  if (!value) return false;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return false;
  const now = Date.now();
  const ageMs = now - parsed.getTime();
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

function detailToSummary(detail: JobDetail): JobSummary {
  return {
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
  };
}

function hasReadyEnrichment(detail: JobDetail): boolean {
  const enrichment = detail.enrichment;
  if (!enrichment) return false;
  const status = (enrichment.enrichment_status ?? "").trim().toLowerCase();
  if (status === "ok" || status === "success") return true;
  return Boolean((enrichment.formatted_description ?? "").trim());
}

export function BoardPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialStatusFilter = parseStatusFilter(searchParams.get("status"));
  const initialAtsFilter = (searchParams.get("ats") ?? "").trim();
  const initialCompanyFilter = (searchParams.get("company") ?? "").trim();
  const initialPostedAfterFilter = parseIsoDate(searchParams.get("posted_after"));
  const initialPostedBeforeFilter = parseIsoDate(searchParams.get("posted_before"));
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
  const [stats, setStats] = useState<StatsResponse | null>(() => (hasFreshCache ? boardPageCache?.stats ?? null : null));
  const [profile, setProfile] = useState<CandidateProfile | null>(() => (hasFreshCache ? boardPageCache?.profile ?? null : null));
  const [selectedUrl, setSelectedUrl] = useState<string | null>(null);
  const [selectedJob, setSelectedJob] = useState<JobDetail | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailCache, setDetailCache] = useState<Record<string, JobDetail>>(() => (hasFreshCache ? boardPageCache?.detailCache ?? {} : {}));
  const [eventsCache, setEventsCache] = useState<Record<string, JobEvent[]>>(() => (hasFreshCache ? boardPageCache?.eventsCache ?? {} : {}));
  const [artifactCache, setArtifactCache] = useState<Record<string, ArtifactSummary[]>>(() => (hasFreshCache ? boardPageCache?.artifactCache ?? {} : {}));
  const [artifactsLoading, setArtifactsLoading] = useState(false);
  const [artifactsGenerating, setArtifactsGenerating] = useState(false);
  const [artifactStarterStatus, setArtifactStarterStatus] = useState<ArtifactStarterStatus | null>(null);
  const [pendingEnrichmentByUrl, setPendingEnrichmentByUrl] = useState<Record<string, true>>({});
  const [loading, setLoading] = useState<boolean>(() => !hasFreshCache);
  const [error, setError] = useState<string | null>(null);
  const [manualError, setManualError] = useState<string | null>(null);
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
    description: "",
  });
  const [searchQuery, setSearchQuery] = useState(() => (hasFreshCache ? boardPageCache?.searchQuery ?? "" : ""));
  const [viewMode, setViewMode] = useState<BoardView>(() => (hasFreshCache ? boardPageCache?.viewMode ?? "kanban" : "kanban"));
  const [sortOption, setSortOption] = useState<SortOption>(() => (hasFreshCache ? boardPageCache?.sortOption ?? "match_desc" : "match_desc"));
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
  const eventsInflightRef = useRef(new Set<string>());
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
  const lastFetchedAtRef = useRef<number>(hasFreshCache ? boardPageCache?.fetchedAt ?? 0 : 0);

  const queryKey = buildQueryKey(statusFilter, atsFilter, companyFilter, postedAfterFilter, postedBeforeFilter);

  useEffect(() => {
    latestQueryKeyRef.current = queryKey;
  }, [queryKey]);

  async function loadBoard(options: { force?: boolean; silent?: boolean } = {}): Promise<void> {
    const force = options.force ?? false;
    const silent = options.silent ?? false;
    const cachedItems = !force ? getJobsQueryCache(queryKey) : null;
    if (cachedItems) {
      setJobs(cachedItems);
      if (!silent) {
        setLoading(false);
      }
      return;
    }

    if (!silent) {
      setLoading(true);
    }
    setError(null);
    try {
      const loadKey = queryKey;
      const [jobsData, statsData, profileData] = await Promise.all([
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
        getStats(),
        getProfile().catch(() => null),
      ]);
      setJobs(jobsData.items);
      setJobsQueryCache(queryKey, jobsData.items);
      setStats(statsData);
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
            const seen = new Set(current.map((job) => job.url));
            const merged = [...current];
            for (const item of nextPage.items) {
              if (!seen.has(item.url)) {
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
    }
  }

  useEffect(() => {
    const cachedItems = getJobsQueryCache(queryKey);
    if (cachedItems) {
      setJobs(cachedItems);
      setLoading(false);
      return;
    }
    void loadBoard();
  }, [queryKey]);

  useEffect(() => {
    return () => {
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
      stats,
      profile,
      detailCache,
      eventsCache,
      artifactCache,
      searchQuery,
      viewMode,
      sortOption,
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
    stats,
    profile,
    detailCache,
    eventsCache,
    artifactCache,
    searchQuery,
    viewMode,
    sortOption,
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
  }, [queryKey, searchQuery, sortOption]);

  useEffect(() => {
    if (!isFilterOpen && !isBrowsePanelOpen) {
      return;
    }
    function onDocumentMouseDown(event: MouseEvent): void {
      const target = event.target as Node;
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
    if (!selectedUrl) {
      setSelectedJob(null);
      setEvents([]);
      setDetailLoading(false);
      return;
    }

    const cachedDetail = detailCache[selectedUrl];
    const cachedEvents = eventsCache[selectedUrl];

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
        getJobDetail(selectedUrl).then((detail) => {
          setDetailCache((current) => ({ ...current, [selectedUrl]: detail }));
          setSelectedJob(detail);
          if (hasReadyEnrichment(detail)) {
            setPendingEnrichmentByUrl((current) => {
              if (!current[selectedUrl]) return current;
              const { [selectedUrl]: _, ...rest } = current;
              return rest;
            });
          }
        }),
      );
    }

    if (!cachedEvents) {
      requests.push(
        getJobEvents(selectedUrl).then((timeline) => {
          setEventsCache((current) => ({ ...current, [selectedUrl]: timeline }));
          setEvents(timeline);
        }),
      );
    }

    void Promise.allSettled(requests).finally(() => {
      setDetailLoading(false);
    });
  }, [selectedUrl, detailCache, eventsCache]);

  useEffect(() => {
    if (!selectedUrl) {
      return;
    }
    setArtifactStarterStatus(null);
    if (artifactCache[selectedUrl]) {
      return;
    }
    setArtifactsLoading(true);
    void getJobArtifacts(selectedUrl)
      .then((rows) => {
        setArtifactCache((current) => ({ ...current, [selectedUrl]: rows }));
      })
      .catch(() => {
        setArtifactCache((current) => ({ ...current, [selectedUrl]: [] }));
      })
      .finally(() => {
        setArtifactsLoading(false);
      });
  }, [selectedUrl, artifactCache]);

  async function prefetchJobDetail(url: string): Promise<void> {
    if (detailCache[url] || detailInflightRef.current.has(url)) {
      return;
    }
    detailInflightRef.current.add(url);
    try {
      const detail = await getJobDetail(url);
      setDetailCache((current) => (current[url] ? current : { ...current, [url]: detail }));
      if (hasReadyEnrichment(detail)) {
        setPendingEnrichmentByUrl((current) => {
          if (!current[url]) return current;
          const { [url]: _, ...rest } = current;
          return rest;
        });
      }
    } catch {
      // Ignore background prefetch failures (e.g., record removed mid-flight).
    } finally {
      detailInflightRef.current.delete(url);
    }
  }

  async function prefetchJobEvents(url: string): Promise<void> {
    if (eventsCache[url] || eventsInflightRef.current.has(url)) {
      return;
    }
    eventsInflightRef.current.add(url);
    try {
      const timeline = await getJobEvents(url);
      setEventsCache((current) => (current[url] ? current : { ...current, [url]: timeline }));
    } catch {
      // Ignore background prefetch failures (e.g., record removed mid-flight).
    } finally {
      eventsInflightRef.current.delete(url);
    }
  }

  function prefetchJob(url: string): void {
    void prefetchJobDetail(url);
    void prefetchJobEvents(url);
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

  function pollManualEnrichment(url: string, attempt = 0): void {
    clearManualEnrichTimer(url);
    void getJobDetail(url)
      .then((detail) => {
        setDetailCache((current) => ({ ...current, [url]: detail }));
        if (selectedUrl === url) {
          setSelectedJob(detail);
        }

        if (hasReadyEnrichment(detail)) {
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
          () => pollManualEnrichment(url, attempt + 1),
          MANUAL_ENRICH_POLL_INTERVAL_MS,
        );
      })
      .catch(() => {
        if (attempt >= MANUAL_ENRICH_POLL_MAX_ATTEMPTS) {
          clearManualEnrichmentPending(url);
          return;
        }
        manualEnrichTimerRef.current[url] = window.setTimeout(
          () => pollManualEnrichment(url, attempt + 1),
          MANUAL_ENRICH_POLL_INTERVAL_MS,
        );
      });
  }

  useEffect(() => {
    if (jobs.length === 0) return;
    jobs.slice(0, 10).forEach((job) => {
      void prefetchJobDetail(job.url);
    });
  }, [jobs]);

  const filteredJobs = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    const subset = !query ? jobs : jobs.filter((job) => {
      const haystack = `${job.title} ${job.company} ${job.location}`.toLowerCase();
      return haystack.includes(query);
    });
    const sorted = [...subset];
    if (sortOption === "company_asc") {
      sorted.sort((left, right) => left.company.localeCompare(right.company));
      return sorted;
    }
    if (sortOption === "posted_desc") {
      sorted.sort((left, right) => new Date(right.posted).valueOf() - new Date(left.posted).valueOf());
      return sorted;
    }
    if (sortOption === "updated_desc") {
      sorted.sort((left, right) => {
        const rightDate = new Date(right.updated_at ?? right.posted).valueOf();
        const leftDate = new Date(left.updated_at ?? left.posted).valueOf();
        return rightDate - leftDate;
      });
      return sorted;
    }
    // match_desc default
    sorted.sort((left, right) => (right.match_score ?? 0) - (left.match_score ?? 0));
    return sorted;
  }, [jobs, searchQuery, sortOption]);

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

  async function applyTrackingPatch(url: string, patch: TrackingPatchRequest): Promise<void> {
    const detail = await patchTracking(url, patch);
    setJobs((current) => current.map((job) => {
      if (job.url !== url) {
        return job;
      }
      return {
        ...job,
        status: detail.tracking_status,
        priority: detail.priority,
        updated_at: detail.tracking_updated_at,
      };
    }));

    if (selectedUrl === url) {
      setSelectedJob(detail);
    }
    setDetailCache((current) => ({ ...current, [url]: detail }));
    if (detail.tracking_status === "staging") {
      try {
        const rows = await getJobArtifacts(url);
        setArtifactCache((current) => ({ ...current, [url]: rows }));
      } catch {
        // Keep board flow resilient if artifact fetch fails.
      }
    }
    jobsQueryCache.clear();

    const newStats = await getStats();
    setStats(newStats);
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

  async function removeJob(url: string): Promise<void> {
    const removedJob = jobs.find((item) => item.url === url) ?? null;
    if (!removedJob) {
      return;
    }

    setJobs((current) => current.filter((job) => job.url !== url));
    setDetailCache((current) => {
      const next = { ...current };
      delete next[url];
      return next;
    });
    setEventsCache((current) => {
      const next = { ...current };
      delete next[url];
      return next;
    });
    setArtifactCache((current) => {
      const next = { ...current };
      delete next[url];
      return next;
    });
    if (selectedUrl === url) {
      setSelectedUrl(null);
      setSelectedJob(null);
      setEvents([]);
    }

    void deleteJob(url)
      .then(async () => {
        jobsQueryCache.clear();
        const newStats = await getStats();
        setStats(newStats);
      })
      .catch((err) => {
        setJobs((current) => [removedJob, ...current]);
        setError(err instanceof Error ? err.message : "Failed to delete job");
      });
  }

  async function suppressJobFromBoard(url: string, reason?: string): Promise<void> {
    const removedJob = jobs.find((item) => item.url === url) ?? null;
    if (!removedJob) {
      return;
    }

    setJobs((current) => current.filter((job) => job.url !== url));
    setDetailCache((current) => {
      const next = { ...current };
      delete next[url];
      return next;
    });
    setEventsCache((current) => {
      const next = { ...current };
      delete next[url];
      return next;
    });
    setArtifactCache((current) => {
      const next = { ...current };
      delete next[url];
      return next;
    });
    if (selectedUrl === url) {
      setSelectedUrl(null);
      setSelectedJob(null);
      setEvents([]);
    }

    try {
      await suppressJob(url, reason);
      if (isSuppressionPanelOpen) {
        const rows = await getSuppressions(300);
        setSuppressions(rows);
      }
      jobsQueryCache.clear();
      const newStats = await getStats();
      setStats(newStats);
    } catch (err) {
      setJobs((current) => [removedJob, ...current]);
      throw err;
    }
  }

  function resetManualForm(): void {
    setManualForm({
      url: "",
      company: "",
      title: "",
      location: "",
      posted: "",
      ats: "manual",
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
    const payload: ManualJobCreateRequest = {
      url: manualForm.url.trim(),
      company: manualForm.company.trim(),
      title: manualForm.title.trim(),
      location: manualForm.location?.trim() || null,
      posted: manualForm.posted?.trim() || null,
      ats: manualForm.ats?.trim() || "manual",
      description: manualForm.description.trim(),
    };
    if (!payload.url || !payload.company || !payload.title || !payload.description) {
      setManualError("URL, company, title, and description are required.");
      return;
    }

    setIsManualSaving(true);
    try {
      const created = await createManualJob(payload);
      jobsQueryCache.clear();
      const summary = detailToSummary(created);
      setJobs((current) => [summary, ...current.filter((item) => item.url !== summary.url)]);
      setDetailCache((current) => ({ ...current, [created.url]: created }));
      setEventsCache((current) => (current[created.url] ? current : { ...current, [created.url]: [] }));
      if (!hasReadyEnrichment(created)) {
        markManualEnrichmentPending(created.url);
        pollManualEnrichment(created.url);
      }
      void loadBoard({ force: true, silent: true });
      setSelectedUrl(created.url);
      setSelectedJob(created);
      setEvents([]);
      setIsManualCreateOpen(false);
      resetManualForm();
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

  async function restoreSuppressedUrl(url: string): Promise<void> {
    if (restoringSuppressionUrl) return;
    setRestoringSuppressionUrl(url);
    setSuppressionsError(null);
    try {
      await unsuppressJob(url);
      setSuppressions((current) => current.filter((item) => item.url !== url));
      jobsQueryCache.clear();
      await loadBoard({ force: true });
      const newStats = await getStats();
      setStats(newStats);
    } catch (fetchError) {
      setSuppressionsError(fetchError instanceof Error ? fetchError.message : "Failed to restore suppressed job");
    } finally {
      setRestoringSuppressionUrl(null);
    }
  }

  async function ensureStarterArtifacts(url: string): Promise<void> {
    const pollStartedAt = Date.now();
    let pollTimer: number | null = null;
    let cancelled = false;
    const poll = async (): Promise<void> => {
      if (cancelled) return;
      try {
        const status = await getStarterArtifactsStatus(url);
        if (cancelled) return;
        setArtifactStarterStatus(status);
        if (status.running) {
          pollTimer = window.setTimeout(() => void poll(), 450);
        }
      } catch {
        pollTimer = window.setTimeout(() => void poll(), 900);
      }
    };
    void poll();
    setArtifactsGenerating(true);
    setArtifactsLoading(true);
    try {
      const rows = await generateStarterArtifacts(url, false);
      setArtifactCache((current) => ({ ...current, [url]: rows }));
      setArtifactStarterStatus({
        job_url: url,
        stage: "done",
        progress_percent: 100,
        running: false,
        updated_at: new Date().toISOString(),
      });
    } finally {
      cancelled = true;
      if (pollTimer) {
        window.clearTimeout(pollTimer);
      }
      if (Date.now() - pollStartedAt > 12000) {
        setArtifactStarterStatus((current) => current ?? {
          job_url: url,
          stage: "done",
          progress_percent: 100,
          running: false,
          updated_at: new Date().toISOString(),
        });
      }
      setArtifactsGenerating(false);
      setArtifactsLoading(false);
    }
  }

  async function tailorBothArtifacts(url: string): Promise<void> {
    let rows = artifactCache[url] ?? [];
    if (rows.length === 0) {
      await ensureStarterArtifacts(url);
      rows = (artifactCache[url] ?? []).length > 0 ? (artifactCache[url] ?? []) : await getJobArtifacts(url);
      setArtifactCache((current) => ({ ...current, [url]: rows }));
    }
    const resume = rows.find((item) => item.artifact_type === "resume");
    const cover = rows.find((item) => item.artifact_type === "cover_letter");
    const targets = [resume, cover].filter(Boolean) as ArtifactSummary[];
    if (targets.length === 0) {
      toast.error("No artifacts available to tailor");
      return;
    }
    try {
      const results = await Promise.all(
        targets.map((artifact) => generateArtifactSuggestions(artifact.id, {
          prompt: "Tailor this artifact to the linked job description with concise, high-impact edits.",
          max_suggestions: 6,
        })),
      );
      const total = results.reduce((sum, current) => sum + current.length, 0);
      toast.success(`Generated ${total} suggestion(s) across resume and cover letter`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to tailor artifacts");
    }
  }

  async function onDropJob(status: string, url: string): Promise<void> {
    const nextStatus = status as TrackingStatus;
    const existing = jobs.find((job) => job.url === url);
    if (!existing || existing.status === nextStatus) {
      return;
    }

    setJobs((current) => current.map((job) => (job.url === url ? { ...job, status: nextStatus } : job)));
    try {
      await applyTrackingPatch(url, { status: nextStatus });
    } catch {
      setJobs((current) => current.map((job) => (job.url === url ? { ...job, status: existing.status } : job)));
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
  ): void {
    const params = new URLSearchParams();
    if (nextStatus !== "all") params.set("status", nextStatus);
    if (nextAts) params.set("ats", nextAts);
    if (nextCompany) params.set("company", nextCompany);
    if (nextPostedAfter) params.set("posted_after", nextPostedAfter);
    if (nextPostedBefore) params.set("posted_before", nextPostedBefore);
    setSearchParams(params, { replace: true });
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

  const activeFilterCount =
    (statusFilter !== "all" ? 1 : 0) +
    (atsFilter ? 1 : 0) +
    (companyFilter ? 1 : 0) +
    (postedAfterFilter ? 1 : 0) +
    (postedBeforeFilter ? 1 : 0);
  const activeFilterChips: Array<{ key: "status" | "ats" | "company" | "posted_after" | "posted_before"; label: string; value: string }> = [
    ...(statusFilter && statusFilter !== "all" ? [{ key: "status" as const, label: "Status", value: statusFilter.replaceAll("_", " ") }] : []),
    ...(atsFilter ? [{ key: "ats" as const, label: "ATS", value: atsFilter }] : []),
    ...(companyFilter ? [{ key: "company" as const, label: "Company", value: companyFilter }] : []),
    ...(postedAfterFilter ? [{ key: "posted_after" as const, label: "Posted after", value: postedAfterFilter }] : []),
    ...(postedBeforeFilter ? [{ key: "posted_before" as const, label: "Posted before", value: postedBeforeFilter }] : []),
  ];

  function removeFilterChip(key: "status" | "ats" | "company" | "posted_after" | "posted_before"): void {
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

  if (loading) {
    return (
      <div className="board-page">
        <div className="page-loader-shell">
          <ThemedLoader label="Loading jobs" />
        </div>
      </div>
    );
  }

  return (
    <div className="board-page board-page-refined">
      <section className="board-toolbar">
        <div>
          <h3 className="board-title">Job Application Pipeline</h3>
          <p className="board-note">Drag roles across stages, open any card for deep fit analysis, and keep execution tight.</p>
        </div>
        <div className="board-toolbar-actions">
          <section className="toolbar-band toolbar-band-controls" aria-label="Browse controls">
            <p className="toolbar-band-label">Browse</p>
            <div className="toolbar-disclose-wrap" ref={browsePanelRef}>
              <button
                type="button"
                className={`ghost-btn compact toolbar-disclose-btn ${isBrowsePanelOpen ? "open" : ""}`}
                data-icon={isBrowsePanelOpen ? "▴" : "▾"}
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
              >
                <span>Controls</span>
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
                      <button type="button" className={`ghost-btn compact filter-btn ${isFilterOpen ? "open" : ""}`} data-icon="⚲" onClick={openFilters}>
                        Filter
                        {activeFilterCount > 0 && <span className="filter-badge">{activeFilterCount}</span>}
                      </button>
                      {isFilterOpen && (
                        <div className="filter-popover">
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
                            <button type="button" className="ghost-btn compact" data-icon="⟲" onClick={clearFilters}>Clear</button>
                            <button type="button" className="primary-btn" data-icon="✓" onClick={applyFilters}>Apply</button>
                          </div>
                        </div>
                      )}
                    </div>
                    <input
                      type="search"
                      className="board-search"
                      value={searchQuery}
                      onChange={(event) => setSearchQuery(event.target.value)}
                      aria-label="Search jobs"
                    />
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
      </section>
      <ScoreRecomputeStatus />
      {activeFilterChips.length > 0 && (
        <section className="active-filters" aria-label="Active filters">
          {activeFilterChips.map((chip) => (
            <span className="active-filter-chip" key={chip.key}>
              <strong>{chip.label}:</strong> {chip.value}
              <button type="button" aria-label={`Remove ${chip.label} filter`} onClick={() => removeFilterChip(chip.key)}>
                ×
              </button>
            </span>
          ))}
        </section>
      )}

      <section className="stats-grid">
        <SpotlightSurface className="stat-card">
          <p>Total Jobs</p>
          <strong>{stats?.total_jobs ?? "-"}</strong>
        </SpotlightSurface>
        <SpotlightSurface className="stat-card">
          <p>Tracked Jobs</p>
          <strong>{stats?.tracked_jobs ?? "-"}</strong>
        </SpotlightSurface>
        <SpotlightSurface className="stat-card">
          <p>Active Pipeline</p>
          <strong>{stats?.active_pipeline ?? "-"}</strong>
        </SpotlightSurface>
        <SpotlightSurface className="stat-card">
          <p>Activity (7d)</p>
          <strong>{stats?.recent_activity_7d ?? "-"}</strong>
        </SpotlightSurface>
      </section>
      <section className="board-flow-strip" aria-label="Pipeline stage distribution">
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
              <div className="board-flow-bar" role="presentation">
                <span style={{ width: `${ratio}%` }} />
              </div>
            </article>
          );
        })}
      </section>

      {error && <div className="error-banner">{error}</div>}
      <main className="board-layout">
          <p className="board-note">
            Backlog only shows jobs posted in the last 3 weeks; all other stages show full history.
          </p>
          {viewMode === "kanban" ? (
            <Kanban
              value={kanbanColumnsState}
              onValueChange={onKanbanValueChange}
              getItemValue={(item) => item.url}
              onItemMove={onKanbanItemMove}
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
                      <header className="column-header">
                        <div className="column-header-title">
                          <span className={`column-tone tone-${column.id.replaceAll("_", "-")}`} aria-hidden="true" />
                          <div className="column-heading">
                            <h3>{column.label}</h3>
                            <p>{(grouped.get(column.id)?.length ?? 0) === 1 ? "1 role" : `${grouped.get(column.id)?.length ?? 0} roles`}</p>
                          </div>
                        </div>
                        <span className="column-count">{grouped.get(column.id)?.length ?? 0}</span>
                      </header>
                      <div className="column-items">
                        {(kanbanColumnsState[column.id] ?? []).map((job) => (
                          <KanbanItem key={job.url} value={job.url}>
                            <JobCard job={job} onSelect={setSelectedUrl} onPrefetch={prefetchJob} />
                          </KanbanItem>
                        ))}
                        {column.id === "not_applied" && (grouped.get(column.id)?.length ?? 0) > backlogVisibleCount && (
                          <button
                            type="button"
                            className="ghost-btn compact"
                            data-icon="↓"
                            onClick={() => loadMoreBacklog(grouped.get(column.id)?.length ?? 0)}
                          >
                            Load More
                          </button>
                        )}
                      </div>
                    </KanbanColumn>
                  </motion.div>
                ))}
              </KanbanBoard>
              <KanbanOverlay>
                <div className="kanban-overlay-card" />
              </KanbanOverlay>
            </Kanban>
          ) : (
            <section className="list-view">
              {filteredJobs.map((job) => (
                <article key={job.url} className="list-row">
                  <button type="button" className="list-row-main" onClick={() => setSelectedUrl(job.url)}>
                    <h4>{job.title}</h4>
                    <p>{job.company} • {job.location || "-"}</p>
                  </button>
                  <div className="list-row-meta">
                    <Badge>{(job.status ?? "not_applied").replaceAll("_", " ")}</Badge>
                    <Badge>{job.ats || "ATS"}</Badge>
                    <Badge>Posted {job.posted || "-"}</Badge>
                  </div>
                </article>
              ))}
            </section>
          )}

          <DetailDrawer
            open={Boolean(selectedUrl)}
            loading={detailLoading}
            job={selectedJob}
            profile={profile}
            events={events}
            enrichmentPending={Boolean(selectedUrl && pendingEnrichmentByUrl[selectedUrl])}
            artifacts={selectedUrl ? artifactCache[selectedUrl] ?? [] : []}
            artifactsLoading={artifactsLoading}
            artifactsGenerating={artifactsGenerating}
            artifactStarterStage={artifactStarterStatus?.stage}
            artifactStarterProgress={artifactStarterStatus?.progress_percent}
            onClose={() => setSelectedUrl(null)}
            onAddSkillToProfile={addSkillToProfile}
            onDeleteJob={removeJob}
            onSuppressJob={suppressJobFromBoard}
            onGenerateArtifacts={ensureStarterArtifacts}
            onTailorArtifacts={tailorBothArtifacts}
            onChangeTracking={async (patch) => {
              if (!selectedUrl) {
                return;
              }
              await applyTrackingPatch(selectedUrl, patch);
            }}
          />
        </main>

      {isManualCreateOpen && (
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
            className="confirm-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="manual-create-title"
            onClick={(event) => event.stopPropagation()}
          >
            <header className="confirm-modal-head">
              <h4 id="manual-create-title">Add Manual Job</h4>
            </header>
            <p className="confirm-modal-message">
              Add a job you found yourself. It will enter the same enrichment and scoring pipeline as scraped jobs.
            </p>
            <div className="drawer-grid">
              <label className="full-width">
                <span>Job URL *</span>
                <input
                  type="url"
                  value={manualForm.url}
                  onChange={(event) => setManualForm((current) => ({ ...current, url: event.target.value }))}
                  placeholder="https://company.com/careers/job/123"
                />
              </label>
              <label>
                <span>Company *</span>
                <input
                  type="text"
                  value={manualForm.company}
                  onChange={(event) => setManualForm((current) => ({ ...current, company: event.target.value }))}
                  placeholder="Company name"
                />
              </label>
              <label>
                <span>Title *</span>
                <input
                  type="text"
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
              <label className="full-width">
                <span>Description *</span>
                <textarea
                  className="manual-job-textarea"
                  value={manualForm.description}
                  onChange={(event) => setManualForm((current) => ({ ...current, description: event.target.value }))}
                  placeholder="Paste the full job description."
                />
              </label>
            </div>
            {manualError && <p className="confirm-modal-error">{manualError}</p>}
            <div className="confirm-modal-actions">
              <button
                type="button"
                className="ghost-btn compact"
                data-icon="↗"
                onClick={() => setIsManualCreateOpen(false)}
                disabled={isManualSaving}
              >
                Cancel
              </button>
              <button
                type="button"
                className="primary-btn"
                data-icon="✓"
                onClick={() => void submitManualJob()}
                disabled={isManualSaving}
              >
                {isManualSaving ? "Adding..." : "Add Job"}
              </button>
            </div>
          </section>
        </div>
      )}

      {isSuppressionPanelOpen && (
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
                  <article key={item.url} className="suppression-item">
                    <div className="suppression-copy">
                      <p>{item.company || "Unknown company"}</p>
                      <small>{item.reason || "No reason provided"}</small>
                      <code>{item.url}</code>
                    </div>
                    <button
                      type="button"
                      className="ghost-btn compact"
                      data-icon="⟲"
                      disabled={restoringSuppressionUrl === item.url}
                      onClick={() => void restoreSuppressedUrl(item.url)}
                    >
                      {restoringSuppressionUrl === item.url ? "Restoring..." : "Restore"}
                    </button>
                  </article>
                ))}
              </div>
            )}
            <div className="confirm-modal-actions">
              <button
                type="button"
                className="ghost-btn compact"
                data-icon="↩"
                onClick={() => setIsSuppressionPanelOpen(false)}
                disabled={Boolean(restoringSuppressionUrl)}
              >
                Close
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
