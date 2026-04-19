import { motion } from "framer-motion";
import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { addToQueue, fetchJobDescriptionPdf } from "../api";
import { useDashboardData } from "../contexts/DashboardDataContext";
import { formatDateTime } from "../dateUtils";
import {
  fuzzySkillsMatch,
  normalizeSkill,
} from "../skillUtils";
import { buildJobFitAnalysis, buildRecommendationGuidance } from "../jobDetailUtils";
import type { CandidateProfile, JobDetail, JobEvent, JobSummary, Priority, Recommendation, TrackingStatus } from "../types";
import { AnimatedList } from "./reactbits/AnimatedList";
import { ThemedSelect } from "./ThemedSelect";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "./ui/alert-dialog";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";

interface DetailDrawerProps {
  open: boolean;
  loading: boolean;
  job: JobDetail | null;
  summaryJob?: JobSummary | null;
  profile: CandidateProfile | null;
  events: JobEvent[];
  enrichmentPending?: boolean;
  onClose: () => void;
  onAddSkillToProfile?: (skill: string) => Promise<void>;
  onDeleteJob?: (jobId: string) => Promise<void>;
  onSuppressJob?: (jobId: string, reason?: string) => Promise<void>;
  onRetryProcessing?: (jobId: string) => Promise<void>;
  onSaveDecision?: (jobId: string, recommendation: Recommendation) => Promise<void>;
  onChangeTracking: (patch: {
    status?: TrackingStatus;
    priority?: Priority;
    pinned?: boolean;
    applied_at?: string | null;
    next_step?: string | null;
    target_compensation?: string | null;
  }) => Promise<void>;
}

const STATUS_OPTIONS: Array<{ value: TrackingStatus; label: string }> = [
  { value: "not_applied", label: "Not Applied" },
  { value: "staging", label: "Staging" },
  { value: "applied", label: "Applied" },
  { value: "interviewing", label: "Interviewing" },
  { value: "offer", label: "Offer" },
  { value: "rejected", label: "Rejected" },
];

const PRIORITY_SELECT_OPTIONS: Array<{ value: Priority; label: string }> = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
];

type FitState = "pass" | "fail" | "unknown";

interface FitCheck {
  label: string;
  detail: string;
  state: FitState;
  impact?: "critical" | "important" | "nice";
}

const DescriptionMarkdown = lazy(async () => import("./DescriptionMarkdown").then((module) => ({ default: module.DescriptionMarkdown })));

function valueOrDash(value: string | number | null | undefined): string {
  return value === null || value === undefined || value === "" ? "-" : String(value);
}

function todayLocalIsoDate(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function salaryLabel(job: JobDetail): string {
  const enrichment = job.enrichment;
  if (!enrichment || (!enrichment.salary_min && !enrichment.salary_max)) {
    return "-";
  }
  const currency = enrichment.salary_currency ?? "";
  if (enrichment.salary_min && enrichment.salary_max) {
    return `${currency} ${enrichment.salary_min.toLocaleString()} - ${enrichment.salary_max.toLocaleString()}`;
  }
  return `${currency} ${(enrichment.salary_min ?? enrichment.salary_max)?.toLocaleString()}`;
}

function slugifyFilenamePart(value: string | null | undefined): string {
  const normalized = (value ?? "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return normalized;
}

function buildDescriptionFilename(job: JobDetail, extension: "md" | "pdf"): string {
  const parts = [
    slugifyFilenamePart(job.company),
    slugifyFilenamePart(job.title),
    "job-description",
  ].filter(Boolean);
  return parts.length > 0 ? `${parts.join("-")}.${extension}` : `job-description-${job.id}.${extension}`;
}

function formatDescription(description: string): ReactNode {
  const base = description.trim();
  if (!base) {
    return <p className="description-text">-</p>;
  }
  return (
    <Suspense fallback={<p className="description-text">Loading formatted description...</p>}>
      <DescriptionMarkdown markdown={base} />
    </Suspense>
  );
}

function cleanSkills(skills: string[]): string[] {
  const seen = new Set<string>();
  const output: string[] = [];
  for (const rawSkill of skills) {
    const skill = rawSkill.trim();
    if (!skill) continue;
    const key = skill.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    output.push(skill);
  }
  return output;
}

function degreeLevel(value: string | null | undefined): number {
  const normalized = (value ?? "").trim().toLowerCase();
  if (!normalized) return 0;
  if (normalized.includes("phd") || normalized.includes("doctorate")) return 6;
  if (normalized.includes("master")) return 5;
  if (normalized.includes("bachelor")) return 4;
  if (normalized.includes("associate")) return 3;
  if (normalized.includes("diploma")) return 2;
  if (normalized.includes("high school")) return 1;
  return 0;
}

function fitIconFor(state: FitState): string {
  if (state === "pass") return "✓";
  if (state === "fail") return "✕";
  return "•";
}

function skillStateLabel(state: "saving" | "error" | "done" | undefined): string | null {
  if (state === "saving") return "Syncing";
  if (state === "error") return "Retry";
  if (state === "done") return "Added";
  return null;
}

function requiredImpact(index: number, total: number): "critical" | "important" {
  if (total <= 4) return "critical";
  return index < Math.ceil(total * 0.5) ? "critical" : "important";
}

function titleCaseLabel(value: string | null | undefined): string {
  if (!value) return "-";
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function recommendationLabel(value: string | null | undefined): string {
  if (!value) return "Unrated";
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

type RecommendationGuidanceMode = "evaluation" | "stage_narrative";

type RecommendationGuidanceFields = {
  guidance_mode?: RecommendationGuidanceMode | null;
  guidance_title?: string | null;
  guidance_summary?: string | null;
  guidance_reasons?: string[];
  next_best_action?: string | null;
  health_label?: string | null;
};

function recommendationGuidance(job: JobDetail): JobDetail & RecommendationGuidanceFields {
  return job as JobDetail & RecommendationGuidanceFields;
}

function guidanceModeLabel(mode: RecommendationGuidanceMode | null | undefined): string {
  if (mode === "stage_narrative") return "Active process";
  return "Opportunity review";
}

function isStageNarrativeJob(job: JobDetail): boolean {
  return ["applied", "interviewing", "offer"].includes(job.tracking_status);
}

function matchTone(job: JobDetail): "high" | "medium" | "low" | "pending" {
  if (typeof job.match?.score !== "number") return "pending";
  if (job.match.score >= 85) return "high";
  if (job.match.score >= 70) return "medium";
  return "low";
}

function matchLabel(job: JobDetail): string {
  if (typeof job.match?.score !== "number") return "Rank pending";
  return `Rank ${job.match.score}${job.match.band ? ` • ${titleCaseLabel(job.match.band)}` : ""}`;
}

function stagingSummary(job: JobDetail): string | null {
  if (job.tracking_status !== "staging" || typeof job.staging_age_hours !== "number") return null;
  if (job.staging_overdue) return `Overdue by ${Math.max(0, job.staging_age_hours - 48)}h`;
  return `Due in ${Math.max(0, 48 - job.staging_age_hours)}h`;
}

export function DetailDrawer({
  open,
  loading,
  job,
  summaryJob = null,
  profile,
  events,
  enrichmentPending = false,
  onClose,
  onAddSkillToProfile,
  onDeleteJob,
  onSuppressJob,
  onRetryProcessing,
  onSaveDecision,
  onChangeTracking,
}: DetailDrawerProps) {
  const { skillAliases: aliases } = useDashboardData();

  const requiredSkills = job?.enrichment ? cleanSkills(job.enrichment.required_skills) : [];
  const preferredSkills = job?.enrichment ? cleanSkills(job.enrichment.preferred_skills) : [];
  const [showScoreDetails, setShowScoreDetails] = useState(false);
  const [skillActionState, setSkillActionState] = useState<Record<string, "saving" | "error" | "done">>({});
  const [optimisticSkillAdds, setOptimisticSkillAdds] = useState<Record<string, true>>({});
  const [isDeleting, setIsDeleting] = useState(false);
  const [isDeleteConfirmOpen, setIsDeleteConfirmOpen] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isSuppressing, setIsSuppressing] = useState(false);
  const [isSuppressConfirmOpen, setIsSuppressConfirmOpen] = useState(false);
  const [suppressReason, setSuppressReason] = useState("");
  const [suppressError, setSuppressError] = useState<string | null>(null);
  const [draftStatus, setDraftStatus] = useState<TrackingStatus>("not_applied");
  const [draftPriority, setDraftPriority] = useState<Priority>("medium");
  const [trackingUpdating, setTrackingUpdating] = useState<false | "status" | "priority" | "pinned">(false);
  const [overdueDialogOpen, setOverdueDialogOpen] = useState(false);
  const [pendingTrackingPatch, setPendingTrackingPatch] = useState<{
    priority?: Priority;
    applied_at?: string | null;
    next_step?: string | null;
    target_compensation?: string | null;
  } | null>(null);
  const [overdueActionBusy, setOverdueActionBusy] = useState(false);
  const [decisionBusy, setDecisionBusy] = useState<Recommendation | null>(null);
  const [retryProcessingBusy, setRetryProcessingBusy] = useState(false);
  const [queueAdded, setQueueAdded] = useState(false);
  useEffect(() => {
    setSkillActionState({});
    setOptimisticSkillAdds({});
  }, [job?.url]);
  useEffect(() => {
    if (!job) return;
    setDraftStatus(job.tracking_status);
    setDraftPriority(job.priority);
  }, [job?.priority, job?.tracking_status, job?.url]);
  useEffect(() => {
    setDeleteError(null);
    setIsDeleting(false);
    setIsDeleteConfirmOpen(false);
    setSuppressError(null);
    setIsSuppressing(false);
    setIsSuppressConfirmOpen(false);
    setSuppressReason("");
    setOverdueDialogOpen(false);
    setPendingTrackingPatch(null);
    setOverdueActionBusy(false);
    setRetryProcessingBusy(false);
  }, [job?.url]);
  useEffect(() => {
    function onEscape(event: KeyboardEvent): void {
      if (event.key === "Escape" && !isDeleting && !isSuppressing) {
        setIsDeleteConfirmOpen(false);
        setIsSuppressConfirmOpen(false);
      }
    }
    if (isDeleteConfirmOpen || isSuppressConfirmOpen) {
      window.addEventListener("keydown", onEscape);
      document.body.classList.add("modal-open");
    }
    return () => {
      window.removeEventListener("keydown", onEscape);
      document.body.classList.remove("modal-open");
    };
  }, [isDeleteConfirmOpen, isSuppressConfirmOpen, isDeleting, isSuppressing]);

  const fitData = useMemo(
    () => buildJobFitAnalysis(job, profile, aliases, optimisticSkillAdds),
    [aliases, job, optimisticSkillAdds, profile],
  );

  async function handleExportPdf(): Promise<void> {
    if (!job) return;
    const formattedMarkdown = job.enrichment?.formatted_description?.trim() ?? "";
    if (!formattedMarkdown) {
      toast.error("PDF export is only available after JD formatting finishes.");
      return;
    }
    try {
      const { blob, filename } = await fetchJobDescriptionPdf(job.id, buildDescriptionFilename(job, "pdf"));
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "PDF export failed");
    }
  }

  async function addSkill(skill: string): Promise<void> {
    if (!onAddSkillToProfile) return;
    const key = normalizeSkill(skill, aliases);
    if (skillActionState[key] === "saving" || skillActionState[key] === "done") {
      return;
    }
    setOptimisticSkillAdds((current) => ({ ...current, [key]: true }));
    setSkillActionState((current) => ({ ...current, [key]: "saving" }));
    void onAddSkillToProfile(skill)
      .then(() => {
        setSkillActionState((current) => ({ ...current, [key]: "done" }));
      })
      .catch(() => {
        setOptimisticSkillAdds((current) => {
          const { [key]: _, ...rest } = current;
          return rest;
        });
        setSkillActionState((current) => ({ ...current, [key]: "error" }));
      });
  }

  async function handleDeleteJob(): Promise<void> {
    if (!job || !onDeleteJob || isDeleting) return;
    setDeleteError(null);
    setIsDeleting(true);
    try {
      await onDeleteJob(job.id);
      setIsDeleteConfirmOpen(false);
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : "Failed to delete job");
      setIsDeleting(false);
    }
  }

  async function handleSuppressJob(): Promise<void> {
    if (!job || !onSuppressJob || isSuppressing) return;
    setSuppressError(null);
    setIsSuppressing(true);
    try {
      await onSuppressJob(job.id, suppressReason);
      setIsSuppressConfirmOpen(false);
    } catch (error) {
      setSuppressError(error instanceof Error ? error.message : "Failed to suppress job");
      setIsSuppressing(false);
    }
  }

  async function handleStatusChange(next: TrackingStatus): Promise<void> {
    if (!job || trackingUpdating) return;
    const previous = draftStatus;
    setDraftStatus(next);
    setTrackingUpdating("status");
    try {
      await onChangeTracking({
        status: next,
        applied_at: next === "applied" ? todayLocalIsoDate() : undefined,
      });
    } catch {
      setDraftStatus(previous);
    } finally {
      setTrackingUpdating(false);
    }
  }

  async function applyTrackingPatchWithOverdueGate(patch: {
    priority?: Priority;
    applied_at?: string | null;
    next_step?: string | null;
    target_compensation?: string | null;
  }): Promise<void> {
    if (!job) return;
    if (job.tracking_status === "staging" && job.staging_overdue) {
      setPendingTrackingPatch(patch);
      setOverdueDialogOpen(true);
      return;
    }
    await onChangeTracking(patch);
  }

  async function handlePriorityChange(next: Priority): Promise<void> {
    if (!job || trackingUpdating) return;
    if (job.tracking_status === "staging" && job.staging_overdue) {
      setPendingTrackingPatch({ priority: next });
      setOverdueDialogOpen(true);
      return;
    }
    const previous = draftPriority;
    setDraftPriority(next);
    setTrackingUpdating("priority");
    try {
      await onChangeTracking({ priority: next });
    } catch {
      setDraftPriority(previous);
    } finally {
      setTrackingUpdating(false);
    }
  }

  async function handlePinnedToggle(): Promise<void> {
    if (!job || trackingUpdating) return;
    setTrackingUpdating("pinned");
    try {
      await onChangeTracking({ pinned: !job.pinned });
    } finally {
      setTrackingUpdating(false);
    }
  }

  async function keepInStagingAndApplyPendingPatch(): Promise<void> {
    if (!pendingTrackingPatch) {
      setOverdueDialogOpen(false);
      return;
    }
    setOverdueActionBusy(true);
    try {
      if (typeof pendingTrackingPatch.priority === "string") {
        setDraftPriority(pendingTrackingPatch.priority);
      }
      await onChangeTracking(pendingTrackingPatch);
      setOverdueDialogOpen(false);
      setPendingTrackingPatch(null);
    } finally {
      setOverdueActionBusy(false);
    }
  }

  async function resolveOverdueByStatus(next: TrackingStatus): Promise<void> {
    setOverdueActionBusy(true);
    try {
      setDraftStatus(next);
      await onChangeTracking({
        status: next,
        applied_at: next === "applied" ? todayLocalIsoDate() : undefined,
      });
      setOverdueDialogOpen(false);
      setPendingTrackingPatch(null);
    } finally {
      setOverdueActionBusy(false);
    }
  }

  async function handleRecommendationOverride(next: Recommendation): Promise<void> {
    if (!job || !onSaveDecision || decisionBusy) return;
    setDecisionBusy(next);
    try {
      await onSaveDecision(job.id, next);
    } finally {
      setDecisionBusy(null);
    }
  }

  async function handleRetryProcessing(): Promise<void> {
    if (!job || !onRetryProcessing) {
      return;
    }
    try {
      setRetryProcessingBusy(true);
      await onRetryProcessing(job.id);
    } finally {
      setRetryProcessingBusy(false);
    }
  }

  const formattedDescription = job?.enrichment?.formatted_description?.trim() ?? "";
  const canExportFormattedDescription = formattedDescription.length > 0;
  const descriptionText = formattedDescription || job?.description || "";
  function handleBackdropClose(event?: { preventDefault?: () => void; stopPropagation?: () => void }): void {
    event?.preventDefault?.();
    event?.stopPropagation?.();
    if (open) {
      onClose();
    }
  }

  return (
    <>
      {open && (
        <button
          className="drawer-overlay"
          type="button"
          aria-label="Close details"
          onPointerDown={handleBackdropClose}
          onClick={handleBackdropClose}
        />
      )}
      <aside className={`detail-drawer ${open ? "open" : ""}`}>
        {loading ? (
          <div className="drawer-loading drawer-skeleton">
            <header className="drawer-hero">
              <div className="drawer-hero-copy">
                <div className="drawer-hero-meta">
                  {summaryJob ? (
                    <>
                      <span className={`drawer-status-pill status-${summaryJob.status.replaceAll("_", "-")}`}>
                        {titleCaseLabel(summaryJob.status)}
                      </span>
                      <span className={`drawer-priority-pill priority-${summaryJob.priority ?? "medium"}`}>
                        {titleCaseLabel(summaryJob.priority ?? "medium")} priority
                      </span>
                    </>
                  ) : (
                    <>
                      <span className="drawer-skeleton-pill" />
                      <span className="drawer-skeleton-pill" />
                    </>
                  )}
                </div>
                <div className="drawer-top">
                  <h2>{summaryJob?.title ?? "Loading job details"}</h2>
                  <Button type="button" onClick={onClose} variant="default" aria-label="Close" data-icon="×">×</Button>
                </div>
                <p className="drawer-company">
                  {summaryJob ? `${summaryJob.company}${summaryJob.location ? ` • ${summaryJob.location}` : ""}` : "Preparing job summary"}
                </p>
                <div className="drawer-summary-chips">
                  <span className="drawer-summary-chip tone-match match-pending">Fetching detail…</span>
                  {summaryJob?.ats ? <span className="drawer-summary-chip tone-ats">{summaryJob.ats}</span> : null}
                  {summaryJob?.posted ? <span className="drawer-summary-chip tone-date">Posted {formatDateTime(summaryJob.posted)}</span> : null}
                </div>
              </div>
            </header>
            <div className="drawer-skeleton-sections" aria-hidden="true">
              <section className="detail-block">
                <h3>Fit Overview</h3>
                <div className="drawer-skeleton-lines">
                  <span className="skeleton-line long" />
                  <span className="skeleton-line medium" />
                  <span className="skeleton-line medium" />
                </div>
              </section>
              <section className="detail-block">
                <h3>Enrichment</h3>
                <div className="drawer-skeleton-grid">
                  {Array.from({ length: 6 }, (_, index) => (
                    <span key={`enrichment-skeleton-${index}`} className="skeleton-line medium" />
                  ))}
                </div>
              </section>
              <section className="detail-block">
                <h3>Job Description</h3>
                <div className="drawer-skeleton-lines">
                  <span className="skeleton-line long" />
                  <span className="skeleton-line long" />
                  <span className="skeleton-line medium" />
                  <span className="skeleton-line short" />
                </div>
              </section>
              <section className="detail-block">
                <h3>Timeline</h3>
                <div className="drawer-skeleton-lines">
                  <span className="skeleton-line medium" />
                  <span className="skeleton-line medium" />
                </div>
              </section>
            </div>
          </div>
        ) : job ? (
          <motion.div
            initial={{ x: 42, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            transition={{ duration: 0.34, ease: [0.2, 0.85, 0.2, 1] }}
            className="drawer-inner"
          >
            <header className="drawer-hero">
              <div className="drawer-hero-copy">
                <div className="drawer-top">
                  <div className="drawer-hero-title-area">
                    <div className="drawer-hero-meta">
                      <span className={`drawer-status-pill status-${job.tracking_status.replaceAll("_", "-")}`}>
                        {titleCaseLabel(job.tracking_status)}
                      </span>
                      <span className={`drawer-priority-pill priority-${job.priority ?? "medium"}`}>
                        {titleCaseLabel(job.priority ?? "medium")}
                      </span>
                      {job.pinned ? <span className="drawer-summary-chip tone-pin">Pinned</span> : null}
                    </div>
                    <h2>{job.title}</h2>
                  </div>
                  <Button type="button" onClick={onClose} variant="default" aria-label="Close" data-icon="×">×</Button>
                </div>

                <div className="drawer-summary-grid">
                  <div className="drawer-summary-item">
                    <span>Company</span>
                    <p>{job.company}</p>
                  </div>
                  <div className="drawer-summary-item">
                    <span>Location</span>
                    <p>{job.location || "Location TBD"}</p>
                  </div>
                  <div className="drawer-summary-item">
                    <span>Applied</span>
                    <p>{job.applied_at ? formatDateTime(job.applied_at) : "-"}</p>
                  </div>
                  <div className="drawer-summary-item">
                    <span>Target Comp</span>
                    <p>{valueOrDash(job.target_compensation)}</p>
                  </div>
                  <div className="drawer-summary-item">
                    <span>Source</span>
                    <p>{job.ats || "Direct"}</p>
                  </div>
                  <div className="drawer-summary-item">
                    <span>Posted</span>
                    <p>{formatDateTime(job.posted)}</p>
                  </div>
                </div>

                <div className="drawer-fit-strip">
                  <span className={`drawer-summary-chip tone-match match-${matchTone(job)}`}>{matchLabel(job)}</span>
                  {fitData && (
                    <>
                      <Badge>Req {fitData.requiredMet}/{fitData.requiredChecks.length}</Badge>
                      <Badge>Pref {fitData.preferredMet}/{fitData.preferredChecks.length}</Badge>
                    </>
                  )}
                  {stagingSummary(job) ? (
                    <span className={`drawer-summary-chip tone-sla ${job.staging_overdue ? "overdue" : "due-soon"}`}>
                      {stagingSummary(job)}
                    </span>
                  ) : null}
                </div>
              </div>

              <div className="drawer-hero-actions">
                <Button
                  type="button"
                  variant="default"
                  size="compact"
                  data-icon="📌"
                  onClick={() => void handlePinnedToggle()}
                  disabled={trackingUpdating !== false}
                >
                  {job.pinned ? "Unpin" : "Pin"}
                </Button>
                <Button
                  type="button"
                  variant="default"
                  size="compact"
                  data-icon="+"
                  onClick={async () => {
                    try {
                      await addToQueue(job.id);
                      setQueueAdded(true);
                      setTimeout(() => setQueueAdded(false), 2000);
                    } catch {
                      // silent
                    }
                  }}
                  disabled={queueAdded}
                >
                  {queueAdded ? "Added" : "Queue"}
                </Button>
                <a href={job.url} target="_blank" rel="noreferrer" className="external-link drawer-link-cta">Open Posting</a>
              </div>
            </header>

            <section className="drawer-control-panel">
              <div className="drawer-control-head">
                <div>
                  <p className="drawer-section-kicker">Tracking</p>
                  <h3>Update Pipeline</h3>
                </div>
              </div>
              <div className="drawer-grid">
                <label>
                  <span>Status</span>
                  <ThemedSelect
                    value={draftStatus}
                    options={STATUS_OPTIONS}
                    onChange={(value) => void handleStatusChange(value as TrackingStatus)}
                    ariaLabel="Tracking status"
                    disabled={trackingUpdating !== false}
                  />
                </label>
                <label>
                  <span>Priority</span>
                  <ThemedSelect
                    value={draftPriority}
                    options={PRIORITY_SELECT_OPTIONS}
                    onChange={(value) => void handlePriorityChange(value as Priority)}
                    ariaLabel="Priority"
                    disabled={trackingUpdating !== false}
                  />
                </label>
                <label>
                  <span>Applied</span>
                  <input
                    type="date"
                    value={job.applied_at ?? ""}
                    onChange={(event) => void applyTrackingPatchWithOverdueGate({ applied_at: event.target.value || null })}
                  />
                </label>
                <label>
                  <span>Target</span>
                  <input
                    key={`target-comp-${job.url}`}
                    type="text"
                    placeholder="e.g. 150k"
                    defaultValue={job.target_compensation ?? ""}
                    onBlur={(event) => void applyTrackingPatchWithOverdueGate({ target_compensation: event.target.value || null })}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        void applyTrackingPatchWithOverdueGate({ target_compensation: (event.target as HTMLInputElement).value || null });
                      }
                    }}
                  />
                </label>
                <label className="full-width">
                  <span>Next Step</span>
                  <input
                    key={`next-step-${job.url}`}
                    type="text"
                    placeholder="e.g. Recruiter call"
                    defaultValue={job.next_step ?? ""}
                    onBlur={(event) => void applyTrackingPatchWithOverdueGate({ next_step: event.target.value || null })}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        void applyTrackingPatchWithOverdueGate({ next_step: (event.target as HTMLInputElement).value || null });
                      }
                    }}
                  />
                </label>
              </div>
              {job.tracking_status === "staging" && (
                <div className="drawer-inline-callout">
                  <div className="drawer-inline-callout-copy">
                    <strong>Staging SLA (48h)</strong>
                    <span>
                      Entered {formatDateTime(job.staging_entered_at)} · Due {formatDateTime(job.staging_due_at)}
                    </span>
                  </div>
                  <div className="fact-grid-actions">
                    <Button
                      type="button"
                      variant="primary"
                      size="compact"
                      data-icon="✓"
                      disabled={trackingUpdating !== false}
                      onClick={() => void handleStatusChange("applied")}
                    >
                      Applied
                    </Button>
                    <Button
                      type="button"
                      variant="danger"
                      size="compact"
                      data-icon="✕"
                      disabled={trackingUpdating !== false}
                      onClick={() => void handleStatusChange("rejected")}
                    >
                      Reject
                    </Button>
                  </div>
                </div>
              )}
            </section>

            <section className="detail-block">
              <div className="detail-block-head">
                <div>
                  <p className="drawer-section-kicker">Analysis</p>
                  <h3>AI Recommendation & Fit</h3>
                </div>
              </div>
              
              {(() => {
                const guidance = buildRecommendationGuidance(job);
                const guidanceMode = guidance.mode;
                const guidanceTitle = guidance.title;
                const guidanceSummary = guidance.summary;
                const guidanceReasons = guidance.reasons;
                const nextBestAction = guidance.nextBestAction;
                const healthLabel = guidance.healthLabel;
                return (
                  <>
                    <p className="detail-block-note">{guidanceSummary}</p>
                    {guidanceMode === "stage_narrative" ? (
                      <div className="assistant-metric-grid">
                        <div className="assistant-metric-card">
                          <span>Health</span>
                          <strong>{titleCaseLabel(healthLabel)}</strong>
                        </div>
                        <div className="assistant-metric-card" style={{ gridColumn: "span 3" }}>
                          <span>Next best action</span>
                          <strong>{nextBestAction}</strong>
                        </div>
                      </div>
                    ) : (
                      <div className="assistant-metric-grid">
                        <div className="assistant-metric-card">
                          <span>Rank</span>
                          <strong>{valueOrDash(job.match?.score)}</strong>
                        </div>
                        <div className="assistant-metric-card">
                          <span>Fit</span>
                          <strong>{valueOrDash(job.fit_score)}</strong>
                        </div>
                        <div className="assistant-metric-card">
                          <span>Urgency</span>
                          <strong>{valueOrDash(job.urgency_score)}</strong>
                        </div>
                        <div className="assistant-metric-card">
                          <span>Friction</span>
                          <strong>{valueOrDash(job.friction_score)}</strong>
                        </div>
                        <div className="assistant-metric-card">
                          <span>Confidence</span>
                          <strong>{valueOrDash(job.confidence_score)}</strong>
                        </div>
                      </div>
                    )}

                    {fitData && (
                  <div className="fit-list fit-list--compact">
                    {fitData.coreChecks.map((item) => (
                      <article key={`core-fit-${item.label}`} className={`fit-card fit-card--compact ${item.state}`}>
                        <span className={`fit-icon ${item.state}`} aria-hidden="true">{fitIconFor(item.state)}</span>
                        <div>
                          <p className="fit-label">{item.label}: {item.detail}</p>
                        </div>

                          </article>
                        ))}
                      </div>
                    )}

                    {guidanceReasons.length > 0 ? (
                      <ul className="assistant-bullet-list">
                        {guidanceReasons.map((reason, index) => (
                          <li key={`${reason}-${index}`}>{reason}</li>
                        ))}
                      </ul>
                    ) : null}

                    {job.match?.breakdown?.suppressor_eligibility || job.match?.breakdown?.suppressor_seniority ? (
                      <p className="detail-block-note">
                        Score suppressor active:
                        {job.match?.breakdown?.suppressor_eligibility ? " eligibility mismatch" : ""}
                        {job.match?.breakdown?.suppressor_eligibility && job.match?.breakdown?.suppressor_seniority ? " and" : ""}
                        {job.match?.breakdown?.suppressor_seniority ? " seniority mismatch" : ""}.
                      </p>
                    ) : null}

                    {onSaveDecision ? (
                      <div className="assistant-chip-list">
                        {(["apply_now", "review_manually", "hold", "archive"] as Recommendation[]).map((option) => (
                          <Button
                            key={option}
                            type="button"
                            size="compact"
                            variant={job.recommendation === option ? "primary" : "default"}
                            disabled={Boolean(decisionBusy)}
                            onClick={() => void handleRecommendationOverride(option)}
                          >
                            {decisionBusy === option ? "Saving..." : recommendationLabel(option)}
                          </Button>
                        ))}
                      </div>
                    ) : null}
                  </>
                );
              })()}

              <div className="fit-group">
                <h4 className="fit-subheading">Skill Alignment</h4>
                {fitData ? (
                  <div className="fit-matrix">
                    <article className="fit-panel fit-panel-pass">
                      <header className="fit-panel-head">
                        <p>Matches</p>
                        <Badge>{fitData.matchedRequired.length + fitData.matchedPreferred.length}</Badge>
                      </header>
                      <div className="fit-panel-groups">
                        <div className="fit-skill-group">
                          <p className="fit-panel-label">Required</p>
                          <AnimatedList
                            className="fit-chip-list matrix"
                            items={fitData.matchedRequired}
                            getKey={(item) => `matched-required-${item.label}`}
                            renderItem={(item) => (
                              <article className="fit-chip pass">
                                <span className="fit-icon pass" aria-hidden="true">{fitIconFor("pass")}</span>
                                <span className="fit-chip-label">{item.label}</span>
                              </article>
                            )}
                          />
                          {fitData.matchedRequired.length === 0 && <p className="empty-text tiny">None.</p>}
                        </div>
                        <div className="fit-skill-group">
                          <p className="fit-panel-label">Preferred</p>
                          <AnimatedList
                            className="fit-chip-list matrix"
                            items={fitData.matchedPreferred}
                            getKey={(item) => `matched-preferred-${item.label}`}
                            renderItem={(item) => (
                              <article className="fit-chip pass">
                                <span className="fit-icon pass" aria-hidden="true">{fitIconFor("pass")}</span>
                                <span className="fit-chip-label">{item.label}</span>
                              </article>
                            )}
                          />
                          {fitData.matchedPreferred.length === 0 && <p className="empty-text tiny">None.</p>}
                        </div>
                      </div>
                    </article>

                    <article className="fit-panel fit-panel-fail">
                      <header className="fit-panel-head">
                        <p>Gaps</p>
                        <Badge>{fitData.missingRequiredChecks.length + fitData.missingPreferredChecks.length}</Badge>
                      </header>
                      <div className="fit-panel-groups">
                        <div className="fit-skill-group">
                          <p className="fit-panel-label">Required</p>
                          <AnimatedList
                            className="fit-chip-list matrix"
                            items={fitData.missingRequiredChecks}
                            getKey={(item) => `missing-required-${item.label}`}
                            renderItem={(item) => {
                              const state = skillActionState[normalizeSkill(item.label, aliases)];
                              const stateLabel = skillStateLabel(state);
                              return (
                              <button
                                type="button"
                                className={`fit-chip fit-chip-interactive fail ${state === "error" ? "error" : ""}`}
                                onClick={() => void addSkill(item.label)}
                                disabled={!onAddSkillToProfile || state === "saving" || state === "done"}
                                aria-label={state === "error" ? `Retry adding missing required skill: ${item.label}` : `Add missing required skill: ${item.label}`}
                              >
                                <span className="fit-icon fail" aria-hidden="true">{fitIconFor("fail")}</span>
                                <span className="fit-chip-label">{item.label}</span>
                                <div className="fit-chip-controls">
                                  {stateLabel && <span className={`fit-state-pill ${state}`}>{stateLabel}</span>}
                                </div>
                              </button>
                            )}}
                          />
                          {fitData.missingRequiredChecks.length === 0 && <p className="empty-text tiny">None.</p>}
                        </div>
                        <div className="fit-skill-group">
                          <p className="fit-panel-label">Preferred</p>
                          <AnimatedList
                            className="fit-chip-list matrix"
                            items={fitData.missingPreferredChecks}
                            getKey={(item) => `missing-preferred-${item.label}`}
                            renderItem={(item) => {
                              const state = skillActionState[normalizeSkill(item.label, aliases)];
                              const stateLabel = skillStateLabel(state);
                              return (
                              <button
                                type="button"
                                className={`fit-chip fit-chip-interactive fail ${state === "error" ? "error" : ""}`}
                                onClick={() => void addSkill(item.label)}
                                disabled={!onAddSkillToProfile || state === "saving" || state === "done"}
                                aria-label={state === "error" ? `Retry adding missing preferred skill: ${item.label}` : `Add missing preferred skill: ${item.label}`}
                              >
                                <span className="fit-icon fail" aria-hidden="true">{fitIconFor("fail")}</span>
                                <span className="fit-chip-label">{item.label}</span>
                                <div className="fit-chip-controls">
                                  {stateLabel && <span className={`fit-state-pill ${state}`}>{stateLabel}</span>}
                                </div>
                              </button>
                            )}}
                          />
                          {fitData.missingPreferredChecks.length === 0 && <p className="empty-text tiny">None.</p>}
                        </div>
                      </div>
                    </article>
                  </div>
                ) : (
                  <p className="empty-text">Skill data unavailable.</p>
                )}
              </div>
            </section>

            <section className="detail-block">
              <div className="detail-block-head">
                <div>
                  <p className="drawer-section-kicker">Facts</p>
                  <h3>Enrichment</h3>
                </div>
              </div>
              {job.enrichment ? (
                <div className="fact-grid">
                  <p><strong>Work mode</strong> {valueOrDash(job.enrichment.work_mode)}</p>
                  <p><strong>Seniority</strong> {valueOrDash(job.enrichment.seniority)}</p>
                  <p><strong>Canada eligible</strong> {valueOrDash(job.enrichment.canada_eligible)}</p>
                  <p><strong>Role family</strong> {valueOrDash(job.enrichment.role_family)}</p>
                  <p><strong>Experience</strong> {valueOrDash(job.enrichment.years_exp_min)} - {valueOrDash(job.enrichment.years_exp_max)}</p>
                  <p><strong>Education</strong> {valueOrDash(job.enrichment.minimum_degree)}</p>
                  <p><strong>Salary</strong> {salaryLabel(job)}</p>
                  <p><strong>Visa</strong> {valueOrDash(job.enrichment.visa_sponsorship)}</p>
                </div>
              ) : (
                <p className="empty-text">No enrichment record available.</p>
              )}
            </section>

            <section className="detail-block">
              <h3>Timeline</h3>
              {events.length > 0 ? (
                <div className="events-list">
                  {events.map((event) => (
                    <article className="event-item" key={event.id}>
                      <div>
                        <p className="event-title">{event.title}</p>
                        <p className="event-meta">{event.event_type} • {event.event_at}</p>
                      </div>
                      {event.body && <p className="event-body">{event.body}</p>}
                    </article>
                  ))}
                </div>
              ) : (
                <p className="empty-text">No events yet.</p>
              )}
            </section>

            <section className="detail-block">
              <div className="detail-block-head">
                <div>
                  <p className="drawer-section-kicker">Job facts</p>
                  <h3>Description</h3>
                </div>

              </div>
              {!canExportFormattedDescription && (
                <p className="empty-text detail-block-note detail-export-note">
                  Available after JD markdown formatting finishes.
                </p>
              )}
              {formatDescription(descriptionText)}
            </section>

            <section className="detail-block">
              <h3>Relevance</h3>
              <p className="empty-text detail-block-note">Mark jobs that are out-of-scope to hide them and prevent future re-ingestion.</p>
              {suppressError && <p className="delete-error">{suppressError}</p>}
              <button
                type="button"
                className="delete-cta delete-cta-fit"
                onClick={() => setIsSuppressConfirmOpen(true)}
                disabled={!onSuppressJob}
              >
                <span className="delete-cta__text">Not a Fit</span>
                <span className="delete-cta__icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" className="delete-cta__svg delete-cta__svg-slim">
                    <path d="M3 12h18" />
                    <path d="M12 3v18" />
                  </svg>
                </span>
              </button>
            </section>

            <section className="detail-block detail-block-danger">
              <h3>Danger Zone</h3>
              <p className="empty-text detail-block-note">This permanently removes the job and linked records from the database.</p>
              {deleteError && <p className="delete-error">{deleteError}</p>}
              <button
                type="button"
                className="delete-cta"
                onClick={() => setIsDeleteConfirmOpen(true)}
                disabled={!onDeleteJob}
              >
                <span className="delete-cta__text">Delete Job</span>
                <span className="delete-cta__icon" aria-hidden="true">
                  <svg viewBox="0 0 512 512" className="delete-cta__svg">
                    <path d="M112 112l20 320c.95 18.49 14.4 32 32 32h184c17.67 0 30.87-13.51 32-32l20-320" />
                    <line x1="80" x2="432" y1="112" y2="112" />
                    <path d="M192 112V72a23.93 23.93 0 0 1 24-24h80a23.93 23.93 0 0 1 24 24v40" />
                    <line x1="256" x2="256" y1="176" y2="400" />
                    <line x1="184" x2="192" y1="176" y2="400" />
                    <line x1="328" x2="320" y1="176" y2="400" />
                  </svg>
                </span>
              </button>
            </section>
          </motion.div>
        ) : (
          <div className="drawer-empty">Select a job card to inspect details.</div>
        )}
      </aside>

      <AlertDialog open={overdueDialogOpen} onOpenChange={setOverdueDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>This job is overdue in Staging</AlertDialogTitle>
            <AlertDialogDescription>
              This role has been in staging for more than 48 hours. Move it to Applied or Rejected, or explicitly keep it in Staging.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <Button
              type="button"
              variant="primary"
              size="compact"
              data-icon="✓"
              disabled={overdueActionBusy}
              onClick={() => void resolveOverdueByStatus("applied")}
            >
              Mark Applied
            </Button>
            <Button
              type="button"
              variant="danger"
              size="compact"
              data-icon="✕"
              disabled={overdueActionBusy}
              onClick={() => void resolveOverdueByStatus("rejected")}
            >
              Mark Rejected
            </Button>
            <AlertDialogCancel
              asChild
              disabled={overdueActionBusy}
              onClick={(event) => {
                event.preventDefault();
                void keepInStagingAndApplyPendingPatch();
              }}
            >
              <Button type="button" variant="default" size="compact" data-icon="↺">
                Keep in Staging
              </Button>
            </AlertDialogCancel>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={isDeleteConfirmOpen} onOpenChange={setIsDeleteConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this job?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently remove <strong>{job?.title ?? "this job"}</strong> and linked enrichment, tracking, and timeline records.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {deleteError && <p className="confirm-modal-error">{deleteError}</p>}
          <AlertDialogFooter>
            <AlertDialogCancel asChild disabled={isDeleting}>
              <Button type="button" variant="default" size="compact" data-icon="×">Cancel</Button>
            </AlertDialogCancel>
            <AlertDialogAction className="confirm-delete-btn" onClick={() => void handleDeleteJob()} disabled={isDeleting}>
              {isDeleting ? "Deleting..." : "Delete Job"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={isSuppressConfirmOpen} onOpenChange={setIsSuppressConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Suppress this job?</AlertDialogTitle>
            <AlertDialogDescription>
              This hides <strong>{job?.title ?? "this job"}</strong> from the board and prevents future scrape updates for this exact URL.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <label className="full-width">
            <span>Reason (optional)</span>
            <input
              type="text"
              value={suppressReason}
              onChange={(event) => setSuppressReason(event.target.value)}
              placeholder="e.g. wrong location, seniority mismatch, irrelevant domain"
            />
          </label>
          {suppressError && <p className="confirm-modal-error">{suppressError}</p>}
          <AlertDialogFooter>
            <AlertDialogCancel asChild disabled={isSuppressing}>
              <Button type="button" variant="default" size="compact" data-icon="×">Cancel</Button>
            </AlertDialogCancel>
            <AlertDialogAction className="confirm-delete-btn" onClick={() => void handleSuppressJob()} disabled={isSuppressing}>
              {isSuppressing ? "Saving..." : "Suppress Job"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
