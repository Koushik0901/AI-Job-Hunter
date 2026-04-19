import { useRef, memo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { AtsCritique } from "../types";

interface ArtifactEditorProps {
  label: "Resume" | "Cover Letter";
  value: string;
  onChange: (v: string) => void;
  onSave: () => void;
  onGenerate: () => void;
  onDownload: () => void;
  generating: boolean;
  saving: boolean;
  saved: boolean;
  artifactId: number | null;
  tab: "edit" | "preview";
  onTabChange: (t: "edit" | "preview") => void;
  storiesGrounded?: number;
  onCheckAts?: () => Promise<AtsCritique>;
}

export const ArtifactEditor = memo(function ArtifactEditor({
  label,
  value,
  onChange,
  onSave,
  onGenerate,
  onDownload,
  generating,
  saving,
  saved,
  artifactId,
  tab,
  onTabChange,
  storiesGrounded = 0,
  onCheckAts,
}: ArtifactEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [critiquing, setCritiquing] = useState(false);
  const [critique, setCritique] = useState<AtsCritique | null>(null);

  async function handleCheckAts() {
    if (!onCheckAts || critiquing) return;
    setCritiquing(true);
    setCritique(null);
    try {
      const result = await onCheckAts();
      setCritique(result);
    } finally {
      setCritiquing(false);
    }
  }

  function handleApplyRevised() {
    if (!critique?.revised_resume) return;
    onChange(critique.revised_resume);
    setCritique(null);
  }

  function handleTextareaChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    onChange(e.target.value);
    // Auto-height
    const el = e.target;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }

  return (
    <div className="artifact-editor">
      <div className="artifact-editor-header">
        <div className="artifact-editor-title">
          <span className="artifact-editor-label">{label}</span>
          {storiesGrounded > 0 && (
            <span
              className="artifact-grounded-badge"
              title={`Generated using ${storiesGrounded} stor${storiesGrounded === 1 ? "y" : "ies"} from your story bank`}
            >
              {storiesGrounded} {storiesGrounded === 1 ? "story" : "stories"} used
            </span>
          )}
        </div>
        <div className="artifact-editor-actions">
          <button
            className="artifact-btn artifact-btn--generate"
            onClick={onGenerate}
            disabled={generating}
            title={`Generate tailored ${label.toLowerCase()}`}
          >
            {generating ? (
              <><span className="artifact-spinner" /> Generating…</>
            ) : (
              <>✨ Generate</>
            )}
          </button>
          {onCheckAts && value && (
            <button
              className="artifact-btn artifact-btn--ats"
              onClick={() => void handleCheckAts()}
              disabled={critiquing || generating}
              title="Check ATS pass likelihood and get suggestions"
            >
              {critiquing ? (
                <><span className="artifact-spinner artifact-spinner--dark" /> Checking…</>
              ) : (
                <>⚡ Check ATS</>
              )}
            </button>
          )}
          {artifactId !== null && (
            <button
              className="artifact-btn artifact-btn--download"
              onClick={onDownload}
              title={`Download ${label} as PDF`}
            >
              ↓ PDF
            </button>
          )}
        </div>
      </div>

      {value && (
        <>
          <div className="artifact-tabs">
            <button
              className={`artifact-tab${tab === "edit" ? " artifact-tab--active" : ""}`}
              onClick={() => onTabChange("edit")}
            >
              Edit
            </button>
            <button
              className={`artifact-tab${tab === "preview" ? " artifact-tab--active" : ""}`}
              onClick={() => onTabChange("preview")}
            >
              Preview
            </button>
          </div>

          {tab === "edit" ? (
            <textarea
              ref={textareaRef}
              className="artifact-textarea"
              value={value}
              onChange={handleTextareaChange}
              spellCheck={false}
              placeholder={`${label} markdown will appear here after generation…`}
            />
          ) : (
            <div className="artifact-preview">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{value}</ReactMarkdown>
            </div>
          )}

          <div className="artifact-footer">
            <button
              className="artifact-btn artifact-btn--save"
              onClick={onSave}
              disabled={saving || saved}
            >
              {saving ? "Saving…" : "Save"}
            </button>
            <span className={`artifact-save-status ${saved ? "artifact-save-status--saved" : "artifact-save-status--unsaved"}`}>
              {saved ? "Saved ✓" : "Unsaved changes •"}
            </span>
          </div>

          {critique && (
            <div className="ats-critique">
              <div className="ats-critique-header">
                <div className="ats-critique-score-row">
                  <span className="ats-critique-title">ATS Analysis</span>
                  <span
                    className={`ats-score-badge ${critique.pass_likelihood >= 75 ? "ats-score-badge--high" : critique.pass_likelihood >= 50 ? "ats-score-badge--mid" : "ats-score-badge--low"}`}
                  >
                    {critique.pass_likelihood}% pass likelihood
                  </span>
                </div>
                <button className="ats-critique-dismiss" onClick={() => setCritique(null)} aria-label="Dismiss">✕</button>
              </div>

              {critique.missing_keywords.length > 0 && (
                <div className="ats-critique-section">
                  <p className="ats-critique-section-label">Missing keywords</p>
                  <div className="ats-keyword-chips">
                    {critique.missing_keywords.map((kw) => (
                      <span key={kw} className="ats-keyword-chip">{kw}</span>
                    ))}
                  </div>
                </div>
              )}

              {critique.weak_sections.length > 0 && (
                <div className="ats-critique-section">
                  <p className="ats-critique-section-label">Weak or missing sections</p>
                  <div className="ats-keyword-chips">
                    {critique.weak_sections.map((s) => (
                      <span key={s} className="ats-weak-chip">{s}</span>
                    ))}
                  </div>
                </div>
              )}

              {critique.suggestions.length > 0 && (
                <div className="ats-critique-section">
                  <p className="ats-critique-section-label">Suggestions</p>
                  <ul className="ats-suggestions">
                    {critique.suggestions.map((s, i) => (
                      <li key={i}>{s}</li>
                    ))}
                  </ul>
                </div>
              )}

              {critique.revised_resume && (
                <button className="ats-apply-btn" onClick={handleApplyRevised}>
                  Apply revised resume
                </button>
              )}
            </div>
          )}
        </>
      )}

      {!value && !generating && (
        <div className="artifact-empty">
          Click Generate to create a tailored {label.toLowerCase()} for this job.
        </div>
      )}
    </div>
  );
});
