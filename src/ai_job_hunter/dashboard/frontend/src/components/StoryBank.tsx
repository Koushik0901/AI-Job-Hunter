import { useCallback, useEffect, useState } from "react";
import type { BaseDocument, UserStory, UserStoryCreate } from "../types";
import {
  bulkAcceptStories,
  createStory,
  deleteStory,
  listStories,
  triggerJobEmbedding,
  triggerStoryEmbedding,
  updateStory,
} from "../api";
import { StoryCard } from "./StoryCard";
import { StoryEditorModal } from "./StoryEditorModal";
import { ResumeExtractModal } from "./ResumeExtractModal";
import { StoryWizard } from "./StoryWizard";

interface Props {
  resumeDocs: BaseDocument[];
}

type ActiveModal = "none" | "editor" | "extract" | "wizard";

export function StoryBank({ resumeDocs }: Props) {
  const [stories, setStories] = useState<UserStory[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeModal, setActiveModal] = useState<ActiveModal>("none");
  const [editingStory, setEditingStory] = useState<UserStory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [embedding, setEmbedding] = useState(false);
  const [embedResult, setEmbedResult] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const all = await listStories({ includeDrafts: true });
      setStories(all);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const drafts = stories.filter((s) => s.draft);
  const accepted = stories.filter((s) => !s.draft);

  async function handleSaveStory(data: UserStoryCreate) {
    if (editingStory) {
      const updated = await updateStory(editingStory.id, data);
      setStories((prev) => prev.map((s) => s.id === editingStory.id ? updated : s));
    } else {
      const created = await createStory(data);
      setStories((prev) => [created, ...prev]);
    }
  }

  async function handleDelete(id: number) {
    setError(null);
    try {
      await deleteStory(id);
      setStories((prev) => prev.filter((s) => s.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  }

  async function handleAcceptDraft(id: number) {
    try {
      await bulkAcceptStories([id]);
      setStories((prev) => prev.map((s) => s.id === id ? { ...s, draft: false } : s));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Accept failed");
    }
  }

  async function handleDiscardDraft(id: number) {
    await handleDelete(id);
  }

  function openEditor(story?: UserStory) {
    setEditingStory(story ?? null);
    setActiveModal("editor");
  }

  async function handleEmbed() {
    setEmbedding(true);
    setEmbedResult(null);
    try {
      const [sr, jr] = await Promise.all([triggerStoryEmbedding(), triggerJobEmbedding()]);
      const total = (sr.embedded ?? 0) + (jr.embedded ?? 0);
      setEmbedResult(total > 0 ? `Embedded ${sr.embedded} stories + ${jr.embedded} jobs` : "All up to date");
      setTimeout(() => setEmbedResult(null), 4000);
    } catch {
      setEmbedResult("Embedding failed");
      setTimeout(() => setEmbedResult(null), 3000);
    } finally {
      setEmbedding(false);
    }
  }

  const hasResume = resumeDocs.length > 0;
  const isEmpty = stories.length === 0;

  return (
    <section className="settings-surface story-bank">
      <div className="settings-surface-head">
        <div>
          <p className="page-kicker">Story bank</p>
          <h2>Who you are beyond a resume</h2>
        </div>
        <div className="story-bank-meta">
          {stories.length > 0 && (
            <span className="page-meta-pill">
              {accepted.length} stor{accepted.length === 1 ? "y" : "ies"}
              {drafts.length > 0 ? ` · ${drafts.length} draft${drafts.length === 1 ? "" : "s"}` : ""}
            </span>
          )}
        </div>
      </div>

      <p className="settings-copy-soft">
        Stories capture the moments that show how you think, build, and grow.
        They ground every resume and cover letter the system generates — so the more context you give, the better tailored your applications will be.
      </p>

      {/* Action bar */}
      <div className="story-bank-actions">
        <button
          className="story-action-btn story-action-btn--primary"
          onClick={() => openEditor()}
          type="button"
        >
          + New story
        </button>
        {hasResume && (
          <button
            className="story-action-btn story-action-btn--extract"
            onClick={() => setActiveModal("extract")}
            type="button"
          >
            &#8593; Draft from my resume
          </button>
        )}
        <button
          className="story-action-btn"
          onClick={() => setActiveModal("wizard")}
          type="button"
        >
          Guided wizard
        </button>
        {accepted.length > 0 && (
          <button
            className="story-action-btn story-action-btn--embed"
            onClick={() => void handleEmbed()}
            type="button"
            disabled={embedding}
            title="Compute semantic embeddings so the Recommend page can match your stories to jobs"
          >
            {embedding ? "Indexing..." : "Index for semantic ranking"}
          </button>
        )}
        {embedResult ? <span className="settings-saved-badge">{embedResult}</span> : null}
      </div>

      {error && <div className="settings-error">{error}</div>}

      {/* Empty state */}
      {isEmpty && !loading && (
        <div className="story-bank-empty">
          {hasResume ? (
            <>
              <p className="story-bank-empty-heading">Let's get to know you.</p>
              <p className="story-bank-empty-copy">
                Your story bank powers better job matching and grounded resume generation.
                Start in under 60 seconds.
              </p>
              <div className="story-bank-empty-actions">
                <button
                  className="story-action-btn story-action-btn--extract"
                  onClick={() => setActiveModal("extract")}
                  type="button"
                >
                  Draft from my resume
                </button>
                <button
                  className="story-action-btn"
                  onClick={() => setActiveModal("wizard")}
                  type="button"
                >
                  Answer 5 quick questions
                </button>
              </div>
            </>
          ) : (
            <>
              <p className="story-bank-empty-heading">Start your story bank.</p>
              <p className="story-bank-empty-copy">
                Upload a base resume in the Document Vault below to auto-draft stories from it,
                or add them manually.
              </p>
              <button
                className="story-action-btn"
                onClick={() => openEditor()}
                type="button"
              >
                Add a story manually
              </button>
            </>
          )}
        </div>
      )}

      {/* Draft section */}
      {drafts.length > 0 && (
        <div className="story-section">
          <div className="story-section-head">
            <span className="story-section-label">Pending review</span>
            <div className="story-section-actions">
              <button
                className="story-action-btn"
                onClick={() => void bulkAcceptStories(drafts.map((s) => s.id)).then(() => load())}
              >
                Keep all
              </button>
              <button
                className="story-action-btn story-action-btn--delete"
                onClick={() => Promise.all(drafts.map((s) => deleteStory(s.id))).then(() => load())}
              >
                Discard all
              </button>
            </div>
          </div>
          <div className="story-grid">
            {drafts.map((s) => (
              <StoryCard
                key={s.id}
                story={s}
                onEdit={openEditor}
                onDelete={handleDelete}
                onAcceptDraft={handleAcceptDraft}
                onDiscardDraft={handleDiscardDraft}
              />
            ))}
          </div>
        </div>
      )}

      {/* Accepted stories */}
      {accepted.length > 0 && (
        <div className="story-section">
          {drafts.length > 0 && (
            <div className="story-section-head">
              <span className="story-section-label">In your bank</span>
            </div>
          )}
          <div className="story-grid">
            {accepted.map((s) => (
              <StoryCard
                key={s.id}
                story={s}
                onEdit={openEditor}
                onDelete={handleDelete}
              />
            ))}
          </div>
        </div>
      )}

      {/* Modals */}
      {activeModal === "editor" && (
        <StoryEditorModal
          story={editingStory}
          onSave={handleSaveStory}
          onClose={() => { setActiveModal("none"); setEditingStory(null); }}
        />
      )}

      {activeModal === "extract" && (
        <ResumeExtractModal
          resumeDocs={resumeDocs}
          onClose={() => setActiveModal("none")}
          onComplete={() => { setActiveModal("none"); void load(); }}
        />
      )}

      {activeModal === "wizard" && (
        <StoryWizard
          onClose={() => setActiveModal("none")}
          onComplete={(_count) => { setActiveModal("none"); void load(); }}
        />
      )}
    </section>
  );
}
