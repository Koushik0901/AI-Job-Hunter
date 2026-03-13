import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type * as Monaco from "monaco-editor";
import { ThemedLoader } from "../components/ThemedLoader";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { useEvidenceVault } from "../hooks/useEvidenceVault";

const EVIDENCE_CONTEXT_PATH = "file:///evidence-context.json";
const PROJECT_CARDS_PATH = "file:///project-cards.json";
const BRAG_DOCUMENT_PATH = "file:///brag-document.md";
const MonacoEditor = lazy(() => import("../components/evidence-vault/LazyMonacoEditor"));
const MarkdownPreview = lazy(() => import("../components/evidence-vault/MarkdownPreview"));

const EVIDENCE_CONTEXT_SCHEMA = {
  type: "object",
  additionalProperties: true,
  properties: {
    candidate_profile: { type: "object" },
    technical_skills: { type: "object" },
    work_experience: { type: "array" },
    selected_projects: { type: "array" },
    behavioral_evidence: { type: "object" },
    high_value_story_bank: { type: "array" },
  },
};

const PROJECT_CARDS_SCHEMA = {
  type: "array",
  items: {
    type: "object",
    additionalProperties: true,
    required: ["title", "summary"],
    properties: {
      title: { type: "string" },
      role: { type: "string" },
      summary: { type: "string" },
      highlights: {
        type: "array",
        items: { type: "string" },
      },
      tags: {
        type: "array",
        items: { type: "string" },
      },
      time: { type: "string" },
      website: { type: "string" },
    },
  },
};

function configureMonaco(monaco: typeof Monaco): void {
  const jsonDefaults = (
    monaco.languages as unknown as {
      json?: {
        jsonDefaults?: {
          setDiagnosticsOptions: (options: unknown) => void;
        };
      };
    }
  ).json?.jsonDefaults;
  jsonDefaults?.setDiagnosticsOptions({
    validate: true,
    allowComments: false,
    enableSchemaRequest: false,
    schemas: [
      {
        uri: "evidence-vault://schemas/evidence-context.json",
        fileMatch: [EVIDENCE_CONTEXT_PATH],
        schema: EVIDENCE_CONTEXT_SCHEMA,
      },
      {
        uri: "evidence-vault://schemas/project-cards.json",
        fileMatch: [PROJECT_CARDS_PATH],
        schema: PROJECT_CARDS_SCHEMA,
      },
    ],
  });
}

function healthTone(configured: boolean, healthy: boolean): string {
  if (healthy) return "good";
  if (configured) return "warn";
  return "muted";
}

function editorFallback(label: string, className?: string): JSX.Element {
  return (
    <div className={className ?? "evidence-vault-editor-shell"}>
      <ThemedLoader label={label} />
    </div>
  );
}

function previewFallback(): JSX.Element {
  return (
    <div className="evidence-vault-markdown-preview">
      <ThemedLoader label="Loading preview" />
    </div>
  );
}

export function EvidenceVaultPage() {
  const evidenceVault = useEvidenceVault();
  const [activeSection, setActiveSection] = useState("context");
  const [monacoTheme, setMonacoTheme] = useState<"vs" | "vs-dark">("vs");

  useEffect(() => {
    const root = document.documentElement;
    const syncTheme = () => {
      setMonacoTheme(root.getAttribute("data-theme") === "dark" ? "vs-dark" : "vs");
    };
    syncTheme();
    const observer = new MutationObserver(syncTheme);
    observer.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);

  const headerBadgeClass = useMemo(() => {
    if (evidenceVault.saveState === "dirty") return "dirty";
    if (evidenceVault.saveState === "saving") return "saving";
    if (evidenceVault.saveState === "saved") return "saved";
    if (evidenceVault.saveState === "error") return "error";
    return "idle";
  }, [evidenceVault.saveState]);

  if (evidenceVault.loading) {
    return (
      <div className="page-loader-shell">
        <ThemedLoader label="Loading Evidence Vault" />
      </div>
    );
  }

  return (
    <div className="evidence-vault-page">
      <section className="evidence-vault-hero">
        <div className="evidence-vault-hero-copy">
          <p className="page-kicker">Canonical Grounding Workspace</p>
          <h1>Evidence Vault</h1>
          <p>
            Author the grounded context that powers safer tailoring. JSON gets schema-aware Monaco diagnostics, markdown gets a live preview, and indexing health stays visible while you work.
          </p>
          <div className="evidence-vault-meta">
            <span className={`save-badge ${headerBadgeClass}`}>
              {evidenceVault.saveState === "dirty"
                ? "Unsaved changes"
                : evidenceVault.saveState === "saving"
                  ? "Saving"
                  : evidenceVault.saveState === "saved"
                    ? "All changes saved"
                    : "Ready"}
            </span>
            <span className={`evidence-health-chip ${healthTone(evidenceVault.health.services.redis.configured, evidenceVault.health.services.redis.healthy)}`}>
              Redis · {evidenceVault.health.services.redis.healthy ? "Healthy" : evidenceVault.health.services.redis.configured ? "Unreachable" : "Not configured"}
            </span>
            <span className={`evidence-health-chip ${healthTone(evidenceVault.health.services.qdrant.configured, evidenceVault.health.services.qdrant.healthy)}`}>
              Qdrant · {evidenceVault.health.services.qdrant.healthy ? "Healthy" : evidenceVault.health.services.qdrant.configured ? "Unreachable" : "Not configured"}
            </span>
            <span className="evidence-health-chip neutral">
              Index · {evidenceVault.indexStatus.status}
            </span>
            <span className="evidence-health-chip neutral">
              Chunks · {evidenceVault.indexStatus.indexed_count}
            </span>
          </div>
        </div>
        <div className="evidence-vault-hero-actions">
          <Button
            type="button"
            variant="default"
            size="compact"
            disabled={!evidenceVault.canSave}
            onClick={() => {
              void evidenceVault.saveEvidenceVault();
            }}
          >
            {evidenceVault.saveState === "saving" ? "Saving..." : "Save Evidence Vault"}
          </Button>
          {evidenceVault.canUseQdrant ? (
            <Button
              type="button"
              variant="primary"
              size="compact"
              disabled={!evidenceVault.canSave || evidenceVault.saveState === "saving" || evidenceVault.indexing}
              onClick={() => {
                void evidenceVault.saveEvidenceVault({ reindexAfterSave: true });
              }}
            >
              {evidenceVault.indexing ? "Indexing..." : "Save + Reindex"}
            </Button>
          ) : null}
          <Button
            type="button"
            variant="default"
            size="compact"
            className="warn"
            disabled={evidenceVault.isDirty || evidenceVault.indexing}
            onClick={() => {
              void evidenceVault.reindexSavedEvidence();
            }}
          >
            {evidenceVault.indexing ? "Reindexing..." : "Reindex Saved Content"}
          </Button>
          <Button type="button" variant="default" size="compact" asChild>
            <Link to="/profile">Back To Profile</Link>
          </Button>
        </div>
      </section>

      {evidenceVault.loadError ? <div className="error-banner">{evidenceVault.loadError}</div> : null}
      {evidenceVault.saveError ? <div className="error-banner">{evidenceVault.saveError}</div> : null}

      <section className="evidence-vault-callout">
        <div>
          <strong>Indexing uses saved content only.</strong> {evidenceVault.isDirty
            ? "Save your draft before reindexing so Qdrant sees the latest changes."
            : "Saved content is ready for reindexing."}
        </div>
        {evidenceVault.statusNotice ? <span>{evidenceVault.statusNotice}</span> : null}
      </section>

      <div className="evidence-vault-layout">
        <div className="evidence-vault-main">
          <Card className="evidence-vault-editor-card">
            <CardHeader className="evidence-vault-editor-head">
              <div>
                <CardTitle>Editor Workspace</CardTitle>
                <p className="board-note">Each section is tuned for the type of content it stores.</p>
              </div>
              <div className="evidence-vault-editor-head-stats">
                <span className="soft-chip">Keys {evidenceVault.counts.evidenceKeys}</span>
                <span className="soft-chip">Cards {evidenceVault.counts.projectCards}</span>
                <span className="soft-chip">Blocked Claims {evidenceVault.counts.blockedClaims}</span>
              </div>
            </CardHeader>
            <CardContent>
              <Tabs className="evidence-vault-tabs" value={activeSection} onValueChange={setActiveSection}>
                <TabsList className="evidence-vault-tabs-list">
                  <TabsTrigger className="profile-tabs-trigger" value="context">Evidence Context</TabsTrigger>
                  <TabsTrigger className="profile-tabs-trigger" value="brag">Brag Document</TabsTrigger>
                  <TabsTrigger className="profile-tabs-trigger" value="cards">Project Cards</TabsTrigger>
                  <TabsTrigger className="profile-tabs-trigger" value="claims">Do Not Claim</TabsTrigger>
                </TabsList>

                <TabsContent value="context" className="evidence-vault-tab-body">
                  <div className="evidence-vault-section-header">
                    <div>
                      <h2>Evidence Context</h2>
                      <p>Canonical claimable facts, role history, tools, story bank, and grounding constraints.</p>
                    </div>
                    <Button type="button" variant="default" size="compact" onClick={evidenceVault.formatEvidenceContext}>
                      Format JSON
                    </Button>
                  </div>
                  <Suspense fallback={editorFallback("Loading JSON editor")}>
                    <div className="evidence-vault-editor-shell">
                      <MonacoEditor
                        beforeMount={configureMonaco}
                        height="68vh"
                        language="json"
                        path={EVIDENCE_CONTEXT_PATH}
                        theme={monacoTheme}
                        value={evidenceVault.evidenceContextInput}
                        onChange={(value) => evidenceVault.setEvidenceContextInput(value ?? "{}")}
                        options={{
                          minimap: { enabled: false },
                          formatOnPaste: true,
                          formatOnType: true,
                          scrollBeyondLastLine: false,
                          wordWrap: "on",
                          lineNumbersMinChars: 3,
                          padding: { top: 14, bottom: 14 },
                        }}
                      />
                    </div>
                  </Suspense>
                </TabsContent>

                <TabsContent value="brag" className="evidence-vault-tab-body">
                  <div className="evidence-vault-section-header">
                    <div>
                      <h2>Brag Document</h2>
                      <p>High-context STAR stories, constraints, decisions, stakeholder friction, and outcomes.</p>
                    </div>
                    <div className="evidence-vault-inline-help">
                      <button type="button" onClick={() => evidenceVault.setBragDocumentMarkdown(`${evidenceVault.draft.brag_document_markdown}\n\n## Situation\n- \n\n## Constraints\n- \n\n## Outcome\n- `)}>
                        Insert Story Skeleton
                      </button>
                    </div>
                  </div>
                  <div className="evidence-vault-markdown-grid">
                    <Suspense fallback={editorFallback("Loading markdown editor", "evidence-vault-editor-shell evidence-vault-markdown-editor-shell")}>
                      <div className="evidence-vault-editor-shell evidence-vault-markdown-editor-shell">
                        <MonacoEditor
                          height="100%"
                          language="markdown"
                          path={BRAG_DOCUMENT_PATH}
                          theme={monacoTheme}
                          value={evidenceVault.draft.brag_document_markdown}
                          onChange={(value) => evidenceVault.setBragDocumentMarkdown(value ?? "")}
                          options={{
                            minimap: { enabled: false },
                            scrollBeyondLastLine: false,
                            wordWrap: "on",
                            quickSuggestions: false,
                            padding: { top: 14, bottom: 14 },
                          }}
                        />
                      </div>
                    </Suspense>
                    <div className="evidence-vault-preview-card">
                      <div className="evidence-vault-preview-head">
                        <h3>Live Preview</h3>
                        <span className="soft-chip">{evidenceVault.bragStats.words} words</span>
                        <span className="soft-chip">{evidenceVault.bragStats.headings} headings</span>
                      </div>
                      <Suspense fallback={previewFallback()}>
                        <div className="evidence-vault-markdown-preview">
                          <MarkdownPreview
                            markdown={evidenceVault.draft.brag_document_markdown ?? ""}
                            emptyState="Add markdown to preview how structure and scanability will look to users."
                          />
                        </div>
                      </Suspense>
                    </div>
                  </div>
                </TabsContent>

                <TabsContent value="cards" className="evidence-vault-tab-body">
                  <div className="evidence-vault-section-header">
                    <div>
                      <h2>Project Cards</h2>
                      <p>Short, retrieval-friendly project summaries with clean titles, clear summaries, and evidence-rich highlights.</p>
                    </div>
                    <Button type="button" variant="default" size="compact" onClick={evidenceVault.formatProjectCards}>
                      Format JSON
                    </Button>
                  </div>
                  <Suspense fallback={editorFallback("Loading project card editor")}>
                    <div className="evidence-vault-editor-shell">
                      <MonacoEditor
                        beforeMount={configureMonaco}
                        height="64vh"
                        language="json"
                        path={PROJECT_CARDS_PATH}
                        theme={monacoTheme}
                        value={evidenceVault.projectCardsInput}
                        onChange={(value) => evidenceVault.setProjectCardsInput(value ?? "[]")}
                        options={{
                          minimap: { enabled: false },
                          formatOnPaste: true,
                          formatOnType: true,
                          scrollBeyondLastLine: false,
                          wordWrap: "on",
                          lineNumbersMinChars: 3,
                          padding: { top: 14, bottom: 14 },
                        }}
                      />
                    </div>
                  </Suspense>
                </TabsContent>

                <TabsContent value="claims" className="evidence-vault-tab-body">
                  <div className="evidence-vault-section-header">
                    <div>
                      <h2>Do Not Claim</h2>
                      <p>Explicit guardrails for easy-to-hallucinate facts, titles, numbers, and sensitive assertions.</p>
                    </div>
                    <Button type="button" variant="default" size="compact" onClick={() => evidenceVault.addDoNotClaimItem()}>
                      Add Claim Guardrail
                    </Button>
                  </div>
                  <div className="evidence-vault-claim-grid">
                    <div className="evidence-vault-claim-list">
                      {evidenceVault.draft.do_not_claim.length > 0 ? evidenceVault.draft.do_not_claim.map((item, index) => (
                        <div className="evidence-vault-claim-row" key={`claim-${index}`}>
                          <span className="evidence-vault-claim-index" aria-hidden="true">
                            {String(index + 1).padStart(2, "0")}
                          </span>
                          <div className="evidence-vault-claim-field">
                            <label className="evidence-vault-claim-label" htmlFor={`do-not-claim-${index}`}>
                              Blocked claim
                            </label>
                            <input
                              id={`do-not-claim-${index}`}
                              className="evidence-vault-claim-input"
                              type="text"
                              value={item}
                              placeholder="Example: Do not claim I managed a team of 10."
                              onChange={(event) => evidenceVault.setDoNotClaimItem(index, event.target.value)}
                            />
                          </div>
                          <button className="evidence-vault-claim-remove" type="button" onClick={() => evidenceVault.removeDoNotClaimItem(index)}>
                            Remove
                          </button>
                        </div>
                      )) : (
                        <div className="evidence-vault-empty">
                          <p>No blocked claims yet.</p>
                          <button type="button" onClick={() => evidenceVault.addDoNotClaimItem()}>Start with one guardrail</button>
                        </div>
                      )}
                    </div>
                    <div className="evidence-vault-bulk-card">
                      <h3>Bulk Paste</h3>
                      <p className="board-note">Paste one blocked claim per line. This replaces the current list after normalization.</p>
                      <textarea
                        className="evidence-vault-bulk-textarea"
                        rows={8}
                        value={evidenceVault.bulkClaimsInput}
                        onChange={(event) => evidenceVault.setBulkClaimsInput(event.target.value)}
                        placeholder={"Do not claim I was a people manager.\nDo not claim production metrics that are not documented."}
                      />
                      <div className="evidence-vault-bulk-actions">
                        <Button
                          type="button"
                          variant="default"
                          size="compact"
                          disabled={!evidenceVault.bulkClaimsInput.trim()}
                          onClick={() => evidenceVault.replaceDoNotClaimFromBulk(evidenceVault.bulkClaimsInput)}
                        >
                          Replace From Bulk Paste
                        </Button>
                      </div>
                    </div>
                  </div>
                </TabsContent>
              </Tabs>
            </CardContent>
          </Card>
        </div>

        <aside className="evidence-vault-side">
          <Card className="evidence-vault-side-card evidence-vault-sticky-card">
            <CardHeader>
              <CardTitle>Diagnostics</CardTitle>
            </CardHeader>
            <CardContent className="evidence-vault-diagnostics">
              {evidenceVault.issues.length > 0 ? evidenceVault.issues.map((issue, index) => (
                <div key={`${issue.field}-${index}`} className={`evidence-vault-issue ${issue.level}`}>
                  <strong>{issue.field.replaceAll("_", " ")}</strong>
                  <p>{issue.message}</p>
                </div>
              )) : (
                <div className="evidence-vault-issue success">
                  <strong>Ready to save</strong>
                  <p>No blocking issues detected in the current draft.</p>
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="evidence-vault-side-card">
            <CardHeader>
              <CardTitle>System Status</CardTitle>
            </CardHeader>
            <CardContent className="evidence-vault-status-grid">
              <div className="evidence-vault-status-row">
                <span>Redis</span>
                <strong>{evidenceVault.health.services.redis.message}</strong>
              </div>
              <div className="evidence-vault-status-row">
                <span>Qdrant</span>
                <strong>{evidenceVault.health.services.qdrant.message}</strong>
              </div>
              <div className="evidence-vault-status-row">
                <span>Collection</span>
                <strong>{evidenceVault.health.services.qdrant.collection ?? evidenceVault.indexStatus.collection ?? "candidate_evidence_chunks"}</strong>
              </div>
              <div className="evidence-vault-status-row">
                <span>Collection Exists</span>
                <strong>{evidenceVault.health.services.qdrant.collection_exists ? "Yes" : "No"}</strong>
              </div>
              <div className="evidence-vault-status-row">
                <span>Last Updated</span>
                <strong>{evidenceVault.draft.updated_at ?? "-"}</strong>
              </div>
              <div className="evidence-vault-status-actions">
                <Button type="button" variant="default" size="compact" disabled={evidenceVault.healthLoading} onClick={() => void evidenceVault.refreshHealth()}>
                  {evidenceVault.healthLoading ? "Refreshing..." : "Refresh Health"}
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card className="evidence-vault-side-card">
            <CardHeader>
              <CardTitle>Vault Snapshot</CardTitle>
            </CardHeader>
            <CardContent className="evidence-vault-summary-grid">
              <div>
                <span>Evidence keys</span>
                <strong>{evidenceVault.counts.evidenceKeys}</strong>
              </div>
              <div>
                <span>Project cards</span>
                <strong>{evidenceVault.counts.projectCards}</strong>
              </div>
              <div>
                <span>Blocked claims</span>
                <strong>{evidenceVault.counts.blockedClaims}</strong>
              </div>
              <div>
                <span>Brag words</span>
                <strong>{evidenceVault.bragStats.words}</strong>
              </div>
            </CardContent>
          </Card>

          <Card className="evidence-vault-side-card">
            <CardHeader>
              <CardTitle>Authoring Guidance</CardTitle>
            </CardHeader>
            <CardContent className="evidence-vault-guidance">
              <p>Recommended evidence context sections:</p>
              <ul>
                <li><code>candidate_profile</code></li>
                <li><code>technical_skills</code></li>
                <li><code>work_experience</code></li>
                <li><code>selected_projects</code></li>
                <li><code>behavioral_evidence</code></li>
                <li><code>high_value_story_bank</code></li>
              </ul>
              <p>Project cards index best when each card has a clear title, one-sentence summary, and concrete highlights.</p>
            </CardContent>
          </Card>
        </aside>
      </div>
    </div>
  );
}
