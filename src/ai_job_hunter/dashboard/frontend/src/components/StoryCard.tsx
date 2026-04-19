import type { UserStory } from "../types";

interface Props {
  story: UserStory;
  onEdit: (story: UserStory) => void;
  onDelete: (id: number) => void;
  onAcceptDraft?: (id: number) => void;
  onDiscardDraft?: (id: number) => void;
}

const KIND_LABEL: Record<string, string> = {
  role: "Role",
  project: "Project",
  aspiration: "Aspiration",
  strength: "Strength",
};

export function StoryCard({ story, onEdit, onDelete, onAcceptDraft, onDiscardDraft }: Props) {
  const visibleSkills = story.skills.slice(0, 5);
  const extraSkills = story.skills.length - visibleSkills.length;

  return (
    <div className={`story-card${story.draft ? " story-card--draft" : ""}`}>
      {story.draft && (
        <div className="story-draft-stripe" aria-label="Draft — awaiting review" />
      )}

      <div className="story-card-body">
        <div className="story-card-header">
          <div className="story-card-meta">
            <span className="story-kind-chip">{KIND_LABEL[story.kind] ?? story.kind}</span>
            {story.time_period && (
              <span className="story-period">{story.time_period}</span>
            )}
            {story.draft && (
              <span className="story-draft-badge">Draft</span>
            )}
          </div>
          <div className="story-importance" aria-label={`Importance ${story.importance} of 5`}>
            {[1, 2, 3, 4, 5].map((n) => (
              <span
                key={n}
                className={`story-star${n <= story.importance ? " story-star--lit" : ""}`}
              >
                &#9733;
              </span>
            ))}
          </div>
        </div>

        <h3 className="story-card-title">{story.title}</h3>
        {story.role_context && (
          <p className="story-role-context">{story.role_context}</p>
        )}

        {story.narrative && (
          <p className="story-narrative-preview">
            {story.narrative.length > 180
              ? `${story.narrative.slice(0, 180).trimEnd()}…`
              : story.narrative}
          </p>
        )}

        {story.outcomes.length > 0 && (
          <ul className="story-outcomes">
            {story.outcomes.slice(0, 3).map((o, i) => (
              <li key={i}>{o}</li>
            ))}
          </ul>
        )}

        {visibleSkills.length > 0 && (
          <div className="story-skills">
            {visibleSkills.map((s) => (
              <span key={s} className="story-skill-chip">{s}</span>
            ))}
            {extraSkills > 0 && (
              <span className="story-skill-chip story-skill-chip--more">+{extraSkills}</span>
            )}
          </div>
        )}
      </div>

      <div className="story-card-actions">
        {story.draft ? (
          <>
            <button
              className="story-action-btn story-action-btn--accept"
              onClick={() => onAcceptDraft?.(story.id)}
            >
              Keep
            </button>
            <button
              className="story-action-btn"
              onClick={() => onEdit(story)}
            >
              Edit
            </button>
            <button
              className="story-action-btn story-action-btn--discard"
              onClick={() => onDiscardDraft?.(story.id)}
            >
              Discard
            </button>
          </>
        ) : (
          <>
            <button className="story-action-btn" onClick={() => onEdit(story)}>
              Edit
            </button>
            <button
              className="story-action-btn story-action-btn--delete"
              onClick={() => onDelete(story.id)}
            >
              Delete
            </button>
          </>
        )}
      </div>
    </div>
  );
}
