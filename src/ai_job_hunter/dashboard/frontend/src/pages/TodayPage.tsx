import { useMemo, useState, useCallback, memo } from "react";
import { motion } from "framer-motion";
import { ArrowUpRight, CalendarCheck2, Clock3, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { completeAction, deferAction, refreshDailyBriefing } from "../api";
import { useDashboardData } from "../contexts/DashboardDataContext";
import { useGlobalHotkeys } from "../hooks/useHotkeys";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { formatDateShort } from "../dateUtils";
import type { DailyBriefing, JobAction } from "../types";

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
  hidden: { opacity: 0, y: 18 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.4, ease: pageEase },
  },
};

function formatOperationalLabel(value: string | null | undefined, fallback = "Review"): string {
  if (!value) return fallback;
  return value.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function buildTopNotes(
  dailyBriefing: DailyBriefing | null,
  suggestedProfileUpdates: string[] | undefined,
): string[] {
  const notes = new Set<string>();
  for (const note of dailyBriefing?.profile_gaps ?? []) notes.add(note);
  for (const note of dailyBriefing?.signals ?? []) notes.add(note);
  for (const note of suggestedProfileUpdates ?? []) notes.add(note);
  if ((dailyBriefing?.apply_now.length ?? 0) === 0 && (dailyBriefing?.follow_ups_due.length ?? 0) === 0) {
    notes.add("Quiet day. Keep the queue short and only move roles that materially change your pipeline.");
  }
  return [...notes].slice(0, 4);
}

function buildChangeSummary(briefing: DailyBriefing | null, activity7d: number): string {
  if (!briefing) {
    return "Generate a briefing to turn the current pipeline into a short, usable daily plan.";
  }
  if (briefing.quiet_day) {
    return `Pipeline is quiet today. ${activity7d} recent updates are still worth a short review pass.`;
  }
  if ((briefing.apply_now.length ?? 0) > 0) {
    return `${briefing.apply_now.length} roles are strong enough to move first today.`;
  }
  if ((briefing.follow_ups_due.length ?? 0) > 0) {
    return `${briefing.follow_ups_due.length} follow-ups are due and should be cleared before new browsing.`;
  }
  return briefing.summary_line;
}

interface TodayTaskCardProps {
  item: NonNullable<DailyBriefing["apply_now"]>[number];
  tone: "must" | "follow" | "watch";
  action: JobAction | undefined;
  busyActionId: number | null;
  onOpenBoard: (jobId: string) => void;
  onComplete: (actionId: number) => void;
  onDefer: (actionId: number) => void;
  onHover?: (jobId: string | null) => void;
}

const TodayTaskCard = memo(function TodayTaskCard({
  item,
  tone,
  action,
  busyActionId,
  onOpenBoard,
  onComplete,
  onDefer,
  onHover,
}: TodayTaskCardProps) {
  return (
    <motion.article
      className={`today-task-card today-task-card--${tone}`}
      variants={sectionRevealVariants}
      onMouseEnter={() => onHover?.(item.job_id)}
      onMouseLeave={() => onHover?.(null)}
    >
      <div className="today-task-card-top">
        <div className="today-task-card-copy">
          <span className="today-task-company">{item.company ?? "Unknown company"}</span>
          <button type="button" className="today-task-link" onClick={() => onOpenBoard(item.job_id)}>
            <strong>{item.title ?? "Untitled role"}</strong>
          </button>
          <p className="today-task-reason">{item.reason}</p>
        </div>
        <div className="today-task-meta">
          <Badge>{formatOperationalLabel(item.recommendation)}</Badge>
          {item.score != null ? <span className="today-task-score">Rank {Math.round(item.score)}</span> : null}
        </div>
      </div>
      <div className="today-task-foot">
        <div className="today-task-foot-meta">
          {item.due_at ? (
            <span className="today-task-when">
              <Clock3 size={14} />
              {formatDateShort(item.due_at, "Due today")}
            </span>
          ) : (
            <span className="today-task-when">
              <CalendarCheck2 size={14} />
              Ready when you are
            </span>
          )}
        </div>
        <div className="today-task-actions">
          <Button type="button" size="compact" variant="default" onClick={() => onOpenBoard(item.job_id)}>
            Open
          </Button>
          {action ? (
            <>
              <Button
                type="button"
                size="compact"
                variant="primary"
                disabled={busyActionId === action.id}
                onClick={() => void onComplete(action.id)}
              >
                Done
              </Button>
              <Button
                type="button"
                size="compact"
                variant="default"
                disabled={busyActionId === action.id}
                onClick={() => void onDefer(action.id)}
              >
                Later
              </Button>
            </>
          ) : null}
        </div>
      </div>
    </motion.article>
  );
});

const EmptyLane = memo(function EmptyLane({
  title,
  body,
}: {
  title: string;
  body: string;
}) {
  return (
    <div className="today-empty-lane">
      <span>{title}</span>
      <p>{body}</p>
    </div>
  );
});

const ColdStartBriefing = memo(function ColdStartBriefing({
  onGenerate,
  generating,
}: {
  onGenerate: () => void;
  generating: boolean;
}) {
  return (
    <motion.article className="today-cold-start" variants={sectionRevealVariants}>
      <div className="today-cold-start-orb">
        <Sparkles size={18} />
      </div>
      <div className="today-cold-start-copy">
        <span className="page-kicker">Daily briefing</span>
        <h3>No briefing yet</h3>
        <p>Generate the first briefing to turn your current pipeline into a short operating list.</p>
      </div>
      <Button type="button" variant="primary" disabled={generating} onClick={onGenerate}>
        {generating ? "Generating..." : "Generate briefing"}
      </Button>
    </motion.article>
  );
});

export function TodayPage() {
  const navigate = useNavigate();
  const {
    dailyBriefing,
    actionQueue,
    profileInsights,
    stats,
    loading,
    error: dataError,
    refreshData,
  } = useDashboardData();

  const [error, setError] = useState<string | null>(null);
  const [busyActionId, setBusyActionId] = useState<number | null>(null);
  const [generatingBriefing, setGeneratingBriefing] = useState(false);
  const [hoveredJobId, setHoveredJobId] = useState<string | null>(null);

  const actionByJobId = useMemo(() => {
    const map = new Map<string, JobAction>();
    for (const action of actionQueue) {
      if (!map.has(action.job_id)) map.set(action.job_id, action);
    }
    return map;
  }, [actionQueue]);

  const topNotes = useMemo(
    () => buildTopNotes(dailyBriefing, profileInsights?.suggested_profile_updates),
    [dailyBriefing, profileInsights],
  );

  const quickFacts = useMemo(
    () => [
      { label: "Active pipeline", value: stats?.active_pipeline ?? 0, note: "live roles" },
      { label: "Tracked jobs", value: stats?.tracked_jobs ?? 0, note: "current records" },
      { label: "7d activity", value: stats?.recent_activity_7d ?? 0, note: "recent movement" },
    ],
    [stats],
  );

  const changeSummary = useMemo(
    () => buildChangeSummary(dailyBriefing, stats?.recent_activity_7d ?? 0),
    [dailyBriefing, stats],
  );

  const handleComplete = useCallback(async (actionId: number): Promise<void> => {
    setBusyActionId(actionId);
    try {
      await completeAction(actionId);
      await refreshData({ background: true });
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : "Failed to complete action");
    } finally {
      setBusyActionId(null);
    }
  }, [refreshData]);

  const handleDefer = useCallback(async (actionId: number): Promise<void> => {
    setBusyActionId(actionId);
    try {
      await deferAction(actionId, 2);
      await refreshData({ background: true });
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : "Failed to defer action");
    } finally {
      setBusyActionId(null);
    }
  }, [refreshData]);

  const handleGenerateBriefing = useCallback(async (): Promise<void> => {
    setGeneratingBriefing(true);
    setError(null);
    try {
      await refreshDailyBriefing();
      await refreshData({ force: true });
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : "Failed to generate briefing");
    } finally {
      setGeneratingBriefing(false);
    }
  }, [refreshData]);

  const openBoard = useCallback((jobId: string): void => {
    navigate("/board", { state: { focusJobId: jobId } });
  }, [navigate]);

  useGlobalHotkeys(
    {
      d: () => {
        if (hoveredJobId) {
          const action = actionByJobId.get(hoveredJobId);
          if (action) {
            void handleComplete(action.id);
            toast.success("Action marked as done");
          }
        }
      },
      f: () => {
        if (hoveredJobId) {
          const action = actionByJobId.get(hoveredJobId);
          if (action) {
            void handleDefer(action.id);
            toast.success("Action deferred");
          }
        }
      },
      enter: () => {
        if (hoveredJobId) openBoard(hoveredJobId);
      },
    },
    [hoveredJobId, actionByJobId, handleComplete, handleDefer, openBoard],
  );

  return (
    <motion.div
      className="dashboard-page today-page today-page-refined"
      variants={pageRevealVariants}
      initial="hidden"
      animate="visible"
    >
      <motion.section className="page-rail today-rail" variants={sectionRevealVariants}>
        <div className="page-rail-copy">
          <p className="page-kicker">Today</p>
          <h1 className="page-title">Daily operating brief</h1>
          <p className="page-caption">{changeSummary}</p>
        </div>
        <div className="page-rail-actions">
          <Button type="button" variant="primary" disabled={generatingBriefing} onClick={() => void handleGenerateBriefing()}>
            {generatingBriefing ? "Generating..." : "Refresh briefing"}
          </Button>
          <Button type="button" variant="default" onClick={() => navigate("/board")}>Open board</Button>
        </div>
      </motion.section>

      {(error || dataError) ? <div className="error-banner">{error || dataError}</div> : null}

      {!dailyBriefing && !loading ? (
        <ColdStartBriefing onGenerate={() => void handleGenerateBriefing()} generating={generatingBriefing} />
      ) : (
        <>
          <motion.section className="today-brief-panel" variants={sectionRevealVariants}>
            <div className="today-brief-panel-copy">
              <span className="today-brief-date">{dailyBriefing?.brief_date ?? "Today"}</span>
              <p>{dailyBriefing?.summary_line ?? "Loading the latest guidance for today."}</p>
            </div>
            <div className="today-brief-panel-meta">
              <Badge>{dailyBriefing?.quiet_day ? "Quiet day" : "Action day"}</Badge>
              {dailyBriefing?.telegram_sent_at ? <Badge>Telegram sent</Badge> : null}
            </div>
          </motion.section>

          <motion.section className="today-layout" variants={sectionRevealVariants}>
            <div className="today-main-column">
              <article className="today-surface today-surface--must">
                <div className="today-surface-head">
                  <div>
                    <p className="page-kicker">Must do now</p>
                    <h2>{dailyBriefing?.apply_now.length ?? 0} roles</h2>
                  </div>
                  <Badge>Priority</Badge>
                </div>
                {(dailyBriefing?.apply_now.length ?? 0) > 0 ? (
                  <div className="today-task-list">
                    {dailyBriefing?.apply_now.map((item, index) => (
                      <TodayTaskCard
                        key={`must-${item.job_id}-${index}`}
                        item={item}
                        tone="must"
                        action={actionByJobId.get(item.job_id)}
                        busyActionId={busyActionId}
                        onOpenBoard={openBoard}
                        onComplete={handleComplete}
                        onDefer={handleDefer}
                        onHover={setHoveredJobId}
                      />
                    ))}
                  </div>
                ) : (
                  <EmptyLane
                    title="Nothing urgent"
                    body="No role is strong enough to interrupt the day. Keep the queue short and only move jobs that materially change the pipeline."
                  />
                )}
              </article>
            </div>

            <div className="today-side-column">
              <article className="today-surface">
                <div className="today-surface-head">
                  <div>
                    <p className="page-kicker">Follow up</p>
                    <h3>{dailyBriefing?.follow_ups_due.length ?? 0} due today</h3>
                  </div>
                </div>
                {(dailyBriefing?.follow_ups_due.length ?? 0) > 0 ? (
                  <div className="today-task-list">
                    {dailyBriefing?.follow_ups_due.map((item, index) => (
                      <TodayTaskCard
                        key={`follow-${item.job_id}-${index}`}
                        item={item}
                        tone="follow"
                        action={actionByJobId.get(item.job_id)}
                        busyActionId={busyActionId}
                        onOpenBoard={openBoard}
                        onComplete={handleComplete}
                        onDefer={handleDefer}
                        onHover={setHoveredJobId}
                      />
                    ))}
                  </div>
                ) : (
                  <EmptyLane title="No follow-ups due" body="Your open loops are under control. Use the Board only if you need to move a role forward deliberately." />
                )}
              </article>

              <article className="today-surface">
                <div className="today-surface-head">
                  <div>
                    <p className="page-kicker">Review later</p>
                    <h3>{dailyBriefing?.watchlist.length ?? 0} lower urgency roles</h3>
                  </div>
                </div>
                {(dailyBriefing?.watchlist.length ?? 0) > 0 ? (
                  <div className="today-task-list">
                    {dailyBriefing?.watchlist.map((item, index) => (
                      <TodayTaskCard
                        key={`watch-${item.job_id}-${index}`}
                        item={item}
                        tone="watch"
                        action={actionByJobId.get(item.job_id)}
                        busyActionId={busyActionId}
                        onOpenBoard={openBoard}
                        onComplete={handleComplete}
                        onDefer={handleDefer}
                        onHover={setHoveredJobId}
                      />
                    ))}
                  </div>
                ) : (
                  <EmptyLane title="Nothing waiting" body="There are no lower-priority roles competing for attention right now." />
                )}
              </article>

              <article className="today-surface today-surface--notes">
                <div className="today-surface-head">
                  <div>
                    <p className="page-kicker">Signals</p>
                    <h3>What changed</h3>
                  </div>
                  <Button type="button" size="compact" variant="default" onClick={() => navigate("/insights")}>
                    Strategy <ArrowUpRight size={14} />
                  </Button>
                </div>
                <div className="today-fact-row">
                  {quickFacts.map((item) => (
                    <div key={item.label} className="today-fact-chip">
                      <span>{item.label}</span>
                      <strong className="tabular-nums">{item.value}</strong>
                      <small>{item.note}</small>
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
                    <EmptyLane title="No unusual signals" body="The pipeline is stable. Let the current queue dictate the day instead of expanding the search." />
                  )}
                </div>
              </article>
            </div>
          </motion.section>
        </>
      )}
    </motion.div>
  );
}
