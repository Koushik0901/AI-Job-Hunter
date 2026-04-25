/* stories.jsx — Guided user stories interview */

const StoryCard = ({ story, expanded, onToggle }) => {
  const kindColors = {
    experience: "#7FB4FF",
    project:    "#F6C66A",
    preference: "#D4FF3A",
    trait:      "#E89BC9",
  };
  const c = kindColors[story.kind] || "#86847F";
  return (
    <div className="card" style={{ padding: 0, overflow: "hidden", cursor: "pointer", transition: "border-color 120ms" }}
      onClick={onToggle}
      onMouseEnter={e => e.currentTarget.style.borderColor = "var(--line-3)"}
      onMouseLeave={e => e.currentTarget.style.borderColor = "var(--line)"}>
      <div style={{ padding: "16px 18px", display: "flex", gap: 14, alignItems: "flex-start" }}>
        <div style={{ width: 2, alignSelf: "stretch", background: c, borderRadius: 2, opacity: 0.75, marginTop: 4, minHeight: 30 }}/>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span className="mono" style={{ fontSize: 9.5, color: c, letterSpacing: "0.14em", textTransform: "uppercase" }}>
              {story.kind}
            </span>
            <span className="mono" style={{ fontSize: 10, color: "var(--ink-4)" }}>{story.id}</span>
            {story.period && <span className="mono" style={{ fontSize: 10, color: "var(--ink-4)", marginLeft: "auto" }}>{story.period}</span>}
          </div>
          <div style={{ fontSize: 16, fontWeight: 400, marginTop: 6, letterSpacing: "-0.01em", color: "var(--ink)", fontFamily: "var(--font-serif)", fontStyle: "italic" }}>{story.title}</div>
          {story.org && <div style={{ fontSize: 12, color: "var(--ink-3)", marginTop: 3 }}>{story.org}</div>}
          <div style={{ fontSize: 13, color: "var(--ink-2)", marginTop: 10, lineHeight: 1.6 }}>
            {expanded ? story.summary : story.summary.slice(0, 140) + (story.summary.length > 140 ? "…" : "")}
          </div>
          <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 12 }}>
            {story.tags.map(t => <span key={t} className="chip mono">{t}</span>)}
          </div>
        </div>
      </div>
    </div>
  );
};

const Stories = () => {
  const [expanded, setExpanded] = useState(null);
  const [draft, setDraft] = useState("");
  const [askIdx, setAskIdx] = useState(0);
  const stories = window.KENJI_DATA.stories;

  const prompts = [
    "Tell me about a time you shipped something hard at work. What did you own, what changed because of you?",
    "What kind of team size do you thrive in — and what have you learned avoiding?",
    "How do you think? In writing, in whiteboards, in code, out loud?",
    "What's a project you did for yourself that said more about you than your résumé did?",
  ];

  return (
    <div className="content" style={{ display: "grid", gridTemplateColumns: "1fr 400px", gap: 36, maxWidth: 1480 }}>
      <div>
        <div style={{ marginBottom: 28, paddingBottom: 24, borderBottom: "1px solid var(--line)" }}>
          <div className="overline" style={{ marginBottom: 14 }}>User stories · 5 captured</div>
          <div className="headline">
            You are more<br/>than a <em>résumé.</em>
          </div>
          <div style={{ fontSize: 13.5, color: "var(--ink-3)", marginTop: 14, maxWidth: 560, lineHeight: 1.6 }}>
            Stories ground everything Kenji does — ranking, tailoring, cover letters. Every edit to your application traces back to a story you've written. Nothing is invented.
          </div>
        </div>

        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 18 }}>
          <span className="chip accent mono">5 captured</span>
          <span className="chip mono">2 experiences</span>
          <span className="chip mono">1 project</span>
          <span className="chip mono">1 preference</span>
          <span className="chip mono">1 trait</span>
          <div style={{ flex: 1 }}/>
          <button className="btn sm"><Icon name="plus" size={12}/>Add story</button>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 10 }} className="stagger">
          {stories.map(s => (
            <StoryCard key={s.id} story={s}
              expanded={expanded === s.id}
              onToggle={() => setExpanded(expanded === s.id ? null : s.id)}/>
          ))}
        </div>
      </div>

      {/* Interview panel */}
      <div style={{ position: "sticky", top: 90, alignSelf: "start" }}>
        <div className="card lifted" style={{ padding: 22 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 18 }}>
            <div className="agent-avatar">k</div>
            <div>
              <div style={{ fontWeight: 500, fontSize: 13 }}>Kenji interview</div>
              <div className="mono" style={{ fontSize: 10, color: "var(--ink-4)", letterSpacing: "0.04em", marginTop: 2 }}>
                conversational · ~3 min
              </div>
            </div>
          </div>

          <div className="mono" style={{ fontSize: 10, color: "var(--ink-4)", letterSpacing: "0.14em", textTransform: "uppercase", marginBottom: 10 }}>
            Q · {askIdx + 1} / {prompts.length}
          </div>
          <div className="serif italic" style={{ fontSize: 22, lineHeight: 1.35, color: "var(--ink)", letterSpacing: "-0.01em" }}>
            "{prompts[askIdx]}"
          </div>

          <textarea
            value={draft}
            onChange={e => setDraft(e.target.value)}
            placeholder="Type, or tap the mic. Kenji will structure it into a story."
            style={{
              width: "100%", marginTop: 16,
              border: "1px solid var(--line-3)",
              borderRadius: 8, padding: "12px 14px",
              minHeight: 130, resize: "vertical",
              background: "var(--bg)", fontSize: 13, lineHeight: 1.55,
              color: "var(--ink)",
            }}
            onFocus={e => e.target.style.borderColor = "var(--ink-4)"}
            onBlur={e => e.target.style.borderColor = "var(--line-3)"}/>

          <div style={{ display: "flex", gap: 6, marginTop: 12, alignItems: "center" }}>
            <button className="btn ghost sm"><Icon name="mic" size={12}/>Voice</button>
            <button className="btn ghost sm" onClick={() => setAskIdx(Math.max(0, askIdx - 1))}>Back</button>
            <div style={{ flex: 1 }}/>
            <button className="btn ghost sm" onClick={() => { setDraft(""); setAskIdx((askIdx + 1) % prompts.length); }}>Skip</button>
            <button className="btn primary sm" onClick={() => { setDraft(""); setAskIdx((askIdx + 1) % prompts.length); }}>
              Next<Icon name="arrow" size={11}/>
            </button>
          </div>

          <div style={{ marginTop: 18, paddingTop: 16, borderTop: "1px solid var(--line)" }}>
            <div className="mono" style={{ fontSize: 10, color: "var(--ink-4)", letterSpacing: "0.14em", textTransform: "uppercase", marginBottom: 10 }}>
              What Kenji extracts
            </div>
            <div style={{ fontSize: 12, color: "var(--ink-3)", lineHeight: 1.6, display: "flex", flexDirection: "column", gap: 6 }}>
              <div style={{ display: "flex", gap: 10 }}>
                <span className="mono" style={{ color: "var(--accent)" }}>→</span>
                <span><b style={{ color: "var(--ink-2)" }}>Claim</b> — concrete outcome, quantified</span>
              </div>
              <div style={{ display: "flex", gap: 10 }}>
                <span className="mono" style={{ color: "var(--accent)" }}>→</span>
                <span><b style={{ color: "var(--ink-2)" }}>Ownership</b> — your contribution, verbatim</span>
              </div>
              <div style={{ display: "flex", gap: 10 }}>
                <span className="mono" style={{ color: "var(--accent)" }}>→</span>
                <span><b style={{ color: "var(--ink-2)" }}>Evidence</b> — links, metrics, screenshots</span>
              </div>
            </div>
          </div>
        </div>

        <div className="card" style={{ padding: 16, marginTop: 14, background: "var(--bg-2)" }}>
          <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
            <Icon name="sparkles" size={13}/>
            <div style={{ fontSize: 12, color: "var(--ink-3)", lineHeight: 1.55 }}>
              <span style={{ fontFamily: "var(--font-serif)", fontStyle: "italic", fontSize: 14, color: "var(--ink)" }}>Tip.</span>{" "}
              Import LinkedIn / GitHub to pre-fill the interview — you only edit, not type.
              <div style={{ marginTop: 10, display: "flex", gap: 6 }}>
                <button className="btn sm"><Icon name="external" size={11}/>LinkedIn</button>
                <button className="btn sm"><Icon name="external" size={11}/>GitHub</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

Object.assign(window, { Stories });
