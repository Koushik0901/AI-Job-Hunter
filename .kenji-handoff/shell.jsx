/* shell.jsx — sidebar + topbar */

const Sidebar = ({ screen, setScreen, unread }) => {
  const items = [
    { id: "discover", label: "Discover", icon: "target", count: 124 },
    { id: "command", label: "Command", icon: "brain", badge: unread ? "·" : null },
    { id: "resume", label: "Resume Lab", icon: "doc" },
    { id: "stories", label: "User Stories", icon: "book", count: 5 },
  ];
  const pipeline = [
    { id: "applied", label: "Applied", count: 8 },
    { id: "drafted", label: "Drafts", count: 3 },
    { id: "archived", label: "Archived", count: 21 },
  ];
  return (
    <aside className="sidebar">
      <div className="brand">
        <BrandMark size={26}/>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <div className="brand-name" style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
            <span>Kenji</span>
            <span style={{ color: "var(--outline)", fontFamily: "var(--font-mono)", fontSize: 10, fontWeight: 400, letterSpacing: "0.02em" }}>v0.4</span>
          </div>
          <div className="brand-sub mono">job agent · private</div>
        </div>
      </div>

      <div className="nav-section-label">Workspace</div>
      {items.map(it => (
        <div key={it.id}
          className={"nav-item" + (screen === it.id ? " active" : "")}
          onClick={() => setScreen(it.id)}>
          <Icon name={it.icon} size={14}/>
          <span>{it.label}</span>
          {it.count != null && <span className="nav-count mono">{it.count}</span>}
          {it.badge && <span className="pulse" style={{ marginLeft: "auto" }}/>}
        </div>
      ))}

      <div className="nav-section-label">Pipeline</div>
      {pipeline.map(p => (
        <div key={p.id} className="nav-item">
          <span className="ni-dot"/>
          <span>{p.label}</span>
          <span className="nav-count mono">{p.count}</span>
        </div>
      ))}

      <div className="nav-section-label">Sources</div>
      <div className="nav-item"><span className="ni-dot" style={{ background: "var(--primary)" }}/>LinkedIn<span className="nav-count mono">live</span></div>
      <div className="nav-item"><span className="ni-dot" style={{ background: "var(--primary)" }}/>Wellfound<span className="nav-count mono">live</span></div>
      <div className="nav-item"><span className="ni-dot" style={{ background: "var(--primary)" }}/>Hacker News<span className="nav-count mono">live</span></div>
      <div className="nav-item" style={{ color: "var(--outline)" }}>
        <Icon name="plus" size={12}/> Add source
      </div>

      <div className="sidebar-footer">
        <div style={{ position: "relative" }}>
          <div className="avatar">AR</div>
          <div className="status-dot" style={{ position: "absolute", right: -1, bottom: -1 }}/>
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 12.5, fontWeight: 500, color: "var(--on-surface)" }}>Arjun Rao</div>
          <div className="mono" style={{ fontSize: 10, color: "var(--outline)" }}>3 runs today · 12¢</div>
        </div>
        <Icon name="settings" size={14} className="" />
      </div>
    </aside>
  );
};

const TopBar = ({ screen }) => {
  const titles = {
    discover: { crumb: "workspace / discover", title: <>124 roles, <span style={{color:"var(--primary)"}}>ranked to you</span></> },
    command: { crumb: "workspace / command", title: <>Agent is <span style={{color:"var(--primary)"}}>drafting</span> 2 tasks</> },
    resume: { crumb: "workspace / resume lab", title: <>Tailoring for <span style={{color:"var(--primary)"}}>Resolute</span> · Founding Engineer</> },
    stories: { crumb: "workspace / stories", title: <>Who <span style={{color:"var(--primary)"}}>Arjun</span> actually is</> },
  };
  const t = titles[screen] || {};
  return (
    <div className="topbar">
      <div className="topbar-title">
        <div>
          <div className="crumb mono">{t.crumb}</div>
          <h1>{t.title}</h1>
        </div>
      </div>
      <div className="topbar-actions">
        <button className="btn ghost sm"><Icon name="search" size={13}/>Find<span className="kbd">⌘K</span></button>
        <button className="btn sm"><Icon name="sparkles" size={13}/>Ask Kenji</button>
        <button className="btn primary sm"><Icon name="bolt" size={13}/>Run agent</button>
      </div>
    </div>
  );
};

Object.assign(window, { Sidebar, TopBar });
