// Kenji — Discover screen, wired to /api/jobs live data.
import { useEffect, useMemo, useState } from "react";
import { api, type JobSummary } from "../api";
import { BarMeter, CoLogo, Icon, Radar, ScoreRing } from "./ui";

const LOGO_PALETTE = [
  "oklch(0.72 0.14 180)",
  "oklch(0.65 0.12 45)",
  "oklch(0.55 0.14 260)",
  "oklch(0.62 0.13 330)",
  "oklch(0.58 0.12 145)",
  "oklch(0.55 0.10 25)",
];

function logoColorFor(name: string) {
  let h = 0; for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return LOGO_PALETTE[h % LOGO_PALETTE.length];
}

function timeAgo(iso: string | null): string {
  if (!iso) return "-";
  const t = new Date(iso).getTime();
  if (isNaN(t)) return iso;
  const dh = (Date.now() - t) / 36e5;
  if (dh < 1) return `${Math.max(1, Math.round(dh * 60))}m`;
  if (dh < 24) return `${Math.round(dh)}h`;
  const dd = dh / 24;
  if (dd < 7) return `${Math.round(dd)}d`;
  if (dd < 30) return `${Math.round(dd / 7)}w`;
  return `${Math.round(dd / 30)}mo`;
}

// Age in whole days — used to surface the recency penalty applied by the
// scoring model. Matches the brackets in match_score.py's _RECENCY_MULTIPLIER.
function ageDaysFor(job: JobSummary): number | null {
  const stamps = [job.posted, (job as unknown as { first_seen?: string | null }).first_seen]
    .filter((s): s is string => typeof s === "string" && s.length > 0)
    .map(s => new Date(s).getTime())
    .filter(t => !isNaN(t));
  if (stamps.length === 0) return null;
  const newest = Math.max(...stamps);
  return Math.max(0, Math.floor((Date.now() - newest) / 86_400_000));
}

function recencyTone(days: number | null): "fresh" | "recent" | "aging" | "stale" | "dead" | "unknown" {
  if (days === null) return "unknown";
  if (days <= 7) return "fresh";
  if (days <= 14) return "recent";
  if (days <= 21) return "aging";
  if (days <= 28) return "stale";
  return "dead";
}

function JobCard({ job, onOpen, pinned, onPin, rank }: {
  job: JobSummary; onOpen: () => void; pinned: boolean; onPin: () => void; rank: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const match = job.match_score ?? 0;
  const top = match >= 85;
  const age = ageDaysFor(job);
  const tone = recencyTone(age);
  const toneColors: Record<"fresh" | "recent" | "aging" | "stale" | "dead" | "unknown", string> = {
    fresh: "var(--primary)",
    recent: "var(--on-surface)",
    aging: "var(--on-surface-variant)",
    stale: "var(--warn)",
    dead: "var(--error)",
    unknown: "var(--outline)",
  };
  const ageLabel = age === null ? null : age === 0 ? "today" : age <= 30 ? `${age}d ago` : `${Math.round(age / 7)}w ago`;

  const axes = {
    skills: job.fit_score ?? match,
    urgency: job.urgency_score ?? 50,
    friction: Math.max(0, 100 - (job.friction_score ?? 50)),
    confidence: job.confidence_score ?? 60,
  };

  const logo = job.company.charAt(0).toUpperCase();
  const color = logoColorFor(job.company);
  const reasoning = job.llm_blurb
    || job.guidance_summary
    || (job.recommendation_reasons.length ? job.recommendation_reasons.join(" · ") : null)
    || job.guidance_title
    || "No ranking reasoning yet — run match scoring to enrich this role.";

  return (
    <div className="card" style={{ padding: 0, position: "relative", overflow: "hidden" }}>
      {top && <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: "linear-gradient(to right, transparent, var(--primary), transparent)", opacity: 0.6 }}/>}
      <div style={{ display: "grid", gridTemplateColumns: "48px 1fr auto", gap: 18, padding: "20px 22px", alignItems: "flex-start" }}>

        <div className="col gap-8" style={{ alignItems: "center", paddingTop: 2 }}>
          <div className="mono" style={{ fontSize: 10, color: "var(--outline)", letterSpacing: "0.08em" }}>{String(rank).padStart(2, "0")}</div>
          <ScoreRing value={match} size={44}/>
        </div>

        <div style={{ minWidth: 0 }}>
          <div className="row gap-10" style={{ marginBottom: 6 }}>
            <CoLogo letter={logo} color={color} size={22}/>
            <span style={{ fontSize: 12.5, color: "var(--on-surface)", fontWeight: 500 }}>{job.company}</span>
            <span className="mono" style={{ fontSize: 10.5, color: "var(--outline)" }}>·</span>
            {job.ats && <span className="chip ghost mono">{job.ats}</span>}
            {job.match_band && <span className="chip ghost mono">{job.match_band}</span>}
          </div>
          <div style={{ fontSize: 18, fontWeight: 400, letterSpacing: "-0.01em", marginBottom: 6, color: "var(--on-surface)", fontFamily: "var(--font-serif)" }}>{job.title}</div>
          <div className="row gap-14" style={{ fontSize: 12, color: "var(--on-surface-variant)", marginBottom: 14 }}>
            <span className="hstack gap-6"><Icon name="globe" size={11}/>{job.location || "-"}</span>
            {job.posted && <span className="mono">{timeAgo(job.posted)} ago</span>}
            {ageLabel && (
              <span className="chip mono" style={{ color: toneColors[tone], borderColor: "var(--outline-variant)" }}>
                {tone === "stale" || tone === "dead" ? "stale · " : ""}{ageLabel}
              </span>
            )}
            {job.desired_title_match && <span className="mono" style={{ color: "var(--primary)" }}>title match</span>}
          </div>

          <div className="trace-block">
            <div className="trace-overline">Kenji's read</div>
            <div className="trace-text">{reasoning}</div>
          </div>

          <div style={{ display: "grid", gridTemplateRows: expanded ? "1fr" : "0fr", transition: "grid-template-rows 280ms cubic-bezier(0.22, 1, 0.36, 1)" }}>
            <div style={{ overflow: "hidden", minHeight: 0 }}>
              <div style={{ display: "grid", gridTemplateColumns: "160px 1fr", gap: 22, marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--outline-variant)" }}>
                <Radar axes={axes as unknown as Record<string, number>} size={150}/>
                <div className="col" style={{ gap: 9 }}>
                  {Object.entries(axes).map(([k, v]) => (
                    <div key={k} className="row gap-12">
                      <div className="mono" style={{ fontSize: 10.5, color: "var(--on-surface-variant)", width: 78, letterSpacing: "0.04em" }}>{k}</div>
                      <BarMeter value={v} color={v >= 85 ? "var(--primary)" : v >= 65 ? "var(--on-surface-variant)" : "var(--warn)"}/>
                      <div className="mono" style={{ fontSize: 11, color: "var(--on-surface)", width: 26, textAlign: "right" }}>{Math.round(v)}</div>
                    </div>
                  ))}
                  {job.required_skills.length > 0 && (
                    <div className="row gap-6" style={{ marginTop: 8, flexWrap: "wrap" }}>
                      {job.required_skills.slice(0, 6).map(s => <span key={s} className="chip mono">{s}</span>)}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>

          <div className="row gap-8" style={{ marginTop: 14 }}>
            <button className="btn primary sm" onClick={onOpen}>
              <Icon name="wand" size={12}/>Tailor & apply
            </button>
            <button className="btn sm" onClick={() => setExpanded(!expanded)}>
              {expanded ? "Hide breakdown" : "Breakdown"}
              <Icon name={expanded ? "chevronDown" : "chevron"} size={11}/>
            </button>
            <button className="btn ghost sm" onClick={onPin} style={{ color: pinned ? "var(--primary)" : undefined }}>
              <Icon name="pin" size={12}/>{pinned ? "Pinned" : "Pin"}
            </button>
            <div className="spacer"/>
            <a className="btn ghost sm" href={job.url} target="_blank" rel="noreferrer" aria-label={`View ${job.company} job posting (opens in new tab)`}><Icon name="external" size={12}/>Source</a>
          </div>
        </div>

        <div className="col gap-4" style={{ alignItems: "flex-end" }}>
          {top && <span className="chip accent mono">top match</span>}
        </div>
      </div>
    </div>
  );
}

export function Discover({ onOpenJob }: { onOpenJob: (job: JobSummary) => void }) {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [pinned, setPinned] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState<"all" | "top" | "remote" | "pinned" | "fresh">("all");
  const [sort, setSort] = useState<"match_desc" | "posted_desc" | "updated_desc" | "company_asc">("match_desc");

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true); setErr(null);
      try {
        const r = await api.listJobs({ status: "not_applied", sort, limit: 200 });
        if (!alive) return;
        setJobs(r.items);
        setTotal(r.total);
      } catch (e) {
        if (alive) setErr(e instanceof Error ? e.message : String(e));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [sort]);

  const filtered = useMemo(() => {
    if (filter === "top") return jobs.filter(j => (j.match_score ?? 0) >= 85);
    if (filter === "remote") return jobs.filter(j => j.location.toLowerCase().includes("remote"));
    if (filter === "pinned") return jobs.filter(j => pinned.has(j.id));
    if (filter === "fresh") return jobs.filter(j => {
      const a = ageDaysFor(j);
      return a !== null && a <= 14;
    });
    return jobs;
  }, [filter, pinned, jobs]);

  const topCount = jobs.filter(j => (j.match_score ?? 0) >= 85).length;
  const remoteCount = jobs.filter(j => j.location.toLowerCase().includes("remote")).length;
  const freshCount = jobs.filter(j => {
    const a = ageDaysFor(j);
    return a !== null && a <= 14;
  }).length;

  return (
    <div className="content">
      <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 40, alignItems: "end", marginBottom: 36, paddingBottom: 24, borderBottom: "1px solid var(--outline-variant)" }}>
        <div>
          <div className="overline" style={{ marginBottom: 14 }}>Discover · {total} in backlog</div>
          <div className="headline">
            Roles you might<br/><em>actually want.</em>
          </div>
          <div style={{ fontSize: 13.5, color: "var(--on-surface-variant)", marginTop: 14, maxWidth: 540, lineHeight: 1.55 }}>
            Ranked against your stories — not keywords. Kenji is showing the top{" "}
            <span className="mono" style={{ color: "var(--on-surface)" }}>{jobs.length}</span> of{" "}
            <span className="mono" style={{ color: "var(--on-surface)" }}>{total}</span> unapplied roles.
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14 }}>
          {([
            ["scanned", String(total), "unapplied"],
            ["ranked", String(topCount), "matched >= 85"],
            ["remote", String(remoteCount), "remote-friendly"],
          ] as const).map(([k, v, sub]) => (
            <div key={k} className="stat-item">
              <div className="stat-key">{k}</div>
              <div className="stat-val">{v}</div>
              <div className="stat-sub">{sub}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="row gap-6" style={{ marginBottom: 20 }}>
        {([
          ["all", `All · ${jobs.length}`],
          ["top", `Top · ${topCount}`],
          ["fresh", `Fresh · ${freshCount}`],
          ["remote", `Remote · ${remoteCount}`],
          ["pinned", `Pinned · ${pinned.size}`],
        ] as const).map(([id, label]) => (
          <button key={id} className={"btn sm " + (filter === id ? "accent-ghost" : "ghost")} onClick={() => setFilter(id)}>{label}</button>
        ))}
        <div className="spacer"/>
        <label className="row gap-6" style={{ fontSize: 10.5, color: "var(--outline)", letterSpacing: "0.06em" }}>
          <span className="mono">sort</span>
          <select
            value={sort}
            onChange={e => setSort(e.target.value as typeof sort)}
            className="mono"
            style={{
              background: "transparent",
              border: "1px solid var(--outline-variant)",
              borderRadius: 6,
              padding: "4px 8px",
              fontSize: 11,
              color: "var(--on-surface)",
              cursor: "pointer",
            }}
          >
            <option value="match_desc">match · desc</option>
            <option value="posted_desc">posted · newest</option>
            <option value="updated_desc">updated · newest</option>
            <option value="company_asc">company · A–Z</option>
          </select>
        </label>
      </div>

      {loading && (
        <div className="row" style={{ justifyContent: "center", padding: "48px 0" }}>
          <div className="boot-screen">
            <div className="boot-label">loading jobs<span className="boot-cursor">|</span></div>
            <div className="boot-bar" />
          </div>
        </div>
      )}
      {err && (
        <div className="card" style={{ padding: 16, borderColor: "var(--error)" }}>
          <div className="mono" style={{ color: "var(--error)", fontSize: 11 }}>backend error</div>
          <div style={{ fontSize: 12.5, marginTop: 6, color: "var(--on-surface-variant)" }}>{err}</div>
        </div>
      )}
      {!loading && !err && filtered.length === 0 && (
        <div style={{ padding: 40, textAlign: "center", color: "var(--on-surface-variant)" }}>
          <div className="serif italic" style={{ fontSize: 18 }}>No matching roles in the backlog.</div>
          <div className="mono" style={{ fontSize: 11, marginTop: 10, color: "var(--outline)" }}>run <span style={{ color: "var(--on-surface)" }}>uv run ai-job-hunter scrape</span> to refresh</div>
        </div>
      )}

      <div className="col gap-10 stagger">
        {filtered.map((j, i) => (
          <JobCard key={j.id} job={j} rank={i + 1}
            onOpen={() => onOpenJob(j)}
            pinned={pinned.has(j.id)}
            onPin={() => {
              const n = new Set(pinned);
              if (n.has(j.id)) n.delete(j.id); else n.add(j.id);
              setPinned(n);
            }}/>
        ))}
      </div>
    </div>
  );
}
