import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { ThemedLoader } from "./components/ThemedLoader";
import { loadAnalyticsPage, loadArtifactsEditorPage, loadArtifactsHubPage, loadBoardPage, loadEvidenceVaultPage, loadProfilePage, loadResumeLatexEditorPage, loadWorkspacePage } from "./routePreload";

const BoardPage = lazy(async () => loadBoardPage().then((module) => ({ default: module.BoardPage })));
const ArtifactsEditorPage = lazy(async () => loadArtifactsEditorPage().then((module) => ({ default: module.ArtifactsEditorPage })));
const ResumeLatexEditorPage = lazy(async () => loadResumeLatexEditorPage().then((module) => ({ default: module.ResumeLatexEditorPage })));
const ArtifactsHubPage = lazy(async () => loadArtifactsHubPage().then((module) => ({ default: module.ArtifactsHubPage })));
const AnalyticsPage = lazy(async () => loadAnalyticsPage().then((module) => ({ default: module.AnalyticsPage })));
const ProfilePage = lazy(async () => loadProfilePage().then((module) => ({ default: module.ProfilePage })));
const EvidenceVaultPage = lazy(async () => loadEvidenceVaultPage().then((module) => ({ default: module.EvidenceVaultPage })));
const WorkspacePage = lazy(async () => loadWorkspacePage().then((module) => ({ default: module.WorkspacePage })));

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
          <Route path="/artifacts" element={<ArtifactsHubPage />} />
          <Route path="/jobs/:jobId/artifacts/resume" element={<ResumeLatexEditorPage />} />
          <Route path="/jobs/:jobId/artifacts/cover-letter" element={<ResumeLatexEditorPage defaultArtifactType="cover_letter" />} />
          <Route path="/jobs/:jobId/artifacts/:artifactType/latex" element={<ResumeLatexEditorPage />} />
          <Route path="/jobs/:jobId/artifacts/:artifactType" element={<ArtifactsEditorPage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="/workspace" element={<WorkspacePage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/evidence-vault" element={<EvidenceVaultPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
