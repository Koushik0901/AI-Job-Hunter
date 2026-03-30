import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import {
  completeAction,
  deferAction,
  getActionQueue,
  getDailyBriefingLatest,
  getProfileInsights,
  getStats,
} from "../api";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { formatDateShort } from "../dateUtils";
import type { DailyBriefing, JobAction, ProfileInsightsResponse, StatsResponse } from "../types";

const pageEase = [0.22, 0.84, 0.24, 1] as [number, number, number, number];

const pageRevealVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.08,
      delayChildren: 0.05,
    },
  },
};

const sectionRevealVariants = {
  hidden: { opacity: 0, y: 22 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.42, ease: pageEase },
  },
};

function formatOperationalLabel(value: string | null | undefined, fallback = "Review"): string {
  if (!value) return fallback;
  return value.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function TodayPage() {
  const navigate = useNavigate();
  const [dailyBriefing, setDailyBriefing] = useState<DailyBriefing | null>(null);
  const [actionQueue, setActionQueue] = useState<JobAction[]>([]);
  const [insights, setInsights] = useState<ProfileInsightsResponse | null>(null);
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyActionId, setBusyActionId] = useState<number | null>(null);
  const actionByJobId = useMemo(() => {
    const map = new Map<string, JobAction>();
    for (const action of actionQueue) {
      if (!map.has(action.job_id)) {
        map.set(action.job_id, action);
      }
    }
    return map;
  }, [actionQueue]);

  const topNotes = useMemo(() => {
    const notes = new Set<string>();
    for (const note of dailyBriefing?.profile_gaps ?? []) {
      notes.add(note);
    }
    for (const note of dailyBriefing?.signals ?? []) {
      notes.add(note);
    }
    for (const note of insights?.suggested_profile_updates ?? []) {
      notes.add(note);
    }
    if (dailyBriefing?.quiet_day) {
      notes.add("Quiet day: keep the queue short and use the board only for real movement.");
    }
    return [...notes].slice(0, 6);
  }, [dailyBriefing, insights]);
  const operationalFacts = useMemo(() => {
    return [
      {
        label: "Active pipeline",
        value: stats?.active_pipeline ?? 0,
        note: "Live roles",
      },
      {
        label: "Tracked jobs",
        value: stats?.tracked_jobs ?? 0,
        note: "Monitored records",
      },
      {
        label: "7d activity",
        value: stats?.recent_activity_7d ?? 0,
        note: "Recent updates",
      },
    ];
  }, [stats]);

  async function loadToday(): Promise<void> {
    setLoading(true);
    setError(null);
    try {
      const [briefingData, queueData, insightsData, statsData] = await Promise.all([
        getDailyBriefingLatest(),
        getActionQueue(),
        getProfileInsights(),
        getStats(),
      ]);
      setDailyBriefing(briefingData);
      setActionQueue(queueData.items);
      setInsights(insightsData);
      setStats(statsData);
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : "Failed to load today view");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadToday();
  }, []);

  async function handleComplete(actionId: number): Promise<void> {
    setBusyActionId(actionId);
    try {
      await completeAction(actionId);
      await loadToday();
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : "Failed to complete action");
    } finally {
      setBusyActionId(null);
    }
  }

  async function handleDefer(actionId: number): Promise<void> {
    setBusyActionId(actionId);
    try {
      await deferAction(actionId, 2);
      await loadToday();
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : "Failed to defer action");
    } finally {
      setBusyActionId(null);
    }
  }

  function openBoard(jobId: string): void {
    navigate(`/board?job=${encodeURIComponent(jobId)}`);
  }

  function renderTodayTaskCard(
    item: NonNullable<DailyBriefing["apply_now"]>[number],
    tone: "must" | "follow" | "watch",
    action: JobAction | undefined,
    index: number,
  ) {
    return (
      <motion.article
        key={`${tone}-${item.job_id}-${index}`}
        className={`today-task-card today-task-card--${tone}`}
        variants={sectionRevealVariants}
      >
        <div className="today-task-card-top">
          <div className="today-task-card-copy">
            <button type="button" className="today-task-link" onClick={() => openBoard(item.job_id)}>
              <strong>{item.title ?? "Untitled role"}</strong>
              <span>{item.company ?? "Unknown company"}</span>
            </button>
            <p className="today-task-reason">{item.reason}</p>
          </div>
          <div className="today-task-meta">
            <Badge>{formatOperationalLabel(item.recommendation)}</Badge>
            {item.score != null ? <Badge>Score {Math.round(item.score)}</Badge> : null}
            {item.due_at ? <span className="today-task-when">{formatDateShort(item.due_at, "Due today")}</span> : null}
          </div>
        </div>
        <div className="today-task-actions">
          <Button type="button" size="compact" variant="default" onClick={() => openBoard(item.job_id)}>
            Open board
          </Button>
          {action ? (
            <>
              <Button
                type="button"
                size="compact"
                variant="primary"
                disabled={busyActionId === action.id}
                onClick={() => void handleComplete(action.id)}
              >
                Done
              </Button>
              <Button
                type="button"
                size="compact"
                variant="default"
                disabled={busyActionId === action.id}
                onClick={() => void handleDefer(action.id)}
              >
                Defer
              </Button>
            </>
          ) : null}
        </div>
      </motion.article>
    );
  }

  return (
    <motion.div
      className="dashboard-page today-page"
      variants={pageRevealVariants}
      initial="hidden"
      animate="visible"
    >
      <motion.section className="page-hero today-hero" variants={sectionRevealVariants}>
        <div className="today-hero-copy">
          <p className="page-kicker">Today</p>
          <h2>What needs your attention now</h2>
          <p className="page-lede">
            Use this view as the daily command center. It should tell you what to apply to, what to follow up on, and what to leave for later.
          </p>
          <div className="today-hero-summary">
            <Badge>{dailyBriefing?.brief_date ?? "Today"}</Badge>
            <p>
              {loading && !dailyBriefing
                ? "Preparing today’s briefing..."
                : dailyBriefing?.summary_line ?? "No briefing is available yet."}
            </p>
            {dailyBriefing?.telegram_sent_at ? <Badge>Telegram sent</Badge> : <Badge>Local only</Badge>}
          </div>
        </div>
        <div className="page-hero-actions today-hero-actions">
          <Button type="button" variant="default" onClick={() => navigate("/board")}>Open Board</Button>
          <Button type="button" variant="default" onClick={() => navigate("/insights")}>Open Insights</Button>
        </div>
      </motion.section>

      {error ? <div className="error-banner">{error}</div> : null}

      <motion.section className="today-grid" aria-label="Today overview" variants={sectionRevealVariants}>
        <article className="today-section today-section--must">
          <div className="today-section-head">
            <div>
              <p className="page-kicker">Must do today</p>
              <h3>{dailyBriefing?.apply_now.length ?? 0} roles</h3>
            </div>
            <Badge>Priority first</Badge>
          </div>
          <p className="today-section-note">These are the jobs worth moving on before anything else.</p>
          {dailyBriefing?.apply_now.length ? (
            <div className="today-task-list">
              {dailyBriefing.apply_now.map((item, index) => renderTodayTaskCard(item, "must", actionByJobId.get(item.job_id), index))}
            </div>
          ) : (
            <p className="empty-text tiny">No urgent applications right now.</p>
          )}
        </article>

        <article className="today-section today-section--follow">
          <div className="today-section-head">
            <div>
              <p className="page-kicker">Follow up today</p>
              <h3>{dailyBriefing?.follow_ups_due.length ?? 0} reminders</h3>
            </div>
            <Badge>Keep momentum</Badge>
          </div>
          <p className="today-section-note">Close loops that are already open so they do not age out.</p>
          {dailyBriefing?.follow_ups_due.length ? (
            <div className="today-task-list">
              {dailyBriefing.follow_ups_due.map((item, index) =>
                renderTodayTaskCard(item, "follow", actionByJobId.get(item.job_id), index),
              )}
            </div>
          ) : (
            <p className="empty-text tiny">No follow-ups due today.</p>
          )}
        </article>

        <article className="today-section today-section--watch">
          <div className="today-section-head">
            <div>
              <p className="page-kicker">Review later</p>
              <h3>{dailyBriefing?.watchlist.length ?? 0} watch items</h3>
            </div>
            <Badge>Lower urgency</Badge>
          </div>
          <p className="today-section-note">Worth reviewing, but not urgent enough to interrupt the day.</p>
          {dailyBriefing?.watchlist.length ? (
            <div className="today-task-list">
              {dailyBriefing.watchlist.map((item, index) => renderTodayTaskCard(item, "watch", actionByJobId.get(item.job_id), index))}
            </div>
          ) : (
            <p className="empty-text tiny">Nothing is waiting for a later pass.</p>
          )}
        </article>

        <article className="today-section today-section--notes">
          <div className="today-section-head">
            <div>
              <p className="page-kicker">Top notes</p>
              <h3>Operational signals</h3>
            </div>
            <Badge>{stats?.total_jobs ?? 0} total jobs</Badge>
          </div>
          <div className="today-metric-grid">
            {operationalFacts.map((item) => (
              <div key={item.label} className="today-metric-card">
                <span>{item.label}</span>
                <strong>{item.value}</strong>
                <p>{item.note}</p>
              </div>
            ))}
          </div>
          <div className="today-note-stack">
            {topNotes.length > 0 ? (
              topNotes.map((item) => (
                <span key={item} className="today-note-chip">
                  {item}
                </span>
              ))
            ) : (
              <p className="empty-text tiny">No special notes right now.</p>
            )}
          </div>
        </article>
      </motion.section>
    </motion.div>
  );
}
