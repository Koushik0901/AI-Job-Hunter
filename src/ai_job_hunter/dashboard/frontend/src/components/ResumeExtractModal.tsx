import { useCallback, useEffect, useRef, useState } from "react";
import type { BaseDocument, ExtractedProfileDelta, UserStory, WorkspaceOperation } from "../types";
import { bulkAcceptStories, extractStoriesFromResume, listStories } from "../api";
import { Button } from "./ui/button";

interface Props {
  resumeDocs: BaseDocument[];
  onClose: () => void;
  onComplete: () => void;
}

type Stage = "pick" | "running" | "review" | "done";

interface DraftBundle {
  stories: UserStory[];
  profileDelta: ExtractedProfileDelta | null;
}

const PROFILE_DELTA_LABELS: Record<string, string> = {
  full_name: "Full name",
  email: "Email",
  phone: "Phone",
  linkedin_url: "LinkedIn URL",
  portfolio_url: "Portfolio / GitHub",
  city: "City",
  country: "Country",
  years_experience: "Years of experience",
  degree: "Degree level",
  degree_field: "Degree field",
};

export function ResumeExtractModal({ resumeDocs, onClose, onComplete }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const pollRef = useRef<number>(0);

  const [stage, setStage] = useState<Stage>(resumeDocs.length === 1 ? "running" : "pick");
  const [selectedDocId, setSelectedDocId] = useState<number>(
    resumeDocs.find((d) => d.is_default)?.id ?? resumeDocs[0]?.id ?? 0
  );
  const [operation, setOperation] = useState<WorkspaceOperation | null>(null);
  const [draft, setDraft] = useState<DraftBundle | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [applyProfile, setApplyProfile] = useState(true);
  const [accepting, setAccepting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    dialogRef.current?.showModal();
    return () => {
      window.clearInterval(pollRef.current);
      dialogRef.current?.close();
    };
  }, []);

  const startExtraction = useCallback(async (docId: number) => {
    setError(null);
    setStage("running");
    try {
      const op = await extractStoriesFromResume(docId);
      setOperation(op);
      pollRef.current = window.setInterval(async () => {
        try {
          const resp = await fetch(`/api/operations/${op.id}`);
          if (!resp.ok) return;
          const fresh: WorkspaceOperation = await resp.json();
          setOperation(fresh);
          if (fresh.status === "completed") {
            window.clearInterval(pollRef.current);
            // Load the drafted stories just saved
            const all = await listStories({ includeDrafts: true });
            const newDrafts = all.filter((s) => s.draft && s.source === "resume_extracted");
            const delta = (fresh.summary as { profile_delta?: ExtractedProfileDelta }).profile_delta ?? null;
            setDraft({ stories: newDrafts, profileDelta: delta });
            setSelectedIds(new Set(newDrafts.map((s) => s.id)));
            setStage("review");
          } else if (fresh.status === "failed") {
            window.clearInterval(pollRef.current);
            setError(fresh.error ?? "Extraction failed. Please try again.");
            setStage("pick");
          }
        } catch {
          // tolerate poll errors
        }
      }, 2500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start extraction");
      setStage("pick");
    }
  }, []);

  // Auto-start if only one doc
  useEffect(() => {
    if (resumeDocs.length === 1 && stage === "running") {
      void startExtraction(resumeDocs[0].id);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleAccept() {
    if (!draft) return;
    setAccepting(true);
    setError(null);
    try {
      const ids = Array.from(selectedIds);
      const delta = applyProfile && draft.profileDelta ? draft.profileDelta : null;
      await bulkAcceptStories(ids, delta);
      setStage("done");
      onComplete();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Accept failed");
    } finally {
      setAccepting(false);
    }
  }

  function toggleStory(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const profileDeltaEntries = draft?.profileDelta
    ? Object.entries(draft.profileDelta).filter(([, v]) => v !== null && v !== undefined && (Array.isArray(v) ? v.length > 0 : true))
    : [];

  return (
    <dialog
      ref={dialogRef}
      className="story-modal story-modal--wide"
      onClick={(e) => { if (e.target === dialogRef.current) onClose(); }}
    >
      <div className="story-modal-inner">
        <div className="story-modal-header">
          <div>
            <p className="page-kicker">Resume extraction</p>
            <h2>
              {stage === "pick" && "Choose a resume to extract from"}
              {stage === "running" && "Reading your resume..."}
              {stage === "review" && "Review extracted stories"}
              {stage === "done" && "Stories added"}
            </h2>
          </div>
          <button className="story-modal-close" onClick={onClose} aria-label="Close">&#x2715;</button>
        </div>

        <div className="story-modal-body">
          {/* Pick stage */}
          {stage === "pick" && (
            <div className="extract-pick">
              <p className="settings-copy-soft">
                We'll read your resume and draft story cards for each role and project,
                plus fill in profile basics. You'll review everything before it's saved.
              </p>
              <div className="extract-doc-list">
                {resumeDocs.map((doc) => (
                  <label key={doc.id} className={`extract-doc-item${selectedDocId === doc.id ? " extract-doc-item--selected" : ""}`}>
                    <input
                      type="radio"
                      name="resume_doc"
                      value={doc.id}
                      checked={selectedDocId === doc.id}
                      onChange={() => setSelectedDocId(doc.id)}
                    />
                    <div>
                      <strong>{doc.filename}</strong>
                      {doc.is_default && <span className="doc-default-badge">Default</span>}
                      <small>{doc.created_at.slice(0, 10)}</small>
                    </div>
                  </label>
                ))}
              </div>
              {error && <div className="settings-error">{error}</div>}
            </div>
          )}

          {/* Running stage */}
          {stage === "running" && (
            <div className="extract-running">
              <div className="extract-spinner" aria-label="Processing" />
              <p>Reading your resume and drafting story cards...</p>
              <p className="settings-copy-soft">This takes about 15-20 seconds.</p>
              {operation && (
                <p className="settings-copy-soft">Status: {operation.status}</p>
              )}
            </div>
          )}

          {/* Review stage */}
          {stage === "review" && draft && (
            <div className="extract-review">
              {profileDeltaEntries.length > 0 && (
                <div className="extract-section">
                  <label className="extract-section-toggle">
                    <input
                      type="checkbox"
                      checked={applyProfile}
                      onChange={(e) => setApplyProfile(e.target.checked)}
                    />
                    <span className="settings-field-label">Also update profile fields</span>
                  </label>
                  {applyProfile && (
                    <div className="extract-profile-delta">
                      {profileDeltaEntries.map(([key, val]) => (
                        <div key={key} className="extract-delta-row">
                          <span className="extract-delta-key">
                            {PROFILE_DELTA_LABELS[key] ?? key}
                          </span>
                          <span className="extract-delta-val">
                            {Array.isArray(val) ? val.join(", ") : String(val)}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              <div className="extract-section">
                <div className="extract-section-head">
                  <span className="settings-field-label">
                    {draft.stories.length} stor{draft.stories.length === 1 ? "y" : "ies"} drafted
                  </span>
                  <div className="extract-select-row">
                    <button
                      className="story-action-btn"
                      onClick={() => setSelectedIds(new Set(draft.stories.map((s) => s.id)))}
                    >
                      Select all
                    </button>
                    <button
                      className="story-action-btn"
                      onClick={() => setSelectedIds(new Set())}
                    >
                      Deselect all
                    </button>
                  </div>
                </div>

                <div className="extract-story-list">
                  {draft.stories.map((s) => (
                    <label
                      key={s.id}
                      className={`extract-story-item${selectedIds.has(s.id) ? " extract-story-item--selected" : ""}`}
                    >
                      <input
                        type="checkbox"
                        checked={selectedIds.has(s.id)}
                        onChange={() => toggleStory(s.id)}
                      />
                      <div className="extract-story-content">
                        <div className="extract-story-title-row">
                          <strong>{s.title}</strong>
                          <span className="story-kind-chip">{s.kind}</span>
                          {s.time_period && <span className="story-period">{s.time_period}</span>}
                        </div>
                        {s.role_context && <p className="story-role-context">{s.role_context}</p>}
                        {s.narrative && (
                          <p className="story-narrative-preview">
                            {s.narrative.length > 200 ? `${s.narrative.slice(0, 200)}…` : s.narrative}
                          </p>
                        )}
                        {s.skills.length > 0 && (
                          <div className="story-skills">
                            {s.skills.slice(0, 6).map((sk) => (
                              <span key={sk} className="story-skill-chip">{sk}</span>
                            ))}
                            {s.skills.length > 6 && (
                              <span className="story-skill-chip story-skill-chip--more">+{s.skills.length - 6}</span>
                            )}
                          </div>
                        )}
                      </div>
                    </label>
                  ))}
                </div>
              </div>

              {error && <div className="settings-error">{error}</div>}
            </div>
          )}
        </div>

        <div className="story-modal-footer">
          {stage === "pick" && (
            <>
              <button className="story-action-btn" onClick={onClose}>Cancel</button>
              <Button
                variant="primary"
                onClick={() => void startExtraction(selectedDocId)}
                disabled={!selectedDocId}
              >
                Extract stories
              </Button>
            </>
          )}
          {stage === "running" && (
            <button className="story-action-btn" onClick={onClose}>Cancel</button>
          )}
          {stage === "review" && (
            <>
              <button className="story-action-btn" onClick={onClose}>Discard all</button>
              <Button
                variant="primary"
                onClick={() => void handleAccept()}
                disabled={accepting || selectedIds.size === 0}
              >
                {accepting
                  ? "Saving..."
                  : `Accept ${selectedIds.size} stor${selectedIds.size === 1 ? "y" : "ies"}`}
              </Button>
            </>
          )}
          {stage === "done" && (
            <Button variant="primary" onClick={onClose}>Done</Button>
          )}
        </div>
      </div>
    </dialog>
  );
}
