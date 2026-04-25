// Kenji — Resume Lab, wired to /api/jobs/{id}/artifacts + ATS critique.
import { useEffect, useMemo, useState } from "react";
import { api, type AtsCritiqueResponse, type JobArtifact, type JobSummary } from "../api";
import { useData } from "../DataContext";
import { BarMeter, Icon, ScoreRing } from "./ui";

function AtsBar({ label, score, note, state }: { label: string; score: number; note: string; state: "ok" | "warn" }) {
  return (
    <div className="row gap-14" style={{ padding: "10px 0", borderBottom: "1px solid var(--outline-variant)" }}>
      <div style={{ flex: "0 0 170px" }}>
        <div style={{ fontSize: 12.5, fontWeight: 400, color: "var(--on-surface)" }}>{label}</div>
        <div className="mono" style={{ fontSize: 10, color: "var(--outline)", marginTop: 3, letterSpacing: "0.02em" }}>{note}</div>
      </div>
      <BarMeter value={score} color={state === "warn" ? "var(--warn)" : "var(--primary)"}/>
      <div className="mono" style={{ fontSize: 11, color: state === "warn" ? "var(--warn)" : "var(--primary)", width: 32, textAlign: "right" }}>
        {score}
      </div>
    </div>
  );
}

export function ResumeLab({ job }: { job: JobSummary | null }) {
  const { profile } = useData();
  const [artifacts, setArtifacts] = useState<JobArtifact[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [view, setView] = useState<"before" | "diff" | "after">("after");
  const [critique, setCritique] = useState<AtsCritiqueResponse | null>(null);
  const [critiquing, setCritiquing] = useState(false);

  useEffect(() => {
    if (!job) { setArtifacts([]); setCritique(null); return; }
    let alive = true;
    setLoading(true); setErr(null); setCritique(null);
    (async () => {
      try {
        const list = await api.jobArtifacts(job.id);
        if (!alive) return;
        setArtifacts(list);
      } catch (e) {
        if (alive) setErr(e instanceof Error ? e.message : String(e));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [job?.id]);

  const resume = useMemo(() => artifacts.find(a => a.artifact_type === "resume" && a.is_active) || null, [artifacts]);
  const coverLetter = useMemo(() => artifacts.find(a => a.artifact_type === "cover_letter" && a.is_active) || null, [artifacts]);

  async function runCritique() {
    if (!job || !resume || critiquing) return;
    setCritiquing(true); setErr(null);
    try {
      const r = await api.atsCritique(job.id, resume.content_md);
      setCritique(r);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setCritiquing(false);
    }
  }

  // Build ATS-style checks list out of critique or fallback placeholder ones.
  const checks = useMemo(() => {
    if (critique) {
      const p = critique.pass_likelihood;
      return [
        { label: "Pass likelihood", score: p, note: `ATS simulator · top ${Math.max(1, 100 - p)}%`, state: (p < 70 ? "warn" : "ok") as "warn" | "ok" },
        { label: "Missing keywords", score: Math.max(0, 100 - (critique.missing_keywords.length * 15)), note: critique.missing_keywords.slice(0, 3).join(", ") || "none flagged", state: (critique.missing_keywords.length > 2 ? "warn" : "ok") as "warn" | "ok" },
        { label: "Weak sections", score: Math.max(0, 100 - (critique.weak_sections.length * 20)), note: critique.weak_sections.slice(0, 2).join(", ") || "no flags", state: (critique.weak_sections.length > 0 ? "warn" : "ok") as "warn" | "ok" },
        { label: "Suggestions", score: critique.suggestions.length > 0 ? 80 : 100, note: `${critique.suggestions.length} open`, state: "ok" as const },
      ];
    }
    if (!resume) return [];
    return [
      { label: "Artifact present", score: 100, note: `v${resume.version}`, state: "ok" as const },
      { label: "Length", score: Math.min(100, Math.round(resume.content_md.length / 30)), note: `${resume.content_md.length} chars`, state: "ok" as const },
      { label: "Stories grounded", score: Math.min(100, resume.story_ids_used.length * 20), note: `${resume.story_ids_used.length} stories cited`, state: "ok" as const },
      { label: "ATS critique", score: 0, note: "not run yet — click below", state: "warn" as const },
    ];
  }, [critique, resume]);

  const overall = checks.length ? Math.round(checks.reduce((a, c) => a + c.score, 0) / checks.length) : 0;

  if (!job) {
    return (
      <div className="content col" style={{ alignItems: "center", justifyContent: "center", minHeight: 400, gap: 14 }}>
        <div className="serif italic" style={{ fontSize: 22, color: "var(--on-surface)" }}>Pick a role from Discover first.</div>
        <div className="mono" style={{ fontSize: 11, color: "var(--outline)", letterSpacing: "0.12em", textTransform: "uppercase" }}>resume lab needs a target job</div>
      </div>
    );
  }

  return (
    <div className="content wide" style={{ display: "grid", gridTemplateColumns: "1fr clamp(280px, 30vw, 400px)", minHeight: "calc(100vh - 58px)" }}>
      {/* Resume canvas */}
      <div className="col" style={{ borderRight: "1px solid var(--outline-variant)" }}>
        <div className="row gap-10" style={{ padding: "16px 28px", borderBottom: "1px solid var(--outline-variant)" }}>
          <div>
            <div style={{ fontWeight: 500, fontSize: 13.5 }}>
              {(profile?.full_name || "you").toLowerCase().replace(/\s+/g, "_")}_resume ·{" "}
              <span className="mono" style={{ color: "var(--on-surface-variant)", fontSize: 11.5 }}>
                {resume ? `v${resume.version} · ${resume.is_active ? "active" : "archived"}` : "no draft yet"}
              </span>
            </div>
            <div className="mono" style={{ fontSize: 10, color: "var(--outline)", marginTop: 3, letterSpacing: "0.04em" }}>
              targeting {job.company} · {job.title}
            </div>
          </div>
          <div className="spacer"/>
          <div className="tweak-seg">
            <button className={view === "before" ? "on" : ""} onClick={() => setView("before")}>Before</button>
            <button className={view === "diff" ? "on" : ""} onClick={() => setView("diff")}>Diff</button>
            <button className={view === "after" ? "on" : ""} onClick={() => setView("after")}>After</button>
          </div>
          {resume && (
            <a className="btn sm" href={api.artifactPdfUrl(resume.id)} target="_blank" rel="noreferrer">
              <Icon name="copy" size={12}/>Export PDF
            </a>
          )}
        </div>

        <div style={{ padding: "32px 32px", overflowY: "auto", flex: 1 }}>
          {loading && (
            <div className="row" style={{ justifyContent: "center", padding: "48px 0" }}>
              <div className="boot-screen">
                <div className="boot-label">loading artifacts<span className="boot-cursor">|</span></div>
                <div className="boot-bar" />
              </div>
            </div>
          )}
          {err && (
            <div className="card" style={{ padding: 14, borderColor: "var(--error)" }}>
              <div className="mono" style={{ color: "var(--error)", fontSize: 11 }}>error</div>
              <div style={{ fontSize: 12.5, marginTop: 4, color: "var(--on-surface-variant)" }}>{err}</div>
            </div>
          )}
          {!loading && !resume && !err && (
            <div style={{
              maxWidth: 680, margin: "0 auto",
              background: "#F2EFE8", color: "#1A1A1A",
              padding: "48px 56px", borderRadius: 4,
              boxShadow: "0 24px 64px -16px rgba(0,0,0,0.6), 0 2px 8px rgba(0,0,0,0.3)",
            }}>
              <div className="serif italic" style={{ fontSize: 20, marginBottom: 12 }}>No résumé drafted for this role yet.</div>
              <div style={{ fontSize: 13, lineHeight: 1.6, color: "#444" }}>
                Head back to <b>Command</b> and say <code style={{ fontFamily: "var(--font-mono)" }}>/resume</code> to generate a tailored draft
                grounded in your user stories. Kenji will write it against <b>{job.company} · {job.title}</b>.
              </div>
            </div>
          )}
          {resume && (
            <div style={{
              maxWidth: 720, margin: "0 auto",
              background: "#F2EFE8", color: "#1A1A1A",
              padding: "48px 56px", borderRadius: 4,
              boxShadow: "0 24px 64px -16px rgba(0,0,0,0.6), 0 2px 8px rgba(0,0,0,0.3)",
              fontFamily: "'Inter', sans-serif",
              whiteSpace: "pre-wrap",
              lineHeight: 1.6,
              fontSize: 13,
            }}>
              {view === "before" && critique?.revised_resume ? resume.content_md : resume.content_md}
              {view === "diff" && critique?.revised_resume && (
                <>
                  <div style={{ background: "color-mix(in oklch, var(--error) 8%, transparent)", borderRadius: 6, padding: "6px 12px", marginBottom: 10 }}>
                    <div className="mono" style={{ fontSize: 10, color: "var(--error)", marginBottom: 4 }}>− current</div>
                    <div style={{ whiteSpace: "pre-wrap" }}>{resume.content_md.slice(0, 800)}{resume.content_md.length > 800 ? "…" : ""}</div>
                  </div>
                  <div style={{ background: "var(--primary-tint)", borderRadius: 6, padding: "6px 12px" }}>
                    <div className="mono" style={{ fontSize: 10, color: "var(--primary)", marginBottom: 4 }}>+ ATS-revised</div>
                    <div style={{ whiteSpace: "pre-wrap" }}>{critique.revised_resume.slice(0, 800)}{critique.revised_resume.length > 800 ? "…" : ""}</div>
                  </div>
                </>
              )}
              {view === "after" && (critique?.revised_resume || resume.content_md)}
              {view === "diff" && !critique?.revised_resume && (
                <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "#666" }}>
                  Run the ATS critique in the right rail to generate a revised version for diffing.
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ATS rail */}
      <div className="col gap-20" style={{ padding: "24px 24px", overflowY: "auto" }}>
        <div>
          <div className="overline" style={{ marginBottom: 14 }}>ATS · {job.ats || "generic"}</div>
          <div className="row gap-16" style={{ padding: "16px 18px", background: "var(--primary-tint)", borderRadius: 12, border: "1px solid rgba(0,96,85,0.22)" }}>
            <ScoreRing value={overall} size={56}/>
            <div>
              <div style={{ fontSize: 15, color: "var(--primary)", fontFamily: "var(--font-serif)", fontStyle: "italic", letterSpacing: "-0.01em" }}>
                {critique ? (critique.pass_likelihood >= 80 ? "Likely to pass" : critique.pass_likelihood >= 60 ? "Borderline" : "Needs work") : "Not yet simulated"}
              </div>
              <div className="mono" style={{ fontSize: 10.5, color: "var(--primary)", marginTop: 2 }}>
                {critique ? `p = ${(critique.pass_likelihood / 100).toFixed(2)}` : "run critique →"}
              </div>
            </div>
          </div>
          <div style={{ marginTop: 10 }}>
            {checks.map((c, i) => <AtsBar key={i} {...c}/>)}
          </div>
          <button className="btn sm" style={{ marginTop: 12, width: "100%" }}
            disabled={!resume || critiquing}
            onClick={runCritique}>
            {critiquing ? <><span className="spinner"/>running…</> : <><Icon name="bolt" size={11}/>Run ATS critique</>}
          </button>
        </div>

        {critique && (critique.missing_keywords.length > 0 || critique.suggestions.length > 0) && (
          <div>
            <div className="overline" style={{ marginBottom: 12 }}>Findings</div>
            <div className="card col gap-10" style={{ padding: 14 }}>
              {critique.missing_keywords.length > 0 && (
                <div>
                  <div className="mono" style={{ fontSize: 10, color: "var(--outline)", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 6 }}>
                    missing keywords
                  </div>
                  <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                    {critique.missing_keywords.map(k => <span key={k} className="chip mono" style={{ color: "var(--warn)" }}>{k}</span>)}
                  </div>
                </div>
              )}
              {critique.suggestions.length > 0 && (
                <div>
                  <div className="mono" style={{ fontSize: 10, color: "var(--outline)", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 6 }}>
                    suggestions
                  </div>
                  <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, lineHeight: 1.55, color: "var(--on-surface)" }}>
                    {critique.suggestions.map((s, i) => <li key={i}>{s}</li>)}
                  </ul>
                </div>
              )}
            </div>
          </div>
        )}

        {coverLetter && (
          <div>
            <div className="overline" style={{ marginBottom: 12 }}>Cover letter</div>
            <div className="card" style={{ padding: 14 }}>
              <div className="mono" style={{ fontSize: 10, color: "var(--outline)", marginBottom: 8 }}>v{coverLetter.version}</div>
              <div style={{ fontSize: 12.5, lineHeight: 1.6, whiteSpace: "pre-wrap", maxHeight: 180, overflowY: "auto", color: "var(--on-surface)" }}>
                {coverLetter.content_md.slice(0, 600)}{coverLetter.content_md.length > 600 ? "…" : ""}
              </div>
              <a className="btn sm" style={{ marginTop: 10 }} href={api.artifactPdfUrl(coverLetter.id)} target="_blank" rel="noreferrer">
                <Icon name="copy" size={11}/>Download cover PDF
              </a>
            </div>
          </div>
        )}

        <div className="row gap-8" style={{ marginTop: "auto", paddingTop: 16, borderTop: "1px solid var(--outline-variant)" }}>
          <a className="btn sm" style={{ flex: 1 }} href={job.url} target="_blank" rel="noreferrer">
            <Icon name="external" size={12}/>Open posting
          </a>
          <button className="btn primary sm" style={{ flex: 1 }}
            onClick={() => api.addToQueue(job.id).catch(e => setErr(e instanceof Error ? e.message : String(e)))}>
            <Icon name="send" size={12}/>Queue to apply
          </button>
        </div>
      </div>
    </div>
  );
}
