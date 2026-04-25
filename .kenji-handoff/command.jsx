/* command.jsx — Agent Command Center */

const ToolCall = ({ name, status, children, needsApproval, onApprove, onReject }) => {
  const statusEl = status === "running" ? <span className="spinner"/>
    : status === "ok" ? <span style={{ color: "var(--accent)", fontFamily: "var(--font-mono)", fontSize: 10.5 }}>✓ done</span>
    : status === "waiting" ? <span className="mono" style={{ color: "var(--warn)", fontSize: 10.5 }}>awaiting approval</span>
    : null;
  return (
    <div className="tool-call">
      <div className="tool-head">
        <span className="tool-glyph mono">▸</span>
        <span className="tool-name mono">{name}</span>
        <span className="tool-status">{statusEl}</span>
      </div>
      <div className="tool-body mono">{children}</div>
      {needsApproval && (
        <div className="approval-bar">
          <span className="label mono">
            <span className="pulse" style={{ marginRight: 8 }}/>
            approval required — Kenji will not proceed without your ok
          </span>
          <span className="spacer"/>
          <button className="btn sm" onClick={onReject}><Icon name="x" size={11}/>Reject</button>
          <button className="btn primary sm" onClick={onApprove}><Icon name="check" size={11}/>Approve</button>
        </div>
      )}
    </div>
  );
};

const AgentMessage = ({ from, time, children, avatar }) => (
  <div className="agent-msg">
    <div className={"agent-avatar" + (from === "Arjun" ? " user" : "")}>{avatar}</div>
    <div className="agent-body">
      <div className="agent-name">{from}<span className="time mono">{time}</span></div>
      {children}
    </div>
  </div>
);

const Command = ({ setScreen, setTargetJob }) => {
  const [step, setStep] = useState(0);
  const [approved, setApproved] = useState(false);
  const [input, setInput] = useState("");
  const scrollRef = useRef(null);

  useEffect(() => {
    if (step < 5) {
      const t = setTimeout(() => setStep(step + 1), step === 0 ? 400 : 1400);
      return () => clearTimeout(t);
    }
  }, [step]);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [step, approved]);

  return (
    <div className="content wide" style={{ display: "grid", gridTemplateColumns: "1fr 340px", minHeight: "calc(100vh - 58px)" }}>
      {/* Thread */}
      <div style={{ borderRight: "1px solid var(--line)", display: "flex", flexDirection: "column" }}>
        <div style={{ padding: "20px 36px 16px", borderBottom: "1px solid var(--line)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <CoLogo letter="R" color="#7FE0D6" size={30}/>
              <div>
                <div style={{ fontWeight: 500, fontSize: 14 }}>Apply to <span style={{color:"var(--primary)", fontWeight: 700, letterSpacing:"-0.015em"}}>Resolute</span> · Founding Engineer, AI Agents</div>
                <div className="mono" style={{ fontSize: 10.5, color: "var(--outline)", marginTop: 3, letterSpacing: "0.04em" }}>
                  run-7f2a · started 2:14pm · 3 tools · 1 approval pending
                </div>
              </div>
            <div style={{ flex: 1 }}/>
            <span className="chip accent mono">
              <span className="pulse" style={{ width: 5, height: 5 }}/>active
            </span>
          </div>
        </div>

        <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", padding: "8px 36px 140px" }}>
          <AgentMessage from="Arjun" time="2:14pm" avatar="AR">
            <div className="agent-text">Apply me to the Resolute founding engineer role. Use the strongest framing of my Monzo dispute work.</div>
          </AgentMessage>

          {step >= 1 && <div className="fade-in">
            <AgentMessage from="Kenji" time="2:14pm" avatar="k">
              <div className="agent-text">
                On it. I'll pull the posting, pattern-match it against your stories, draft a tailored résumé, run it through an ATS simulator, and draft the cover letter. I'll stop for your <em>approval</em> before anything leaves your machine.
              </div>

              <ToolCall name="scrape.job_posting" status={step >= 2 ? "ok" : "running"}>
                <div className="line"><span className="k">url</span><span className="v">resolute.com/careers/founding-eng-agents</span></div>
                <div className="line"><span className="k">title</span><span className="v">Founding Engineer, AI Agents</span></div>
                <div className="line"><span className="k">stack</span><span className="v">Python · FastAPI · TypeScript · Postgres · Temporal</span></div>
                <div className="line"><span className="k">must_have</span><span className="v">agents_in_production, state_machines, evidence_pipelines</span></div>
                <div className="line"><span className="k">nice_to_have</span><span className="v">insurance_domain, async_culture</span></div>
                <div className="line"><span className="k">density</span><span className="v">agent×6 · evidence×4 · dispute×2</span></div>
              </ToolCall>
            </AgentMessage>
          </div>}

          {step >= 2 && <div className="fade-in">
            <AgentMessage from="Kenji" time="2:14pm" avatar="k">
              <div className="agent-text">
                Your <em>Monzo dispute</em> story is a near-perfect ground truth — state machines, evidence gathering, customer surfaces. I'll lead with it. Your Stripe fraud loop adds a human-in-the-loop signal they explicitly ask for.
              </div>

              <ToolCall name="match.stories_to_jd" status="ok">
                <div className="line good"><span className="k">s1 · Monzo</span><span className="v">strong · 4/4 must_have hits</span></div>
                <div className="line good"><span className="k">s2 · Stripe</span><span className="v">strong · matches HITL signal</span></div>
                <div className="line"><span className="k">s3 · Kenji OSS</span><span className="v">medium · proves agent ownership</span></div>
                <div className="line good"><span className="k">s4 · pref</span><span className="v">match · 12-eng team</span></div>
                <div className="line good"><span className="k">s5 · trait</span><span className="v">match · runs on RFCs</span></div>
              </ToolCall>
            </AgentMessage>
          </div>}

          {step >= 3 && <div className="fade-in">
            <AgentMessage from="Kenji" time="2:15pm" avatar="k">
              <div className="agent-text">
                Draft résumé <em>v3</em>. The only new phrasing pulls directly from your story text — nothing invented.
              </div>

              <ToolCall name="resume.tailor" status="ok">
                <div className="line"><span className="k">base</span><span className="v">arjun_rao_resume.pdf · v2024-11</span></div>
                <div className="line"><span className="k">edits</span><span className="v">7 bullets rewritten · 0 fabricated · 3 reordered</span></div>
                <div className="line"><span className="k">grounded_in</span><span className="v">s1, s2, s3</span></div>
                <div className="line good"><span className="k">truthfulness</span><span className="v">100% · every claim traces to a story</span></div>
              </ToolCall>

              <ToolCall name="ats.simulate" status="ok">
                <div className="line"><span className="k">filter</span><span className="v">Greenhouse AI-screener v3 · BERT-base</span></div>
                <div className="line good"><span className="k">pass_probability</span><span className="v">0.91 · top 8% of applicants</span></div>
                <div className="line"><span className="k">weak_signal</span><span className="v">keyword 'agent' 1× — posting uses it 6×</span></div>
                <div className="line"><span className="k">fix</span><span className="v">reword bullet 3 of Monzo section</span></div>
              </ToolCall>
            </AgentMessage>
          </div>}

          {step >= 4 && <div className="fade-in">
            <AgentMessage from="Kenji" time="2:15pm" avatar="k">
              <div className="agent-text">
                I'd like to make the keyword edit and open a <em>side-by-side diff</em>. Accept, reject, or rewrite line-by-line. After that I'll draft the cover letter.
              </div>

              <ToolCall
                name="resume.apply_edit"
                status={approved ? "ok" : "waiting"}
                needsApproval={!approved}
                onApprove={() => { setApproved(true); setStep(5); }}
                onReject={() => { setApproved(true); setStep(5); }}>
                <div className="line"><span className="k">edit</span><span className="v">bullet M.3 · Monzo section</span></div>
                <div style={{ background: "var(--danger-soft)", borderLeft: "2px solid var(--danger)", padding: "4px 10px", margin: "4px 0", borderRadius: "0 3px 3px 0" }}>
                  <span style={{ color: "var(--danger)" }}>−</span> <span style={{ color: "var(--ink-2)" }}>Designed evidence-gathering state machine, cut resolution 11 → 3.4 days.</span>
                </div>
                <div style={{ background: "var(--accent-soft)", borderLeft: "2px solid var(--accent)", padding: "4px 10px", margin: "4px 0", borderRadius: "0 3px 3px 0" }}>
                  <span style={{ color: "var(--accent)" }}>+</span> <span style={{ color: "var(--ink)" }}>Designed the <b style={{ color: "var(--accent)" }}>agent-driven</b> evidence state machine; shipped <b style={{ color: "var(--accent)" }}>agent</b> tooling for ops; the <b style={{ color: "var(--accent)" }}>agent</b> cut resolution 11→3.4 days.</span>
                </div>
                <div className="line"><span className="k">ats_delta</span><span className="v">0.91 → 0.96</span></div>
              </ToolCall>
            </AgentMessage>
          </div>}

          {step >= 5 && approved && <div className="fade-in">
            <AgentMessage from="Kenji" time="2:16pm" avatar="k">
              <div className="agent-text">
                Done. <em>Open Resume Lab</em> to see the final diff. I've also drafted a 160-word cover letter grounded in s1+s4 — send the package to Resolute's form, or hold for review?
              </div>
              <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                <button className="btn primary sm" onClick={() => { setTargetJob(window.KENJI_DATA.jobs[0]); setScreen("resume"); }}>
                  <Icon name="split" size={11}/>Open Resume Lab
                </button>
                <button className="btn sm"><Icon name="mail" size={11}/>Preview cover letter</button>
                <button className="btn ghost sm"><Icon name="pause" size={11}/>Hold</button>
              </div>
            </AgentMessage>
          </div>}

          {step < 5 && step >= 1 && (
            <div style={{ padding: "6px 0 0 38px" }}>
              <div className="typing"><span/><span/><span/></div>
            </div>
          )}
        </div>

        {/* Composer */}
        <div style={{ position: "sticky", bottom: 0, background: "linear-gradient(to top, var(--surface) 70%, transparent)", padding: "16px 36px 28px" }}>
          <div style={{
            border: "1px solid var(--outline-variant)",
            background: "var(--sc-lowest)",
            borderRadius: 12,
            padding: 12,
            boxShadow: "var(--shadow-2)",
          }}>
            <div style={{ display: "flex", gap: 6, marginBottom: 10, flexWrap: "wrap" }}>
              <span className="chip mono">
                <Icon name="file" size={10}/>resume · v2024-11
              </span>
              <span className="chip primary mono">
                <Icon name="target" size={10}/>target: Resolute
              </span>
              <span className="chip ghost mono" style={{ cursor: "pointer" }}>
                <Icon name="plus" size={10}/>add context
              </span>
            </div>
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              placeholder="Tell Kenji what to do — 'draft a cover letter grounded in s1' or 'queue for nightly resubmit'…"
              style={{
                width: "100%", resize: "none", border: 0, outline: 0,
                background: "transparent", minHeight: 56, lineHeight: 1.55,
                fontSize: 13.5, color: "var(--on-surface)",
              }}/>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <button className="btn ghost sm"><Icon name="mic" size={12}/></button>
              <button className="btn ghost sm"><Icon name="plus" size={12}/>Attach</button>
              <span className="mono" style={{ fontSize: 10, color: "var(--outline)", marginLeft: 4 }}>haiku-4.5 · 14 tools</span>
              <div style={{ flex: 1 }}/>
              <span className="mono" style={{ fontSize: 10, color: "var(--outline)" }}>
                <span className="kbd">⌘</span><span className="kbd">↵</span>
              </span>
              <button className="btn primary sm" disabled={!input.trim()}>
                <Icon name="send" size={12}/>Send
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Right rail */}
      <div style={{ padding: "24px 24px", overflowY: "auto" }}>
        <div className="overline" style={{ marginBottom: 16 }}>Run timeline</div>
        <div style={{ position: "relative", paddingLeft: 18 }}>
          <div style={{ position: "absolute", left: 4, top: 8, bottom: 8, width: 1, background: "var(--line-3)" }}/>
          {[
            ["2:14:02", "Received instruction", "ok"],
            ["2:14:04", "scrape.job_posting", "ok"],
            ["2:14:18", "match.stories_to_jd", "ok"],
            ["2:14:41", "resume.tailor", "ok"],
            ["2:15:02", "ats.simulate", "ok"],
            ["2:15:19", "resume.apply_edit", approved ? "ok" : "wait"],
            ["—", "cover.draft", "queued"],
            ["—", "application.autofill", "blocked"],
          ].map(([t, label, st], i) => (
            <div key={i} style={{ position: "relative", paddingBottom: 14 }}>
              <div style={{
                position: "absolute", left: -14, top: 5,
                width: 9, height: 9, borderRadius: 50,
                background: st === "ok" ? "var(--accent)" : st === "wait" ? "var(--warn)" : st === "blocked" ? "var(--bg)" : "var(--ink-4)",
                border: st === "blocked" ? "1.5px dashed var(--line-3)" : "2px solid var(--bg)",
                boxShadow: st === "ok" ? "0 0 0 2px var(--bg), 0 0 6px rgba(212,255,58,0.4)" : "none",
              }}/>
              <div className="mono" style={{ fontSize: 10, color: "var(--ink-4)", letterSpacing: "0.04em" }}>{t}</div>
              <div style={{ fontSize: 12.5, color: st === "blocked" ? "var(--ink-4)" : "var(--ink)", fontWeight: 400 }}>{label}</div>
            </div>
          ))}
        </div>

        <div className="divider"/>

        <div className="overline" style={{ marginBottom: 14 }}>Guardrails</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8, fontSize: 12.5 }}>
          {[
            ["Never fabricate claims", true],
            ["Approve before submit", true],
            ["Ground every edit in a story", true],
            ["Auto-resubmit rejected apps", false],
          ].map(([l, on]) => (
            <div key={l} style={{ display: "flex", gap: 10, alignItems: "center", color: on ? "var(--ink-2)" : "var(--ink-4)" }}>
              <Icon name={on ? "check" : "dot"} size={12} className="" />
              <span>{l}</span>
              <span className={"chip mono " + (on ? "accent" : "")} style={{ marginLeft: "auto" }}>{on ? "on" : "off"}</span>
            </div>
          ))}
        </div>

        <div className="divider"/>

        <div className="overline" style={{ marginBottom: 14 }}>Memory, this run</div>
        <div className="card" style={{ padding: 12, fontSize: 12, color: "var(--ink-2)", background: "var(--bg-3)" }}>
          <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
            <Icon name="sparkles" size={13} />
            <div style={{ lineHeight: 1.5 }}>You prefer <span className="mono" style={{ color: "var(--accent)" }}>"agent-driven"</span> over <span className="mono" style={{ color: "var(--ink-3)" }}>"ML-powered"</span> for the Monzo work. I'll use this phrasing by default.</div>
          </div>
        </div>
      </div>
    </div>
  );
};

Object.assign(window, { Command });
