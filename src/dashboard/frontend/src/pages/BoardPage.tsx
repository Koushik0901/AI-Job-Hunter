import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { deleteJob, getJobDetail, getJobEvents, getJobsWithParams, getProfile, getStats, patchTracking, putProfile } from "../api";
import { DetailDrawer } from "../components/DetailDrawer";
import { JobCard } from "../components/JobCard";
import { KanbanColumn } from "../components/KanbanColumn";
import { ThemedLoader } from "../components/ThemedLoader";
import { ThemedSelect } from "../components/ThemedSelect";
import { SpotlightSurface } from "../components/reactbits/SpotlightSurface";
import type { CandidateProfile, JobDetail, JobEvent, JobSummary, StatsResponse, TrackingPatchRequest, TrackingStatus } from "../types";

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

const PAGE_SIZE = 25;
const BACKLOG_MAX_AGE_DAYS = 21;
const BOARD_CACHE_TTL_MS = 3 * 60 * 1000;

type BoardView = "kanban" | "list";
type SortOption = "match_desc" | "posted_desc" | "updated_desc" | "company_asc";

type BoardPageCache = {
  jobs: JobSummary[];
  stats: StatsResponse | null;
  profile: CandidateProfile | null;
  detailCache: Record<string, JobDetail>;
  eventsCache: Record<string, JobEvent[]>;
  searchQuery: string;
  viewMode: BoardView;
  sortOption: SortOption;
  statusFilter: TrackingStatus | "all";
  atsFilter: string;
  companyFilter: string;
  columnVisibleCount: Record<TrackingStatus, number>;
  fetchedAt: number;
  queryKey: string;
};

let boardPageCache: BoardPageCache | null = null;

function buildQueryKey(sort: SortOption, status: TrackingStatus | "all", ats: string, company: string): string {
  return `${sort}|${status}|${ats.trim().toLowerCase()}|${company.trim().toLowerCase()}`;
}

function createInitialColumnVisibleCount(): Record<TrackingStatus, number> {
  return {
    not_applied: PAGE_SIZE,
    staging: PAGE_SIZE,
    applied: PAGE_SIZE,
    interviewing: PAGE_SIZE,
    offer: PAGE_SIZE,
    rejected: PAGE_SIZE,
  };
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

export function BoardPage() {
  const now = Date.now();
  const hasFreshCache =
    boardPageCache !== null &&
    now - boardPageCache.fetchedAt < BOARD_CACHE_TTL_MS &&
    boardPageCache.queryKey ===
      buildQueryKey(boardPageCache.sortOption, boardPageCache.statusFilter, boardPageCache.atsFilter, boardPageCache.companyFilter);

  const [jobs, setJobs] = useState<JobSummary[]>(() => (hasFreshCache ? boardPageCache?.jobs ?? [] : []));
  const [stats, setStats] = useState<StatsResponse | null>(() => (hasFreshCache ? boardPageCache?.stats ?? null : null));
  const [profile, setProfile] = useState<CandidateProfile | null>(() => (hasFreshCache ? boardPageCache?.profile ?? null : null));
  const [selectedUrl, setSelectedUrl] = useState<string | null>(null);
  const [selectedJob, setSelectedJob] = useState<JobDetail | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailCache, setDetailCache] = useState<Record<string, JobDetail>>(() => (hasFreshCache ? boardPageCache?.detailCache ?? {} : {}));
  const [eventsCache, setEventsCache] = useState<Record<string, JobEvent[]>>(() => (hasFreshCache ? boardPageCache?.eventsCache ?? {} : {}));
  const [activeDrop, setActiveDrop] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(() => !hasFreshCache);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState(() => (hasFreshCache ? boardPageCache?.searchQuery ?? "" : ""));
  const [viewMode, setViewMode] = useState<BoardView>(() => (hasFreshCache ? boardPageCache?.viewMode ?? "kanban" : "kanban"));
  const [sortOption, setSortOption] = useState<SortOption>(() => (hasFreshCache ? boardPageCache?.sortOption ?? "match_desc" : "match_desc"));
  const [statusFilter, setStatusFilter] = useState<TrackingStatus | "all">(() => (hasFreshCache ? boardPageCache?.statusFilter ?? "all" : "all"));
  const [atsFilter, setAtsFilter] = useState(() => (hasFreshCache ? boardPageCache?.atsFilter ?? "" : ""));
  const [companyFilter, setCompanyFilter] = useState(() => (hasFreshCache ? boardPageCache?.companyFilter ?? "" : ""));
  const [isFilterOpen, setIsFilterOpen] = useState(false);
  const [draftStatusFilter, setDraftStatusFilter] = useState<TrackingStatus | "all">(() => (hasFreshCache ? boardPageCache?.statusFilter ?? "all" : "all"));
  const [draftAtsFilter, setDraftAtsFilter] = useState(() => (hasFreshCache ? boardPageCache?.atsFilter ?? "" : ""));
  const [draftCompanyFilter, setDraftCompanyFilter] = useState(() => (hasFreshCache ? boardPageCache?.companyFilter ?? "" : ""));
  const detailInflightRef = useRef(new Set<string>());
  const eventsInflightRef = useRef(new Set<string>());
  const filterPanelRef = useRef<HTMLDivElement | null>(null);
  const [columnVisibleCount, setColumnVisibleCount] = useState<Record<TrackingStatus, number>>(
    () => (hasFreshCache ? boardPageCache?.columnVisibleCount ?? createInitialColumnVisibleCount() : createInitialColumnVisibleCount()),
  );
  const lastFetchedAtRef = useRef<number>(hasFreshCache ? boardPageCache?.fetchedAt ?? 0 : 0);

  const queryKey = buildQueryKey(sortOption, statusFilter, atsFilter, companyFilter);

  async function loadBoard(): Promise<void> {
    setLoading(true);
    setError(null);
    try {
      const [jobsData, statsData] = await Promise.all([
        getJobsWithParams({
          sort: sortOption,
          status: statusFilter,
          ats: atsFilter,
          company: companyFilter,
        }),
        getStats(),
      ]);
      setJobs(jobsData.items);
      setStats(statsData);
      lastFetchedAtRef.current = Date.now();
      try {
        const profileData = await getProfile();
        setProfile(profileData);
      } catch {
        setProfile(null);
      }
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (
      boardPageCache &&
      boardPageCache.queryKey === queryKey &&
      Date.now() - boardPageCache.fetchedAt < BOARD_CACHE_TTL_MS
    ) {
      setLoading(false);
      return;
    }
    void loadBoard();
  }, [queryKey]);

  useEffect(() => {
    boardPageCache = {
      jobs,
      stats,
      profile,
      detailCache,
      eventsCache,
      searchQuery,
      viewMode,
      sortOption,
      statusFilter,
      atsFilter,
      companyFilter,
      columnVisibleCount,
      fetchedAt: lastFetchedAtRef.current,
      queryKey,
    };
  }, [
    jobs,
    stats,
    profile,
    detailCache,
    eventsCache,
    searchQuery,
    viewMode,
    sortOption,
    statusFilter,
    atsFilter,
    companyFilter,
    columnVisibleCount,
    queryKey,
  ]);

  useEffect(() => {
    if (!isFilterOpen) {
      return;
    }
    function onDocumentMouseDown(event: MouseEvent): void {
      if (!filterPanelRef.current) {
        return;
      }
      if (!filterPanelRef.current.contains(event.target as Node)) {
        setIsFilterOpen(false);
      }
    }
    window.addEventListener("mousedown", onDocumentMouseDown);
    return () => window.removeEventListener("mousedown", onDocumentMouseDown);
  }, [isFilterOpen]);

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

  async function prefetchJobDetail(url: string): Promise<void> {
    if (detailCache[url] || detailInflightRef.current.has(url)) {
      return;
    }
    detailInflightRef.current.add(url);
    try {
      const detail = await getJobDetail(url);
      setDetailCache((current) => (current[url] ? current : { ...current, [url]: detail }));
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

  useEffect(() => {
    if (jobs.length === 0) return;
    jobs.slice(0, 10).forEach((job) => {
      void prefetchJobDetail(job.url);
    });
  }, [jobs]);

  const filteredJobs = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) {
      return jobs;
    }
    return jobs.filter((job) => {
      const haystack = `${job.title} ${job.company} ${job.location}`.toLowerCase();
      return haystack.includes(query);
    });
  }, [jobs, searchQuery]);

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

    const newStats = await getStats();
    setStats(newStats);
  }

  async function addSkillToProfile(skill: string): Promise<void> {
    if (!profile) {
      throw new Error("Profile unavailable");
    }
    const incoming = skill.trim();
    if (!incoming) {
      return;
    }
    const existing = new Set((profile.skills ?? []).map((item) => normalizeSkill(item)));
    if (existing.has(normalizeSkill(incoming))) {
      return;
    }
    const optimistic: CandidateProfile = {
      ...profile,
      skills: [...profile.skills, incoming],
    };
    setProfile(optimistic);
    try {
      const saved = await putProfile(optimistic);
      setProfile(saved);
    } catch (error) {
      setProfile(profile);
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
    if (selectedUrl === url) {
      setSelectedUrl(null);
      setSelectedJob(null);
      setEvents([]);
    }

    void deleteJob(url)
      .then(async () => {
        const newStats = await getStats();
        setStats(newStats);
      })
      .catch((err) => {
        setJobs((current) => [removedJob, ...current]);
        setError(err instanceof Error ? err.message : "Failed to delete job");
      });
  }

  async function onDropJob(status: string, url: string): Promise<void> {
    setActiveDrop(null);
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

  function loadMoreForColumn(status: TrackingStatus): void {
    setColumnVisibleCount((current) => ({
      ...current,
      [status]: current[status] + PAGE_SIZE,
    }));
  }

  function openFilters(): void {
    setDraftStatusFilter(statusFilter);
    setDraftAtsFilter(atsFilter);
    setDraftCompanyFilter(companyFilter);
    setIsFilterOpen((current) => !current);
  }

  function applyFilters(): void {
    setStatusFilter(draftStatusFilter);
    setAtsFilter(draftAtsFilter.trim());
    setCompanyFilter(draftCompanyFilter.trim());
    setIsFilterOpen(false);
  }

  function clearFilters(): void {
    setStatusFilter("all");
    setAtsFilter("");
    setCompanyFilter("");
    setDraftStatusFilter("all");
    setDraftAtsFilter("");
    setDraftCompanyFilter("");
    setIsFilterOpen(false);
  }

  const activeFilterCount =
    (statusFilter !== "all" ? 1 : 0) +
    (atsFilter ? 1 : 0) +
    (companyFilter ? 1 : 0);
  const activeFilterChips: Array<{ key: "status" | "ats" | "company"; label: string; value: string }> = [
    ...(statusFilter !== "all" ? [{ key: "status" as const, label: "Status", value: statusFilter.replaceAll("_", " ") }] : []),
    ...(atsFilter ? [{ key: "ats" as const, label: "ATS", value: atsFilter }] : []),
    ...(companyFilter ? [{ key: "company" as const, label: "Company", value: companyFilter }] : []),
  ];

  function removeFilterChip(key: "status" | "ats" | "company"): void {
    if (key === "status") {
      setStatusFilter("all");
      setDraftStatusFilter("all");
      return;
    }
    if (key === "ats") {
      setAtsFilter("");
      setDraftAtsFilter("");
      return;
    }
    setCompanyFilter("");
    setDraftCompanyFilter("");
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
    <div className="board-page">
      <section className="board-toolbar">
        <div>
          <h3 className="board-title">Job Application Pipeline</h3>
        </div>
        <div className="board-toolbar-actions">
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
            <button type="button" className={`ghost-btn compact filter-btn ${isFilterOpen ? "open" : ""}`} onClick={openFilters}>
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
                </div>
                <div className="filter-actions">
                  <button type="button" className="ghost-btn compact" onClick={clearFilters}>Clear</button>
                  <button type="button" className="primary-btn" onClick={applyFilters}>Apply</button>
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
          <button type="button" onClick={() => void loadBoard()} className="primary-btn">Refresh</button>
        </div>
      </section>
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

      {error && <div className="error-banner">{error}</div>}
      <main className="board-layout">
          <p className="board-note">
            Backlog only shows jobs posted in the last 3 weeks; all other stages show full history.
          </p>
          {viewMode === "kanban" ? (
            <section className="kanban-board">
              {STATUS_COLUMNS.map((column, index) => (
                <motion.div
                  initial={{ opacity: 0, y: 24 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.04 * index }}
                  key={column.id}
                  onDragEnter={() => setActiveDrop(column.id)}
                >
                  <KanbanColumn
                    id={column.id}
                    label={column.label}
                    count={grouped.get(column.id)?.length ?? 0}
                    isActiveDrop={activeDrop === column.id}
                    onDropJob={(status, url) => void onDropJob(status, url)}
                    hasMore={(grouped.get(column.id)?.length ?? 0) > columnVisibleCount[column.id]}
                    onLoadMore={() => loadMoreForColumn(column.id)}
                  >
                    {(grouped.get(column.id) ?? []).slice(0, columnVisibleCount[column.id]).map((job) => (
                      <JobCard key={job.url} job={job} onSelect={setSelectedUrl} onPrefetch={prefetchJob} />
                    ))}
                  </KanbanColumn>
                </motion.div>
              ))}
            </section>
          ) : (
            <section className="list-view">
              {filteredJobs.map((job) => (
                <article key={job.url} className="list-row">
                  <button type="button" className="list-row-main" onClick={() => setSelectedUrl(job.url)}>
                    <h4>{job.title}</h4>
                    <p>{job.company} • {job.location || "-"}</p>
                  </button>
                  <div className="list-row-meta">
                    <span className="soft-chip">{job.status.replaceAll("_", " ")}</span>
                    <span className="soft-chip">{job.ats || "ATS"}</span>
                    <span className="soft-chip">Posted {job.posted || "-"}</span>
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
            onClose={() => setSelectedUrl(null)}
            onAddSkillToProfile={addSkillToProfile}
            onDeleteJob={removeJob}
            onChangeTracking={async (patch) => {
              if (!selectedUrl) {
                return;
              }
              await applyTrackingPatch(selectedUrl, patch);
            }}
          />
        </main>
    </div>
  );
}
