/* resume.jsx — Resume Lab */

const AtsBar = ({ label, score, note, state }) => (
  <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "10px 0", borderBottom: "1px solid var(--line)" }}>
    <div style={{ flex: "0 0 170px" }}>
      <div style={{ fontSize: 12.5, fontWeight: 400, color: "var(--ink)" }}>{label}</div>
      <div className="mono" style={{ fontSize: 10, color: "var(--ink-4)", marginTop: 3, letterSpacing: "0.02em" }}>{note}</div>
    </div>
    <BarMeter value={score} color={state === "warn" ? "var(--warn)" : "var(--accent)"}/>
    <div className="mono" style={{ fontSize: 11, color: state === "warn" ? "var(--warn)" : "var(--accent)", width: 32, textAlign: "right" }}>
      {score}
    </div>
  </div>
);

const Hi = ({ view, children }) => {
  if (view === "before" || view === "after") return children;
  return <mark style={{
    background: "var(--accent-soft)",
    color: "var(--accent)",
    padding: "0 3px",
    borderRadius: 2,
  }}>{children}</mark>;
};

const ResumeLab = ({ job }) => {
  const [view, setView] = useState("diff");
  const target = job || window.KENJI_DATA.jobs[0];
  const checks = window.KENJI_DATA.atsChecks;
  const overall = Math.round(checks.reduce((a,c) => a + c.score, 0) / checks.length);

  return (
    <div className="content wide" style={{ display: "grid", gridTemplateColumns: "1fr 400px", minHeight: "calc(100vh - 58px)" }}>
      {/* Resume canvas */}
      <div style={{ borderRight: "1px solid var(--line)", display: "flex", flexDirection: "column" }}>
        <div style={{ padding: "16px 28px", borderBottom: "1px solid var(--line)", display: "flex", alignItems: "center", gap: 10 }}>
          <div>
            <div style={{ fontWeight: 500, fontSize: 13.5 }}>arjun_rao_resume · <span className="mono" style={{ color: "var(--ink-3)", fontSize: 11.5 }}>v3 · tailored</span></div>
            <div className="mono" style={{ fontSize: 10, color: "var(--ink-4)", marginTop: 3, letterSpacing: "0.04em" }}>
              targeting {target.company} · {target.role}
            </div>
          </div>
          <div style={{ flex: 1 }}/>
          <div className="tweak-seg">
            <button className={view === "before" ? "on" : ""} onClick={() => setView("before")}>Before</button>
            <button className={view === "diff" ? "on" : ""} onClick={() => setView("diff")}>Diff</button>
            <button className={view === "after" ? "on" : ""} onClick={() => setView("after")}>After</button>
          </div>
          <button className="btn sm"><Icon name="copy" size={12}/>Export PDF</button>
        </div>

        <div style={{ padding: "32px 32px", overflowY: "auto", flex: 1 }}>
          <div style={{
            maxWidth: 680, margin: "0 auto",
            background: "#F2EFE8", color: "#1A1A1A",
            padding: "48px 56px", borderRadius: 4,
            boxShadow: "0 24px 64px -16px rgba(0,0,0,0.6), 0 2px 8px rgba(0,0,0,0.3)",
            fontFamily: "'Inter', sans-serif",
          }}>
            <div style={{ borderBottom: "1px solid #D4D1CA", paddingBottom: 18, marginBottom: 20 }}>
              <div style={{ fontFamily: "var(--font-serif)", fontSize: 32, letterSpacing: "-0.02em", lineHeight: 1, fontStyle: "normal" }}>Arjun Rao</div>
              <div className="mono" style={{ fontSize: 11, color: "#666", marginTop: 8, letterSpacing: "0.02em" }}>
                arjun@rao.dev · lisbon, pt · github.com/arao · in/arao
              </div>
            </div>

            <div style={{ marginBottom: 22 }}>
              <div className="mono" style={{ fontSize: 10, color: "#888", letterSpacing: "0.14em", textTransform: "uppercase" }}>Experience</div>
              <div style={{ marginTop: 10 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>Senior Engineer · Monzo</div>
                  <div className="mono" style={{ fontSize: 11, color: "#888" }}>2022 — 2024</div>
                </div>
                <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 12.5, lineHeight: 1.65 }}>
                  <li>Owned the merchant dispute product end-to-end — from API to React Native surface.</li>
                  <li>Shipped the <Hi view={view}>agent-driven evidence state machine</Hi> handling <b>40k disputes/month</b>.</li>
                  <li>
                    {view !== "before" ? (
                      <span>Designed the <Hi view={view}>agent-driven</Hi> evidence state machine; shipped <Hi view={view}>agent</Hi> tooling for ops; the <Hi view={view}>agent</Hi> cut resolution 11 → 3.4 days.</span>
                    ) : (
                      <span>Designed evidence-gathering state machine; cut resolution time 11 → 3.4 days.</span>
                    )}
                  </li>
                  <li>Wrote the FastAPI service backing it; drove a 3-engineer team via RFCs + async review.</li>
                </ul>
              </div>

              <div style={{ marginTop: 18 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>Engineer · Stripe</div>
                  <div className="mono" style={{ fontSize: 11, color: "#888" }}>2020 — 2022</div>
                </div>
                <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 12.5, lineHeight: 1.65 }}>
                  <li>Built Stripe's first <Hi view={view}>human-in-the-loop</Hi> fraud feedback pipeline.</li>
                  <li>Surfaced uncertain decisions to analysts, fed corrections into training. <b>F1 0.78 → 0.86</b>.</li>
                  <li>Partnered with risk-ops; shipped the UI they used daily.</li>
                </ul>
              </div>
            </div>

            <div style={{ marginBottom: 18 }}>
              <div className="mono" style={{ fontSize: 10, color: "#888", letterSpacing: "0.14em", textTransform: "uppercase" }}>Projects</div>
              <div style={{ marginTop: 8, fontSize: 12.5, lineHeight: 1.65 }}>
                <b>Kenji</b> — open-source job agent. React + FastAPI + Turso. <Hi view={view}>Agent</Hi> command center tailors résumés against ATS filters and ranks jobs against user stories. 2.1k stars.
              </div>
            </div>

            <div>
              <div className="mono" style={{ fontSize: 10, color: "#888", letterSpacing: "0.14em", textTransform: "uppercase" }}>Stack</div>
              <div style={{ marginTop: 8, fontSize: 12.5 }} className="mono">
                Python · FastAPI · TypeScript · React · Postgres · Turso · Temporal
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ATS rail */}
      <div style={{ padding: "24px 24px", display: "flex", flexDirection: "column", gap: 22, overflowY: "auto" }}>
        <div>
          <div className="overline" style={{ marginBottom: 14 }}>ATS · Greenhouse v3</div>
          <div style={{ display: "flex", alignItems: "center", gap: 16, padding: "16px 18px", background: "var(--accent-soft)", borderRadius: 12, border: "1px solid rgba(212,255,58,0.22)" }}>
            <ScoreRing value={overall} size={56}/>
            <div>
              <div style={{ fontSize: 15, color: "var(--accent)", fontFamily: "var(--font-serif)", fontStyle: "italic", letterSpacing: "-0.01em" }}>Likely to pass</div>
              <div className="mono" style={{ fontSize: 10.5, color: "var(--accent-dim)", marginTop: 2 }}>top {100 - overall}% · p=0.96</div>
            </div>
          </div>
          <div style={{ marginTop: 10 }}>
            {checks.map((c, i) => <AtsBar key={i} {...c}/>)}
          </div>
        </div>

        <div>
          <div className="overline" style={{ marginBottom: 12 }}>Grounding · every edit → a story</div>
          <div className="card" style={{ padding: 14, display: "flex", flexDirection: "column", gap: 10 }}>
            {[
              ["M.3 bullet", "s1 Monzo dispute", "agent-driven"],
              ["Stripe bullet", "s2 Stripe fraud", "human-in-the-loop"],
              ["Projects", "s3 Kenji OSS", "agent command center"],
            ].map(([loc, src, phrase], i) => (
              <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
                <Icon name="check" size={12} className="" />
                <div style={{ fontSize: 12 }}>
                  <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-3)" }}>{loc}</span>{" "}
                  <span style={{ color: "var(--ink-3)" }}>← {src}</span>
                  <div className="mono" style={{ fontSize: 10.5, color: "var(--accent)", background: "var(--accent-soft)", padding: "2px 6px", borderRadius: 3, display: "inline-block", marginTop: 5 }}>"{phrase}"</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div>
          <div className="overline" style={{ marginBottom: 12 }}>Recruiter red-team</div>
          <div className="card" style={{ padding: 16, fontSize: 12.5, lineHeight: 1.6, color: "var(--ink-2)" }}>
            <div className="mono" style={{ fontSize: 10, color: "var(--ink-4)", letterSpacing: "0.08em", marginBottom: 8, textTransform: "uppercase" }}>
              role-playing hiring manager
            </div>
            <div className="serif italic" style={{ fontSize: 15, color: "var(--ink)", lineHeight: 1.5, marginBottom: 10 }}>
              "Monzo dispute experience is the exact shape of what we're building. I'd bring them in. Only question — do they want zero-to-one, or is Monzo-scale where they're most comfortable?"
            </div>
            <button className="btn sm"><Icon name="pencil" size={11}/>Pre-empt this in cover letter</button>
          </div>
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: "auto", paddingTop: 16, borderTop: "1px solid var(--line)" }}>
          <button className="btn sm" style={{ flex: 1 }}><Icon name="mail" size={12}/>Draft cover</button>
          <button className="btn primary sm" style={{ flex: 1 }}><Icon name="send" size={12}/>Queue to apply</button>
        </div>
      </div>
    </div>
  );
};

Object.assign(window, { ResumeLab });
