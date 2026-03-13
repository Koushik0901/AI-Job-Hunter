import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  createCompanySource,
  getCompanySources,
  getWorkspaceOperations,
  getWorkspaceOverview,
  importCompanySources,
  previewCompanySourceImport,
  previewWorkspacePrune,
  probeCompanySources,
  runWorkspaceEnrichBackfill,
  runWorkspaceJdReformat,
  runWorkspacePrune,
  runWorkspaceReEnrichAll,
  runWorkspaceScrape,
  updateCompanySource,
} from "../api";
import { ThemedLoader } from "../components/ThemedLoader";
import { Button } from "../components/ui/button";
import { Switch } from "../components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import type {
  CompanySource,
  CompanySourceImportResponse,
  CompanySourceProbeResponse,
  WorkspaceOperation,
  WorkspaceOverview,
} from "../types";
import { toast } from "sonner";

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return value;
  return parsed.toLocaleString();
}

function titleCase(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function operationSummary(operation: WorkspaceOperation): string {
  const summary = operation.summary ?? {};
  if (typeof summary.message === "string" && summary.message.trim()) return summary.message;
  if (operation.error) return operation.error;
  return `${titleCase(operation.kind)} ${operation.status}`;
}

export function WorkspacePage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"setup" | "sources" | "pipeline" | "maintenance">("setup");
  const [overview, setOverview] = useState<WorkspaceOverview | null>(null);
  const [sources, setSources] = useState<CompanySource[]>([]);
  const [operations, setOperations] = useState<WorkspaceOperation[]>([]);
  const [probeQuery, setProbeQuery] = useState("");
  const [probeExtraSlugs, setProbeExtraSlugs] = useState("");
  const [probeLoading, setProbeLoading] = useState(false);
  const [probeResult, setProbeResult] = useState<CompanySourceProbeResponse | null>(null);
  const [importPreview, setImportPreview] = useState<CompanySourceImportResponse | null>(null);
  const [importLoading, setImportLoading] = useState(false);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [pruneDays, setPruneDays] = useState(28);
  const [prunePreviewOperation, setPrunePreviewOperation] = useState<WorkspaceOperation | null>(null);

  async function refreshAll(): Promise<void> {
    const [overviewData, sourceData, operationData] = await Promise.all([
      getWorkspaceOverview(),
      getCompanySources(),
      getWorkspaceOperations(20),
    ]);
    setOverview(overviewData);
    setSources(sourceData);
    setOperations(operationData);
  }

  useEffect(() => {
    let cancelled = false;
    async function load(): Promise<void> {
      setLoading(true);
      setError(null);
      try {
        const [overviewData, sourceData, operationData] = await Promise.all([
          getWorkspaceOverview(),
          getCompanySources(),
          getWorkspaceOperations(20),
        ]);
        if (cancelled) return;
        setOverview(overviewData);
        setSources(sourceData);
        setOperations(operationData);
      } catch (loadError) {
        if (cancelled) return;
        setError(loadError instanceof Error ? loadError.message : "Failed to load workspace");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  async function runAction<T>(key: string, action: () => Promise<T>, onDone?: (result: T) => Promise<void> | void): Promise<void> {
    setActionBusy(key);
    try {
      const result = await action();
      await onDone?.(result);
    } catch (actionError) {
      const message = actionError instanceof Error ? actionError.message : "Workspace action failed";
      setError(message);
      toast.error(message);
    } finally {
      setActionBusy(null);
    }
  }

  async function handleProbe(): Promise<void> {
    if (!probeQuery.trim()) return;
    setProbeLoading(true);
    setError(null);
    try {
      const result = await probeCompanySources({
        query: probeQuery.trim(),
        extra_slugs: probeExtraSlugs.split(",").map((item) => item.trim()).filter(Boolean),
      });
      setProbeResult(result);
    } catch (probeError) {
      const message = probeError instanceof Error ? probeError.message : "Failed to probe company sources";
      setError(message);
      toast.error(message);
    } finally {
      setProbeLoading(false);
    }
  }

  async function handleCreateSource(match: {
    name: string;
    ats_type: string;
    slug: string;
    ats_url: string;
  }): Promise<void> {
    await runAction(
      `create-source-${match.slug}`,
      () => createCompanySource({ ...match, enabled: true, source: "manual" }),
      async () => {
        toast.success("Company source saved");
        await refreshAll();
        if (probeResult) {
          const refreshed = await probeCompanySources({
            query: probeResult.query,
            extra_slugs: probeResult.slugs,
          });
          setProbeResult(refreshed);
        }
      },
    );
  }

  async function handleToggleSource(source: CompanySource, enabled: boolean): Promise<void> {
    await runAction(
      `toggle-source-${source.id}`,
      () => updateCompanySource(source.id, { enabled }),
      async () => {
        setSources((current) => current.map((item) => (item.id === source.id ? { ...item, enabled } : item)));
        await refreshAll();
      },
    );
  }

  const enabledSourceCount = useMemo(
    () => sources.filter((item) => item.enabled).length,
    [sources],
  );

  if (loading) {
    return <ThemedLoader label="Loading workspace" />;
  }

  return (
    <div className="workspace-page">
      <section className="workspace-hero">
        <div>
          <p className="page-kicker">Open-Source Workspace</p>
          <h2>Self-serve setup, source management, and pipeline operations</h2>
          <p className="workspace-hero-copy">
            Fresh clones start blank. Use this workspace to define your own targets, add your own sources, and run the pipeline without editing backend code.
          </p>
        </div>
        <div className="workspace-hero-actions">
          <Button type="button" variant="default" asChild>
            <Link to="/profile">Edit Profile</Link>
          </Button>
          <Button type="button" variant="primary" asChild>
            <Link to="/">Open Board</Link>
          </Button>
        </div>
      </section>

      {error && <div className="error-banner">{error}</div>}

      <section className="workspace-summary-grid">
        <article className="workspace-summary-card">
          <span className="workspace-summary-label">Sources</span>
          <strong>{enabledSourceCount}/{overview?.total_company_sources ?? 0}</strong>
          <p>Enabled sources ready for scrape runs.</p>
        </article>
        <article className="workspace-summary-card">
          <span className="workspace-summary-label">Desired Titles</span>
          <strong>{overview?.desired_job_titles_count ?? 0}</strong>
          <p>Search preferences saved on your profile.</p>
        </article>
        <article className="workspace-summary-card">
          <span className="workspace-summary-label">Jobs Indexed</span>
          <strong>{overview?.total_jobs ?? 0}</strong>
          <p>Total jobs currently available on the board.</p>
        </article>
        <article className="workspace-summary-card">
          <span className="workspace-summary-label">Recent Ops</span>
          <strong>{operations.length}</strong>
          <p>Operation history for scrape, enrichment, and maintenance tasks.</p>
        </article>
      </section>

      <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as typeof activeTab)}>
        <TabsList className="profile-tabs-list workspace-tabs-list">
          <TabsTrigger className="profile-tabs-trigger" value="setup">Setup</TabsTrigger>
          <TabsTrigger className="profile-tabs-trigger" value="sources">Sources</TabsTrigger>
          <TabsTrigger className="profile-tabs-trigger" value="pipeline">Pipeline</TabsTrigger>
          <TabsTrigger className="profile-tabs-trigger" value="maintenance">Maintenance</TabsTrigger>
        </TabsList>

        <TabsContent value="setup">
          <section className="workspace-grid">
            <section className="profile-card">
              <h3>Onboarding Checklist</h3>
              <div className="workspace-checklist">
                <article className={`workspace-check ${overview?.has_profile_basics ? "complete" : ""}`}>
                  <strong>Profile basics</strong>
                  <p>{overview?.has_profile_basics ? "Profile inputs are present." : "Add your target job titles and core skills on the Profile page."}</p>
                </article>
                <article className={`workspace-check ${enabledSourceCount > 0 ? "complete" : ""}`}>
                  <strong>Company sources</strong>
                  <p>{enabledSourceCount > 0 ? "At least one source is enabled." : "Probe or import company sources before running scrape."}</p>
                </article>
                <article className={`workspace-check ${(overview?.total_jobs ?? 0) > 0 ? "complete" : ""}`}>
                  <strong>Board inventory</strong>
                  <p>{(overview?.total_jobs ?? 0) > 0 ? "Jobs are available on the board." : "Run your first scrape to populate the board."}</p>
                </article>
              </div>
            </section>
            <section className="profile-card">
              <h3>Service Health</h3>
              <div className="workspace-health-list">
                {Object.entries(overview?.services ?? {}).map(([name, service]) => (
                  <article key={name} className={`workspace-health-item ${service.healthy ? "healthy" : "degraded"}`}>
                    <div>
                      <strong>{titleCase(name)}</strong>
                      <p>{service.message}</p>
                    </div>
                    <span>{service.healthy ? "Healthy" : service.configured ? "Attention" : "Not configured"}</span>
                  </article>
                ))}
              </div>
            </section>
          </section>
        </TabsContent>

        <TabsContent value="sources">
          <section className="workspace-grid">
            <section className="profile-card profile-card-wide">
              <h3>Add Company Source</h3>
              <p className="board-note">Paste any company name or careers URL to probe supported ATS boards before saving.</p>
              <div className="workspace-form-grid">
                <label>
                  <span>Company or careers URL</span>
                  <input type="text" value={probeQuery} onChange={(event) => setProbeQuery(event.target.value)} placeholder="Example Company or https://jobs.ashbyhq.com/example-company" />
                </label>
                <label>
                  <span>Extra slugs (optional)</span>
                  <input type="text" value={probeExtraSlugs} onChange={(event) => setProbeExtraSlugs(event.target.value)} placeholder="example-company, example-careers" />
                </label>
              </div>
              <div className="profile-inline-actions">
                <Button type="button" variant="primary" onClick={() => void handleProbe()} disabled={probeLoading || !probeQuery.trim()}>
                  {probeLoading ? "Probing..." : "Probe Sources"}
                </Button>
                <Button
                  type="button"
                  variant="default"
                  onClick={() => void runAction("import-preview", previewCompanySourceImport, (result) => setImportPreview(result))}
                  disabled={actionBusy === "import-preview"}
                >
                  {actionBusy === "import-preview" ? "Loading..." : "Preview Import"}
                </Button>
                <Button
                  type="button"
                  variant="default"
                  onClick={() => void runAction("import-apply", importCompanySources, async (result) => {
                    setImportPreview(result);
                    toast.success(`Imported ${result.imported ?? 0} sources`);
                    await refreshAll();
                  })}
                  disabled={actionBusy === "import-apply"}
                >
                  {actionBusy === "import-apply" ? "Importing..." : "Import Sources"}
                </Button>
              </div>
              {probeResult && (
                <div className="workspace-result-stack">
                  <h4>Probe Results</h4>
                  {probeResult.matches.length === 0 ? (
                    <p className="empty-text">No active job boards found for this query.</p>
                  ) : (
                    probeResult.matches.map((match) => (
                      <article key={`${match.ats_type}-${match.slug}`} className="workspace-result-card">
                        <div>
                          <strong>{match.name}</strong>
                          <p>{match.ats_type} · {match.slug} · {match.jobs} jobs</p>
                          <p className="board-note">{match.ats_url}</p>
                        </div>
                        <Button
                          type="button"
                          variant={match.exists ? "default" : "primary"}
                          disabled={Boolean(match.exists) || actionBusy === `create-source-${match.slug}`}
                          onClick={() => void handleCreateSource(match)}
                        >
                          {match.exists ? "Already Added" : actionBusy === `create-source-${match.slug}` ? "Saving..." : "Add Source"}
                        </Button>
                      </article>
                    ))
                  )}
                </div>
              )}
              {importPreview && (
                <div className="workspace-result-stack">
                  <h4>Import Preview</h4>
                  <p className="board-note">{importPreview.new_entries.length} new candidates, {importPreview.skipped_duplicates} duplicates skipped.</p>
                  <div className="workspace-preview-list">
                    {importPreview.new_entries.slice(0, 12).map((entry) => (
                      <span key={`${entry.ats_type}-${entry.slug}`} className="token-chip">{entry.name} · {entry.slug}</span>
                    ))}
                  </div>
                </div>
              )}
            </section>

            <section className="profile-card profile-card-wide">
              <h3>Source Registry</h3>
              {sources.length === 0 ? (
                <p className="empty-text">No company sources saved yet.</p>
              ) : (
                <div className="workspace-source-list">
                  {sources.map((source) => (
                    <article key={source.id} className="workspace-source-row">
                      <div>
                        <strong>{source.name}</strong>
                        <p>{source.ats_type} · {source.slug}</p>
                        <p className="board-note">{source.source || "manual"}</p>
                      </div>
                      <div className="workspace-source-actions">
                        <span className={`job-chip ${source.enabled ? "tone-match match-high" : "tone-match match-pending"}`}>
                          {source.enabled ? "Enabled" : "Disabled"}
                        </span>
                        <Switch
                          checked={source.enabled}
                          onCheckedChange={(checked) => void handleToggleSource(source, checked)}
                          disabled={actionBusy === `toggle-source-${source.id}`}
                        />
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </section>
          </section>
        </TabsContent>

        <TabsContent value="pipeline">
          <section className="workspace-grid">
            <section className="profile-card">
              <h3>Run Pipeline</h3>
              <div className="workspace-action-stack">
                <Button type="button" variant="primary" disabled={actionBusy === "scrape"} onClick={() => void runAction("scrape", () => runWorkspaceScrape(), async (result) => {
                  setOperations((current) => [result, ...current].slice(0, 20));
                  toast.success("Scrape operation completed");
                  await refreshAll();
                })}>
                  {actionBusy === "scrape" ? "Running scrape..." : "Run Scrape"}
                </Button>
                <Button type="button" variant="default" disabled={actionBusy === "enrich-backfill"} onClick={() => void runAction("enrich-backfill", runWorkspaceEnrichBackfill, async (result) => {
                  setOperations((current) => [result, ...current].slice(0, 20));
                  toast.success("Enrichment backfill completed");
                  await refreshAll();
                })}>
                  {actionBusy === "enrich-backfill" ? "Running..." : "Enrich Backfill"}
                </Button>
                <Button type="button" variant="default" disabled={actionBusy === "re-enrich-all"} onClick={() => void runAction("re-enrich-all", runWorkspaceReEnrichAll, async (result) => {
                  setOperations((current) => [result, ...current].slice(0, 20));
                  toast.success("Re-enrich all completed");
                  await refreshAll();
                })}>
                  {actionBusy === "re-enrich-all" ? "Running..." : "Re-enrich All"}
                </Button>
                <Button type="button" variant="default" disabled={actionBusy === "jd-reformat-missing"} onClick={() => void runAction("jd-reformat-missing", () => runWorkspaceJdReformat({ missing_only: true }), async (result) => {
                  setOperations((current) => [result, ...current].slice(0, 20));
                  toast.success("JD reformat completed");
                  await refreshAll();
                })}>
                  {actionBusy === "jd-reformat-missing" ? "Running..." : "JD Reformat Missing"}
                </Button>
                <Button type="button" variant="default" disabled={actionBusy === "jd-reformat-all"} onClick={() => void runAction("jd-reformat-all", () => runWorkspaceJdReformat({ missing_only: false }), async (result) => {
                  setOperations((current) => [result, ...current].slice(0, 20));
                  toast.success("Full JD reformat completed");
                  await refreshAll();
                })}>
                  {actionBusy === "jd-reformat-all" ? "Running..." : "JD Reformat All"}
                </Button>
              </div>
            </section>
            <section className="profile-card profile-card-wide">
              <h3>Recent Operations</h3>
              {operations.length === 0 ? (
                <p className="empty-text">No workspace operations recorded yet.</p>
              ) : (
                <div className="workspace-operation-list">
                  {operations.map((operation) => (
                    <article key={operation.id} className={`workspace-operation-card status-${operation.status}`}>
                      <div className="workspace-operation-topline">
                        <strong>{titleCase(operation.kind)}</strong>
                        <span className={`job-chip tone-match ${operation.status === "completed" ? "match-high" : operation.status === "failed" ? "match-low" : "match-pending"}`}>
                          {titleCase(operation.status)}
                        </span>
                      </div>
                      <p>{operationSummary(operation)}</p>
                      <p className="board-note">Started {formatDateTime(operation.started_at)} · Finished {formatDateTime(operation.finished_at)}</p>
                      {operation.log_tail ? <pre className="workspace-log-tail">{operation.log_tail}</pre> : null}
                    </article>
                  ))}
                </div>
              )}
            </section>
          </section>
        </TabsContent>

        <TabsContent value="maintenance">
          <section className="workspace-grid">
            <section className="profile-card">
              <h3>Prune Old Backlog</h3>
              <p className="board-note">Preview the number of old `not_applied` jobs before deleting them.</p>
              <label>
                <span>Days</span>
                <input type="number" min={1} max={365} value={pruneDays} onChange={(event) => setPruneDays(Math.max(1, Number(event.target.value || 28)))} />
              </label>
              <div className="profile-inline-actions">
                <Button type="button" variant="default" disabled={actionBusy === "prune-preview"} onClick={() => void runAction("prune-preview", () => previewWorkspacePrune(pruneDays), (result) => setPrunePreviewOperation(result))}>
                  {actionBusy === "prune-preview" ? "Previewing..." : "Preview Prune"}
                </Button>
                <Button type="button" variant="danger" disabled={actionBusy === "prune"} onClick={() => void runAction("prune", () => runWorkspacePrune(pruneDays), async (result) => {
                  setOperations((current) => [result, ...current].slice(0, 20));
                  toast.success("Prune completed");
                  await refreshAll();
                })}>
                  {actionBusy === "prune" ? "Deleting..." : "Run Prune"}
                </Button>
              </div>
              {prunePreviewOperation && (
                <div className="workspace-preview-callout">
                  <strong>Preview result</strong>
                  <p>{operationSummary(prunePreviewOperation)}</p>
                </div>
              )}
            </section>
          </section>
        </TabsContent>
      </Tabs>
    </div>
  );
}
