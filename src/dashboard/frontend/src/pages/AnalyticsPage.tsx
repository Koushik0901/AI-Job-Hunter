import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getFunnelAnalytics } from "../api";
import { ThemedLoader } from "../components/ThemedLoader";
import type { FunnelAnalyticsResponse, SourceQualityItem } from "../types";

type RangePreset = "30d" | "90d" | "all";

const PIPELINE_ORDER = ["not_applied", "staging", "applied", "interviewing", "offer", "rejected"] as const;
const STATUS_LABELS: Record<string, string> = {
  not_applied: "Backlog",
  staging: "Staging",
  applied: "Applied",
  interviewing: "Interviewing",
  offer: "Offer",
  rejected: "Rejected",
};

const CONVERSION_ITEMS: Array<{
  key: keyof FunnelAnalyticsResponse["conversions"];
  label: string;
}> = [
  { key: "backlog_to_staging", label: "Backlog -> Staging" },
  { key: "staging_to_applied", label: "Staging -> Applied" },
  { key: "applied_to_interviewing", label: "Applied -> Interviewing" },
  { key: "interviewing_to_offer", label: "Interviewing -> Offer" },
  { key: "backlog_to_offer", label: "Backlog -> Offer" },
];

const ALERT_ITEMS: Array<{ key: keyof FunnelAnalyticsResponse["alerts"]; title: string; detail: string }> = [
  { key: "staging_stale_7d", title: "Staging stale", detail: "Drafting started, no update in 7+ days." },
  { key: "interviewing_no_activity_5d", title: "Interviewing idle", detail: "No follow-up activity in 5+ days." },
  { key: "backlog_expiring_soon", title: "Backlog expiring", detail: "Jobs close to 3-week freshness cutoff." },
];

function clamp(value: number, low: number, high: number): number {
  return Math.max(low, Math.min(high, value));
}

function asPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function signedCount(value: number): string {
  return value > 0 ? `+${value}` : `${value}`;
}

function signedPercentPoint(value: number): string {
  const pp = value * 100;
  const sign = pp > 0 ? "+" : "";
  return `${sign}${pp.toFixed(1)}pp`;
}

function addDays(isoDate: string, days: number): string {
  const value = new Date(isoDate);
  if (Number.isNaN(value.valueOf())) return isoDate;
  value.setDate(value.getDate() + days);
  return value.toISOString().slice(0, 10);
}

function ProgressRing({
  label,
  value,
  target,
}: {
  label: string;
  value: number;
  target: number;
}) {
  const ratio = clamp(target > 0 ? value / target : 0, 0, 1);
  const angle = Math.round(ratio * 360);
  return (
    <article className="analytics-ring-card">
      <div
        className="analytics-ring"
        style={{ background: `conic-gradient(var(--accent) ${angle}deg, var(--surface-2) ${angle}deg 360deg)` }}
        aria-label={`${label} progress ${Math.round(ratio * 100)} percent`}
      >
        <div className="analytics-ring-inner">
          <strong>{Math.round(ratio * 100)}%</strong>
          <span>{value}/{target}</span>
        </div>
      </div>
      <p>{label}</p>
    </article>
  );
}

function ForecastTrendChart({
  points,
}: {
  points: Array<{
    day: number;
    interviews: number;
    offers: number;
    interviewsLow: number;
    interviewsHigh: number;
    offersLow: number;
    offersHigh: number;
  }>;
}) {
  const width = 540;
  const height = 210;
  const padX = 26;
  const padTop = 20;
  const padBottom = 28;
  const maxValue = Math.max(
    1,
    ...points.map((point) => Math.max(point.interviewsHigh, point.offersHigh)),
  );
  const xStep = points.length > 1 ? (width - padX * 2) / (points.length - 1) : 0;
  const y = (value: number) => {
    const usableHeight = height - padTop - padBottom;
    return padTop + (1 - value / maxValue) * usableHeight;
  };
  const x = (index: number) => padX + index * xStep;

  const interviewsLine = points.map((point, index) => `${x(index)},${y(point.interviews)}`).join(" ");
  const offersLine = points.map((point, index) => `${x(index)},${y(point.offers)}`).join(" ");
  const interviewBand = [
    ...points.map((point, index) => `${x(index)},${y(point.interviewsHigh)}`),
    ...points.slice().reverse().map((point, index) => {
      const realIndex = points.length - 1 - index;
      return `${x(realIndex)},${y(point.interviewsLow)}`;
    }),
  ].join(" ");
  const offerBand = [
    ...points.map((point, index) => `${x(index)},${y(point.offersHigh)}`),
    ...points.slice().reverse().map((point, index) => {
      const realIndex = points.length - 1 - index;
      return `${x(realIndex)},${y(point.offersLow)}`;
    }),
  ].join(" ");

  return (
    <div className="analytics-forecast-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Interview and offer projection trend">
        <line x1={padX} y1={height - padBottom} x2={width - padX} y2={height - padBottom} className="axis" />
        <line x1={padX} y1={padTop} x2={padX} y2={height - padBottom} className="axis" />
        <polygon points={interviewBand} className="band band-interviews" />
        <polygon points={offerBand} className="band band-offers" />
        <polyline points={interviewsLine} className="line line-interviews" />
        <polyline points={offersLine} className="line line-offers" />
        {points.map((point, index) => (
          <g key={point.day}>
            <circle cx={x(index)} cy={y(point.interviews)} r={3.3} className="dot dot-interviews" />
            <circle cx={x(index)} cy={y(point.offers)} r={3.3} className="dot dot-offers" />
            <text x={x(index)} y={height - 8} textAnchor="middle" className="tick">
              D{point.day}
            </text>
          </g>
        ))}
      </svg>
      <div className="analytics-legend">
        <span><i className="line-key interviews" />Interviews</span>
        <span><i className="line-key offers" />Offers</span>
        <span><i className="line-key band" />Confidence band</span>
      </div>
    </div>
  );
}

function SourceRankChart({
  title,
  items,
  onClick,
}: {
  title: string;
  items: SourceQualityItem[];
  onClick: (name: string) => void;
}) {
  const maxRate = Math.max(0.01, ...items.map((item) => item.offer_rate));
  return (
    <article className="analytics-subcard">
      <header>
        <h5>{title}</h5>
      </header>
      <div className="analytics-rank-list">
        {items.map((item) => {
          const width = clamp((item.offer_rate / maxRate) * 100, 0, 100);
          return (
            <button
              type="button"
              key={`${title}-${item.name}`}
              className="analytics-rank-item"
              onClick={() => onClick(item.name)}
              title={`Open board filtered for ${item.name}`}
            >
              <div className="analytics-rank-copy">
                <p>{item.name}</p>
                <small>{item.tracked_total} tracked • {item.offers} offers</small>
              </div>
              <div className="analytics-rank-meter">
                <span style={{ width: `${width}%` }} />
              </div>
              <strong>{asPercent(item.offer_rate)}</strong>
            </button>
          );
        })}
      </div>
    </article>
  );
}

export function AnalyticsPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [preset, setPreset] = useState<RangePreset>("90d");
  const [data, setData] = useState<FunnelAnalyticsResponse | null>(null);
  const [applicationsGoalTarget, setApplicationsGoalTarget] = useState(10);
  const [interviewsGoalTarget, setInterviewsGoalTarget] = useState(3);
  const [forecastAppsPerWeek, setForecastAppsPerWeek] = useState(10);
  const [forecastTouched, setForecastTouched] = useState(false);

  async function load(selectedPreset = preset): Promise<void> {
    setLoading(true);
    setError(null);
    try {
      const response = await getFunnelAnalytics({
        preset: selectedPreset,
        status_scope: "pipeline",
        applications_goal_target: applicationsGoalTarget,
        interviews_goal_target: interviewsGoalTarget,
        forecast_apps_per_week: forecastAppsPerWeek,
      });
      setData(response);
      if (!forecastTouched) {
        setForecastAppsPerWeek(response.forecast.applications_per_week);
      }
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load analytics");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load(preset);
  }, [preset]);

  function goToBoardWithFilters(filters: {
    ats?: string;
    company?: string;
    posted_after?: string;
    posted_before?: string;
  }): void {
    const params = new URLSearchParams();
    if (filters.ats) params.set("ats", filters.ats);
    if (filters.company) params.set("company", filters.company);
    if (filters.posted_after) params.set("posted_after", filters.posted_after);
    if (filters.posted_before) params.set("posted_before", filters.posted_before);
    const query = params.toString();
    navigate(query ? `/?${query}` : "/");
  }

  const stageMap = useMemo(() => {
    const result = new Map<string, number>();
    (data?.stages ?? []).forEach((stage) => result.set(stage.status, stage.count));
    return result;
  }, [data]);

  const orderedStages = useMemo(
    () => PIPELINE_ORDER.map((status) => ({ status, count: stageMap.get(status) ?? 0 })),
    [stageMap],
  );

  const maxStageCount = Math.max(1, ...orderedStages.map((stage) => stage.count));

  const forecastPoints = useMemo(() => {
    if (!data) return [];
    const interviewRate = data.forecast.interview_rate;
    const offerRate = data.forecast.offer_rate_from_interview;
    const margin = data.forecast.confidence_margin;
    const windows = [7, 14, 21, 30];
    return windows.map((days) => {
      const applications = forecastAppsPerWeek * (days / 7);
      const interviews = applications * interviewRate;
      const offers = interviews * offerRate;
      const lowMultiplier = Math.max(0, 1 - margin);
      const highMultiplier = 1 + margin;
      return {
        day: days,
        interviews,
        offers,
        interviewsLow: interviews * lowMultiplier,
        interviewsHigh: interviews * highMultiplier,
        offersLow: offers * lowMultiplier,
        offersHigh: offers * highMultiplier,
      };
    });
  }, [data, forecastAppsPerWeek]);

  const forecastSummary = useMemo(() => {
    if (!forecastPoints.length) {
      return { interviews30d: 0, offers30d: 0, interviewsBand: "0 - 0", offersBand: "0 - 0" };
    }
    const point30 = forecastPoints[forecastPoints.length - 1];
    return {
      interviews30d: point30.interviews,
      offers30d: point30.offers,
      interviewsBand: `${point30.interviewsLow.toFixed(1)} - ${point30.interviewsHigh.toFixed(1)}`,
      offersBand: `${point30.offersLow.toFixed(1)} - ${point30.offersHigh.toFixed(1)}`,
    };
  }, [forecastPoints]);

  if (loading) {
    return (
      <div className="board-page">
        <div className="page-loader-shell">
          <ThemedLoader label="Loading analytics" />
        </div>
      </div>
    );
  }

  return (
    <div className="board-page analytics-redesign">
      <header className="analytics-hero">
        <div className="analytics-hero-copy">
          <p className="analytics-kicker">Pipeline Intelligence</p>
          <h2>Application Analytics</h2>
          <p className="board-note">One clear flow: where you are, where friction exists, and what to do next.</p>
        </div>
        <div className="analytics-controls">
          <div className="analytics-preset-group" role="group" aria-label="Analytics date window">
            {(["30d", "90d", "all"] as RangePreset[]).map((option) => (
              <button
                type="button"
                key={option}
                className={`ghost-btn compact ${preset === option ? "active" : ""}`}
                data-icon={preset === option ? "●" : "◦"}
                onClick={() => setPreset(option)}
              >
                {option === "all" ? "All time" : `Last ${option.slice(0, -1)} days`}
              </button>
            ))}
          </div>
          <label className="toolbar-control analytics-goal-input">
            <span>Apps goal</span>
            <input
              type="number"
              min={1}
              max={100}
              value={applicationsGoalTarget}
              onChange={(event) => setApplicationsGoalTarget(Math.max(1, Math.min(100, Number(event.target.value) || 1)))}
            />
          </label>
          <label className="toolbar-control analytics-goal-input">
            <span>Interview goal</span>
            <input
              type="number"
              min={1}
              max={50}
              value={interviewsGoalTarget}
              onChange={(event) => setInterviewsGoalTarget(Math.max(1, Math.min(50, Number(event.target.value) || 1)))}
            />
          </label>
          <label className="toolbar-control analytics-goal-input">
            <span>Forecast apps/wk</span>
            <input
              type="number"
              min={1}
              max={150}
              value={forecastAppsPerWeek}
              onChange={(event) => {
                setForecastTouched(true);
                setForecastAppsPerWeek(Math.max(1, Math.min(150, Number(event.target.value) || 1)));
              }}
            />
          </label>
          <button type="button" onClick={() => void load()} className="primary-btn" data-icon="↻">
            Refresh
          </button>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <section className="analytics-snapshot">
        <article className="analytics-stat-tile">
          <p>Tracked</p>
          <strong>{data?.totals.tracked_total ?? 0}</strong>
          <small>{signedCount(data?.deltas.tracked_total ?? 0)} vs previous</small>
        </article>
        <article className="analytics-stat-tile">
          <p>Active pipeline</p>
          <strong>{data?.totals.active_total ?? 0}</strong>
          <small>{signedCount(data?.deltas.active_total ?? 0)} vs previous</small>
        </article>
        <article className="analytics-stat-tile">
          <p>Offers</p>
          <strong>{data?.totals.offer_total ?? 0}</strong>
          <small>{signedCount(data?.deltas.offer_total ?? 0)} vs previous</small>
        </article>
        <article className="analytics-stat-tile">
          <p>Backlog to offer</p>
          <strong>{asPercent(data?.conversions.backlog_to_offer ?? 0)}</strong>
          <small>{signedPercentPoint(data?.deltas.conversions.backlog_to_offer ?? 0)} vs previous</small>
        </article>
      </section>

      <section className="analytics-layout">
        <div className="analytics-main-col">
          <article className="analytics-panel">
            <div className="analytics-panel-head">
              <div>
                <p className="analytics-panel-kicker">Flow</p>
                <h3>Pipeline Funnel</h3>
              </div>
            </div>
            <div className="analytics-funnel">
              {orderedStages.map((stage) => {
                const width = clamp((stage.count / maxStageCount) * 100, 0, 100);
                return (
                  <div key={stage.status} className="analytics-funnel-row">
                    <div className="analytics-funnel-label">
                      <span>{STATUS_LABELS[stage.status] ?? stage.status}</span>
                      <strong>{stage.count}</strong>
                    </div>
                    <div className={`analytics-funnel-track stage-${stage.status}`}>
                      <span style={{ width: `${width}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="analytics-conversion-grid">
              {CONVERSION_ITEMS.map((item) => {
                const rate = data?.conversions[item.key] ?? 0;
                return (
                  <article key={item.key} className="analytics-conversion-tile">
                    <p>{item.label}</p>
                    <strong>{asPercent(rate)}</strong>
                    <small>{signedPercentPoint(data?.deltas.conversions[item.key] ?? 0)} vs previous</small>
                    <div className="analytics-inline-meter">
                      <span style={{ width: `${clamp(rate * 100, 0, 100)}%` }} />
                    </div>
                  </article>
                );
              })}
            </div>
          </article>

          <article className="analytics-panel">
            <div className="analytics-panel-head">
              <div>
                <p className="analytics-panel-kicker">Projection</p>
                <h3>30-Day Outlook</h3>
              </div>
              <small className="analytics-context-note">
                Confidence {data?.forecast.confidence_band ?? "low"}
              </small>
            </div>
            <ForecastTrendChart points={forecastPoints} />
            <div className="analytics-forecast-summary">
              <article>
                <p>Projected interviews</p>
                <strong>{forecastSummary.interviews30d.toFixed(1)}</strong>
                <small>{forecastSummary.interviewsBand}</small>
              </article>
              <article>
                <p>Projected offers</p>
                <strong>{forecastSummary.offers30d.toFixed(1)}</strong>
                <small>{forecastSummary.offersBand}</small>
              </article>
            </div>
          </article>
        </div>

        <aside className="analytics-side-col">
          <article className="analytics-panel">
            <div className="analytics-panel-head">
              <div>
                <p className="analytics-panel-kicker">Execution</p>
                <h3>Weekly Goal Pulse</h3>
              </div>
              <small className="analytics-context-note">
                {data?.weekly_goals ? `${data.weekly_goals.window_start} -> ${data.weekly_goals.window_end}` : ""}
              </small>
            </div>
            <div className="analytics-rings">
              <ProgressRing
                label="Applications"
                value={data?.weekly_goals.applications.actual ?? 0}
                target={data?.weekly_goals.applications.target ?? applicationsGoalTarget}
              />
              <ProgressRing
                label="Interview activity"
                value={data?.weekly_goals.interviews.actual ?? 0}
                target={data?.weekly_goals.interviews.target ?? interviewsGoalTarget}
              />
            </div>
          </article>

          <article className="analytics-panel">
            <div className="analytics-panel-head">
              <div>
                <p className="analytics-panel-kicker">Attention</p>
                <h3>Alerts</h3>
              </div>
            </div>
            <div className="analytics-alert-list">
              {ALERT_ITEMS.map((alert) => (
                <article key={alert.key} className="analytics-alert-item">
                  <div>
                    <p>{alert.title}</p>
                    <small>{alert.detail}</small>
                  </div>
                  <strong>{data?.alerts?.[alert.key] ?? 0}</strong>
                </article>
              ))}
            </div>
          </article>
        </aside>
      </section>

      <section className="analytics-drilldowns">
        <article className="analytics-panel">
          <div className="analytics-panel-head">
            <div>
              <p className="analytics-panel-kicker">Source Quality</p>
              <h3>Where offers are coming from</h3>
            </div>
          </div>
          <div className="analytics-source-grid">
            <SourceRankChart
              title="ATS"
              items={(data?.source_quality.ats ?? []).slice(0, 8)}
              onClick={(name) => goToBoardWithFilters({ ats: name })}
            />
            <SourceRankChart
              title="Companies"
              items={(data?.source_quality.companies ?? []).slice(0, 8)}
              onClick={(name) => goToBoardWithFilters({ company: name })}
            />
          </div>
        </article>

        <article className="analytics-panel">
          <div className="analytics-panel-head">
            <div>
              <p className="analytics-panel-kicker">Cohorts</p>
              <h3>Posted-week performance bands</h3>
            </div>
          </div>
          <div className="analytics-cohort-list">
            {(data?.cohorts ?? []).map((cohort) => {
              const stageCounts = new Map(cohort.stages.map((stage) => [stage.status, stage.count]));
              const total = Math.max(1, cohort.tracked_total);
              return (
                <button
                  type="button"
                  key={cohort.week_start}
                  className="analytics-cohort-item"
                  onClick={() =>
                    goToBoardWithFilters({
                      posted_after: cohort.week_start,
                      posted_before: addDays(cohort.week_start, 6),
                    })
                  }
                  title="Open board filtered to this posted week"
                >
                  <div className="analytics-cohort-meta">
                    <p>{cohort.week_start}</p>
                    <small>{cohort.tracked_total} tracked • {asPercent(cohort.offer_rate)} offer rate</small>
                  </div>
                  <div className="analytics-cohort-stack" aria-hidden="true">
                    {PIPELINE_ORDER.map((status) => {
                      const count = stageCounts.get(status) ?? 0;
                      const width = (count / total) * 100;
                      return <span key={`${cohort.week_start}-${status}`} className={`segment ${status}`} style={{ width: `${width}%` }} />;
                    })}
                  </div>
                </button>
              );
            })}
            {!(data?.cohorts?.length) && <p className="empty-text">No cohort data in this range.</p>}
          </div>
        </article>
      </section>
    </div>
  );
}
