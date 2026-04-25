/* app.jsx — root */

const App = () => {
  const [screen, setScreen] = useState("command");
  const [targetJob, setTargetJob] = useState(null);
  const [tweaksOpen, setTweaksOpen] = useState(false);
  const [density, setDensity] = useState(window.KENJI_TWEAKS?.density || "comfortable");
  const [agentVoice, setAgentVoice] = useState(window.KENJI_TWEAKS?.agentVoice || "warm");

  // Persist screen
  useEffect(() => {
    const s = localStorage.getItem("kenji-screen");
    if (s) setScreen(s);
  }, []);
  useEffect(() => { localStorage.setItem("kenji-screen", screen); }, [screen]);

  useEffect(() => {
    document.body.classList.toggle("density-compact", density === "compact");
    document.body.classList.toggle("density-comfortable", density === "comfortable");
  }, [density]);

  useEffect(() => {
    document.body.dataset.agentVoice = agentVoice;
  }, [agentVoice]);

  // Tweaks wire-up — register listener BEFORE announcing availability
  useEffect(() => {
    const onMsg = (e) => {
      const d = e.data || {};
      if (d.type === "__activate_edit_mode") setTweaksOpen(true);
      if (d.type === "__deactivate_edit_mode") setTweaksOpen(false);
    };
    window.addEventListener("message", onMsg);
    window.parent.postMessage({ type: "__edit_mode_available" }, "*");
    return () => window.removeEventListener("message", onMsg);
  }, []);

  const persist = (edits) => {
    window.parent.postMessage({ type: "__edit_mode_set_keys", edits }, "*");
  };

  const onOpenJob = (job) => { setTargetJob(job); setScreen("command"); };

  return (
    <div className="app">
      <Sidebar screen={screen} setScreen={setScreen} unread={screen !== "command"}/>
      <div className="main">
        <TopBar screen={screen}/>
        <div style={{ flex: 1, minWidth: 0 }} key={screen} className="fade-in" data-screen-label={screenLabel(screen)}>
          {screen === "discover" && <Discover onOpenJob={onOpenJob}/>}
          {screen === "command" && <Command setScreen={setScreen} setTargetJob={setTargetJob} voice={agentVoice}/>}
          {screen === "resume" && <ResumeLab job={targetJob}/>}
          {screen === "stories" && <Stories/>}
        </div>
      </div>

      {tweaksOpen && (
        <div className="tweaks fade-in">
          <h4 className="mono">Tweaks</h4>
          <div className="tweak-row">
            <label>Density</label>
            <div className="tweak-seg">
              {["comfortable", "compact"].map(d => (
                <button key={d} className={density === d ? "on" : ""} onClick={() => { setDensity(d); persist({ density: d }); }}>{d}</button>
              ))}
            </div>
          </div>
          <div className="tweak-row">
            <label>Agent voice</label>
            <div className="tweak-seg">
              {["warm", "direct", "terse"].map(v => (
                <button key={v} className={agentVoice === v ? "on" : ""} onClick={() => { setAgentVoice(v); persist({ agentVoice: v }); }}>{v}</button>
              ))}
            </div>
          </div>
          <div className="tweak-row">
            <label>Jump to</label>
            <div className="tweak-seg">
              {[["discover", "jobs"], ["command", "agent"], ["resume", "résumé"], ["stories", "stories"]].map(([id, l]) => (
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
};

const screenLabel = (s) => ({
  discover: "01 Discover",
  command: "02 Command Center",
  resume: "03 Resume Lab",
  stories: "04 User Stories",
}[s] || s);

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
