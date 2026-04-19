import { useEffect, useRef, useState } from "react";
import { getScoreRecomputeStatus, triggerScoreRecompute } from "../api";
import { Button } from "./ui/button";
import type { ScoreRecomputeStatus as ScoreRecomputeStatusType } from "../types";

function formatTimestamp(value: string | null): string {
  if (!value) return "never";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return "unknown";
  return parsed.toLocaleString();
}

export function ScoreRecomputeStatus() {
  const [status, setStatus] = useState<ScoreRecomputeStatusType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [triggering, setTriggering] = useState(false);
  const timeoutRef = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function refresh(): Promise<void> {
      let nextRunning = false;
      try {
        const next = await getScoreRecomputeStatus();
        if (cancelled) return;
        setStatus(next);
        setError(null);
        nextRunning = Boolean(next.running);
      } catch (fetchError) {
        if (cancelled) return;
        setError(fetchError instanceof Error ? fetchError.message : "Failed to load score recompute status");
      } finally {
        if (!cancelled) {
          setLoading(false);
          const ms = nextRunning ? 1500 : 8000;
          timeoutRef.current = window.setTimeout(() => {
            void refresh();
          }, ms);
        }
      }
    }

    void refresh();
    return () => {
      cancelled = true;
      if (timeoutRef.current) {
        window.clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  async function handleTrigger(): Promise<void> {
    setTriggering(true);
    try {
      await triggerScoreRecompute();
      const next = await getScoreRecomputeStatus();
      setStatus(next);
      setError(null);
    } catch (triggerError) {
      setError(triggerError instanceof Error ? triggerError.message : "Failed to trigger score recompute");
    } finally {
      setTriggering(false);
    }
  }

  const running = Boolean(status?.running);
  const progress = running
    ? `Recomputing match scores ${status?.last_processed ?? 0}/${status?.last_total ?? "?"}`
    : `Last recompute: ${formatTimestamp(status?.last_finished_at ?? null)}`;
  const meta = running
    ? `Scope: ${status?.last_scope ?? "all"}`
    : `Duration: ${status?.last_duration_ms ?? 0}ms`;

  return (
    <section className="score-recompute-banner" aria-live="polite">
      <div>
        <p className="score-recompute-title">{running ? "Score Refresh Running" : "Score Refresh Status"}</p>
        <p className="score-recompute-body">{loading ? "Loading status..." : progress}</p>
        <p className="score-recompute-meta">
          {meta}
          {status && status.queued_while_running > 0 ? ` · queued: ${status.queued_while_running}` : ""}
        </p>
        {status?.last_error && <p className="score-recompute-error">Last error: {status.last_error}</p>}
        {error && <p className="score-recompute-error">{error}</p>}
      </div>
      <Button
        type="button"
        variant="default"
        size="compact"
        data-icon="↻"
        onClick={() => void handleTrigger()}
        disabled={triggering || running}
      >
        {running ? "Running..." : triggering ? "Scheduling..." : "Recompute now"}
      </Button>
    </section>
  );
}
