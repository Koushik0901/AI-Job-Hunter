import { useRef, memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

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
}: ArtifactEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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
        <span className="artifact-editor-label">{label}</span>
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
