// Kenji — Command Center, wired to /api/agent/chat.
// Chat state (messages, sending, errors, unread flag) is owned by DataContext so
// the conversation survives navigation away from this screen and the sidebar
// can flag unread agent replies.
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { type JobSummary } from "../api";
import { useData } from "../DataContext";
import { CoLogo, Icon } from "./ui";
import type { Screen } from "./Shell";

function nowStamp() {
  return new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function OutputPayload({ kind, payload }: { kind: string; payload: Record<string, unknown> | null }) {
  if (!payload) return null;
  if (kind === "discovery") {
    const jobs = (payload.jobs as Array<{ id: string; company: string; title: string; match_score?: number | null }>) || [];
    return (
      <div className="tool-call">
        <div className="tool-head">
          <span className="tool-glyph mono">▸</span>
          <span className="tool-name mono">discover.jobs</span>
          <span className="tool-status"><span style={{ color: "var(--primary)", fontFamily: "var(--font-mono)", fontSize: 10.5 }}>✓ {jobs.length} hits</span></span>
        </div>
        <div className="tool-body mono col gap-4">
          {jobs.slice(0, 8).map(j => (
            <div key={j.id} className="line">
              <span className="k">{j.company}</span>
              <span className="v">{j.title}{j.match_score != null ? ` · ${j.match_score}` : ""}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }
  if (kind === "critique") {
    const p = payload as { pass_likelihood?: number; missing_keywords?: string[]; suggestions?: string[] };
    return (
      <div className="tool-call">
        <div className="tool-head">
          <span className="tool-glyph mono">▸</span>
          <span className="tool-name mono">ats.simulate</span>
          <span className="tool-status"><span style={{ color: "var(--primary)", fontFamily: "var(--font-mono)", fontSize: 10.5 }}>✓ done</span></span>
        </div>
        <div className="tool-body mono">
          <div className="line good"><span className="k">pass_probability</span><span className="v">{(p.pass_likelihood ?? 0) / 100}</span></div>
          {(p.missing_keywords ?? []).slice(0, 5).map((kw, i) => (
            <div key={i} className="line"><span className="k">missing</span><span className="v">{kw}</span></div>
          ))}
          {(p.suggestions ?? []).slice(0, 3).map((s, i) => (
            <div key={`s${i}`} className="line"><span className="k">suggest</span><span className="v">{s}</span></div>
          ))}
        </div>
      </div>
    );
  }
  if (kind === "resume" || kind === "cover_letter") {
    const md = typeof payload.content_md === "string" ? payload.content_md : "";
    return (
      <div className="tool-call">
        <div className="tool-head">
          <span className="tool-glyph mono">▸</span>
          <span className="tool-name mono">{kind === "resume" ? "resume.tailor" : "cover.draft"}</span>
          <span className="tool-status"><span style={{ color: "var(--primary)", fontFamily: "var(--font-mono)", fontSize: 10.5 }}>✓ drafted</span></span>
        </div>
        <div className="tool-body mono" style={{ whiteSpace: "pre-wrap", maxHeight: 240, overflowY: "auto", fontSize: 11.5, lineHeight: 1.5, color: "var(--on-surface)" }}>
          {md.slice(0, 1400)}{md.length > 1400 ? "\n…" : ""}
        </div>
      </div>
    );
  }
  return null;
}

function AgentMessage({ from, time, avatar, isUser, children }: {
  from: string; time: string; avatar: string; isUser: boolean; children: ReactNode;
}) {
  return (
    <div className="agent-msg">
      <div className={"agent-avatar" + (isUser ? " user" : "")}>{avatar}</div>
      <div className="agent-body">
        <div className="agent-name">{from}<span className="time mono">{time}</span></div>
        {children}
      </div>
    </div>
  );
}

export function Command({ setScreen, targetJob, setTargetJob }: {
  setScreen: (s: Screen) => void;
  targetJob: JobSummary | null;
  setTargetJob: (j: JobSummary | null) => void;
}) {
  const {
    profile, stats, recommendedJobs,
    agentMessages: messages, setAgentMessages,
    agentSending: sending, agentError: err,
    sendAgentMessage,
  } = useData();
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const firstName = (profile?.full_name || "You").split(/\s+/)[0];
  const userInitials = (profile?.full_name || "You").split(/\s+/).slice(0, 2).map(p => p[0]?.toUpperCase() ?? "").join("") || "·";

  // Seed welcome message once — only when the conversation is empty so it
  // doesn't overwrite history when the user re-enters this screen.
  useEffect(() => {
    if (messages.length > 0) return;
    const bestJob = targetJob || recommendedJobs[0] || null;
    const hint = bestJob
      ? `I've loaded ${bestJob.company} · ${bestJob.title} as your current target. Say the word and I'll draft a tailored résumé, run it through an ATS simulator, and prep the cover letter.`
      : `Pick a role from Discover and I'll tailor your résumé against it — or just tell me what you want. Try /discover "senior ml engineer", /resume, /cover-letter, /critique.`;
    setAgentMessages([{
      role: "assistant",
      content: hint,
      time: nowStamp(),
    }]);
  }, [messages.length, targetJob, recommendedJobs, setAgentMessages]);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, sending]);

  const parseSlash = (text: string): { skill: "discover" | "resume" | "cover-letter" | "critique" | null; args: string } => {
    const m = text.trim().match(/^\/(discover|resume|cover-letter|cover_letter|critique)\b\s*(.*)$/i);
    if (!m) return { skill: null, args: "" };
    const raw = m[1].toLowerCase();
    const skill = raw === "cover_letter" ? "cover-letter" : (raw as "discover" | "resume" | "cover-letter" | "critique");
    return { skill, args: m[2].trim() };
  };

  async function send() {
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    const { skill, args } = parseSlash(text);
    await sendAgentMessage(text, {
      skillInvocation: skill ? {
        name: skill,
        arguments: args,
        selected_job_id: targetJob?.id ?? null,
      } : undefined,
    });
  }

  const runStats = useMemo(() => {
    const s = stats?.by_status || {};
    return [
      ["active", String(stats?.active_pipeline ?? 0), "in pipeline"],
      ["applied", String(s["applied"] ?? 0), "this cohort"],
      ["recent", String(stats?.recent_activity_7d ?? 0), "last 7d"],
    ] as const;
  }, [stats]);

  return (
    <div className="content wide" style={{ display: "grid", gridTemplateColumns: "1fr 340px", minHeight: "calc(100vh - 58px)" }}>
      {/* Thread */}
      <div className="col" style={{ borderRight: "1px solid var(--outline-variant)" }}>
        <div style={{ padding: "20px 36px 16px", borderBottom: "1px solid var(--outline-variant)" }}>
          <div className="row gap-12">
            {targetJob ? (
              <>
                <CoLogo letter={targetJob.company.charAt(0).toUpperCase()} color="var(--primary)" size={30}/>
                <div>
                  <div style={{ fontWeight: 500, fontSize: 14 }}>
                    Apply to <span style={{ color: "var(--primary)", fontWeight: 700, letterSpacing: "-0.015em" }}>{targetJob.company}</span>
                    {" · "}{targetJob.title}
                  </div>
                  <div className="mono" style={{ fontSize: 10.5, color: "var(--outline)", marginTop: 3, letterSpacing: "0.04em" }}>
                    match {targetJob.match_score ?? "?"} · {targetJob.ats || "unknown ATS"} · {targetJob.status}
                  </div>
                </div>
                <button className="btn ghost sm" onClick={() => setTargetJob(null)} style={{ marginLeft: 8 }}>
                  <Icon name="x" size={10}/>clear
                </button>
              </>
            ) : (
              <>
                <div className="agent-avatar">k</div>
                <div>
                  <div style={{ fontWeight: 500, fontSize: 14 }}>
                    Talk to <span style={{ color: "var(--primary)", fontWeight: 700 }}>Kenji</span>
                  </div>
                  <div className="mono" style={{ fontSize: 10.5, color: "var(--outline)", marginTop: 3 }}>
                    no job targeted — use /discover or pick from Discover
                  </div>
                </div>
              </>
            )}
            <div className="spacer"/>
            <span className="chip accent mono">
              <span className="pulse" style={{ width: 5, height: 5 }}/>ready
            </span>
          </div>
        </div>

        <div ref={scrollRef} role="log" aria-live="polite" aria-atomic="false" style={{ flex: 1, overflowY: "auto", padding: "8px 36px 140px" }}>
          {messages.map((m, i) => (
            <div key={i} className={i === 0 ? "" : "fade-in"}>
              <AgentMessage
                from={m.role === "user" ? firstName : "Kenji"}
                time={m.time}
                avatar={m.role === "user" ? userInitials : "k"}
                isUser={m.role === "user"}>
                <div className="agent-text" style={{ whiteSpace: "pre-wrap" }}>{m.content}</div>
                {m.meta?.kind && m.meta.kind !== "none" && (
                  <OutputPayload kind={m.meta.kind} payload={m.meta.payload ?? null}/>
                )}
                {m.meta?.kind === "resume" && (
                  <div className="row gap-8" style={{ marginTop: 12 }}>
                    <button className="btn primary sm" onClick={() => setScreen("resume")}>
                      <Icon name="split" size={11}/>Open Resume Lab
                    </button>
                  </div>
                )}
              </AgentMessage>
            </div>
          ))}

          {sending && (
            <div style={{ padding: "6px 0 0 38px" }} aria-live="polite" aria-label="Kenji is thinking">
              <div className="typing" aria-hidden="true"><span/><span/><span/></div>
            </div>
          )}

          {err && (
            <div className="card" style={{ padding: 12, marginTop: 12, borderColor: "var(--error)" }}>
              <div className="mono" style={{ fontSize: 11, color: "var(--error)" }}>agent error</div>
              <div style={{ fontSize: 12.5, marginTop: 4, color: "var(--on-surface-variant)" }}>{err}</div>
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
            <div className="row gap-6" style={{ marginBottom: 10, flexWrap: "wrap" }}>
              {targetJob ? (
                <span className="chip primary mono">
                  <Icon name="target" size={10}/>target: {targetJob.company}
                </span>
              ) : (
                <span className="chip ghost mono">
                  <Icon name="target" size={10}/>no target
                </span>
              )}
              <span className="chip mono"><Icon name="file" size={10}/>/discover /resume /cover-letter /critique</span>
            </div>
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); send(); }
              }}
              placeholder={targetJob
                ? `Tell Kenji what to do — 'draft a résumé' or '/critique the current résumé'`
                : `/discover "staff ML role remote" — or type naturally`}
              style={{
                width: "100%", resize: "none", border: 0, outline: 0,
                background: "transparent", minHeight: 56, lineHeight: 1.55,
                fontSize: 13.5, color: "var(--on-surface)",
              }}/>
            <div className="row gap-6">
              <button className="btn ghost sm" disabled><Icon name="mic" size={12}/></button>
              <button className="btn ghost sm" disabled><Icon name="plus" size={12}/>Attach</button>
              <span className="mono" style={{ fontSize: 10, color: "var(--outline)", marginLeft: 4 }}>
                {sending ? "thinking…" : "ready"}
              </span>
              <div className="spacer"/>
              <span className="mono" style={{ fontSize: 10, color: "var(--outline)" }}>
                <span className="kbd">⌘</span><span className="kbd">↵</span>
              </span>
              <button className="btn primary sm" disabled={!input.trim() || sending} onClick={send}>
                <Icon name="send" size={12}/>Send
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Right rail */}
      <div style={{ padding: "24px 24px", overflowY: "auto" }}>
        <div className="overline" style={{ marginBottom: 16 }}>Pipeline pulse</div>
        <div className="col gap-10">
          {runStats.map(([k, v, sub]) => (
            <div key={k} className="card" style={{ padding: 12, display: "flex", alignItems: "baseline", gap: 10 }}>
              <div className="mono" style={{ fontSize: 10, color: "var(--outline)", letterSpacing: "0.08em", textTransform: "uppercase", width: 60 }}>{k}</div>
              <div className="serif" style={{ fontSize: 22, letterSpacing: "-0.02em", color: "var(--on-surface)" }}>{v}</div>
              <div className="mono" style={{ fontSize: 10.5, color: "var(--on-surface-variant)", marginLeft: "auto" }}>{sub}</div>
            </div>
          ))}
        </div>

        <div className="divider"/>

        <div className="overline" style={{ marginBottom: 14 }}>Top recommendations</div>
        <div className="col gap-8">
          {recommendedJobs.slice(0, 4).map(j => (
            <div key={j.id}
              className="card"
              style={{ padding: 10, cursor: "pointer" }}
              onClick={() => setTargetJob(j)}>
              <div style={{ fontSize: 12.5, color: "var(--on-surface)", fontWeight: 500 }}>{j.company}</div>
              <div style={{ fontSize: 11.5, color: "var(--on-surface-variant)", marginTop: 2 }}>{j.title}</div>
              <div className="mono" style={{ fontSize: 10, color: "var(--primary)", marginTop: 6 }}>match {j.match_score ?? "?"}</div>
            </div>
          ))}
          {recommendedJobs.length === 0 && (
            <div className="mono" style={{ fontSize: 11, color: "var(--outline)" }}>no bootstrap recommendations yet</div>
          )}
        </div>

        <div className="divider"/>

        <div className="overline" style={{ marginBottom: 14 }}>Guardrails</div>
        <div className="col gap-8" style={{ fontSize: 12.5 }}>
          {([
            ["Never fabricate claims", true],
            ["Approve before submit", true],
            ["Ground every edit in a story", true],
            ["Auto-resubmit rejected apps", false],
          ] as const).map(([l, on]) => (
            <div key={l} className="row gap-10" style={{ color: on ? "var(--on-surface)" : "var(--outline)" }}>
              <Icon name={on ? "check" : "dot"} size={12} />
              <span>{l}</span>
              <span className={"chip mono " + (on ? "accent" : "")} style={{ marginLeft: "auto" }}>{on ? "on" : "off"}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
