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

export function loadAnalyticsPage() {
  return import("./pages/AnalyticsPage");
}

export function loadProfilePage() {
  return import("./pages/ProfilePage");
}

export function preloadRouteChunk(route: "board" | "artifacts" | "analytics" | "profile"): void {
  if (route === "board") {
    void once("board", loadBoardPage);
    return;
  }
  if (route === "artifacts") {
    void once("artifacts", loadArtifactsEditorPage);
    return;
  }
  if (route === "analytics") {
    void once("analytics", loadAnalyticsPage);
    return;
  }
  void once("profile", loadProfilePage);
}

