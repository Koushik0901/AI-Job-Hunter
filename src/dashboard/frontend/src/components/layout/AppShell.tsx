import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { ThemeToggle } from "../ThemeToggle";

interface AppShellProps {
  isDark: boolean;
  onToggleTheme: () => void;
}

export function AppShell({ isDark, onToggleTheme }: AppShellProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="app-shell">
      <button
        type="button"
        className="mobile-rail-toggle"
        aria-label="Toggle navigation"
        onClick={() => setSidebarOpen((current) => !current)}
      >
        ☰
      </button>

      <aside className={`side-rail ${sidebarOpen ? "open" : ""}`}>
        <div className="rail-brand">
          <span className="rail-logo" aria-hidden="true">▣</span>
          <div>
            <p className="eyebrow">AI Job Hunter</p>
            <h1>Career Pipeline</h1>
          </div>
        </div>

        <nav className="rail-nav" aria-label="Primary navigation">
          <NavLink to="/" end className={({ isActive }) => `rail-link ${isActive ? "active" : ""}`} onClick={() => setSidebarOpen(false)}>
            <span className="rail-link-dot" aria-hidden="true" />
            Board
          </NavLink>
          <NavLink to="/profile" className={({ isActive }) => `rail-link ${isActive ? "active" : ""}`} onClick={() => setSidebarOpen(false)}>
            <span className="rail-link-dot" aria-hidden="true" />
            Profile
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
