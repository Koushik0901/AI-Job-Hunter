// Kenji — sidebar + topbar (wired to real backend stats/profile/stories)
import type { CSSProperties, ReactNode } from "react";
import { BrandMark, Icon } from "./ui";
import { useData } from "../DataContext";

export type Screen = "discover" | "command" | "pipeline" | "resume" | "stories" | "insights" | "profile" | "settings";

function initialsOf(name: string | null | undefined): string {
  if (!name) return "··";
  const parts = name.trim().split(/\s+/).slice(0, 2);
  return parts.map(p => p[0]?.toUpperCase() || "").join("") || "··";
}

export function Sidebar({ screen, setScreen, unread }: { screen: Screen; setScreen: (s: Screen) => void; unread: boolean }) {
  const { stats, stories, profile } = useData();
  const byStatus = stats?.by_status || {};
  const notApplied = byStatus["not_applied"] ?? 0;
  const activePipeline = stats?.active_pipeline ?? 0;

  const items: Array<{ id: Screen; label: string; icon: Parameters<typeof Icon>[0]["name"]; count?: number; badge?: string | null }> = [
    { id: "discover",  label: "Discover",     icon: "target",  count: notApplied },
    { id: "command",   label: "Command",      icon: "brain",   badge: unread ? "·" : null },
    { id: "pipeline",  label: "Pipeline",     icon: "pipe",    count: activePipeline },
    { id: "resume",    label: "Resume Lab",   icon: "doc" },
    { id: "stories",   label: "User Stories", icon: "book",    count: stories.length },
    { id: "insights",  label: "Insights",     icon: "sliders" },
    { id: "settings",  label: "Settings",     icon: "settings" },
  ];

  const displayName = profile?.full_name || "You";
  const location = [profile?.city, profile?.country].filter(Boolean).join(", ") || "profile incomplete";

  return (
    <aside className="sidebar">
      <div className="brand">
        <BrandMark size={26}/>
        <div className="col" style={{ gap: 2 }}>
          <div className="brand-name row gap-6" style={{ alignItems: "baseline" }}>
            <span>Kenji</span>
            <span style={{ color: "var(--outline)", fontFamily: "var(--font-mono)", fontSize: 10, fontWeight: 400, letterSpacing: "0.02em" }}>v0.4</span>
          </div>
          <div className="brand-sub mono">job agent · private</div>
        </div>
      </div>

      <div className="nav-section-label">Workspace</div>
      {items.map(it => (
        <button key={it.id}
          className={"nav-item" + (screen === it.id ? " active" : "")}
          onClick={() => setScreen(it.id)}
          aria-current={screen === it.id ? "page" : undefined}
          aria-label={it.label}>
          <Icon name={it.icon} size={14}/>
          <span>{it.label}</span>
          {it.count != null && <span className="nav-count mono">{it.count}</span>}
          {it.badge && <span className="pulse" style={{ marginLeft: "auto" }}/>}
        </button>
      ))}

      <div className="nav-sources">
        <div className="nav-section-label">Sources</div>
        <div className="nav-item"><span className="ni-dot" style={{ background: "var(--primary)" }}/>Greenhouse<span className="nav-count mono">live</span></div>
        <div className="nav-item"><span className="ni-dot" style={{ background: "var(--primary)" }}/>Lever<span className="nav-count mono">live</span></div>
        <div className="nav-item"><span className="ni-dot" style={{ background: "var(--primary)" }}/>Ashby + HN<span className="nav-count mono">live</span></div>
        <div className="nav-item" style={{ color: "var(--outline)" }}>
          <Icon name="plus" size={12}/> Add source
        </div>
      </div>

      <button className="sidebar-footer"
        onClick={() => setScreen("profile")}
        aria-label="Open profile settings"
        aria-current={screen === "profile" ? "page" : undefined}
        title="Open profile settings">
        <div style={{ position: "relative" }}>
          <div className={"avatar" + (screen === "profile" ? " active" : "")}
            style={screen === "profile" ? { boxShadow: "0 0 0 2px var(--primary)" } : {}}>
            {initialsOf(profile?.full_name)}
          </div>
          <div className="status-dot" style={{ position: "absolute", right: -1, bottom: -1 }}/>
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 12.5, fontWeight: 500, color: "var(--on-surface)" }}>{displayName}</div>
          <div className="mono" style={{ fontSize: 10, color: "var(--outline)" }}>{location}</div>
        </div>
        <Icon name="settings" size={14}
          style={{ color: screen === "profile" ? "var(--primary)" : "var(--outline)" } as CSSProperties}/>
      </button>
    </aside>
  );
}

export function TopBar({ screen, targetCompany, targetRole }: { screen: Screen; targetCompany?: string | null; targetRole?: string | null }) {
  const { stats, profile } = useData();
  const notApplied = stats?.by_status?.["not_applied"] ?? 0;
  const applied = stats?.by_status?.["applied"] ?? 0;

  const firstName = (profile?.full_name || "you").split(/\s+/)[0];

  const activePipeline = stats?.active_pipeline ?? 0;
  const titles: Record<Screen, { crumb: string; title: ReactNode }> = {
    discover: { crumb: "workspace / discover",  title: <>{notApplied} roles, <span style={{color:"var(--primary)"}}>ranked to you</span></> },
    command:  { crumb: "workspace / command",   title: <>Agent ready, <span style={{color:"var(--primary)"}}>{applied} applications sent</span></> },
    pipeline: { crumb: "workspace / pipeline",  title: <>{activePipeline} active, <span style={{color:"var(--primary)"}}>tracked by Kenji</span></> },
    resume:   { crumb: "workspace / resume lab", title: targetCompany ? <>Tailoring for <span style={{color:"var(--primary)"}}>{targetCompany}</span>{targetRole ? ` · ${targetRole}` : ""}</> : <>Resume Lab · <span style={{color:"var(--primary)"}}>pick a job</span></> },
    stories:  { crumb: "workspace / stories",   title: <>Who <span style={{color:"var(--primary)"}}>{firstName}</span> actually is</> },
    insights: { crumb: "workspace / insights",  title: <>Pipeline, <span style={{color:"var(--primary)"}}>read clearly</span></> },
    profile:  { crumb: "workspace / profile",   title: <>{firstName}, <span style={{color:"var(--primary)"}}>your career identity</span></> },
    settings: { crumb: "workspace / settings",  title: <>App <span style={{color:"var(--primary)"}}>settings</span></> },
  };
  const t = titles[screen];
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
}
