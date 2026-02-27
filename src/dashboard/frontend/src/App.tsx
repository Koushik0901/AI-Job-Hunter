import { Navigate, Route, Routes } from "react-router-dom";
import { useEffect, useRef, useState } from "react";
import { AppShell } from "./components/layout/AppShell";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { BoardPage } from "./pages/BoardPage";
import { ProfilePage } from "./pages/ProfilePage";

export function App() {
  const hasMounted = useRef(false);
  const [isDark, setIsDark] = useState<boolean>(() => {
    const saved = localStorage.getItem("dashboard-theme");
    if (saved === "dark") return true;
    if (saved === "light") return false;
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  });

  useEffect(() => {
    const theme = isDark ? "dark" : "light";
    if (hasMounted.current) {
      document.documentElement.classList.add("theme-transition");
      window.setTimeout(() => {
        document.documentElement.classList.remove("theme-transition");
      }, 240);
    }
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("dashboard-theme", theme);
    hasMounted.current = true;
  }, [isDark]);

  return (
    <Routes>
      <Route element={<AppShell isDark={isDark} onToggleTheme={() => setIsDark((value) => !value)} />}>
        <Route path="/" element={<BoardPage />} />
        <Route path="/analytics" element={<AnalyticsPage />} />
        <Route path="/profile" element={<ProfilePage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
