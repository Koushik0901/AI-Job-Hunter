import { useEffect, useRef, useState } from "react";
import type { StoryKind, UserStory, UserStoryCreate } from "../types";
import { Button } from "./ui/button";

interface Props {
  story?: UserStory | null;
  onSave: (data: UserStoryCreate) => Promise<void>;
  onClose: () => void;
}

const KIND_OPTIONS: { value: StoryKind; label: string; description: string }[] = [
  { value: "role", label: "Role", description: "A job or position you've held" },
  { value: "project", label: "Project", description: "A project you built or contributed to" },
  { value: "aspiration", label: "Aspiration", description: "What you want to do next" },
  { value: "strength", label: "Strength", description: "What you're known for or praised for" },
];

function listToChips(text: string): string[] {
  return text
    .split(/\n|,/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export function StoryEditorModal({ story, onSave, onClose }: Props) {
  const isEdit = !!story;
  const dialogRef = useRef<HTMLDialogElement>(null);

  const [title, setTitle] = useState(story?.title ?? "");
  const [narrative, setNarrative] = useState(story?.narrative ?? "");
  const [roleContext, setRoleContext] = useState(story?.role_context ?? "");
  const [timePeriod, setTimePeriod] = useState(story?.time_period ?? "");
  const [skillsText, setSkillsText] = useState((story?.skills ?? []).join(", "));
  const [outcomesText, setOutcomesText] = useState((story?.outcomes ?? []).join("\n"));
  const [tagsText, setTagsText] = useState((story?.tags ?? []).join(", "));
  const [kind, setKind] = useState<StoryKind>(story?.kind ?? "role");
  const [importance, setImportance] = useState(story?.importance ?? 3);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    dialogRef.current?.showModal();
    return () => dialogRef.current?.close();
  }, []);

  async function handleSave() {
    if (!title.trim()) {
      setError("Title is required.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSave({
        title: title.trim(),
        narrative: narrative.trim(),
        role_context: roleContext.trim() || null,
        time_period: timePeriod.trim() || null,
        skills: listToChips(skillsText),
        outcomes: listToChips(outcomesText),
        tags: listToChips(tagsText),
        kind,
        importance,
        draft: false,
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <dialog
      ref={dialogRef}
      className="story-modal"
      onClick={(e) => { if (e.target === dialogRef.current) onClose(); }}
    >
      <div className="story-modal-inner">
        <div className="story-modal-header">
          <div>
            <p className="page-kicker">{isEdit ? "Edit story" : "New story"}</p>
            <h2>{isEdit ? story.title : "Capture a moment"}</h2>
          </div>
          <button className="story-modal-close" onClick={onClose} aria-label="Close">&#x2715;</button>
        </div>

        <div className="story-modal-body">
          {/* Kind selector */}
          <div className="story-kind-selector">
            {KIND_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                className={`story-kind-option${kind === opt.value ? " story-kind-option--active" : ""}`}
                onClick={() => setKind(opt.value)}
                type="button"
              >
                <span className="story-kind-option-label">{opt.label}</span>
                <span className="story-kind-option-desc">{opt.description}</span>
              </button>
            ))}
          </div>

          {/* Title */}
          <label className="settings-field">
            <span className="settings-field-label">Title <span className="required-star">*</span></span>
            <input
              className="settings-field-input"
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={
                kind === "role" ? "Senior ML Engineer at Acme" :
                kind === "project" ? "Built semantic search for 1M product catalog" :
                kind === "aspiration" ? "What I want to work on next" :
                "What colleagues say about working with me"
              }
            />
          </label>

          {/* Role context */}
          {(kind === "role" || kind === "project") && (
            <label className="settings-field">
              <span className="settings-field-label">
                {kind === "role" ? "Company and dates" : "Project context"}
              </span>
              <input
                className="settings-field-input"
                type="text"
                value={roleContext}
                onChange={(e) => setRoleContext(e.target.value)}
                placeholder={kind === "role" ? "Acme Corp (2022-2024)" : "Personal project / Hackathon 2023"}
              />
            </label>
          )}

          {/* Time period */}
          <label className="settings-field">
            <span className="settings-field-label">Time period</span>
            <input
              className="settings-field-input"
              type="text"
              value={timePeriod}
              onChange={(e) => setTimePeriod(e.target.value)}
              placeholder="2022-2024"
            />
          </label>

          {/* Narrative */}
          <label className="settings-field">
            <span className="settings-field-label">What happened?</span>
            <p className="settings-field-hint">
              Situation &rarr; what you did &rarr; what changed. Be specific and honest — this becomes grounding for your tailored resumes.
            </p>
            <textarea
              className="settings-field-textarea settings-field-textarea--large"
              value={narrative}
              onChange={(e) => setNarrative(e.target.value)}
              placeholder="We had a search system that returned irrelevant results for 40% of queries. I redesigned the ranking pipeline using dense retrieval (FAISS + bi-encoder), built an evaluation harness, and ran an A/B test. Precision@10 went from 0.54 to 0.81 across 3M queries. The team adopted it and I mentored two engineers through the embeddings stack."
            />
          </label>

          {/* Outcomes */}
          <label className="settings-field">
            <span className="settings-field-label">Outcomes and impact</span>
            <p className="settings-field-hint">One per line. Quantify where you can.</p>
            <textarea
              className="settings-field-textarea"
              value={outcomesText}
              onChange={(e) => setOutcomesText(e.target.value)}
              placeholder={"Precision@10 improved 54% -> 81%\nReduced search latency by 40ms\nMentored 2 engineers"}
            />
          </label>

          {/* Skills */}
          <label className="settings-field">
            <span className="settings-field-label">Skills demonstrated</span>
            <input
              className="settings-field-input"
              type="text"
              value={skillsText}
              onChange={(e) => setSkillsText(e.target.value)}
              placeholder="Python, FAISS, PyTorch, MLOps, A/B testing"
            />
          </label>

          {/* Tags */}
          <label className="settings-field">
            <span className="settings-field-label">Domain tags</span>
            <input
              className="settings-field-input"
              type="text"
              value={tagsText}
              onChange={(e) => setTagsText(e.target.value)}
              placeholder="search, nlp, leadership"
            />
          </label>

          {/* Importance */}
          <div className="settings-field">
            <span className="settings-field-label">Importance</span>
            <p className="settings-field-hint">How central is this story to your profile? 5 = defining career moment.</p>
            <div className="story-importance-row">
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  key={n}
                  type="button"
                  className={`story-importance-btn${n <= importance ? " story-importance-btn--lit" : ""}`}
                  onClick={() => setImportance(n)}
                  aria-label={`Importance ${n}`}
                >
                  &#9733;
                </button>
              ))}
              <span className="story-importance-label">
                {importance === 5 ? "Defining moment" :
                 importance === 4 ? "Very important" :
                 importance === 3 ? "Solid example" :
                 importance === 2 ? "Supporting detail" :
                 "Minor reference"}
              </span>
            </div>
          </div>

          {error && <div className="settings-error">{error}</div>}
        </div>

        <div className="story-modal-footer">
          <button className="story-action-btn" onClick={onClose} type="button">Cancel</button>
          <Button variant="primary" onClick={() => void handleSave()} disabled={saving}>
            {saving ? "Saving..." : isEdit ? "Save changes" : "Add story"}
          </Button>
        </div>
      </div>
    </dialog>
  );
}
