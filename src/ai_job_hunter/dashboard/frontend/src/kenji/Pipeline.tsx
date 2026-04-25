// Kenji — Pipeline kanban board, wired to real backend job tracking
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api, type JobSummary } from "../api";
import { BarMeter, CoLogo, Icon, ScoreRing } from "./ui";

const STAGES = [
  { id: "staging",      label: "Staging",      sub: "drafting / queued",   tint: "var(--tertiary)",          softBg: "var(--tertiary-tint)" },
  { id: "applied",      label: "Applied",      sub: "submitted, waiting",  tint: "var(--secondary)",         softBg: "var(--secondary-container)" },
  { id: "interviewing", label: "Interviewing", sub: "scheduled rounds",    tint: "var(--primary)",           softBg: "var(--primary-tint)" },
  { id: "offer",        label: "Offer",        sub: "decide by deadline",  tint: "var(--primary-container)", softBg: "var(--primary-tint-2)" },
  { id: "rejected",     label: "Closed",       sub: "rejected / archived", tint: "var(--outline)",           softBg: "var(--sc-low)" },
] as const;

type StageId = (typeof STAGES)[number]["id"];

interface PipelineItem {
  id: string;
  logo: string;
  company: string;
  role: string;
  match: number;
  stage: StageId;
  note: string;
  updated: string;
  // staging
  resumeState?: "ready" | "drafting" | "queued";
  coverState?: "ready" | "drafting" | "queued";
  atsScore?: number | null;
  // applied
  submittedAt?: string;
  readReceipt?: boolean;
  daysAgo?: number;
  // interviewing
  round?: string;
  nextAt?: string;
  interviewer?: string;
  // offer
  comp?: string;
  offerDate?: string;
  deadline?: string;
  // rejected
  rejectedAt?: string;
  reason?: string;
}

function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "-";
  const t = new Date(iso).getTime();
  if (isNaN(t)) return "-";
  const dh = (Date.now() - t) / 36e5;
  if (dh < 1) return `${Math.max(1, Math.round(dh * 60))}m ago`;
  if (dh < 24) return `${Math.round(dh)}h ago`;
  const dd = dh / 24;
  if (dd < 7) return `${Math.round(dd)}d ago`;
  if (dd < 30) return `${Math.round(dd / 7)}w ago`;
  return `${Math.round(dd / 30)}mo ago`;
}

function daysSince(iso: string | null | undefined): number {
  if (!iso) return 0;
  const t = new Date(iso).getTime();
  if (isNaN(t)) return 0;
  return Math.max(0, Math.round((Date.now() - t) / 864e5));
}

function toItem(job: JobSummary): PipelineItem {
  const stage = job.status as StageId;
  const note =
    job.guidance_summary ||
    (job.recommendation_reasons.length ? job.recommendation_reasons[0] : null) ||
    job.guidance_title ||
    "no agent note yet — run scoring to enrich";

  const base: PipelineItem = {
    id: job.id,
    logo: job.company.charAt(0).toUpperCase(),
    company: job.company,
    role: job.title,
    match: job.match_score ?? 0,
    stage,
    note,
    updated: timeAgo(job.updated_at),
  };

  switch (stage) {
    case "staging":
      return { ...base, resumeState: "queued", coverState: "queued", atsScore: job.match_score };
    case "applied":
      return {
        ...base,
        submittedAt: timeAgo(job.updated_at),
        readReceipt: false,
        daysAgo: daysSince(job.updated_at),
      };
    case "interviewing":
      return {
        ...base,
        round: job.guidance_title || "Round 1",
        nextAt: "scheduled",
        interviewer: "-",
      };
    case "offer":
      return { ...base, comp: "-", offerDate: timeAgo(job.updated_at), deadline: "-" };
    case "rejected":
      return {
        ...base,
        rejectedAt: timeAgo(job.updated_at),
        reason: job.guidance_summary || "no reason recorded",
      };
    default:
      return base;
  }
}

function StagePill({ state, label }: { state: "ready" | "drafting" | "queued"; label: string }) {
  const map = {
    ready:    { bg: "var(--primary-tint)",  color: "var(--primary)",              spin: false, icon: "check" as const },
    drafting: { bg: "var(--tertiary-tint)", color: "var(--on-tertiary-container)", spin: true,  icon: null },
    queued:   { bg: "var(--sc-low)",        color: "var(--outline)",              spin: false, icon: "dot"   as const },
  };
  const m = map[state];
  return (
    <span className="chip mono" style={{ background: m.bg, color: m.color, gap: 5, fontSize: 10 }}>
      {m.spin
        ? <span style={{ width: 8, height: 8, borderRadius: "50%", border: "1.2px solid currentColor", borderTopColor: "transparent", display: "inline-block", animation: "spin 0.7s linear infinite" }}/>
        : m.icon ? <Icon name={m.icon} size={9}/> : null}
      {label}
    </span>
  );
}

function PipelineCard({ item }: { item: PipelineItem }) {
  return (
    <div
      className="col gap-10 pipeline-card"
      style={{
        background: "var(--sc-lowest)", padding: 14,
        boxShadow: "var(--shadow-1)",
        borderRadius: 12,
        border: "1px solid transparent",
        transition: "box-shadow 140ms ease, border-color 140ms ease",
      }}
    >
      {/* Head */}
      <div className="row-top gap-10">
        <CoLogo letter={item.logo} size={28}/>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12.5, color: "var(--on-surface-variant)", fontWeight: 500 }}>{item.company}</div>
          <div style={{ fontFamily: "var(--font-display)", fontSize: 15, fontWeight: 600, letterSpacing: "-0.015em", color: "var(--on-surface)", lineHeight: 1.25, marginTop: 2 }}>
            {item.role}
          </div>
        </div>
        <ScoreRing value={item.match} size={32} stroke={2.5}/>
      </div>

      {/* Stage-specific body */}
      {item.stage === "staging" && (
        <div className="col gap-6">
          <div className="row gap-6" style={{ flexWrap: "wrap" }}>
            <StagePill state={item.resumeState!} label={`résumé · ${item.resumeState}`}/>
            <StagePill state={item.coverState!}  label={`cover · ${item.coverState}`}/>
          </div>
          {item.atsScore != null && (
            <div className="row gap-8">
              <span className="mono" style={{ fontSize: 9.5, color: "var(--outline)", letterSpacing: "0.08em", textTransform: "uppercase" }}>ATS</span>
              <BarMeter value={item.atsScore} color={item.atsScore >= 85 ? "var(--primary)" : "var(--tertiary)"}/>
              <span className="mono" style={{ fontSize: 10.5, color: "var(--on-surface-variant)", width: 22, textAlign: "right" }}>{item.atsScore}</span>
            </div>
          )}
        </div>
      )}

      {item.stage === "applied" && (
        <div className="col gap-4">
          <div className="mono" style={{ fontSize: 10.5, color: "var(--on-surface-variant)" }}>
            submitted {item.submittedAt}
          </div>
          <div className="row gap-8" style={{ fontSize: 11.5 }}>
            <span style={{
              width: 6, height: 6, borderRadius: "50%",
              background: item.readReceipt ? "var(--primary)" : "var(--outline-variant)",
              flexShrink: 0,
              animation: item.readReceipt ? "pulse 2s infinite" : "none",
            }}/>
            <span style={{ color: item.readReceipt ? "var(--primary)" : "var(--outline)" }}>
              {item.readReceipt ? "viewed" : "no signal"}
            </span>
            <span className="mono" style={{ color: "var(--outline)", marginLeft: "auto" }}>day {item.daysAgo}</span>
          </div>
        </div>
      )}

      {item.stage === "interviewing" && (
        <div className="col gap-6">
          <div className="mono" style={{ fontSize: 10, color: "var(--primary)", letterSpacing: "0.1em", textTransform: "uppercase", fontWeight: 600 }}>
            {item.round}
          </div>
          <div className="row gap-8" style={{
            padding: "8px 10px", background: "var(--primary-tint)",
            borderRadius: 8, fontSize: 12,
          }}>
            <Icon name="target" size={12}/>
            <div style={{ flex: 1, color: "var(--primary)", fontWeight: 500 }}>{item.nextAt}</div>
          </div>
          <div style={{ fontSize: 11.5, color: "var(--on-surface-variant)" }}>
            w/ <b style={{ color: "var(--on-surface)" }}>{item.interviewer}</b>
          </div>
        </div>
      )}

      {item.stage === "offer" && (
        <div className="col gap-8">
          <div className="col gap-4" style={{
            padding: "10px 12px",
            background: "linear-gradient(135deg, var(--primary-tint) 0%, rgba(0,96,85,0.16) 100%)",
            borderRadius: 10,
          }}>
            <div className="mono" style={{ fontSize: 9.5, color: "var(--primary)", letterSpacing: "0.14em", textTransform: "uppercase", fontWeight: 700 }}>offer in hand</div>
            <div style={{ fontFamily: "var(--font-display)", fontSize: 20, fontWeight: 700, letterSpacing: "-0.02em", color: "var(--primary)", lineHeight: 1 }}>
              {item.comp}
            </div>
          </div>
          <div className="row gap-10" style={{ fontSize: 11.5, color: "var(--on-surface-variant)" }}>
            <span>offered {item.offerDate}</span>
            <span style={{ marginLeft: "auto", color: "var(--tertiary)", fontWeight: 500 }}>decide by {item.deadline}</span>
          </div>
        </div>
      )}

      {item.stage === "rejected" && (
        <div className="col gap-4">
          <div className="mono" style={{ fontSize: 10.5, color: "var(--outline)" }}>closed {item.rejectedAt}</div>
          <div style={{ fontSize: 11.5, color: "var(--on-surface-variant)", lineHeight: 1.45, fontStyle: "italic" }}>
            "{item.reason}"
          </div>
        </div>
      )}

      {/* Kenji note */}
      <div className="row-top gap-6" style={{
        fontSize: 11.5, lineHeight: 1.5,
        color: "var(--on-surface-variant)",
        paddingTop: 9, borderTop: "1px dashed var(--outline-variant)",
      }}>
        <span style={{
          width: 16, height: 16, borderRadius: 5, flexShrink: 0,
          background: "var(--primary)", color: "#fff",
          fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 9,
          display: "grid", placeItems: "center", marginTop: 1,
          letterSpacing: "-0.02em",
        }}>K</span>
        <span>{item.note}</span>
      </div>

      <div className="row gap-6" style={{ fontSize: 10.5, color: "var(--outline)" }}>
        <span className="mono" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 120 }}>#{item.id}</span>
        <span style={{ marginLeft: "auto" }} className="mono">updated {item.updated}</span>
      </div>
    </div>
  );
}

function Column({ stage, items, compact, onToggle }: {
  stage: typeof STAGES[number];
  items: PipelineItem[];
  compact: boolean;
  onToggle: () => void;
}) {
  const count = items.length;
  return (
    <div className="col" style={{
      minWidth: compact ? 68 : 296,
      maxWidth: compact ? 68 : 320,
      flexShrink: 0,
      transition: "min-width 200ms ease, max-width 200ms ease",
    }}>
      {/* Column head */}
      <div
        className="row gap-10"
        style={{
          padding: "10px 12px",
          background: stage.softBg,
          borderRadius: 12,
          marginBottom: 12,
          position: "sticky", top: 0, zIndex: 2,
          cursor: "pointer",
        }}
        onClick={onToggle}
      >
        <div style={{ width: 6, height: 6, borderRadius: "50%", background: stage.tint, flexShrink: 0 }}/>
        {!compact && (
          <>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="row gap-6" style={{ fontFamily: "var(--font-display)", fontSize: 13.5, fontWeight: 700, color: "var(--on-surface)", letterSpacing: "-0.01em" }}>
                {stage.label}
                <span className="mono" style={{ fontSize: 10, color: "var(--on-surface-variant)", fontWeight: 400 }}>· {count}</span>
              </div>
              <div className="mono" style={{ fontSize: 9.5, color: "var(--on-surface-variant)", letterSpacing: "0.04em", marginTop: 1 }}>
                {stage.sub}
              </div>
            </div>
            <Icon name="plus" size={12}/>
          </>
        )}
        {compact && (
          <div style={{ fontFamily: "var(--font-display)", fontSize: 12, fontWeight: 700, color: "var(--on-surface)" }}>{count}</div>
        )}
      </div>

      {!compact && (
        <div className="col gap-10 stagger">
          {items.map(it => <PipelineCard key={it.id} item={it}/>)}
          {items.length === 0 && (
            <div style={{
              padding: "22px 14px", textAlign: "center",
              border: "1px dashed var(--outline-variant)",
              borderRadius: 10, fontSize: 11.5,
              color: "var(--outline)", fontStyle: "italic",
            }}>
              nothing here yet
            </div>
          )}
        </div>
      )}
      {compact && (
        <div className="mono" style={{
          fontSize: 10, color: "var(--outline)",
          writingMode: "vertical-rl", transform: "rotate(180deg)",
          margin: "0 auto", letterSpacing: "0.14em", textTransform: "uppercase",
        }}>{stage.label}</div>
      )}
    </div>
  );
}

export function Pipeline() {
  const [all, setAll] = useState<PipelineItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [addOpen, setAddOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      api.listJobs({ status: "staging",      limit: 100 }),
      api.listJobs({ status: "applied",      limit: 100 }),
      api.listJobs({ status: "interviewing", limit: 100 }),
      api.listJobs({ status: "offer",        limit: 100 }),
      api.listJobs({ status: "rejected",     limit: 100 }),
    ]).then(([s, a, i, o, r]) => {
      if (cancelled) return;
      setAll([...s.items, ...a.items, ...i.items, ...o.items, ...r.items].map(toItem));
      setLoading(false);
    }).catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const byStage = useMemo(() => {
    const m: Record<string, PipelineItem[]> = {};
    STAGES.forEach(s => { m[s.id] = []; });
    all.forEach(it => { if (m[it.stage]) m[it.stage].push(it); });
    return m;
  }, [all]);

  const totals = STAGES.reduce((acc, s) => ({ ...acc, [s.id]: byStage[s.id]?.length ?? 0 }), {} as Record<string, number>);
  const totalActive = totals.staging + totals.applied + totals.interviewing + totals.offer;

  const toggle = (id: string) => {
    const n = new Set(collapsed);
    n.has(id) ? n.delete(id) : n.add(id);
    setCollapsed(n);
  };

  const offerCount = totals.offer;
  const interviewCount = totals.interviewing;
  const stagingCount = totals.staging;
  const insightText = offerCount > 0
    ? `You have ${offerCount === 1 ? "one live offer" : `${offerCount} live offers`} in play — review them before submitting new applications.`
    : interviewCount > 0
    ? `${interviewCount} active interview${interviewCount > 1 ? "s" : ""} — keep the pipeline warm but prioritise prep over new applications.`
    : stagingCount > 0
    ? `${stagingCount} role${stagingCount > 1 ? "s" : ""} in staging — finish the drafts and get them submitted.`
    : "Your pipeline is clear. Head to Discover to find your next opportunity.";

  if (loading) {
    return (
      <div className="row" style={{ justifyContent: "center", alignItems: "center", minHeight: 300 }}>
        <div className="boot-screen">
          <div className="boot-label">loading pipeline<span className="boot-cursor">|</span></div>
          <div className="boot-bar" />
        </div>
      </div>
    );
  }

  return (
    <div className="content wide" style={{ padding: "36px 40px 56px" }}>
      {/* Hero */}
      <div style={{
        marginBottom: 28, paddingBottom: 22,
        borderBottom: "1px solid var(--outline-variant)",
        display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 40, alignItems: "end",
      }}>
        <div>
          <div className="overline" style={{ marginBottom: 12 }}>Pipeline · every role you're in motion on</div>
          <div className="headline" style={{ fontSize: 48 }}>
            {totalActive} roles,{" "}
            <span style={{ fontFamily: "var(--font-display)", fontStyle: "italic", fontWeight: 500, color: "var(--primary)" }}>5 stages.</span>
          </div>
          <div style={{ fontSize: 14, color: "var(--on-surface-variant)", marginTop: 12, maxWidth: 560, lineHeight: 1.55 }}>
            Kenji tracks every application from draft to outcome. Cards move right as you progress — drop them back any time. The agent watches, learns which edits you kept, and applies them to the next role.
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 10 }}>
          {STAGES.map(s => (
            <div key={s.id} style={{ paddingTop: 8, borderTop: `2px solid ${s.tint}` }}>
              <div className="mono" style={{ fontSize: 9.5, color: "var(--on-surface-variant)", letterSpacing: "0.06em", textTransform: "uppercase" }}>{s.label}</div>
              <div style={{ fontFamily: "var(--font-display)", fontSize: 24, fontWeight: 700, letterSpacing: "-0.02em", color: "var(--on-surface)", lineHeight: 1, marginTop: 4 }}>{totals[s.id]}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Toolbar */}
      <div className="row gap-8" style={{ marginBottom: 22 }}>
        <div className="tweak-seg">
          <button className="on">All</button>
          <button>My turn</button>
          <button>This week</button>
          <button>&gt;= 85 match</button>
        </div>
        <div className="spacer"/>
        {totalActive > 0 && (
          <span className="mono" style={{ fontSize: 10.5, color: "var(--outline)", letterSpacing: "0.08em" }}>
            <span style={{ color: "var(--primary)" }}>●</span> {totalActive} in motion
          </span>
        )}
        <button className="btn sm"><Icon name="sliders" size={12}/>Columns</button>
        <button className="btn sm" onClick={() => setAddOpen(true)}>
          <Icon name="plus" size={12}/>Add role
        </button>
        <button className="btn primary sm"><Icon name="bolt" size={12}/>Run agent</button>
      </div>

      {addOpen && (
        <AddRoleModal
          onClose={() => setAddOpen(false)}
          onOptimisticAdd={(item) => {
            setAll((prev) => [item, ...prev]);
            setAddOpen(false);
          }}
          onResolved={(tempId, job, requestedStage) => {
            // Force the user-requested stage to win, even when the backend
            // returns a duplicate's existing tracking status.
            const coerced: JobSummary = { ...job, status: requestedStage };
            setAll((prev) => prev.map((p) => (p.id === tempId ? toItem(coerced) : p)));
            if (job.status !== requestedStage) {
              // Sync the backend so it matches what the user sees.
              api.updateTracking(job.id, { status: requestedStage }).catch(() => {
                // Best-effort; the card stays put either way.
              });
            }
          }}
          onFailed={(tempId, message) => {
            setAll((prev) => prev.filter((p) => p.id !== tempId));
            // Surface the error so the user knows nothing was saved.
            // Keeping it simple — no toast system in place yet.
            window.alert(`Couldn't add role: ${message}`);
          }}
        />
      )}

      {/* Board */}
      <div className="row gap-14" style={{
        alignItems: "flex-start",
        overflowX: "auto", paddingBottom: 20,
      }}>
        {STAGES.map(s => (
          <Column
            key={s.id}
            stage={s}
            items={byStage[s.id] ?? []}
            compact={collapsed.has(s.id)}
            onToggle={() => toggle(s.id)}
          />
        ))}
      </div>

      {/* Agent insight footer */}
      <div className="row-top gap-16" style={{
        marginTop: 24, padding: "18px 22px",
        background: "var(--sc-lowest)",
        border: "1px solid var(--outline-variant)",
        borderRadius: 16,
        boxShadow: "var(--shadow-1)",
      }}>
        <div style={{
          width: 32, height: 32, borderRadius: 10, flexShrink: 0,
          background: "var(--primary)", color: "#fff",
          fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 14,
          display: "grid", placeItems: "center",
          letterSpacing: "-0.02em",
        }}>K</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontFamily: "var(--font-display)", fontWeight: 600, fontSize: 13.5, color: "var(--on-surface)" }}>
            Kenji's read on your pipeline
          </div>
          <div style={{ fontSize: 14, color: "var(--on-surface)", lineHeight: 1.6, marginTop: 6, maxWidth: "72ch" }}>
            {insightText}
          </div>
          <div className="row gap-8" style={{ marginTop: 12, flexWrap: "wrap" }}>
            <button className="btn sm"><Icon name="bolt" size={11}/>Run agent on pipeline</button>
            <button className="btn sm"><Icon name="mail" size={11}/>Draft follow-ups</button>
            <button className="btn tertiary-ghost sm"><Icon name="pause" size={11}/>Review staging</button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---- Add role modal -------------------------------------------------------

interface AddRoleModalProps {
  onClose: () => void;
  onOptimisticAdd: (item: PipelineItem) => void;
  onResolved: (tempId: string, job: JobSummary, requestedStage: ManualStage) => void;
  onFailed: (tempId: string, message: string) => void;
}

type ManualStage = "staging" | "applied" | "interviewing" | "offer" | "rejected";

function AddRoleModal({ onClose, onOptimisticAdd, onResolved, onFailed }: AddRoleModalProps) {
  const [url, setUrl] = useState("");
  const [company, setCompany] = useState("");
  const [title, setTitle] = useState("");
  const [location, setLocation] = useState("");
  const [description, setDescription] = useState("");
  const [stage, setStage] = useState<ManualStage>("staging");

  // Close on Escape
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const canSubmit =
    url.trim().length >= 8 &&
    company.trim().length >= 1 &&
    title.trim().length >= 1 &&
    description.trim().length >= 1;

  const submit = () => {
    // eslint-disable-next-line no-console
    console.log("[AddRoleModal] submit clicked", {
      canSubmit,
      url_len: url.trim().length,
      company_len: company.trim().length,
      title_len: title.trim().length,
      description_len: description.trim().length,
      stage,
    });
    if (!canSubmit) return;
    const payload = {
      url: url.trim(),
      company: company.trim(),
      title: title.trim(),
      description: description.trim(),
      location: location.trim() || undefined,
      status: stage,
    };
    // Build an optimistic card with a temp id and render it immediately.
    const tempId = `pending-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const optimistic: PipelineItem = {
      id: tempId,
      logo: payload.company.charAt(0).toUpperCase(),
      company: payload.company,
      role: payload.title,
      match: 0,
      stage,
      note: "added manually — Kenji is enriching in the background",
      updated: "just now",
      ...(stage === "staging"   && { resumeState: "queued" as const, coverState: "queued" as const, atsScore: null }),
      ...(stage === "applied"   && { submittedAt: "just now", readReceipt: false, daysAgo: 0 }),
      ...(stage === "offer"     && { offerDate: "just now" }),
    };
    // eslint-disable-next-line no-console
    console.log("[AddRoleModal] firing onOptimisticAdd", optimistic);
    onOptimisticAdd(optimistic);
    // Fire the request in the background. Modal is already closed.
    api.createManualJob(payload)
      .then((job) => {
        // eslint-disable-next-line no-console
        console.log("[AddRoleModal] POST resolved", { id: job.id, status: job.status, requestedStage: stage });
        onResolved(tempId, job, stage);
      })
      .catch((err) => {
        const msg = err instanceof Error ? err.message : "Failed to add role";
        onFailed(tempId, msg);
      });
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="add-role-title"
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: 1000,
        background: "rgba(24,28,27,0.32)",
        display: "grid", placeItems: "center",
        padding: 24,
        animation: "fadeIn 200ms ease-out",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--surface)",
          borderRadius: 16,
          boxShadow: "0 24px 64px rgba(24,28,27,0.18), 0 8px 24px rgba(24,28,27,0.10)",
          width: "min(560px, 100%)",
          maxHeight: "calc(100vh - 48px)",
          overflow: "auto",
          padding: "28px 28px 24px",
        }}
      >
        <div className="overline" style={{ marginBottom: 6 }}>Pipeline · manual entry</div>
        <div id="add-role-title" className="headline" style={{ fontSize: 26, marginBottom: 6 }}>
          Add a role <span style={{ fontFamily: "var(--font-display)", fontStyle: "italic", fontWeight: 500, color: "var(--primary)" }}>by hand.</span>
        </div>
        <div style={{ fontSize: 13, color: "var(--on-surface-variant)", lineHeight: 1.5, marginBottom: 20 }}>
          For roles you found outside the scrapers. Paste the posting and Kenji will enrich and score it in the background.
        </div>

        <div style={{ display: "grid", gap: 12 }}>
          <Field label="Posting URL" required>
            <input
              className="field-input"
              placeholder="https://jobs.lever.co/..."
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              autoFocus
            />
          </Field>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Field label="Company" required>
              <input className="field-input" value={company} onChange={(e) => setCompany(e.target.value)} />
            </Field>
            <Field label="Role title" required>
              <input className="field-input" value={title} onChange={(e) => setTitle(e.target.value)} />
            </Field>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Field label="Location">
              <input className="field-input" placeholder="Remote · Canada" value={location} onChange={(e) => setLocation(e.target.value)} />
            </Field>
            <Field label="Stage">
              <select
                className="field-input"
                value={stage}
                onChange={(e) => setStage(e.target.value as typeof stage)}
              >
                <option value="staging">Staging</option>
                <option value="applied">Applied</option>
                <option value="interviewing">Interviewing</option>
                <option value="offer">Offer</option>
                <option value="rejected">Closed</option>
              </select>
            </Field>
          </div>
          <Field label="Job description" required>
            <textarea
              className="field-input"
              rows={8}
              placeholder="Paste the full job description here. Kenji uses this to score fit and generate tailoring."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              style={{ resize: "vertical", minHeight: 140, fontFamily: "inherit", lineHeight: 1.5 }}
            />
          </Field>
        </div>

        <div className="row gap-8" style={{ marginTop: 22, justifyContent: "flex-end" }}>
          <button className="btn sm" onClick={onClose}>Cancel</button>
          <button className="btn primary sm" onClick={submit} disabled={!canSubmit}>
            Add to pipeline
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, required, children }: { label: string; required?: boolean; children: ReactNode }) {
  return (
    <label style={{ display: "grid", gap: 6 }}>
      <span className="mono" style={{ fontSize: 10.5, color: "var(--on-surface-variant)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
        {label}{required && <span style={{ color: "var(--tertiary, #82442f)", marginLeft: 4 }}>*</span>}
      </span>
      {children}
    </label>
  );
}
