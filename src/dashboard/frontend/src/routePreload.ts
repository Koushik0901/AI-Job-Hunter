const loaded = new Set<string>();

function once(key: string, loader: () => Promise<unknown>): Promise<void> {
  if (loaded.has(key)) return Promise.resolve();
  loaded.add(key);
  return loader().then(() => undefined).catch(() => undefined);
}

export function loadBoardPage() {
  return import("./pages/BoardPage");
}

export function loadArtifactsEditorPage() {
  return import("./pages/ArtifactsEditorPage");
}

export function loadResumeLatexEditorPage() {
  return import("./pages/ResumeLatexEditorPage");
}

export function loadArtifactsHubPage() {
  return import("./pages/ArtifactsHubPage");
}

export function loadAnalyticsPage() {
  return import("./pages/AnalyticsPage");
}

export function loadProfilePage() {
  return import("./pages/ProfilePage");
}

export function loadEvidenceVaultPage() {
  return import("./pages/EvidenceVaultPage");
}

export function loadWorkspacePage() {
  return import("./pages/WorkspacePage");
}

export function preloadRouteChunk(route: "board" | "artifacts" | "artifacts-hub" | "analytics" | "profile" | "evidence-vault" | "workspace"): void {
  if (route === "board") {
    void once("board", loadBoardPage);
    return;
  }
  if (route === "artifacts-hub") {
    void once("artifacts-hub", loadArtifactsHubPage);
    return;
  }
  if (route === "artifacts") {
    void once("artifacts", loadArtifactsEditorPage);
    void once("artifacts-latex", loadResumeLatexEditorPage);
    return;
  }
  if (route === "analytics") {
    void once("analytics", loadAnalyticsPage);
    return;
  }
  if (route === "evidence-vault") {
    void once("evidence-vault", loadEvidenceVaultPage);
    return;
  }
  if (route === "workspace") {
    void once("workspace", loadWorkspacePage);
    return;
  }
  void once("profile", loadProfilePage);
}
