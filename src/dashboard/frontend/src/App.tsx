import { Suspense, useEffect, useState } from "react";
import { AnimatePresence, LayoutGroup, motion } from "framer-motion";
import { Menu, X } from "lucide-react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ThemedLoader } from "./components/ThemedLoader";
import { ThemeToggle } from "./components/ThemeToggle";
import { Button } from "./components/ui/button";
import {
  NavigationMenu,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
} from "./components/ui/navigation-menu";
import { VisuallyHidden } from "./components/ui/visually-hidden";
import { BoardPage } from "./pages/BoardPage";
import { InsightsPage } from "./pages/InsightsPage";
import { TodayPage } from "./pages/TodayPage";

const THEME_STORAGE_KEY = "ai-job-hunter-theme";

type ThemeMode = "light" | "dark";

const NAV_ITEMS = [
  { to: "/today", label: "Today" },
  { to: "/board", label: "Board" },
  { to: "/insights", label: "Insights" },
] as const;

const NAV_SPRING = {
  type: "spring",
  stiffness: 420,
  damping: 34,
  mass: 0.78,
} as const;

export function App() {
  const location = useLocation();
  const [theme, setTheme] = useState<ThemeMode>(() => {
    if (typeof window === "undefined") {
      return "light";
    }
    try {
      const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
      return storedTheme === "dark" ? "dark" : "light";
    } catch {
      return "light";
    }
  });
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    const root = document.documentElement;
    const shouldAnimate = Boolean(root.dataset.theme) && root.dataset.theme !== theme;
    root.dataset.theme = theme;
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      // Keep the app usable when storage access is blocked.
    }
    if (!shouldAnimate) {
      return;
    }
    root.classList.add("theme-transition");
    const timeoutId = window.setTimeout(() => {
      root.classList.remove("theme-transition");
    }, 200);
    return () => {
      window.clearTimeout(timeoutId);
      root.classList.remove("theme-transition");
    };
  }, [theme]);

  useEffect(() => {
    setMobileNavOpen(false);
  }, [location.pathname]);

  return (
    <Suspense fallback={<ThemedLoader label="Loading dashboard" />}>
      <div className="app-shell">
        <header className="app-shell-header">
          <div className={`app-shell-rail ${mobileNavOpen ? "menu-open" : ""}`}>
            <NavLink to="/today" className="app-shell-brand" aria-label="Open Today view">
              <span className="app-shell-brand-kicker">AI Job Hunter</span>
              <span className="app-shell-brand-title">Job Search Dashboard</span>
            </NavLink>
            <div className="app-shell-nav-region">
              <NavigationMenu
                id="app-primary-nav"
                className={`app-shell-nav ${mobileNavOpen ? "open" : ""}`}
                aria-label="Primary"
              >
                <LayoutGroup id="primary-navigation">
                  <NavigationMenuList className="app-shell-nav-list">
                    {NAV_ITEMS.map((item) => {
                      const isActive = location.pathname === item.to;
                      return (
                        <NavigationMenuItem key={item.to} className="app-shell-nav-item">
                          <NavigationMenuLink asChild>
                            <NavLink to={item.to} className="app-shell-nav-link">
                              <>
                                {isActive ? (
                                  <motion.span
                                    layoutId="app-shell-nav-active"
                                    className="app-shell-nav-link-indicator"
                                    transition={NAV_SPRING}
                                  />
                                ) : null}
                                <span className="app-shell-nav-link-text">{item.label}</span>
                              </>
                            </NavLink>
                          </NavigationMenuLink>
                        </NavigationMenuItem>
                      );
                    })}
                  </NavigationMenuList>
                </LayoutGroup>
              </NavigationMenu>
            </div>
            <div className="app-shell-actions">
              <ThemeToggle
                isDark={theme === "dark"}
                onToggle={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
              />
              <Button
                variant="default"
                size="compact"
                data-icon="true"
                className="app-shell-menu-toggle"
                aria-expanded={mobileNavOpen}
                aria-controls="app-primary-nav"
                onClick={() => setMobileNavOpen((current) => !current)}
              >
                <AnimatePresence mode="wait" initial={false}>
                  <motion.span
                    key={mobileNavOpen ? "close" : "open"}
                    className="app-shell-menu-toggle-icon"
                    initial={{ opacity: 0, rotate: mobileNavOpen ? -18 : 18, scale: 0.84 }}
                    animate={{ opacity: 1, rotate: 0, scale: 1 }}
                    exit={{ opacity: 0, rotate: mobileNavOpen ? 18 : -18, scale: 0.84 }}
                    transition={{ duration: 0.18, ease: [0.22, 0.84, 0.24, 1] }}
                  >
                    {mobileNavOpen ? <X size={18} strokeWidth={2.3} aria-hidden="true" /> : <Menu size={18} strokeWidth={2.3} aria-hidden="true" />}
                  </motion.span>
                </AnimatePresence>
                <VisuallyHidden>{mobileNavOpen ? "Close navigation menu" : "Open navigation menu"}</VisuallyHidden>
              </Button>
            </div>
          </div>
        </header>
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
                <Route path="/insights" element={<InsightsPage />} />
              </Routes>
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </Suspense>
  );
}
