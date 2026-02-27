import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { ThemeToggle } from "../ThemeToggle";

interface AppShellProps {
  isDark: boolean;
  onToggleTheme: () => void;
}

function BoardIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <rect x="4" y="5" width="7" height="6" rx="1.4" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <rect x="13" y="5" width="7" height="6" rx="1.4" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <rect x="4" y="13" width="16" height="6" rx="1.4" fill="none" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

function AnalyticsIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M4 19h16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <rect x="6" y="11" width="3" height="8" rx="1" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <rect x="11" y="8" width="3" height="11" rx="1" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <rect x="16" y="5" width="3" height="14" rx="1" fill="none" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

function ProfileIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle cx="12" cy="8" r="3.2" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path
        d="M5.5 18.5a6.5 6.5 0 0 1 13 0"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function AppShell({ isDark, onToggleTheme }: AppShellProps) {
  const [railExpanded, setRailExpanded] = useState(false);

  return (
    <div className={`app-shell ${railExpanded ? "rail-expanded" : "rail-collapsed"}`}>
      <button
        type="button"
        className={`rail-toggle-btn ${railExpanded ? "open" : ""}`}
        aria-label="Toggle navigation"
        aria-pressed={railExpanded}
        onClick={() => setRailExpanded((current) => !current)}
      >
        <span className="rail-toggle-icon" aria-hidden="true">
          <span className="rail-toggle-bar rail-toggle-bar-top" />
          <span className="rail-toggle-bar rail-toggle-bar-middle" />
          <span className="rail-toggle-bar rail-toggle-bar-bottom" />
        </span>
      </button>

      <aside className={`side-rail ${railExpanded ? "open" : ""}`}>
        <div className="rail-brand">
          <div className="rail-brand-copy">
            <p className="eyebrow">AI Job Hunter</p>
            <h1>Career Pipeline</h1>
          </div>
        </div>

        <nav className="rail-nav" aria-label="Primary navigation">
          <NavLink to="/" end className={({ isActive }) => `rail-link ${isActive ? "active" : ""}`} data-label="Board">
            <span className="rail-link-icon" aria-hidden="true"><BoardIcon /></span>
            <span className="rail-link-text">Board</span>
          </NavLink>
          <NavLink to="/analytics" className={({ isActive }) => `rail-link ${isActive ? "active" : ""}`} data-label="Analytics">
            <span className="rail-link-icon" aria-hidden="true"><AnalyticsIcon /></span>
            <span className="rail-link-text">Analytics</span>
          </NavLink>
          <NavLink to="/profile" className={({ isActive }) => `rail-link ${isActive ? "active" : ""}`} data-label="Profile">
            <span className="rail-link-icon" aria-hidden="true"><ProfileIcon /></span>
            <span className="rail-link-text">Profile</span>
          </NavLink>
        </nav>

        <div className="rail-meta">
          <p className="rail-meta-title">Focus</p>
          <p className="rail-meta-copy">Track every opportunity from backlog to offer.</p>
        </div>

        <div className="rail-footer">
          <ThemeToggle isDark={isDark} onToggle={onToggleTheme} />
        </div>
      </aside>

      <div className="shell-content">
        <div className="app-main">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
