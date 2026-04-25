// Kenji — Insights screen. Real conversion data, skill gaps, role signals.
import { useEffect, useState } from "react";
import {
  api,
  type ConversionBucket,
  type ConversionResponse,
  type ProfileGapItem,
  type ProfileInsightsResponse,
  type SourceQualityItem,
} from "../api";
import { Icon } from "./ui";

// ─── helpers ────────────────────────────────────────────────────────────────

function pct(n: number, d: number): string {
  if (d === 0) return "—";
  return `${Math.round((n / d) * 100)}%`;
}

function atsLabel(key: string): string {
  const map: Record<string, string> = {
    manual: "Manual / direct",
    greenhouse: "Greenhouse",
    ashby: "Ashby",
    lever: "Lever",
    workable: "Workable",
    smartrecruiters: "SmartRecruiters",
    hn_hiring: "HN Hiring",
    recruitee: "Recruitee",
    teamtailor: "Teamtailor",
    unknown: "Unknown",
  };
  return map[key] ?? key.replace(/_/g, " ");
}

function roleLabel(key: string): string {
  return key
    .split(" ")
    .map(w => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function kindColor(kind: string): string {
  if (kind === "skill_gap") return "var(--warn)";
  if (kind === "seniority_mismatch") return "var(--tertiary)";
  if (kind === "work_authorization_mismatch") return "var(--error)";
  return "var(--outline)";
}

// ─── sub-components ──────────────────────────────────────────────────────────

function Stat({ label, value, sub, loading = false }: { label: string; value: string | number; sub?: string; loading?: boolean }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {loading ? (
        <div className="skeleton" style={{ height: 36, width: 68, borderRadius: 4, marginBottom: 2 }}/>
      ) : (
        <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 36, letterSpacing: "-0.03em", color: "var(--on-surface)", lineHeight: 1 }}>
          {value}
        </div>
      )}
      <div style={{ fontSize: 12.5, fontWeight: 500, color: "var(--on-surface-variant)" }}>{label}</div>
      {sub && (loading
        ? <div className="skeleton" style={{ height: 11, width: 52, borderRadius: 4 }}/>
        : <div className="mono" style={{ fontSize: 10.5, color: "var(--outline)" }}>{sub}</div>
      )}
    </div>
  );
}

function FunnelBar({ label, n, total, color = "var(--primary)" }: { label: string; n: number; total: number; color?: string }) {
  const targetW = total > 0 ? Math.max(4, Math.round((n / total) * 100)) : 0;
  const [w, setW] = useState(0);
  useEffect(() => {
    const id = requestAnimationFrame(() => setW(targetW));
    return () => cancelAnimationFrame(id);
  }, [targetW]);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "100px 1fr 48px", gap: 12, alignItems: "center" }}>
      <div style={{ fontSize: 12, color: "var(--on-surface-variant)", textAlign: "right", fontWeight: 500 }}>{label}</div>
      <div style={{ height: 6, background: "var(--sc-high)", borderRadius: 3, overflow: "hidden" }}>
        <div style={{ width: `${w}%`, height: "100%", background: color, borderRadius: 3, transition: "width 700ms cubic-bezier(0.22, 1, 0.36, 1)" }}/>
      </div>
      <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 15, color: "var(--on-surface)", letterSpacing: "-0.02em" }}>
        {n}
      </div>
    </div>
  );
}

function SourceRow({ item }: { item: SourceQualityItem }) {
  const score = Math.round(item.quality_score);
  const color = score >= 55 ? "var(--primary)" : score >= 50 ? "var(--warn)" : "var(--error)";
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr auto auto", gap: 16, alignItems: "center", padding: "10px 0", borderBottom: "1px solid var(--sc-high)" }}>
      <div>
        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--on-surface)" }}>{atsLabel(item.ats)}</div>
        <div className="mono" style={{ fontSize: 10.5, color: "var(--outline)", marginTop: 2 }}>
          {item.applied} applied · {item.positive_outcomes} positive · {item.negative_outcomes} negative
        </div>
      </div>
      <div style={{ fontSize: 12, color: "var(--outline)", textAlign: "right" }}>
        {pct(item.positive_outcomes, item.applied)} response
      </div>
      <div style={{
        fontFamily: "var(--font-mono)", fontSize: 11.5, fontWeight: 600,
        color, background: `color-mix(in oklch, ${color} 12%, transparent)`,
        padding: "3px 8px", borderRadius: 6,
      }}>
        {score}
      </div>
    </div>
  );
}

function RoleBucket({ bucket }: { bucket: ConversionBucket }) {
  const rate = bucket.applied > 0 ? Math.round((bucket.responses / bucket.applied) * 100) : 0;
  const barW = Math.min(100, rate * 2); // scale so 50% rate = full bar
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 12, alignItems: "center", padding: "8px 0", borderBottom: "1px solid var(--sc-high)" }}>
      <div>
        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--on-surface)", marginBottom: 5 }}>{roleLabel(bucket.key)}</div>
        <div style={{ height: 4, background: "var(--sc-high)", borderRadius: 2, overflow: "hidden" }}>
          <div style={{ width: `${barW}%`, height: "100%", background: "var(--primary)", borderRadius: 2 }}/>
        </div>
      </div>
      <div className="mono" style={{ fontSize: 10.5, color: "var(--outline)", textAlign: "right", flexShrink: 0 }}>
        {bucket.applied} → {bucket.responses}<br/>
        <span style={{ color: rate > 0 ? "var(--primary)" : "var(--outline)" }}>{pct(bucket.responses, bucket.applied)}</span>
      </div>
    </div>
  );
}

function GapChip({ gap }: { gap: ProfileGapItem }) {
  const color = kindColor(gap.kind);
  return (
    <div style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      padding: "5px 10px", borderRadius: "var(--r)",
      background: `color-mix(in oklch, ${color} 10%, var(--sc-lowest))`,
      border: `1px solid color-mix(in oklch, ${color} 25%, transparent)`,
    }}>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 11.5, fontWeight: 600, color: "var(--on-surface)" }}>
        {gap.label}
      </span>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color, fontWeight: 700 }}>
        ×{gap.count}
      </span>
    </div>
  );
}

// ─── loading / empty states ───────────────────────────────────────────────────

function Skeleton({ h = 18 }: { h?: number }) {
  return <div className="skeleton" style={{ height: h }}/>;
}

// ─── main component ──────────────────────────────────────────────────────────

interface InsightsData {
  conversion: ConversionResponse;
  sourceQuality: SourceQualityItem[];
  profileInsights: ProfileInsightsResponse;
}

export function Insights() {
  const [data, setData] = useState<InsightsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      api.conversion(),
      api.sourceQuality(),
      api.profileInsights(),
    ]).then(([conversion, sq, pi]) => {
      if (cancelled) return;
      setData({ conversion, sourceQuality: sq.items, profileInsights: pi });
    }).catch(e => {
      if (!cancelled) setError(String(e));
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, []);

  if (error) {
    return (
      <div className="content" style={{ maxWidth: 900 }}>
        <div className="mono" style={{ color: "var(--error)", fontSize: 12 }}>Failed to load insights: {error}</div>
      </div>
    );
  }

  const overall = data?.conversion.overall;
  const byAts = data?.conversion.by_ats ?? [];
  const byRole = data?.conversion.by_role_family ?? [];
  const gaps = data?.profileInsights.top_missing_signals ?? [];
  const moreRoles = data?.profileInsights.roles_you_should_target_more ?? [];
  const lessRoles = data?.profileInsights.roles_you_should_target_less ?? [];
  const suggestions = data?.profileInsights.suggested_profile_updates ?? [];
  const sourceQuality = data?.sourceQuality ?? [];

  return (
    <div className="content" style={{ maxWidth: 1000, paddingBottom: 64 }}>

      {/* ── header ── */}
      <div style={{ marginBottom: 24 }}>
        <div className="mono" style={{ fontSize: 9.5, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--outline)", marginBottom: 10 }}>
          insights
        </div>
        <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 32, letterSpacing: "-0.025em", color: "var(--on-surface)", lineHeight: 1.1 }}>
          Your pipeline,<span style={{ fontStyle: "italic", fontWeight: 500, color: "var(--primary)" }}> read clearly.</span>
        </div>
        <div style={{ marginTop: 10, fontSize: 13.5, color: "var(--outline)", maxWidth: 500 }}>
          Built from every application, event, and match score in your database. No estimates.
        </div>
      </div>

      {/* ── top stats row ── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 1, marginBottom: 20, background: "var(--outline-variant)", borderRadius: "var(--r-lg)", overflow: "hidden" }}>
        {[
          { label: "Applications sent",  value: String(overall?.applied ?? 0), sub: "total tracked" },
          { label: "Response rate",      value: pct(overall?.responses ?? 0, overall?.applied ?? 0), sub: `${overall?.responses ?? 0} replies` },
          { label: "Interview rate",     value: pct(overall?.interviews ?? 0, overall?.applied ?? 0), sub: `${overall?.interviews ?? 0} interviews` },
          { label: "Offers",             value: String(overall?.offers ?? 0), sub: `${overall?.rejections ?? 0} rejections` },
        ].map((s, i) => (
          <div key={i} style={{ background: "var(--sc-lowest)", padding: "18px 20px" }}>
            <Stat {...s} loading={loading}/>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, alignItems: "start" }}>

        {/* ── LEFT column ── */}
        <div className="col" style={{ gap: 24 }}>

          {/* Funnel */}
          <div className="card" style={{ padding: "18px 20px" }}>
            <div className="mono" style={{ fontSize: 9.5, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--outline)", marginBottom: 16 }}>
              Application funnel
            </div>
            {loading ? (
              <div className="col" style={{ gap: 10 }}>{[1,2,3,4].map(i => <Skeleton key={i}/>)}</div>
            ) : (
              <div className="col" style={{ gap: 10 }}>
                <FunnelBar label="Applied"    n={overall?.applied    ?? 0} total={overall?.applied ?? 0} color="var(--primary)"/>
                <FunnelBar label="Responses"  n={overall?.responses  ?? 0} total={overall?.applied ?? 0} color="var(--primary)"/>
                <FunnelBar label="Interviews" n={overall?.interviews ?? 0} total={overall?.applied ?? 0} color="var(--warn)"/>
                <FunnelBar label="Offers"     n={overall?.offers     ?? 0} total={overall?.applied ?? 0} color="var(--tertiary)"/>
                <FunnelBar label="Rejections" n={overall?.rejections ?? 0} total={overall?.applied ?? 0} color="var(--error)"/>
              </div>
            )}
            {!loading && overall && overall.applied > 0 && (
              <div className="mono" style={{ marginTop: 16, fontSize: 10.5, color: "var(--outline)" }}>
                {pct(overall.responses, overall.applied)} response · {pct(overall.interviews, overall.responses)} of responses → interview
              </div>
            )}
            {!loading && (overall?.applied ?? 0) === 0 && (
              <div style={{ fontSize: 12.5, color: "var(--outline)", fontStyle: "italic", marginTop: 8 }}>
                No applications tracked yet. Mark jobs as applied in the Pipeline.
              </div>
            )}
          </div>

          {/* Role conversion */}
          <div className="card" style={{ padding: "18px 20px" }}>
            <div className="mono" style={{ fontSize: 9.5, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--outline)", marginBottom: 4 }}>
              By role family
            </div>
            <div style={{ fontSize: 12, color: "var(--outline)", marginBottom: 16 }}>Response rate per role category</div>
            {loading ? (
              <div className="col" style={{ gap: 8 }}>{[1,2,3].map(i => <Skeleton key={i}/>)}</div>
            ) : byRole.filter(b => b.applied > 0).length === 0 ? (
              <div style={{ fontSize: 12.5, color: "var(--outline)", fontStyle: "italic" }}>No data yet — apply to some roles to see trends.</div>
            ) : (
              <div>
                {byRole.filter(b => b.applied > 0).map(b => <RoleBucket key={b.key} bucket={b}/>)}
              </div>
            )}
          </div>

          {/* Source quality */}
          <div className="card" style={{ padding: "18px 20px" }}>
            <div className="mono" style={{ fontSize: 9.5, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--outline)", marginBottom: 4 }}>
              Source quality
            </div>
            <div style={{ fontSize: 12, color: "var(--outline)", marginBottom: 16 }}>
              Score 50 = neutral · &gt;55 = positive signal · &lt;45 = avoid
            </div>
            {loading ? (
              <div className="col" style={{ gap: 8 }}>{[1,2,3].map(i => <Skeleton key={i}/>)}</div>
            ) : sourceQuality.filter(s => s.applied > 0).length === 0 ? (
              <div style={{ fontSize: 12.5, color: "var(--outline)", fontStyle: "italic" }}>No source data yet.</div>
            ) : (
              <div>
                {sourceQuality.filter(s => s.applied > 0).map(s => <SourceRow key={s.ats} item={s}/>)}
              </div>
            )}
          </div>

        </div>

        {/* ── RIGHT column ── */}
        <div className="col" style={{ gap: 24 }}>

          {/* Skill gaps */}
          <div className="card" style={{ padding: "18px 20px" }}>
            <div className="mono" style={{ fontSize: 9.5, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--outline)", marginBottom: 4 }}>
              Skill gaps
            </div>
            <div style={{ fontSize: 12, color: "var(--outline)", marginBottom: 16 }}>
              Required by roles you scored highly on, but missing from your profile
            </div>
            {loading ? (
              <div className="col" style={{ gap: 8 }}>{[1,2,3,4].map(i => <Skeleton key={i}/>)}</div>
            ) : gaps.filter(g => g.kind === "skill_gap").length === 0 ? (
              <div style={{ fontSize: 12.5, color: "var(--outline)", fontStyle: "italic" }}>
                No skill gaps detected — profile looks strong against current roles.
              </div>
            ) : (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {gaps.filter(g => g.kind === "skill_gap").map(g => <GapChip key={g.label} gap={g}/>)}
              </div>
            )}

            {/* Other gap types */}
            {!loading && gaps.filter(g => g.kind !== "skill_gap").length > 0 && (
              <div className="col" style={{ gap: 8, marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--sc-high)" }}>
                {gaps.filter(g => g.kind !== "skill_gap").map(g => (
                  <div key={g.label} className="row gap-10" style={{ fontSize: 12.5, color: "var(--on-surface-variant)" }}>
                    <div style={{ width: 6, height: 6, borderRadius: "50%", background: kindColor(g.kind), flexShrink: 0, marginTop: 4 }}/>
                    <span>{g.label}</span>
                    <span className="mono" style={{ fontSize: 10.5, color: "var(--outline)", marginLeft: "auto" }}>×{g.count}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Role signals */}
          <div className="card" style={{ padding: "18px 20px" }}>
            <div className="mono" style={{ fontSize: 9.5, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--outline)", marginBottom: 16 }}>
              Role signals
            </div>
            {loading ? (
              <div className="col" style={{ gap: 8 }}>{[1,2].map(i => <Skeleton key={i}/>)}</div>
            ) : (
              <div className="col" style={{ gap: 18 }}>
                {moreRoles.length > 0 && (
                  <div>
                    <div style={{ fontSize: 11.5, fontWeight: 600, color: "var(--primary)", marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
                      <Icon name="arrow" size={12}/> Target more
                    </div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                      {moreRoles.map(r => (
                        <span key={r} style={{ fontSize: 12, fontWeight: 500, padding: "4px 10px", borderRadius: "var(--r)", background: "color-mix(in oklch, var(--primary) 10%, transparent)", color: "var(--primary)", border: "1px solid color-mix(in oklch, var(--primary) 22%, transparent)" }}>
                          {roleLabel(r)}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {lessRoles.length > 0 && (
                  <div>
                    <div style={{ fontSize: 11.5, fontWeight: 600, color: "var(--tertiary)", marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
                      <Icon name="x" size={12}/> Deprioritise
                    </div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                      {lessRoles.map(r => (
                        <span key={r} style={{ fontSize: 12, fontWeight: 500, padding: "4px 10px", borderRadius: "var(--r)", background: "color-mix(in oklch, var(--tertiary) 10%, transparent)", color: "var(--tertiary)", border: "1px solid color-mix(in oklch, var(--tertiary) 22%, transparent)" }}>
                          {roleLabel(r)}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {moreRoles.length === 0 && lessRoles.length === 0 && (
                  <div style={{ fontSize: 12.5, color: "var(--outline)", fontStyle: "italic" }}>
                    Apply to more roles to surface targeting signals.
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Suggestions */}
          {(loading || suggestions.length > 0) && (
            <div className="card" style={{ padding: "18px 20px" }}>
              <div className="mono" style={{ fontSize: 9.5, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--outline)", marginBottom: 16 }}>
                Profile suggestions
              </div>
              {loading ? (
                <div className="col" style={{ gap: 10 }}>{[1,2,3].map(i => <Skeleton key={i}/>)}</div>
              ) : (
                <div className="col" style={{ gap: 10 }}>
                  {suggestions.map((s, i) => (
                    <div key={i} style={{ display: "grid", gridTemplateColumns: "20px 1fr", gap: 10, fontSize: 13, color: "var(--on-surface-variant)", lineHeight: 1.5 }}>
                      <div className="mono" style={{ fontSize: 11, color: "var(--outline)", paddingTop: 1 }}>{String(i + 1).padStart(2, "0")}</div>
                      <div>{s}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* By ATS */}
          {byAts.filter(b => b.applied > 0).length > 0 && (
            <div className="card" style={{ padding: "18px 20px" }}>
              <div className="mono" style={{ fontSize: 9.5, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--outline)", marginBottom: 4 }}>
                By ATS source
              </div>
              <div style={{ fontSize: 12, color: "var(--outline)", marginBottom: 16 }}>Applied → responses per platform</div>
              {loading ? (
                <div className="col" style={{ gap: 8 }}>{[1,2].map(i => <Skeleton key={i}/>)}</div>
              ) : (
                <div>
                  {byAts.filter(b => b.applied > 0).map(b => (
                    <div key={b.key} style={{ display: "grid", gridTemplateColumns: "1fr auto auto", gap: 12, alignItems: "center", padding: "9px 0", borderBottom: "1px solid var(--sc-high)" }}>
                      <div style={{ fontSize: 13, fontWeight: 500, color: "var(--on-surface)" }}>{atsLabel(b.key)}</div>
                      <div className="mono" style={{ fontSize: 10.5, color: "var(--outline)" }}>{b.applied} sent</div>
                      <div className="mono" style={{ fontSize: 11, fontWeight: 600, color: b.responses > 0 ? "var(--primary)" : "var(--outline)" }}>
                        {pct(b.responses, b.applied)}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

        </div>
      </div>
    </div>
  );
}
