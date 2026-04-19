import { useEffect, useMemo, useState, useCallback } from "react";
import { motion } from "framer-motion";
import { ArrowUpRight, Compass, Sparkles } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { addToQueue, suppressJob } from "../api";
import { useDashboardData } from "../contexts/DashboardDataContext";
import { RecommendJobCard } from "../components/RecommendJobCard";
import { Button } from "../components/ui/button";
import { useGlobalHotkeys } from "../hooks/useHotkeys";
import { fuzzySkillsMatch, normalizeSkill } from "../skillUtils";

const pageEase = [0.22, 0.84, 0.24, 1] as [number, number, number, number];

const fadeUp = {
  hidden: { opacity: 0, y: 18 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.4, ease: pageEase } },
};

const staggerContainer = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { staggerChildren: 0.07, delayChildren: 0.04 } },
};

const RANK_FILTERS = [
  { label: "All scored", min: 0 },
  { label: "Strong", min: 70 },
  { label: "Top band", min: 85 },
] as const;

function isSkillMatched(skill: string, profileSkills: string[], aliases: Record<string, string>): boolean {
  return profileSkills.some((profileSkill) => fuzzySkillsMatch(skill, profileSkill, aliases));
}

function buildGapSummary(
  jobs: ReturnType<typeof useDashboardData>["recommendedJobs"],
  profileSkills: string[],
  skillAliases: Record<string, string>,
) {
  const counts: Record<string, { jobs: number }> = {};
  const normalizedSeenByJob = new Set<string>();
  jobs.slice(0, 12).forEach((job) => {
    (job.required_skills ?? []).slice(0, 6).forEach((skill) => {
      if (isSkillMatched(skill, profileSkills, skillAliases)) return;
      const normalized = normalizeSkill(skill, skillAliases);
      if (!normalized) return;
      const seenKey = `${job.id}:${normalized}`;
      if (normalizedSeenByJob.has(seenKey)) return;
      normalizedSeenByJob.add(seenKey);
      if (!counts[normalized]) counts[normalized] = { jobs: 0 };
      counts[normalized].jobs += 1;
    });
  });
  return Object.entries(counts)
    .sort((left, right) => right[1].jobs - left[1].jobs)
    .slice(0, 4)
    .map(([skill, data]) => ({ skill, jobs: data.jobs }));
}

export function RecommendPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const {
    profile,
    recommendedJobs: jobs,
    loading: contextLoading,
    error: dataError,
    refreshData,
    skillAliases,
  } = useDashboardData();

  const [error, setError] = useState<string | null>(null);
  const [scoreThreshold, setScoreThreshold] = useState<number>(70);
  const [atsFilter, setAtsFilter] = useState<string>("all");
  const [titleMatchOnly, setTitleMatchOnly] = useState(false);
  const [hoveredJobId, setHoveredJobId] = useState<string | null>(null);

  const loading = contextLoading && jobs.length === 0;

  const openJobDetail = useCallback((jobId: string) => {
    navigate(`/jobs/${encodeURIComponent(jobId)}`, {
      state: { from: `${location.pathname}${location.search}` },
    });
  }, [location.pathname, location.search, navigate]);

  useGlobalHotkeys(
    {
      enter: () => {
        if (hoveredJobId) openJobDetail(hoveredJobId);
      },
      s: () => {
        if (hoveredJobId) {
          void addToQueue(hoveredJobId);
          toast.success("Job added to queue");
        }
      },
      r: () => {
        if (hoveredJobId) {
          void suppressJob(hoveredJobId, "Not a fit");
          toast.success("Role hidden");
          refreshData({ background: true });
        }
      },
    },
    [hoveredJobId, openJobDetail, refreshData],
  );

  const atsList = useMemo(() => {
    const set = new Set(jobs.map((j) => j.ats).filter(Boolean));
    return ["all", ...Array.from(set).sort()];
  }, [jobs]);

  const filtered = useMemo(() => {
    return jobs.filter((job) => {
      if (job.status !== "not_applied") return false;
      if (typeof job.match_score !== "number") return false;
      if ((job.match_score ?? 0) < scoreThreshold) return false;
      if (atsFilter !== "all" && job.ats !== atsFilter) return false;
      if (titleMatchOnly && !job.desired_title_match) return false;
      return true;
    });
  }, [jobs, scoreThreshold, atsFilter, titleMatchOnly]);

  const profileSkills = profile?.skills ?? [];
  const topJob = filtered[0] ?? null;
  const titleMatchCount = filtered.filter((job) => job.desired_title_match).length;
  const topBandCount = filtered.filter((job) => (job.match_score ?? 0) >= 85).length;
  const gapSummary = useMemo(
    () => buildGapSummary(filtered, profileSkills, skillAliases),
    [filtered, profileSkills, skillAliases],
  );

  useEffect(() => {
    setError(null);
  }, [scoreThreshold, atsFilter, titleMatchOnly]);

  return (
    <motion.div
      className="dashboard-page discover-page"
      variants={staggerContainer}
      initial="hidden"
      animate="visible"
    >
      <motion.section className="page-rail discover-rail" variants={fadeUp}>
        <div className="page-rail-copy">
          <p className="page-kicker">Discover</p>
          <h1 className="page-title">Curated roles worth a first serious pass</h1>
          <p className="page-caption">
            This page is for discovery only: strong opportunities you have not worked yet. Queue the good ones, then handle the real workflow in Board or Apply.
          </p>
        </div>
        <div className="page-rail-meta">
          <span className="page-meta-pill">{filtered.length} in view</span>
          <span className="page-meta-pill">{topBandCount} top band</span>
          <span className="page-meta-pill">{titleMatchCount} title matches</span>
        </div>
      </motion.section>

      <motion.section className="discover-toolbar" variants={fadeUp}>
        <div className="discover-toolbar-group">
          {RANK_FILTERS.map((filter) => (
            <button
              key={filter.label}
              type="button"
              className={`discover-filter-chip ${scoreThreshold === filter.min ? "active" : ""}`}
              onClick={() => setScoreThreshold(filter.min)}
            >
              {filter.label}
            </button>
          ))}
        </div>

        <div className="discover-toolbar-group discover-toolbar-group--controls">
          <select value={atsFilter} onChange={(e) => setAtsFilter(e.target.value)} className="discover-select">
            {atsList.map((ats) => (
              <option key={ats} value={ats}>{ats === "all" ? "All sources" : ats}</option>
            ))}
          </select>
          <label className="discover-toggle">
            <input
              type="checkbox"
              checked={titleMatchOnly}
              onChange={(e) => setTitleMatchOnly(e.target.checked)}
            />
            <span>Title match only</span>
          </label>
        </div>
      </motion.section>

      {(error || dataError) ? <div className="error-banner">{error || dataError}</div> : null}

      <motion.section className="discover-layout" variants={fadeUp}>
        <div className="discover-main">
          {loading ? (
            <div className="recommend-loading">
              <div className="recommend-loading-dot" />
              <div className="recommend-loading-dot" />
              <div className="recommend-loading-dot" />
            </div>
          ) : filtered.length === 0 ? (
            <div className="discover-empty">
              <Compass size={24} />
              <h3>No strong discovery roles in this filter</h3>
              <p>Widen the filter or update your profile targets if you want a broader intake queue.</p>
            </div>
          ) : (
            <div className="discover-feed">
              {filtered.map((job) => (
                <RecommendJobCard
                  key={job.id}
                  job={job}
                  profile={profile}
                  onView={openJobDetail}
                  onStageApplied={() => void 0}
                  onHover={setHoveredJobId}
                />
              ))}
            </div>
          )}
        </div>

        <aside className="discover-side">
          <article className="discover-side-card">
            <div className="discover-side-head">
              <div>
                <p className="page-kicker">Discovery focus</p>
                <h3>What belongs here</h3>
              </div>
            </div>
            <div className="discover-checklist">
              <p><strong>Strong fit first.</strong> Use this page to find roles worth a closer read, not to manage the active pipeline.</p>
              <p><strong>Queue the good ones.</strong> Once a role looks real, move it into Apply or Board instead of living here.</p>
              <p><strong>Keep the bar high.</strong> If a source produces weak results repeatedly, suppress faster and spend time elsewhere.</p>
            </div>
          </article>

          <article className="discover-side-card">
            <div className="discover-side-head">
              <div>
                <p className="page-kicker">Profile pressure</p>
                <h3>Skills showing up in strong roles</h3>
              </div>
            </div>
            {gapSummary.length > 0 ? (
              <div className="discover-gap-stack">
                {gapSummary.map((gap) => (
                  <div key={gap.skill} className="discover-gap-row">
                    <span>{gap.skill}</span>
                    <strong>{gap.jobs} jobs</strong>
                  </div>
                ))}
              </div>
            ) : (
              <p className="discover-copy-soft">The strongest roles in this view are already well aligned with your current skill profile.</p>
            )}
          </article>

          <article className="discover-side-card discover-side-card--accent">
            <div className="discover-side-head">
              <div>
                <p className="page-kicker">Next move</p>
                <h3>Work the top role properly</h3>
              </div>
            </div>
            {topJob ? (
              <>
                <p className="discover-copy-soft">
                  {topJob.company} — {topJob.title} is the strongest current role in this view.
                </p>
                <div className="discover-side-actions">
                  <Button type="button" variant="primary" onClick={() => openJobDetail(topJob.id)}>
                    Review role
                  </Button>
                  <Button type="button" variant="default" onClick={() => navigate("/agent")}>
                    Open Apply <ArrowUpRight size={14} />
                  </Button>
                </div>
              </>
            ) : (
              <p className="discover-copy-soft">Nothing in the current filter deserves a first serious pass yet.</p>
            )}
          </article>
        </aside>
      </motion.section>
    </motion.div>
  );
}
