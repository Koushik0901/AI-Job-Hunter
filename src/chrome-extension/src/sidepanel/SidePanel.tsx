import { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { marked } from "marked";
import { checkHealth, getArtifactsByUrl, getDashboardUrl, saveCorrections } from "../api";
import type { ArtifactInfo, ArtifactsByUrlResponse } from "../api";
import type { FieldProposal, ScanResult } from "../content/types";
import "./sidepanel.css";

type Status = "checking" | "connected" | "disconnected";
type Phase = "idle" | "scanning" | "reviewing" | "filling" | "done";

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

function sendToBackground<T>(message: Record<string, unknown>): Promise<T> {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(message, (response) => resolve(response as T));
  });
}

function SidePanel() {
  const [status, setStatus] = useState<Status>("checking");
  const [dashUrl, setDashUrl] = useState("http://127.0.0.1:8000");
  const [artifacts, setArtifacts] = useState<ArtifactsByUrlResponse | null>(null);
  const [activeTab, setActiveTab] = useState<"resume" | "cover_letter">("resume");

  // Confirmation flow
  const [phase, setPhase] = useState<Phase>("idle");
  const [scanResult, setScanResult] = useState<ScanResult | null>(null);
  const [editedValues, setEditedValues] = useState<Record<string, string>>({});
  const [fillResult, setFillResult] = useState<FillResult | null>(null);

  const refresh = useCallback(async () => {
    setStatus("checking");
    const [url, ok] = await Promise.all([getDashboardUrl(), checkHealth()]);
    setDashUrl(url);
    setStatus(ok ? "connected" : "disconnected");

    if (ok) {
      const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
      const tabUrl = tabs[0]?.url;
      if (tabUrl) {
        const result = await getArtifactsByUrl(tabUrl);
        setArtifacts(result);
      }
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    const listener = (_tabId: number, changeInfo: chrome.tabs.TabChangeInfo) => {
      if (changeInfo.status === "complete") {
        setPhase("idle");
        setFillResult(null);
        setScanResult(null);
        void refresh();
      }
    };
    chrome.tabs.onUpdated.addListener(listener);
    return () => chrome.tabs.onUpdated.removeListener(listener);
  }, [refresh]);

  async function handleScan() {
    setPhase("scanning");
    setFillResult(null);
    const result = await sendToBackground<ScanResult>({ type: "SCAN_FIELDS" });
    if (!result || !result.fields) {
      setFillResult({ ok: false, error: "Could not scan page fields. Make sure you are on a supported job application page." });
      setPhase("idle");
      return;
    }
    setScanResult(result);
    const initial: Record<string, string> = {};
    for (const f of result.fields) initial[f.key] = f.value;
    setEditedValues(initial);
    setPhase("reviewing");
  }

  async function handleApply() {
    if (!scanResult) return;
    setPhase("filling");

    const result = await sendToBackground<FillResult>({
      type: "DO_FILL_FIELDS",
      confirmedValues: editedValues,
      resumeArtifactId: artifacts?.resume?.id ?? null,
      coverLetterArtifactId: artifacts?.cover_letter?.id ?? null,
    });

    // Learn from edits: compare confirmed vs. original proposals, save differences
    const originals: Record<string, string> = {};
    for (const f of scanResult.fields) originals[f.key] = f.value;
    const corrections: Record<string, string> = {};
    for (const [key, val] of Object.entries(editedValues)) {
      if (val && val !== originals[key]) corrections[key] = val;
    }
    if (Object.keys(corrections).length > 0) {
      void saveCorrections(scanResult.ats_host, corrections);
    }

    setFillResult(result || { ok: false, error: "No response from content script." });
    setPhase("done");
  }

  const statusLabel =
    status === "connected" ? "Connected" : status === "disconnected" ? "Offline" : "...";

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
          <div className="sp-checking-dots"><span /><span /><span /></div>
        )}

        {status === "disconnected" && (
          <div className="sp-empty-state">
            <div className="sp-empty-state-icon">&#x1F50C;</div>
            <div className="sp-empty-state-title">Backend not running</div>
            <div className="sp-empty-state-sub">
              Start the AI Job Hunter server at<br />{dashUrl}
            </div>
          </div>
        )}

        {status === "connected" && !hasArtifacts && phase === "idle" && (
          <div className="sp-no-artifacts">
            <div className="sp-no-artifacts-icon">&#x1F4C4;</div>
            <div className="sp-no-artifacts-title">No artifacts for this page</div>
            <div className="sp-no-artifacts-sub">
              Prepare a tailored resume and cover letter in the Agent page of the AI Job Hunter dashboard,
              then return here to autofill.
            </div>
          </div>
        )}

        {status === "connected" && hasArtifacts && phase === "idle" && (
          <>
            {artifacts?.job_info && (
              <div className="sp-job-info">
                <div className="sp-job-company">{artifacts.job_info.company}</div>
                <div className="sp-job-title">{artifacts.job_info.title}</div>
                {artifacts.job_info.location && (
                  <div className="sp-job-location">{artifacts.job_info.location}</div>
                )}
              </div>
            )}

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

        {/* Scanning spinner */}
        {phase === "scanning" && (
          <div className="sp-checking-dots" style={{ marginTop: 32 }}>
            <span /><span /><span />
            <p style={{ fontSize: 12, color: "#6b7280", marginTop: 12 }}>Scanning page fields...</p>
          </div>
        )}

        {/* Review phase */}
        {phase === "reviewing" && scanResult && (
          <div className="sp-review-panel">
            <div className="sp-review-title">Review fields to fill</div>
            <p className="sp-review-hint">
              Edit any value before applying. Changes are remembered for {scanResult.ats_host}.
            </p>
            <div className="sp-review-fields">
              {scanResult.fields.map((f: FieldProposal) => (
                <div key={f.key} className="sp-review-field">
                  <label className="sp-review-label">
                    {f.label}
                    {!f.found && <span className="sp-review-not-found"> (field not found on page)</span>}
                  </label>
                  <input
                    className="sp-review-input"
                    type="text"
                    value={editedValues[f.key] ?? f.value}
                    onChange={(e) => setEditedValues((prev) => ({ ...prev, [f.key]: e.target.value }))}
                    placeholder={f.label}
                  />
                </div>
              ))}
              {scanResult.fields.length === 0 && (
                <p className="sp-review-hint">No fillable profile fields detected on this page.</p>
              )}
            </div>
          </div>
        )}

        {/* Filling spinner */}
        {phase === "filling" && (
          <div className="sp-checking-dots" style={{ marginTop: 32 }}>
            <span /><span /><span />
            <p style={{ fontSize: 12, color: "#6b7280", marginTop: 12 }}>Applying fields...</p>
          </div>
        )}

        {/* Fill result */}
        {fillResult && (
          <div className={`sp-fill-result ${fillResult.ok ? "sp-fill-result--ok" : "sp-fill-result--err"}`}>
            <span className="sp-fill-result-icon">{fillResult.ok ? "+" : "!"}</span>
            <span>
              {fillResult.ok
                ? `Filled ${fillResult.filled} field${fillResult.filled === 1 ? "" : "s"}: ${fillResult.fields?.join(", ") || "none"}`
                : fillResult.error}
            </span>
          </div>
        )}
      </div>

      {/* CTA */}
      <div className="sp-footer-actions">
        {(phase === "idle" || phase === "done") && (
          <button
            className="sp-autofill-btn"
            disabled={status !== "connected" || !hasArtifacts}
            onClick={() => void handleScan()}
          >
            <span className="sp-btn-lightning">&#9889;</span> Review &amp; Fill
          </button>
        )}
        {phase === "reviewing" && (
          <div className="sp-review-actions">
            <button className="sp-btn-secondary" onClick={() => setPhase("idle")}>Cancel</button>
            <button className="sp-autofill-btn sp-autofill-btn--apply" onClick={() => void handleApply()}>
              Apply fills
            </button>
          </div>
        )}
      </div>

      <div className="sp-footer">
        Greenhouse · Lever · Ashby · Workable · SmartRecruiters
      </div>
    </div>
  );
}

const root = document.getElementById("root");
if (root) createRoot(root).render(<SidePanel />);
