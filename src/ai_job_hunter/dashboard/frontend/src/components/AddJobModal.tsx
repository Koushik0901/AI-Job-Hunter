import React, { memo } from "react";
import { formatDateShort } from "../dateUtils";
import { Button } from "./ui/button";
import { ThemedSelect } from "./ThemedSelect";
import type { ManualJobCreateRequest, TrackingStatus } from "../types";

interface AddJobModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: () => void;
  form: ManualJobCreateRequest;
  onFormChange: (form: ManualJobCreateRequest) => void;
  isSaving: boolean;
  attemptedSubmit: boolean;
  isFieldMissing: (field: string) => boolean;
  duplicateCandidate: {
    jobId: string;
    title: string;
    company: string;
    location: string;
    posted: string;
    matchKind: "url" | "content";
  } | null;
  error: string | null;
  stageOptions: Array<{ value: TrackingStatus; label: string }>;
}

export const AddJobModal = memo(function AddJobModal({
  isOpen,
  onClose,
  onSave,
  form,
  onFormChange,
  isSaving,
  attemptedSubmit,
  isFieldMissing,
  duplicateCandidate,
  error,
  stageOptions,
}: AddJobModalProps) {
  if (!isOpen) return null;

  return (
    <div
      className="confirm-modal-layer"
      role="presentation"
      onClick={() => {
        if (!isSaving) onClose();
      }}
    >
      <section
        className="confirm-modal confirm-modal--manual"
        role="dialog"
        aria-modal="true"
        aria-labelledby="manual-create-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="confirm-modal-head confirm-modal-head--manual">
          <div>
            <h4 id="manual-create-title">Add job</h4>
          </div>
        </header>
        {duplicateCandidate ? (
          <div className="manual-modal-warning manual-modal-warning--duplicate">
            <strong>Already on the board</strong>
            <span>
              {duplicateCandidate.title} · {duplicateCandidate.company} · {duplicateCandidate.location} ·{" "}
              {formatDateShort(duplicateCandidate.posted, "Unknown date")} · saving will open the existing record.
            </span>
          </div>
        ) : null}
        <div className="drawer-grid">
          <label className="full-width">
            <span>Job URL *</span>
            <input
              type="url"
              className={attemptedSubmit && isFieldMissing("url") ? "field-invalid" : undefined}
              aria-invalid={attemptedSubmit && isFieldMissing("url")}
              value={form.url}
              onChange={(event) => onFormChange({ ...form, url: event.target.value })}
              placeholder="https://company.com/careers/job/123"
            />
          </label>
          <label>
            <span>Company *</span>
            <input
              type="text"
              className={attemptedSubmit && isFieldMissing("company") ? "field-invalid" : undefined}
              aria-invalid={attemptedSubmit && isFieldMissing("company")}
              value={form.company}
              onChange={(event) => onFormChange({ ...form, company: event.target.value })}
              placeholder="Company name"
            />
          </label>
          <label>
            <span>Title *</span>
            <input
              type="text"
              className={attemptedSubmit && isFieldMissing("title") ? "field-invalid" : undefined}
              aria-invalid={attemptedSubmit && isFieldMissing("title")}
              value={form.title}
              onChange={(event) => onFormChange({ ...form, title: event.target.value })}
              placeholder="Role title"
            />
          </label>
          <label>
            <span>Location</span>
            <input
              type="text"
              value={form.location ?? ""}
              onChange={(event) => onFormChange({ ...form, location: event.target.value })}
              placeholder="City, Country / Remote"
            />
          </label>
          <label>
            <span>Posted Date</span>
            <input
              type="date"
              value={form.posted ?? ""}
              onChange={(event) => onFormChange({ ...form, posted: event.target.value })}
            />
          </label>
          <label>
            <span>Stage</span>
            <ThemedSelect
              value={(form.status ?? "staging") as TrackingStatus}
              options={stageOptions}
              onChange={(value) => onFormChange({ ...form, status: value as TrackingStatus })}
              ariaLabel="Manual job stage"
            />
          </label>
          <label className="full-width">
            <span>Description *</span>
            <textarea
              className={`manual-job-textarea ${attemptedSubmit && isFieldMissing("description") ? "field-invalid" : ""}`.trim()}
              aria-invalid={attemptedSubmit && isFieldMissing("description")}
              value={form.description}
              onChange={(event) => onFormChange({ ...form, description: event.target.value })}
              placeholder="Paste the full job description."
            />
          </label>
        </div>
        {error ? <p className="confirm-modal-error">{error}</p> : null}
        <div className="confirm-modal-footer">
          <div className="confirm-modal-actions">
            <Button
              type="button"
              variant="default"
              size="compact"
              data-icon="↗"
              onClick={onClose}
              disabled={isSaving}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              data-icon="✓"
              onClick={onSave}
              disabled={isSaving}
            >
              {isSaving ? "Saving..." : duplicateCandidate ? "Open existing" : "Save"}
            </Button>
          </div>
        </div>
      </section>
    </div>
  );
});
