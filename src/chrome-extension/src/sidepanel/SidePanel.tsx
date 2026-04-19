import { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { marked } from "marked";
import { checkHealth, getArtifactsByUrl, getDashboardUrl } from "../api";
import type { ArtifactInfo, ArtifactsByUrlResponse } from "../api";
import "./sidepanel.css";

type Status = "checking" | "connected" | "disconnected";

interface FillResult {
  ok: boolean;
  filled?: number;
  fields?: string[];
  error?: string;
}

function renderMarkdown(md: string): string {
  const result = marked.parse(md, { async: false });
  return typeof result === "string" ? result : md;
}

function SidePanel() {
  const [status, setStatus] = useState<Status>("checking");
  const [dashUrl, setDashUrl] = useState("http://127.0.0.1:8000");
  const [artifacts, setArtifacts] = useState<ArtifactsByUrlResponse | null>(null);
  const [activeTab, setActiveTab] = useState<"resume" | "cover_letter">("resume");
  const [filling, setFilling] = useState(false);
  const [fillResult, setFillResult] = useState<FillResult | null>(null);

  const refresh = useCallback(async () => {
    setStatus("checking");
    const [url, ok] = await Promise.all([getDashboardUrl(), checkHealth()]);
    setDashUrl(url);
    setStatus(ok ? "connected" : "disconnected");

    if (ok) {
      // Get current tab URL and look up artifacts
      const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
      const tabUrl = tabs[0]?.url;
      if (tabUrl) {
        const result = await getArtifactsByUrl(tabUrl);
        setArtifacts(result);
      }
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Re-check when active tab changes
  useEffect(() => {
    const listener = (tabId: number, changeInfo: chrome.tabs.TabChangeInfo) => {
      if (changeInfo.status === "complete") {
        void refresh();
      }
    };
    chrome.tabs.onUpdated.addListener(listener);
    return () => chrome.tabs.onUpdated.removeListener(listener);
  }, [refresh]);

  function handleAutofill() {
    setFilling(true);
    setFillResult(null);
    chrome.runtime.sendMessage(
      {
        type: "SIDEPANEL_AUTOFILL",
        resumeArtifactId: artifacts?.resume?.id ?? null,
        coverLetterArtifactId: artifacts?.cover_letter?.id ?? null,
      },
      (response) => {
        setFilling(false);
        if (!response) {
          setFillResult({ ok: false, error: "No response from content script. Make sure you are on a supported job application page." });
          return;
        }
        setFillResult(response as FillResult);
      }
    );
  }

  const statusLabel =
    status === "connected" ? "Connected" : status === "disconnected" ? "Offline" : "…";

  const hasArtifacts = artifacts && (artifacts.resume || artifacts.cover_letter);
  const activeArtifact: ArtifactInfo | null =
    activeTab === "resume" ? (artifacts?.resume ?? null) : (artifacts?.cover_letter ?? null);

  return (
    <div className="sp-root">
      {/* Header */}
      <div className="sp-header">
        <div className="sp-header-brand">
          <div className="sp-logo">AJH</div>
          <div>
            <div className="sp-brand-name">AI Job Hunter</div>
            <div className="sp-brand-sub">Side Panel</div>
          </div>
        </div>
        <div className={`sp-status-badge sp-status-badge--${status}`}>
          <span className="sp-status-dot" />
          {statusLabel}
        </div>
      </div>

      {/* Body */}
      <div className="sp-body">
        {status === "checking" && (
          <div className="sp-checking-dots">
            <span /><span /><span />
          </div>
        )}

        {status === "disconnected" && (
          <div className="sp-empty-state">
            <div className="sp-empty-state-icon">🔌</div>
            <div className="sp-empty-state-title">Backend not running</div>
            <div className="sp-empty-state-sub">
              Start the AI Job Hunter server at<br />{dashUrl}
            </div>
          </div>
        )}

        {status === "connected" && !hasArtifacts && (
          <div className="sp-no-artifacts">
            <div className="sp-no-artifacts-icon">📄</div>
            <div className="sp-no-artifacts-title">No artifacts for this page</div>
            <div className="sp-no-artifacts-sub">
              Prepare a tailored resume and cover letter in the Agent page of the AI Job Hunter dashboard,
              then return here to autofill.
            </div>
          </div>
        )}

        {status === "connected" && hasArtifacts && (
          <>
            {/* Job info */}
            {artifacts?.job_info && (
              <div className="sp-job-info">
                <div className="sp-job-company">{artifacts.job_info.company}</div>
                <div className="sp-job-title">{artifacts.job_info.title}</div>
                {artifacts.job_info.location && (
                  <div className="sp-job-location">{artifacts.job_info.location}</div>
                )}
              </div>
            )}

            {/* Tabs */}
            <div className="sp-tabs">
              {artifacts?.resume && (
                <button
                  className={`sp-tab${activeTab === "resume" ? " sp-tab--active" : ""}`}
                  onClick={() => setActiveTab("resume")}
                >
                  Resume
                </button>
              )}
              {artifacts?.cover_letter && (
                <button
                  className={`sp-tab${activeTab === "cover_letter" ? " sp-tab--active" : ""}`}
                  onClick={() => setActiveTab("cover_letter")}
                >
                  Cover Letter
                </button>
              )}
            </div>

            {/* Artifact preview */}
            {activeArtifact && (
              <div className="sp-artifact-content">
                <div
                  dangerouslySetInnerHTML={{ __html: renderMarkdown(activeArtifact.content_md) }}
                  style={{ fontSize: 12, lineHeight: 1.6, color: "#374151" }}
                />
                <div className="sp-artifact-meta">
                  Updated: {activeArtifact.updated_at.slice(0, 16).replace("T", " ")}
                </div>
              </div>
            )}
          </>
        )}

        {/* Fill result */}
        {fillResult && (
          <div className={`sp-fill-result ${fillResult.ok ? "sp-fill-result--ok" : "sp-fill-result--err"}`}>
            <span className="sp-fill-result-icon">{fillResult.ok ? "✓" : "!"}</span>
            <span>
              {fillResult.ok
                ? `Filled ${fillResult.filled} field${fillResult.filled === 1 ? "" : "s"}: ${fillResult.fields?.join(", ") || "none"}`
                : fillResult.error}
            </span>
          </div>
        )}

        {/* CTA */}
        <button
          className="sp-autofill-btn"
          disabled={filling || status !== "connected" || !hasArtifacts}
          onClick={handleAutofill}
        >
          {filling ? (
            <><span className="sp-btn-spinner" /> Filling…</>
          ) : (
            <><span className="sp-btn-lightning">⚡</span> Autofill + Upload Files</>
          )}
        </button>
      </div>

      {/* Footer */}
      <div className="sp-footer">
        Greenhouse · Lever · Ashby · Workable · SmartRecruiters
      </div>
    </div>
  );
}

const root = document.getElementById("root");
if (root) createRoot(root).render(<SidePanel />);
