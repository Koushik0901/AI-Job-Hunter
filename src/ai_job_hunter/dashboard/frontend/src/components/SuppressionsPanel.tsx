import React, { memo } from "react";
import { Button } from "./ui/button";
import { ThemedLoader } from "./ThemedLoader";
import type { SuppressedJob } from "../types";

interface SuppressionsPanelProps {
  isOpen: boolean;
  onClose: () => void;
  suppressions: SuppressedJob[];
  loading: boolean;
  error: string | null;
  onRestore: (jobId: string, url: string) => void;
  restoringUrl: string | null;
}

export const SuppressionsPanel = memo(function SuppressionsPanel({
  isOpen,
  onClose,
  suppressions,
  loading,
  error,
  onRestore,
  restoringUrl,
}: SuppressionsPanelProps) {
  if (!isOpen) return null;

  return (
    <div
      className="confirm-modal-layer"
      role="presentation"
      onClick={() => {
        if (!restoringUrl) onClose();
      }}
    >
      <section
        className="confirm-modal suppression-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="suppression-list-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="confirm-modal-head">
          <h4 id="suppression-list-title">Suppressed Jobs</h4>
        </header>
        <p className="confirm-modal-message">
          These jobs are hidden and blocked from future scrape ingestion. Restore any URL to allow it again.
        </p>
        {error && <p className="confirm-modal-error">{error}</p>}
        {loading ? (
          <div className="suppression-loading">
            <ThemedLoader label="Loading suppressions" />
          </div>
        ) : suppressions.length === 0 ? (
          <p className="empty-text">No suppressed jobs.</p>
        ) : (
          <div className="suppression-list">
            {suppressions.map((item) => (
              <article key={item.job_id || item.url} className="suppression-item">
                <div className="suppression-copy">
                  <p>{item.company || "Unknown company"}</p>
                  <small>{item.reason || "No reason provided"}</small>
                  <code>{item.url}</code>
                </div>
                <Button
                  type="button"
                  variant="default"
                  size="compact"
                  data-icon="⟲"
                  disabled={restoringUrl === item.url}
                  onClick={() => onRestore(item.job_id, item.url)}
                >
                  {restoringUrl === item.url ? "Restoring..." : "Restore"}
                </Button>
              </article>
            ))}
          </div>
        )}
        <div className="confirm-modal-actions">
          <Button
            type="button"
            variant="default"
            size="compact"
            data-icon="↩"
            onClick={onClose}
            disabled={Boolean(restoringUrl)}
          >
            Close
          </Button>
        </div>
      </section>
    </div>
  );
});
