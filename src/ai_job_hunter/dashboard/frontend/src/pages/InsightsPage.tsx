import { useEffect, useMemo, useRef, useState, memo } from "react";
import { motion } from "framer-motion";
import { ArrowUpRight, TrendingUp, TriangleAlert } from "lucide-react";
import { agentChat, getJobsWithParams } from "../api";
import { useDashboardData } from "../contexts/DashboardDataContext";
import type {
  JobSummary,
  StatsResponse,
  ConversionResponse,
  ProfileGapsResponse,
  SourceQualityResponse,
} from "../types";

const ease = [0.22, 0.84, 0.24, 1] as [number, number, number, number];
const stagger = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { staggerChildren: 0.07, delayChildren: 0.04 } },
};
const fadeUp = {
  hidden: { opacity: 0, y: 18 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.38, ease } },
};

function clamp(n: number, lo = 0, hi = 100) {
  return Math.max(lo, Math.min(hi, n));
}

function buildChangeNextList({
  conversion,
  sourceQuality,
  profileGaps,
  stats,
}: {
  conversion: ConversionResponse | null;
  sourceQuality: SourceQualityResponse | null;
  profileGaps: ProfileGapsResponse | null;
  stats: StatsResponse | null;
}): string[] {
  const notes: string[] = [];
  const weakRoleFamilies = (conversion?.by_role_family ?? [])
    .filter((item) => item.applied >= 2 && item.responses === 0)
    .slice(0, 2);
  const bestSource = (sourceQuality?.items ?? [])
    .filter((item) => item.applied > 0)
    .sort((a, b) => b.quality_score - a.quality_score)[0];
  const weakSource = (sourceQuality?.items ?? [])
    .filter((item) => item.applied >= 2)
    .sort((a, b) => a.quality_score - b.quality_score)[0];
  const topGap = (profileGaps?.items ?? []).find((item) => item.kind === "skill_gap");

  if ((stats?.overdue_staging_count ?? 0) > 0) {
    notes.push(`Clear ${stats?.overdue_staging_count} overdue staging roles before expanding your search.`); 
  }
  if (bestSource) {
    notes.push(`${bestSource.ats} is producing the best outcomes. Keep feeding it before widening to weaker sources.`);
  }
  if (weakSource && weakSource !== bestSource) {
    notes.push(`${weakSource.ats} is underperforming after ${weakSource.applied} applications. Tighten your bar there or reduce time spent on it.`);
  }
  if (topGap) {
    notes.push(`${topGap.label} is still the clearest blocker in strong roles. Update your profile before chasing more similar listings.`);
  }
  if (weakRoleFamilies.length > 0) {
    notes.push(`You are spending effort on ${weakRoleFamilies.map((item) => item.key).join(" and ")} without replies. Tighten targeting there.`);
  }

  if (notes.length === 0) {
    notes.push("Your search is relatively balanced. Keep the pipeline moving and use this page for weekly course correction.");
  }

  return notes.slice(0, 4);
}

const HBar = memo(function HBar({ pct, color = "var(--accent)" }: { pct: number; color?: string }) {
  return (
    <div className="insights-hbar-track">
      <div className="insights-hbar-fill" style={{ width: `${clamp(pct)}%`, background: color }} />
    </div>
  );
});

const FunnelChart = memo(function FunnelChart({ byStatus }: { byStatus: Record<string, number> }) {
  const stages = [
    { key: "staging", label: "Staging", color: "#7c3aed" },
    { key: "applied", label: "Applied", color: "#0058be" },
    { key: "interviewing", label: "Interviewing", color: "#0891b2" },
    { key: "offer", label: "Offer", color: "#16a34a" },
  ];
  const values = stages.map((stage) => byStatus[stage.key] ?? 0);
  const maxVal = Math.max(...values, 1);

  return (
    <div className="insights-funnel">
      {stages.map((stage, index) => {
        const value = values[index];
        const pct = (value / maxVal) * 100;
        const prev = index === 0 ? null : values[index - 1];
        const conversion = prev && prev > 0 ? Math.round((value / prev) * 100) : null;

        return (
          <div key={stage.key} className="insights-funnel-stage">
            <div className="insights-funnel-label-row">
              <span className="insights-funnel-label">{stage.label}</span>
              <span className="insights-funnel-count" style={{ color: stage.color }}>{value}</span>
              {conversion !== null ? <span className="insights-funnel-rate">{conversion}% from previous stage</span> : null}
            </div>
            <div className="insights-funnel-bar-wrap">
              <motion.div
                className="insights-funnel-fill"
                initial={{ width: 0 }}
                animate={{ width: `${pct}%` }}
                transition={{ duration: 0.72, ease }}
                style={{ background: stage.color }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
});

const ScoreHistogram = memo(function ScoreHistogram({ jobs }: { jobs: JobSummary[] }) {
  const buckets = [
    { label: "90+", min: 90, max: 100, color: "#16a34a" },
    { label: "80s", min: 80, max: 89, color: "#0ea5e9" },
    { label: "70s", min: 70, max: 79, color: "var(--accent)" },
    { label: "60s", min: 60, max: 69, color: "#f59e0b" },
    { label: "<60", min: Number.NEGATIVE_INFINITY, max: 59, color: "#f97316" },
  ].map((bucket) => ({
    ...bucket,
    count: jobs.filter((job) => {
      const score = job.match_score;
      return typeof score === "number" && score >= bucket.min && score <= bucket.max;
    }).length,
  }));

  const maxCount = Math.max(...buckets.map((bucket) => bucket.count), 1);
  const total = buckets.reduce((sum, bucket) => sum + bucket.count, 0);

  if (total === 0) {
    return <p className="insights-empty-note">Match-score visuals appear once jobs have been scored.</p>;
  }

  return (
    <div className="insights-histogram" aria-label="Match score distribution">
      {buckets.map((bucket) => {
        const height = Math.max(8, (bucket.count / maxCount) * 100);
        return (
          <div key={bucket.label} className="insights-histogram-col" title={`${bucket.label}: ${bucket.count} jobs`}>
            <span className="insights-histogram-count">{bucket.count}</span>
            <div className="insights-histogram-bar-wrap">
              <motion.div
                className="insights-histogram-bar"
                initial={{ height: 0 }}
                animate={{ height: `${height}%` }}
                transition={{ duration: 0.68, ease }}
                style={{ background: bucket.color }}
              />
            </div>
            <span className="insights-histogram-label">{bucket.label}</span>
          </div>
        );
      })}
    </div>
  );
});

const PipelineDonut = memo(function PipelineDonut({ byStatus }: { byStatus: Record<string, number> }) {
  const segments = [
    { key: "staging", label: "Staging", value: byStatus.staging ?? 0, color: "#7c3aed" },
    { key: "applied", label: "Applied", value: byStatus.applied ?? 0, color: "#0058be" },
    { key: "interviewing", label: "Interviewing", value: byStatus.interviewing ?? 0, color: "#0891b2" },
    { key: "offer", label: "Offer", value: byStatus.offer ?? 0, color: "#16a34a" },
    { key: "rejected", label: "Rejected", value: byStatus.rejected ?? 0, color: "#f97316" },
  ].filter((segment) => segment.value > 0);

  const total = segments.reduce((sum, segment) => sum + segment.value, 0);

  if (total === 0) {
    return <p className="insights-donut-empty">Tracked roles will appear here once the pipeline starts moving.</p>;
  }

  const radius = 52;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;

  return (
    <div className="insights-donut-wrap">
      <div className="insights-donut-container">
        <svg viewBox="0 0 140 140" className="insights-donut-svg" role="img" aria-label="Tracked pipeline mix">
          <circle cx="70" cy="70" r={radius} className="insights-donut-ring-bg" />
          {segments.map((segment) => {
            const segmentLength = (segment.value / total) * circumference;
            const strokeDashoffset = -offset;
            offset += segmentLength;

            return (
              <motion.circle
                key={segment.key}
                cx="70"
                cy="70"
                r={radius}
                fill="none"
                stroke={segment.color}
                strokeWidth="14"
                strokeLinecap="round"
                className="insights-donut-segment"
                transform="rotate(-90 70 70)"
                initial={{ strokeDasharray: `0 ${circumference}` }}
                animate={{ strokeDasharray: `${segmentLength} ${circumference - segmentLength}`, strokeDashoffset }}
                transition={{ duration: 0.8, ease }}
              />
            );
          })}
        </svg>
        <div className="insights-donut-center">
          <strong className="insights-donut-center-value">{total}</strong>
          <span className="insights-donut-center-label">tracked</span>
        </div>
      </div>
      <div className="insights-donut-legend">
        {segments.map((segment) => {
          const pct = Math.round((segment.value / total) * 100);
          return (
            <div key={segment.key} className="insights-donut-legend-item">
              <span className="insights-donut-dot" style={{ background: segment.color }} />
              <span className="insights-donut-legend-label">{segment.label}</span>
              <span className="insights-donut-legend-count">{segment.value} · {pct}%</span>
            </div>
          );
        })}
      </div>
    </div>
  );
});

const StrategyCoachCard = memo(function StrategyCoachCard({
  stats,
  conversion,
  profileGaps,
  sourceQuality,
  avgScore,
}: {
  stats: StatsResponse | null;
  conversion: ConversionResponse | null;
  profileGaps: ProfileGapsResponse | null;
  sourceQuality: SourceQualityResponse | null;
  avgScore: number | null;
}) {
  const [advice, setAdvice] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  async function generate() {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true);
    setAdvice(null);

    const topGaps = (profileGaps?.items ?? []).slice(0, 4).map((g) => `${g.label} (${g.count})`).join(", ") || "none";
    const topSource = (sourceQuality?.items ?? []).sort((a, b) => b.quality_score - a.quality_score)[0];
    const weakRole = (conversion?.by_role_family ?? []).filter((r) => r.applied >= 2 && r.responses === 0)[0];

    const prompt = `You are a calm but blunt search strategist. Give 3 short bullets only. Use "•" bullets. Explain what this candidate should change next based on the following data.

- active pipeline: ${stats?.active_pipeline ?? 0}
- overdue staging: ${stats?.overdue_staging_count ?? 0}
- applied: ${conversion?.overall.applied ?? 0}
- responses: ${conversion?.overall.responses ?? 0}
- interviews: ${conversion?.overall.interviews ?? 0}
- average rank score: ${avgScore ?? "unknown"}
- strongest source: ${topSource ? `${topSource.ats} (${Math.round(topSource.quality_score)}/100)` : "none"}
- biggest profile gaps: ${topGaps}
- weakest role family: ${weakRole ? weakRole.key : "none"}

Focus on action, not encouragement.`;

    try {
      const data = await agentChat([{ role: "user", content: prompt }]);
      if (!ctrl.signal.aborted) setAdvice(data.reply);
    } catch {
      if (!ctrl.signal.aborted) setAdvice("Could not generate strategy notes right now.");
    } finally {
      if (!ctrl.signal.aborted) setLoading(false);
    }
  }

  useEffect(() => () => abortRef.current?.abort(), []);

  return (
    <article className="strategy-surface strategy-surface--coach">
      <div className="strategy-surface-head">
        <div>
          <p className="page-kicker">AI strategy note</p>
          <h3>What to change next</h3>
        </div>
        <button type="button" className="strategy-ghost-btn" onClick={generate} disabled={loading}>
          {loading ? "Thinking..." : advice ? "Refresh" : "Generate"}
        </button>
      </div>
      {advice ? (
        <div className="strategy-note-list">
          {advice.split("\n").filter(Boolean).map((line, index) => (
            <p key={index} className={line.trim().startsWith("•") ? "strategy-note-item" : "strategy-note-copy"}>
              {line}
            </p>
          ))}
        </div>
      ) : (
        <p className="strategy-copy-soft">
          Generate a short strategy pass when you want the system to interpret conversion, source quality, and blockers together.
        </p>
      )}
    </article>
  );
});

export function InsightsPage() {
  const {
    stats,
    conversion,
    sourceQuality,
    profileGaps,
    profileInsights,
    loading: contextLoading,
    error: dataError,
  } = useDashboardData();

  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    getJobsWithParams({ limit: 200 })
      .then((jl) => setJobs(jl.items))
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load strategy view"))
      .finally(() => setLoading(false));
  }, []);

  const isInitialLoading = (loading && jobs.length === 0) || (contextLoading && !stats);
  const byStatus = stats?.by_status ?? {};
  const trackedTotal = Object.entries(byStatus)
    .filter(([k]) => k !== "not_applied")
    .reduce((sum, [, value]) => sum + value, 0);
  const scoredJobs = jobs.filter((job) => typeof job.match_score === "number");
  const avgRankScore = scoredJobs.length
    ? Math.round(scoredJobs.reduce((sum, job) => sum + (job.match_score ?? 0), 0) / scoredJobs.length)
    : null;
  const responseRate = conversion?.overall.applied
    ? Math.round((conversion.overall.responses / conversion.overall.applied) * 100)
    : null;
  const bestSource = (sourceQuality?.items ?? [])
    .filter((item) => item.applied > 0)
    .sort((a, b) => b.quality_score - a.quality_score)[0];
  const weakSource = (sourceQuality?.items ?? [])
    .filter((item) => item.applied >= 2)
    .sort((a, b) => a.quality_score - b.quality_score)[0];
  const topGap = (profileGaps?.items ?? []).find((item) => item.kind === "skill_gap");
  const topSources = (sourceQuality?.items ?? []).filter((item) => item.applied > 0).sort((a, b) => b.applied - a.applied).slice(0, 5);
  const topSourceMax = Math.max(...topSources.map((item) => item.applied), 1);
  const roleFamilies = (conversion?.by_role_family ?? []).filter((item) => item.applied > 0).sort((a, b) => b.applied - a.applied).slice(0, 5);
  const roleMax = Math.max(...roleFamilies.map((item) => item.applied), 1);
  const highScoreCount = scoredJobs.filter((job) => (job.match_score ?? 0) >= 80).length;
  const changeNext = useMemo(
    () => buildChangeNextList({ conversion, sourceQuality, profileGaps, stats }),
    [conversion, sourceQuality, profileGaps, stats],
  );

  return (
    <motion.div
      className="dashboard-page insights-page insights-page-refined"
      variants={stagger}
      initial="hidden"
      animate="visible"
    >
      <motion.section className="page-rail strategy-rail" variants={fadeUp}>
        <div className="page-rail-copy">
          <p className="page-kicker">Strategy</p>
          <h1 className="page-title">Search patterns and course correction</h1>
          <p className="page-caption">
            Use this view to decide what to change in your search, not to stare at numbers.
          </p>
        </div>
        <div className="page-rail-meta">
          <span className="page-meta-pill">{trackedTotal} tracked</span>
          <span className="page-meta-pill">{stats?.active_pipeline ?? 0} active</span>
          <span className="page-meta-pill">{responseRate != null ? `${responseRate}% response rate` : "No response baseline yet"}</span>
        </div>
      </motion.section>

      {(error || dataError) ? <div className="error-banner">{error || dataError}</div> : null}

      {isInitialLoading ? (
        <div className="insights-loading-state">
          <div className="recommend-loading-dot" />
          <div className="recommend-loading-dot" />
          <div className="recommend-loading-dot" />
        </div>
      ) : (
        <>
          <motion.section className="strategy-overview-grid" variants={fadeUp}>
            <article className="strategy-story-card strategy-story-card--accent">
              <span className="strategy-story-label">Search health</span>
              <strong>{responseRate != null ? `${responseRate}%` : "—"}</strong>
              <p>
                {responseRate != null
                  ? `${conversion?.overall.responses ?? 0} of ${conversion?.overall.applied ?? 0} applications have produced replies.`
                  : "You need more applied roles before the response pattern becomes meaningful."}
              </p>
            </article>
            <article className="strategy-story-card">
              <span className="strategy-story-label">Strongest source</span>
              <strong>{bestSource?.ats ?? "No signal yet"}</strong>
              <p>
                {bestSource
                  ? `Quality score ${Math.round(bestSource.quality_score)}/100 with ${bestSource.applied} applications sent through it.`
                  : "Keep applying before source quality becomes directional."}
              </p>
            </article>
            <article className="strategy-story-card">
              <span className="strategy-story-label">Biggest blocker</span>
              <strong>{topGap?.label ?? "No urgent blocker"}</strong>
              <p>
                {topGap
                  ? `Showing up in ${topGap.count} strong jobs. This is the clearest profile gap right now.`
                  : "Your current profile is not showing one dominant blocker across strong roles."}
              </p>
            </article>
          </motion.section>

          <motion.section className="strategy-visual-grid" variants={fadeUp}>
            <article className="strategy-surface strategy-surface--visual">
              <div className="strategy-surface-head">
                <div>
                  <p className="page-kicker">Pipeline mix</p>
                  <h2>Where tracked roles are sitting now</h2>
                </div>
                <span className="strategy-meta-inline">{trackedTotal} total</span>
              </div>
              <PipelineDonut byStatus={byStatus} />
              <p className="strategy-copy-soft">
                Read this as balance, not volume. Too much weight in staging usually means decision drag; too much in rejected means targeting or positioning drift.
              </p>
            </article>

            <article className="strategy-surface strategy-surface--visual">
              <div className="strategy-surface-head">
                <div>
                  <p className="page-kicker">Opportunity quality</p>
                  <h2>How strong the current search looks</h2>
                </div>
                <span className="strategy-meta-inline">{highScoreCount} roles at 80+</span>
              </div>
              <ScoreHistogram jobs={jobs} />
              <p className="strategy-copy-soft">
                This is your fast quality check. If strong-score buckets thin out, adjust sources and targeting before forcing more applications.
              </p>
            </article>
          </motion.section>

          <motion.section className="strategy-layout" variants={fadeUp}>
            <div className="strategy-main-column">
              <article className="strategy-surface">
                <div className="strategy-surface-head">
                  <div>
                    <p className="page-kicker">Pipeline health</p>
                    <h2>How momentum is actually moving</h2>
                  </div>
                  {(stats?.overdue_staging_count ?? 0) > 0 ? (
                    <span className="strategy-alert-chip">
                      <TriangleAlert size={14} />
                      {stats?.overdue_staging_count} overdue
                    </span>
                  ) : null}
                </div>
                <FunnelChart byStatus={byStatus} />
                <p className="strategy-copy-soft">
                  {(stats?.overdue_staging_count ?? 0) > 0
                    ? "Staging is the first place to clear friction. Roles that sit here too long usually decay before they become applications."
                    : "The pipeline is moving without obvious staging drag. Use this as a weekly sanity check instead of a daily alarm."}
                </p>
              </article>

              <article className="strategy-surface">
                <div className="strategy-surface-head">
                  <div>
                    <p className="page-kicker">Source performance</p>
                    <h2>Where your effort is paying back</h2>
                  </div>
                  {bestSource ? <span className="strategy-meta-inline">Best: {bestSource.ats}</span> : null}
                </div>
                {topSources.length > 0 ? (
                  <div className="strategy-bar-stack">
                    {topSources.map((source) => {
                      const qualColor = source.quality_score >= 70 ? "#16a34a" : source.quality_score >= 50 ? "var(--accent)" : "#dc2626";
                      return (
                        <div key={source.ats} className="strategy-bar-row">
                          <div className="strategy-bar-head">
                            <span>{source.ats}</span>
                            <small>
                              {source.applied} applied
                              {source.positive_outcomes > 0 ? ` · ${source.positive_outcomes} replies` : ""}
                            </small>
                            <strong style={{ color: qualColor }}>{Math.round(source.quality_score)}/100</strong>
                          </div>
                          <HBar pct={(source.applied / topSourceMax) * 100} color={qualColor} />
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <p className="strategy-copy-soft">Source quality becomes useful once you start applying through multiple channels.</p>
                )}
                {weakSource && weakSource !== bestSource ? (
                  <p className="strategy-inline-note">
                    <TrendingUp size={14} />
                    {weakSource.ats} is the weakest current source after at least two applications. Reduce time spent there unless the jobs are unusually strong.
                  </p>
                ) : null}
              </article>

              <article className="strategy-surface">
                <div className="strategy-surface-head">
                  <div>
                    <p className="page-kicker">Role families</p>
                    <h2>Where replies are actually showing up</h2>
                  </div>
                </div>
                {roleFamilies.length > 0 ? (
                  <div className="strategy-bar-stack">
                    {roleFamilies.map((role) => {
                      const responsePct = role.applied > 0 ? Math.round((role.responses / role.applied) * 100) : 0;
                      return (
                        <div key={role.key} className="strategy-bar-row">
                          <div className="strategy-bar-head">
                            <span>{role.key}</span>
                            <small>{role.applied} applied · {role.responses} replies</small>
                            <strong>{responsePct}%</strong>
                          </div>
                          <div className="strategy-role-bars">
                            <HBar pct={(role.applied / roleMax) * 100} color="var(--surface-3)" />
                            <HBar pct={(role.responses / roleMax) * 100} color="#16a34a" />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <p className="strategy-copy-soft">You need more application volume before role family patterns become trustworthy.</p>
                )}
              </article>
            </div>

            <div className="strategy-side-column">
              <article className="strategy-surface">
                <div className="strategy-surface-head">
                  <div>
                    <p className="page-kicker">Profile blockers</p>
                    <h3>What is still costing you access</h3>
                  </div>
                </div>
                {(profileGaps?.items.length ?? 0) > 0 ? (
                  <div className="strategy-chip-stack">
                    {profileGaps?.items.slice(0, 6).map((gap) => (
                      <a
                        key={`${gap.kind}-${gap.label}`}
                        href={`/board?q=${encodeURIComponent(gap.label)}`}
                        className="strategy-chip-card strategy-chip-card--link"
                      >
                        <span>{gap.kind === "skill_gap" ? "Skill" : "Signal"}</span>
                        <strong>{gap.label}</strong>
                        <small>{gap.count} jobs · view in board</small>
                      </a>
                    ))}
                  </div>
                ) : (
                  <p className="strategy-copy-soft">No clear blockers are dominating your strongest roles right now.</p>
                )}
              </article>

              <article className="strategy-surface">
                <div className="strategy-surface-head">
                  <div>
                    <p className="page-kicker">Targeting signals</p>
                    <h3>Where to shift your focus</h3>
                  </div>
                </div>
                {(profileInsights?.roles_you_should_target_more?.length ?? 0) > 0 ? (
                  <div className="strategy-targeting-group">
                    <p className="strategy-targeting-label strategy-targeting-label--more">Target more</p>
                    <div className="strategy-targeting-chips">
                      {profileInsights!.roles_you_should_target_more.map((role) => (
                        <a key={role} href={`/board?q=${encodeURIComponent(role)}`} className="strategy-targeting-chip strategy-targeting-chip--more">{role}</a>
                      ))}
                    </div>
                  </div>
                ) : null}
                {(profileInsights?.roles_you_should_target_less?.length ?? 0) > 0 ? (
                  <div className="strategy-targeting-group">
                    <p className="strategy-targeting-label strategy-targeting-label--less">Reduce focus</p>
                    <div className="strategy-targeting-chips">
                      {profileInsights!.roles_you_should_target_less.map((role) => (
                        <span key={role} className="strategy-targeting-chip strategy-targeting-chip--less">{role}</span>
                      ))}
                    </div>
                  </div>
                ) : null}
                {(profileInsights?.suggested_profile_updates?.length ?? 0) > 0 ? (
                  <div className="strategy-targeting-group">
                    <p className="strategy-targeting-label">Suggested updates</p>
                    <ul className="strategy-update-list">
                      {profileInsights!.suggested_profile_updates.map((upd, i) => (
                        <li key={i} className="strategy-note-item">• {upd}</li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <p className="strategy-copy-soft">Targeting signals will appear once there is enough conversion data.</p>
                )}
              </article>

              <article className="strategy-surface">
                <div className="strategy-surface-head">
                  <div>
                    <p className="page-kicker">Change next</p>
                    <h3>Immediate course corrections</h3>
                  </div>
                </div>
                <div className="strategy-note-list">
                  {changeNext.map((note) => (
                    <p key={note} className="strategy-note-item">
                      • {note}
                    </p>
                  ))}
                </div>
                {avgRankScore != null ? (
                  <a href="/board" className="strategy-inline-link">
                    Open board to work the highest-value roles <ArrowUpRight size={14} />
                  </a>
                ) : null}
              </article>

              <StrategyCoachCard
                stats={stats}
                conversion={conversion}
                profileGaps={profileGaps}
                sourceQuality={sourceQuality}
                avgScore={avgRankScore}
              />
            </div>
          </motion.section>
        </>
      )}
    </motion.div>
  );
}
