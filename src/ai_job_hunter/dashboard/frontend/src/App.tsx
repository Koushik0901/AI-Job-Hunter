// Kenji — root shell. Screen routing + tweaks panel + target-job handoff.
import { useEffect, useState } from "react";
import { Sidebar, TopBar, type Screen } from "./kenji/Shell";
import { Discover } from "./kenji/Discover";
import { Command } from "./kenji/Command";
import { ResumeLab } from "./kenji/ResumeLab";
import { Stories } from "./kenji/Stories";
import { Pipeline } from "./kenji/Pipeline";
import { Profile } from "./kenji/Profile";
import { Insights } from "./kenji/Insights";
import type { JobSummary } from "./api";
import { useData } from "./DataContext";

type Density = "comfortable" | "compact";
type AgentVoice = "warm" | "direct" | "terse";

interface KenjiTweaks { density?: Density; agentVoice?: AgentVoice }

declare global {
  interface Window { KENJI_TWEAKS?: KenjiTweaks }
}

export function App() {
  const { loading, error, agentUnread, setOnAgentScreen } = useData();
  const [screen, setScreen] = useState<Screen>("discover");
  const [targetJob, setTargetJob] = useState<JobSummary | null>(null);
  const [tweaksOpen, setTweaksOpen] = useState(false);
  const [density, setDensity] = useState<Density>(window.KENJI_TWEAKS?.density || "comfortable");
  const [agentVoice, setAgentVoice] = useState<AgentVoice>(window.KENJI_TWEAKS?.agentVoice || "warm");

  useEffect(() => {
    const s = localStorage.getItem("kenji-screen") as Screen | null;
    if (s && ["discover", "command", "pipeline", "resume", "stories", "insights", "profile"].includes(s)) setScreen(s);
  }, []);
  useEffect(() => { localStorage.setItem("kenji-screen", screen); }, [screen]);

  useEffect(() => { setOnAgentScreen(screen === "command"); }, [screen, setOnAgentScreen]);

  useEffect(() => {
    document.body.classList.toggle("density-compact", density === "compact");
    document.body.classList.toggle("density-comfortable", density === "comfortable");
  }, [density]);

  useEffect(() => {
    document.body.dataset.agentVoice = agentVoice;
  }, [agentVoice]);

  useEffect(() => {
    const onMsg = (e: MessageEvent) => {
      const d = (e.data || {}) as { type?: string };
      if (d.type === "__activate_edit_mode") setTweaksOpen(true);
      if (d.type === "__deactivate_edit_mode") setTweaksOpen(false);
    };
    window.addEventListener("message", onMsg);
    window.parent.postMessage({ type: "__edit_mode_available" }, "*");
    return () => window.removeEventListener("message", onMsg);
  }, []);

  const persist = (edits: Partial<KenjiTweaks>) => {
    window.parent.postMessage({ type: "__edit_mode_set_keys", edits }, "*");
  };

  const onOpenJob = (job: JobSummary) => { setTargetJob(job); setScreen("command"); };

  if (loading) {
    return (
      <div className="app">
        <div className="main row" style={{ justifyContent: "center", alignItems: "center", minHeight: "100vh" }}>
          <div className="boot-screen">
            <div className="boot-label">booting kenji<span className="boot-cursor">|</span></div>
            <div className="boot-bar" />
          </div>
        </div>
      </div>
    );
  }
  if (error) {
    return (
      <div className="app">
        <div className="main col gap-12" style={{ alignItems: "center", justifyContent: "center", minHeight: "100vh" }}>
          <div className="mono" style={{ color: "var(--error)" }}>backend unreachable</div>
          <div style={{ fontSize: 12, color: "var(--outline)", maxWidth: 480, textAlign: "center" }}>{error}</div>
          <div className="mono" style={{ fontSize: 10.5, color: "var(--outline)" }}>start it with: <span style={{ color: "var(--on-surface)" }}>uv run ai-job-hunter-backend</span></div>
        </div>
      </div>
    );
  }

  return (
    <div className="app">
      <Sidebar screen={screen} setScreen={setScreen} unread={agentUnread}/>
      <div className="main">
        <TopBar screen={screen} targetCompany={targetJob?.company} targetRole={targetJob?.title}/>
        <div style={{ flex: 1, minWidth: 0 }} key={screen} className="fade-in">
          {screen === "discover" && <Discover onOpenJob={onOpenJob}/>}
          {screen === "command" && <Command setScreen={setScreen} targetJob={targetJob} setTargetJob={setTargetJob}/>}
          {screen === "pipeline" && <Pipeline/>}
          {screen === "resume" && <ResumeLab job={targetJob}/>}
          {screen === "stories" && <Stories/>}
          {screen === "insights" && <Insights/>}
          {screen === "profile" && <Profile/>}
        </div>
      </div>

      {tweaksOpen && (
        <div className="tweaks fade-in">
          <h4 className="mono">Tweaks</h4>
          <div className="tweak-row">
            <label>Density</label>
            <div className="tweak-seg">
              {(["comfortable", "compact"] as const).map(d => (
                <button key={d} className={density === d ? "on" : ""} onClick={() => { setDensity(d); persist({ density: d }); }}>{d}</button>
              ))}
            </div>
          </div>
          <div className="tweak-row">
            <label>Agent voice</label>
            <div className="tweak-seg">
              {(["warm", "direct", "terse"] as const).map(v => (
                <button key={v} className={agentVoice === v ? "on" : ""} onClick={() => { setAgentVoice(v); persist({ agentVoice: v }); }}>{v}</button>
              ))}
            </div>
          </div>
          <div className="tweak-row">
            <label>Jump to</label>
            <div className="tweak-seg">
              {([
                ["discover", "jobs"],
                ["command",  "agent"],
                ["pipeline", "pipeline"],
                ["resume",   "résumé"],
                ["stories",  "stories"],
                ["profile",  "profile"],
              ] as const).map(([id, l]) => (
                <button key={id} className={screen === id ? "on" : ""} onClick={() => setScreen(id)}>{l}</button>
              ))}
            </div>
          </div>
          <div style={{ fontSize: 10.5, color: "var(--outline)", marginTop: 10, fontFamily: "var(--font-mono)" }}>
            tweak the look · toggle off in toolbar
          </div>
        </div>
      )}
    </div>
  );
}
