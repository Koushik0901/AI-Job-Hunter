import { Suspense, useEffect, useState, lazy } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { BarChart2, Bot, ChevronLeft, ChevronRight, Home, LayoutDashboard, Menu, Settings, Sparkles, X, Keyboard } from "lucide-react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ThemedLoader } from "./components/ThemedLoader";
import { ThemeToggle } from "./components/ThemeToggle";
import { DashboardDataProvider } from "./contexts/DashboardDataContext";
import { useHotkeys } from "./hooks/useHotkeys";

// Lazy load pages for code splitting
const loadTodayPage = () => import("./pages/TodayPage");
const loadBoardPage = () => import("./pages/BoardPage");
const loadInsightsPage = () => import("./pages/InsightsPage");
const loadRecommendPage = () => import("./pages/RecommendPage");
const loadAgentPage = () => import("./pages/AgentPage");
const loadJobDetailPage = () => import("./pages/JobDetailPage");
const loadSettingsPage = () => import("./pages/SettingsPage");
const TodayPage = lazy(() => loadTodayPage().then(m => ({ default: m.TodayPage })));
const BoardPage = lazy(() => loadBoardPage().then(m => ({ default: m.BoardPage })));
const InsightsPage = lazy(() => loadInsightsPage().then(m => ({ default: m.InsightsPage })));
const RecommendPage = lazy(() => loadRecommendPage().then(m => ({ default: m.RecommendPage })));
const AgentPage = lazy(() => loadAgentPage().then(m => ({ default: m.AgentPage })));
const JobDetailPage = lazy(() => loadJobDetailPage().then(m => ({ default: m.JobDetailPage })));
const SettingsPage = lazy(() => loadSettingsPage().then(m => ({ default: m.SettingsPage })));

const SIDEBAR_COLLAPSED_KEY = "ajh_sidebar_collapsed";

const NAV_ITEMS = [
  { to: "/today", label: "Today", icon: Home },
  { to: "/board", label: "Board", icon: LayoutDashboard },
  { to: "/recommend", label: "Discover", icon: Sparkles },
  { to: "/agent", label: "Apply", icon: Bot },
  { to: "/insights", label: "Strategy", icon: BarChart2 },
  { to: "/settings", label: "Settings", icon: Settings },
] as const;

const ROUTE_PRELOADERS: Record<string, () => Promise<unknown>> = {
  "/today": loadTodayPage,
  "/board": loadBoardPage,
  "/recommend": loadRecommendPage,
  "/agent": loadAgentPage,
  "/insights": loadInsightsPage,
  "/settings": loadSettingsPage,
};

function prefetchRoute(pathname: string): void {
  const loader = ROUTE_PRELOADERS[pathname];
  if (!loader) return;
  void loader();
}

function KeyboardShortcutsModal({ onClose }: { onClose: () => void }) {
  const sections = [
    {
      title: "Global",
      keys: [
        { key: "?", label: "Toggle shortcuts legend" },
        { key: "Esc", label: "Close modal" },
      ],
    },
    {
      title: "Board / Discover",
      keys: [
        { key: "Enter", label: "Open focused job page" },
        { key: "S", label: "Staging / Add to Queue" },
        { key: "A", label: "Mark as Applied (Board)" },
        { key: "R", label: "Reject / Not a fit" },
        { key: "P", label: "Toggle Pin (Board)" },
      ],
    },
    {
      title: "Today",
      keys: [
        { key: "D", label: "Mark action as Done" },
        { key: "F", label: "Defer action" },
      ],
    },
  ];

  return (
    <div className="modal-overlay" onClick={onClose} style={{ zIndex: 3000 }}>
      <div className="modal-box shortcuts-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Keyboard size={20} />
            <h3>Keyboard Shortcuts</h3>
          </div>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="shortcuts-content">
          {sections.map((section) => (
            <div key={section.title} className="shortcut-section">
              <h4>{section.title}</h4>
              <div className="shortcut-grid">
                {section.keys.map((k) => (
                  <div key={k.key} className="shortcut-item">
                    <kbd className="kbd-key">{k.key}</kbd>
                    <span className="shortcut-label">{k.label}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function App() {
  const location = useLocation();
  const [theme, setTheme] = useState(() => {
    if (typeof window === "undefined") return "light";
    return window.localStorage.getItem("theme") || "light";
  });

  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    if (typeof window === "undefined") return false;
    try {
      return window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "true";
    } catch {
      return false;
    }
  });
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [showShortcuts, setShowShortcuts] = useState(false);

  useHotkeys("?", () => setShowShortcuts((s) => !s), []);
  useHotkeys("escape", () => setShowShortcuts(false), []);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);

  useEffect(() => {
    setMobileNavOpen(false);
  }, [location.pathname]);

  function toggleSidebar() {
    setSidebarCollapsed((prev) => {
      const next = !prev;
      try { window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(next)); } catch { /* ignore */ }
      return next;
    });
  }

  return (
    <Suspense fallback={<ThemedLoader label="Loading dashboard" />}>
      <DashboardDataProvider>
        <div className={`app-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>

        {/* ── Bottom Nav (Mobile) ── */}
        <nav className="bottom-nav">
          {NAV_ITEMS.slice(0, 5).map((item) => {
            const isActive = location.pathname === item.to;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) => `bottom-nav-link${isActive ? " active" : ""}`}
                onMouseEnter={() => prefetchRoute(item.to)}
                onFocus={() => prefetchRoute(item.to)}
              >
                <item.icon size={20} strokeWidth={isActive ? 2.4 : 2} className="bottom-nav-icon" />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
          <NavLink
            to="/settings"
            className={({ isActive }) => `bottom-nav-link${isActive ? " active" : ""}`}
            onMouseEnter={() => prefetchRoute("/settings")}
            onFocus={() => prefetchRoute("/settings")}
          >
            <Settings size={20} strokeWidth={location.pathname === "/settings" ? 2.4 : 2} className="bottom-nav-icon" />
            <span>Settings</span>
          </NavLink>
        </nav>

        <aside className={`side-nav ${sidebarCollapsed ? "side-nav--collapsed" : ""}`} aria-label="Primary navigation">
          {/* Identity block */}
          <div className="side-nav-top">
            <div className="side-nav-orb">
              <Sparkles size={20} strokeWidth={2} />
            </div>
            <div className="side-nav-identity">
              <span className="side-nav-identity-name">The Navigator</span>
              <span className="side-nav-identity-badge">Search system</span>
            </div>
          </div>

          <div className="side-nav-divider" />

          <nav className="side-nav-links" aria-label="Sidebar navigation">
            {NAV_ITEMS.map((item) => {
              const isActive = location.pathname === item.to;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={`side-nav-link${isActive ? " active" : ""}`}
                  aria-current={isActive ? "page" : undefined}
                  title={sidebarCollapsed ? item.label : undefined}
                  onMouseEnter={() => prefetchRoute(item.to)}
                  onFocus={() => prefetchRoute(item.to)}
                >
                  <item.icon size={21} strokeWidth={isActive ? 2.35 : 2} className="side-nav-link-icon" aria-hidden="true" />
                  <span className="side-nav-link-label">{item.label}</span>
                </NavLink>
              );
            })}
          </nav>

          {/* Bottom controls */}
          <div className="side-nav-bottom">
            <div className="side-nav-divider" />
            <div className="side-nav-bottom-row">
              <button
                className="side-nav-btn"
                onClick={() => setShowShortcuts(true)}
                title="Keyboard Shortcuts (?)"
                aria-label="Keyboard Shortcuts"
              >
                <Keyboard size={18} strokeWidth={2} />
              </button>
              <ThemeToggle
                isDark={theme === "dark"}
                onToggle={() => setTheme((c) => (c === "dark" ? "light" : "dark"))}
              />
              <div className="side-nav-avatar" aria-hidden="true">K</div>
            </div>
            {/* Collapse toggle (desktop) */}
            <button
              className="side-nav-collapse-btn"
              onClick={toggleSidebar}
              aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
              title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            >
              {sidebarCollapsed
                ? <ChevronRight size={16} strokeWidth={2.2} />
                : <ChevronLeft size={16} strokeWidth={2.2} />}
            </button>
          </div>
        </aside>

        {/* ── Main Layout Wrapper ── */}
        <div className="app-shell-main">
          {/* ── Mobile Top Bar ── */}
          <header className="mobile-top-bar">
            <div className="side-nav-orb side-nav-orb--sm" style={{ width: 32, height: 32 }}>
              <Sparkles size={14} strokeWidth={2} />
            </div>
            <span className="mobile-logo-text">The Navigator</span>
            <div className="side-nav-avatar" style={{ width: 32, height: 32, fontSize: 12 }} aria-hidden="true">K</div>
          </header>

          {/* ── Content ── */}
          <div className="app-shell-content">
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={location.pathname}
                className="route-stage"
                initial={{ opacity: 0, y: 18, filter: "blur(10px)" }}
                animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                exit={{ opacity: 0, y: -14, filter: "blur(8px)" }}
                transition={{ duration: 0.36, ease: [0.22, 0.84, 0.24, 1] }}
              >
                <Routes location={location}>
                  <Route path="/" element={<Navigate to="/today" replace />} />
                  <Route path="/today" element={<TodayPage />} />
                  <Route path="/board" element={<BoardPage />} />
                  <Route path="/jobs/:jobId" element={<JobDetailPage />} />
                  <Route path="/insights" element={<InsightsPage />} />
                  <Route path="/recommend" element={<RecommendPage />} />
                  <Route path="/agent" element={<AgentPage />} />
                  <Route path="/settings" element={<SettingsPage />} />
                </Routes>
              </motion.div>
            </AnimatePresence>
          </div>
        </div>

        <AnimatePresence>
          {showShortcuts && (
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              transition={{ duration: 0.15 }}
              style={{ position: "fixed", inset: 0, zIndex: 3000 }}
            >
              <KeyboardShortcutsModal onClose={() => setShowShortcuts(false)} />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </DashboardDataProvider>
    </Suspense>
  );
}
