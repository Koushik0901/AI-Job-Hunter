import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { ThemedLoader } from "./components/ThemedLoader";
import { loadAnalyticsPage, loadArtifactsEditorPage, loadBoardPage, loadProfilePage } from "./routePreload";

const BoardPage = lazy(async () => loadBoardPage().then((module) => ({ default: module.BoardPage })));
const ArtifactsEditorPage = lazy(async () => loadArtifactsEditorPage().then((module) => ({ default: module.ArtifactsEditorPage })));
const AnalyticsPage = lazy(async () => loadAnalyticsPage().then((module) => ({ default: module.AnalyticsPage })));
const ProfilePage = lazy(async () => loadProfilePage().then((module) => ({ default: module.ProfilePage })));

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
    <Suspense fallback={<ThemedLoader label="Loading page" />}>
      <Routes>
        <Route element={<AppShell isDark={isDark} onToggleTheme={() => setIsDark((value) => !value)} />}>
          <Route path="/" element={<BoardPage />} />
          <Route path="/jobs/:jobUrl/artifacts/:artifactType" element={<ArtifactsEditorPage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="/profile" element={<ProfilePage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
