import { motion } from "framer-motion";
import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { ArtifactSummary, CandidateProfile, JobDetail, JobEvent, Priority, TrackingStatus } from "../types";
import { preloadRouteChunk } from "../routePreload";
import { AnimatedList } from "./reactbits/AnimatedList";
import { ThemedLoader } from "./ThemedLoader";
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
import { Progress } from "./ui/progress";

interface DetailDrawerProps {
  open: boolean;
  loading: boolean;
  job: JobDetail | null;
  profile: CandidateProfile | null;
  events: JobEvent[];
  artifacts?: ArtifactSummary[];
  artifactsLoading?: boolean;
  artifactsGenerating?: boolean;
  artifactStarterStage?: string;
  artifactStarterProgress?: number;
  enrichmentPending?: boolean;
  onClose: () => void;
  onAddSkillToProfile?: (skill: string) => Promise<void>;
  onDeleteJob?: (jobId: string) => Promise<void>;
  onSuppressJob?: (jobId: string, reason?: string) => Promise<void>;
  onGenerateArtifacts?: (jobId: string) => Promise<void>;
  onChangeTracking: (patch: {
    status?: TrackingStatus;
    priority?: Priority;
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

function normalizeSkill(value: string): string {
  const normalized = value.trim().toLowerCase();
  const parenthetical = [...normalized.matchAll(/\(([^)]{1,32})\)/g)].map((match) => match[1] ?? "");
  const stripped = normalized
    .replace(/[/_-]+/g, " ")
    .replace(/\([^)]*\)/g, " ")
    .replace(/[^a-z0-9\s]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  const aliases: Record<string, string> = {
    js: "javascript",
    ts: "typescript",
    k8s: "kubernetes",
    tf: "tensorflow",
    torch: "pytorch",
    rag: "retrieval augmented generation",
    llm: "large language model",
    llms: "large language model",
    nlp: "natural language processing",
    cv: "computer vision",
    ml: "machine learning",
    genai: "generative ai",
    cicd: "ci cd",
  };
  for (const raw of parenthetical) {
    const key = raw.replace(/[^a-z0-9]+/g, "");
    if (aliases[key]) {
      return aliases[key];
    }
  }
  if (aliases[stripped]) {
    return aliases[stripped];
  }
  const tokens = stripped.split(" ").filter(Boolean);
  if (tokens.length >= 2) {
    const acronym = tokens.map((token) => token[0]).join("");
    if (aliases[acronym]) {
      return aliases[acronym];
    }
  }
  return stripped;
}

function compactSkill(value: string): string {
  return normalizeSkill(value).replace(/[^a-z0-9]+/g, "");
}

function acronymSkill(value: string): string {
  const tokens = normalizeSkill(value).split(" ").filter(Boolean);
  if (tokens.length < 2) return "";
  return tokens.map((token) => token[0]).join("");
}

function tokenizeSkill(value: string): Set<string> {
  return new Set(
    normalizeSkill(value)
      .split(/[^a-z0-9]+/g)
      .map((token) => token.trim())
      .filter(Boolean),
  );
}

function fuzzySkillSimilarity(left: string, right: string): number {
  const l = normalizeSkill(left);
  const r = normalizeSkill(right);
  if (!l || !r) return 0;
  if (l === r) return 1;

  const lCompact = compactSkill(l);
  const rCompact = compactSkill(r);
  if (lCompact && lCompact === rCompact) return 1;

  const lAcronym = acronymSkill(l);
  const rAcronym = acronymSkill(r);
  if ((lAcronym && lAcronym === rCompact) || (rAcronym && rAcronym === lCompact)) return 1;
  if (lAcronym && rAcronym && lAcronym === rAcronym) return 1;

  const minLength = Math.min(l.length, r.length);
  const containsRatio = minLength >= 4 && (l.includes(r) || r.includes(l))
    ? minLength / Math.max(l.length, r.length)
    : 0;

  const lTokens = tokenizeSkill(l);
  const rTokens = tokenizeSkill(r);
  const overlap = [...lTokens].filter((token) => rTokens.has(token)).length;
  const tokenRatio = lTokens.size > 0 && rTokens.size > 0
    ? overlap / Math.max(lTokens.size, rTokens.size)
    : 0;

  const longer = l.length >= r.length ? l : r;
  const shorter = l.length >= r.length ? r : l;
  let prefix = 0;
  while (prefix < shorter.length && shorter[prefix] === longer[prefix]) {
    prefix += 1;
  }
  const prefixRatio = shorter.length >= 4 ? prefix / shorter.length : 0;

  return Math.max(containsRatio, tokenRatio, prefixRatio);
}

function fuzzySkillsMatch(left: string, right: string, threshold = 0.8): boolean {
  return fuzzySkillSimilarity(left, right) >= threshold;
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

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return value;
  return parsed.toLocaleString();
}

function titleCaseLabel(value: string | null | undefined): string {
  if (!value) return "-";
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function matchTone(job: JobDetail): "high" | "medium" | "low" | "pending" {
  if (typeof job.match?.score !== "number") return "pending";
  if (job.match.score >= 80) return "high";
  if (job.match.score >= 60) return "medium";
  return "low";
}

function matchLabel(job: JobDetail): string {
  if (typeof job.match?.score !== "number") return "Match pending";
  return `Match ${job.match.score}${job.match.band ? ` • ${titleCaseLabel(job.match.band)}` : ""}`;
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
  profile,
  events,
  artifacts = [],
  artifactsLoading = false,
  artifactsGenerating = false,
  artifactStarterStage = "queued",
  artifactStarterProgress = 0,
  enrichmentPending = false,
  onClose,
  onAddSkillToProfile,
  onDeleteJob,
  onSuppressJob,
  onGenerateArtifacts,
  onChangeTracking,
}: DetailDrawerProps) {
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
  const [trackingUpdating, setTrackingUpdating] = useState<false | "status" | "priority">(false);
  const [overdueDialogOpen, setOverdueDialogOpen] = useState(false);
  const [pendingTrackingPatch, setPendingTrackingPatch] = useState<{
    priority?: Priority;
    applied_at?: string | null;
    next_step?: string | null;
    target_compensation?: string | null;
  } | null>(null);
  const [overdueActionBusy, setOverdueActionBusy] = useState(false);
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

  const fitData = useMemo(() => {
    if (!job?.enrichment) {
      return null;
    }

    const profileSkillSet = new Set([
      ...(profile?.skills ?? []).map((skill) => normalizeSkill(skill)),
      ...Object.keys(optimisticSkillAdds),
    ]);

    const requiredChecks: FitCheck[] = requiredSkills.map((skill, index) => {
      const matched = [...profileSkillSet].some((profileSkill) => fuzzySkillsMatch(skill, profileSkill));
      return {
        label: skill,
        detail: matched ? "Matched from your profile" : "Missing from your profile",
        state: matched ? "pass" : "fail",
        impact: requiredImpact(index, requiredSkills.length),
      };
    });

    const preferredChecks: FitCheck[] = preferredSkills.map((skill) => {
      const matched = [...profileSkillSet].some((profileSkill) => fuzzySkillsMatch(skill, profileSkill));
      return {
        label: skill,
        detail: matched ? "Nice-to-have matched" : "Not present in your profile",
        state: matched ? "pass" : "fail",
        impact: "nice",
      };
    });

    const matchedRequired = requiredChecks.filter((item) => item.state === "pass");
    const missingRequiredChecks = requiredChecks.filter((item) => item.state === "fail");
    const matchedPreferred = preferredChecks.filter((item) => item.state === "pass");
    const missingPreferredChecks = preferredChecks.filter((item) => item.state === "fail");
    const requiredMet = matchedRequired.length;
    const preferredMet = matchedPreferred.length;

    const yearsMin = job.enrichment.years_exp_min;
    const candidateYears = profile?.years_experience;
    const experienceCheck: FitCheck = typeof yearsMin === "number" && typeof candidateYears === "number"
      ? {
          label: "Experience",
          detail: candidateYears >= yearsMin ? `${candidateYears} yrs vs min ${yearsMin} yrs` : `${candidateYears} yrs vs min ${yearsMin} yrs`,
          state: candidateYears >= yearsMin ? "pass" : "fail",
        }
      : {
          label: "Experience",
          detail: "Insufficient data to evaluate",
          state: "unknown",
        };

    const requiredDegree = job.enrichment.minimum_degree;
    const candidateDegreeLevel = Math.max(
      degreeLevel(profile?.degree),
      ...((profile?.education ?? []).map((entry) => degreeLevel(entry.degree))),
    );
    const requiredDegreeLevel = degreeLevel(requiredDegree);
    const degreeCheck: FitCheck = requiredDegree
      ? requiredDegreeLevel > 0
        ? {
            label: "Education",
            detail: `Required ${requiredDegree}`,
            state: candidateDegreeLevel >= requiredDegreeLevel ? "pass" : "fail",
          }
        : {
            label: "Education",
            detail: `Required ${requiredDegree}`,
            state: "unknown",
          }
      : {
          label: "Education",
          detail: "No minimum degree listed",
          state: "unknown",
        };

    const canadaEligible = (job.enrichment.canada_eligible ?? "").trim().toLowerCase();
    const visaSponsorship = (job.enrichment.visa_sponsorship ?? "").trim().toLowerCase();
    const needsVisa = Boolean(profile?.requires_visa_sponsorship);
    let visaState: FitState = "unknown";
    let visaDetail = "Insufficient data to evaluate";
    if (canadaEligible === "no") {
      visaState = "fail";
      visaDetail = "Role is not Canada-eligible";
    } else if (needsVisa && visaSponsorship === "no") {
      visaState = "fail";
      visaDetail = "Visa sponsorship unavailable";
    } else if (canadaEligible || visaSponsorship || !needsVisa) {
      visaState = "pass";
      visaDetail = needsVisa ? "Visa compatibility looks okay" : "No visa requirement on your profile";
    }
    const visaCheck: FitCheck = {
      label: "Visa / Eligibility",
      detail: visaDetail,
      state: visaState,
    };

    const coreChecks = [experienceCheck, degreeCheck, visaCheck];
    const corePassCount = coreChecks.filter((item) => item.state === "pass").length;
    const missingRequiredHighlights = missingRequiredChecks
      .sort((a, b) => {
        const weight = (impact: FitCheck["impact"]) => (impact === "critical" ? 2 : 1);
        return weight(b.impact) - weight(a.impact);
      })
      .slice(0, 3)
      .map((item) => ({ label: item.label, impact: item.impact ?? "important" }));

    return {
      requiredChecks,
      preferredChecks,
      matchedRequired,
      missingRequiredChecks,
      matchedPreferred,
      missingPreferredChecks,
      requiredMet,
      preferredMet,
      coreChecks,
      corePassCount,
      missingRequiredHighlights,
    };
  }, [job?.enrichment, profile, requiredSkills, preferredSkills, optimisticSkillAdds]);

  async function addSkill(skill: string): Promise<void> {
    if (!onAddSkillToProfile) return;
    const key = normalizeSkill(skill);
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
  const descriptionText = job?.enrichment?.formatted_description || job?.description || "";

  return (
    <>
      {open && <button className="drawer-overlay" onClick={onClose} type="button" aria-label="Close details" />}
      <aside className={`detail-drawer ${open ? "open" : ""}`}>
        {loading ? (
          <div className="drawer-loading">
            <ThemedLoader label="Loading job details" />
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
                <div className="drawer-hero-meta">
                  <span className={`drawer-status-pill status-${job.tracking_status.replaceAll("_", "-")}`}>
                    {titleCaseLabel(job.tracking_status)}
                  </span>
                  <span className={`drawer-priority-pill priority-${job.priority ?? "medium"}`}>
                    {titleCaseLabel(job.priority ?? "medium")} priority
                  </span>
                </div>
                <div className="drawer-top">
                  <h2>{job.title}</h2>
                  <Button type="button" onClick={onClose} variant="default" data-icon="×">Close</Button>
                </div>
                <p className="drawer-company">
                  {job.company}
                  {job.location ? <span> • {job.location}</span> : null}
                </p>
                <div className="drawer-summary-chips">
                  <span className={`drawer-summary-chip tone-match match-${matchTone(job)}`}>{matchLabel(job)}</span>
                  {job.desired_title_match ? <span className="drawer-summary-chip tone-match match-high">Desired title match</span> : null}
                  <span className="drawer-summary-chip tone-ats">{job.ats || "ATS"}</span>
                  <span className="drawer-summary-chip tone-date">Posted {formatDateTime(job.posted)}</span>
                  {stagingSummary(job) ? (
                    <span className={`drawer-summary-chip tone-sla ${job.staging_overdue ? "overdue" : "due-soon"}`}>
                      {stagingSummary(job)}
                    </span>
                  ) : null}
                </div>
                <div className="drawer-summary-facts">
                  <span>Tracking updated {formatDateTime(job.tracking_updated_at)}</span>
                  <span>Applied {formatDateTime(job.applied_at)}</span>
                  <span>Target {valueOrDash(job.target_compensation)}</span>
                </div>
              </div>
              <div className="drawer-hero-actions">
                <a href={job.url} target="_blank" rel="noreferrer" className="external-link drawer-link-cta">Open original posting</a>
              </div>
            </header>

            <section className="drawer-control-panel">
              <div className="drawer-control-head">
                <div>
                  <p className="drawer-section-kicker">Pipeline controls</p>
                  <h3>Keep this role moving</h3>
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
                  <span>Applied Date</span>
                  <input
                    type="date"
                    value={job.applied_at ?? ""}
                    onChange={(event) => void applyTrackingPatchWithOverdueGate({ applied_at: event.target.value || null })}
                  />
                </label>
                <label>
                  <span>Target Compensation</span>
                  <input
                    key={`target-comp-${job.url}`}
                    type="text"
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
            </section>

            {job.tracking_status === "staging" && (
              <section className="detail-block">
                <h3>Staging SLA (48h)</h3>
                <div className="fact-grid">
                  <p>
                    <strong>Entered:</strong> {formatDateTime(job.staging_entered_at)}
                  </p>
                  <p>
                    <strong>Due:</strong> {formatDateTime(job.staging_due_at)}
                  </p>
                  <p>
                    <strong>State:</strong> {job.staging_overdue ? "Overdue" : "On track"}
                  </p>
                  {typeof job.staging_age_hours === "number" && (
                    <p>
                      <strong>Age:</strong> {job.staging_age_hours}h
                    </p>
                  )}
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
                    Mark Applied
                  </Button>
                  <Button
                    type="button"
                    variant="danger"
                    size="compact"
                    data-icon="✕"
                    disabled={trackingUpdating !== false}
                    onClick={() => void handleStatusChange("rejected")}
                  >
                    Mark Rejected
                  </Button>
                </div>
              </section>
            )}

            <section className="detail-block">
              <h3>Artifacts</h3>
              <div className="fact-grid">
                {["resume", "cover_letter"].map((kind) => {
                  const artifact = artifacts.find((item) => item.artifact_type === kind);
                  const label = kind === "resume" ? "Resume" : "Cover Letter";
                  const openHref = kind === "resume"
                    ? `/jobs/${encodeURIComponent(job.id)}/artifacts/resume`
                    : `/jobs/${encodeURIComponent(job.id)}/artifacts/cover-letter`;
                  return (
                    <p key={kind}>
                      <strong>{label}:</strong>{" "}
                      {artifact ? (
                        <>
                          {artifact.active_version?.label ?? "draft"} v{artifact.active_version?.version ?? 1}{" "}
                          <Link to={openHref} className="external-link" style={{ display: "inline" }} onMouseEnter={() => preloadRouteChunk("artifacts")} onFocus={() => preloadRouteChunk("artifacts")}>
                            Open
                          </Link>
                        </>
                      ) : (
                        "Not created"
                      )}
                    </p>
                  );
                })}
              </div>
              {artifactsGenerating && artifacts.length === 0 ? (
                <div className="artifact-generate-progress" aria-live="polite">
                  <p className="empty-text">Generating starter drafts ({artifactStarterStage.replaceAll("_", " ")})...</p>
                  <Progress value={artifactStarterProgress} />
                </div>
              ) : artifactsLoading && artifacts.length === 0 ? (
                <p className="empty-text">Loading artifacts...</p>
              ) : artifacts.length === 0 ? (
                <Button
                  type="button"
                  variant="default"
                  size="compact"
                  data-icon="＋"
                  onClick={() => job && onGenerateArtifacts ? void onGenerateArtifacts(job.id) : undefined}
                  disabled={!onGenerateArtifacts || artifactsLoading || artifactsGenerating}
                >
                  Generate starter drafts
                </Button>
              ) : null}
            </section>

            <section className="detail-block">
              <h3>Fit Overview</h3>
              {fitData ? (
                <>
                  <div className="fit-summary">
                    <Badge>Required {fitData.requiredMet}/{fitData.requiredChecks.length || 0}</Badge>
                    <Badge>Preferred {fitData.preferredMet}/{fitData.preferredChecks.length || 0}</Badge>
                    <Badge>Core checks {fitData.corePassCount}/{fitData.coreChecks.length}</Badge>
                    <Badge>Confidence {job.match?.confidence ?? "-"}</Badge>
                  </div>

                  <div className="fit-group">
                    <h4 className="fit-subheading">Skill Alignment</h4>
                    <div className="fit-matrix">
                      <article className="fit-panel fit-panel-pass">
                        <header className="fit-panel-head">
                          <p>You already have these</p>
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
                            {fitData.matchedRequired.length === 0 && <p className="empty-text tiny">No required matches yet.</p>}
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
                            {fitData.matchedPreferred.length === 0 && <p className="empty-text tiny">No preferred matches yet.</p>}
                          </div>
                        </div>
                      </article>

                      <article className="fit-panel fit-panel-fail">
                        <header className="fit-panel-head">
                          <p>Gaps to close</p>
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
                                const state = skillActionState[normalizeSkill(item.label)];
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
                                    {item.impact && (
                                      <span className={`fit-impact ${item.impact}`}>
                                        {item.impact === "critical" ? "Critical" : "Important"}
                                      </span>
                                    )}
                                    {stateLabel && <span className={`fit-state-pill ${state}`}>{stateLabel}</span>}
                                  </div>
                                </button>
                              )}}
                            />
                            {fitData.missingRequiredChecks.length === 0 && <p className="empty-text tiny">No required gaps.</p>}
                          </div>
                          <div className="fit-skill-group">
                            <p className="fit-panel-label">Preferred</p>
                            <AnimatedList
                              className="fit-chip-list matrix"
                              items={fitData.missingPreferredChecks}
                              getKey={(item) => `missing-preferred-${item.label}`}
                              renderItem={(item) => {
                                const state = skillActionState[normalizeSkill(item.label)];
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
                                    <span className="fit-impact nice">Nice-to-have</span>
                                    {stateLabel && <span className={`fit-state-pill ${state}`}>{stateLabel}</span>}
                                  </div>
                                </button>
                              )}}
                            />
                            {fitData.missingPreferredChecks.length === 0 && <p className="empty-text tiny">No preferred gaps.</p>}
                          </div>
                        </div>
                      </article>
                    </div>
                  </div>

                  <div className="fit-group">
                    <h4 className="fit-subheading">Core Requirements</h4>
                    <div className="fit-list">
                      {fitData.coreChecks.map((item) => (
                        <article key={`core-fit-${item.label}`} className={`fit-card ${item.state}`}>
                          <span className={`fit-icon ${item.state}`} aria-hidden="true">{fitIconFor(item.state)}</span>
                          <div>
                            <p className="fit-label">{item.label}</p>
                            <p className="fit-detail">{item.detail}</p>
                          </div>
                        </article>
                      ))}
                    </div>
                  </div>

                  {fitData.missingRequiredHighlights.length > 0 && (
                <p className="fit-missing">
                      Missing key requirements: {fitData.missingRequiredHighlights.map((item) => `${item.label} (${item.impact})`).join(", ")}
                    </p>
                  )}

                  <div className="match-secondary">
                    <button
                      type="button"
                      className={`score-toggle-btn ${showScoreDetails ? "active" : ""}`}
                      onClick={() => setShowScoreDetails((current) => !current)}
                    >
                      {showScoreDetails ? "Hide score details" : "Show score details"}
                    </button>
                    {showScoreDetails && job.match && (
                      <div className="fit-score-details">
                        <p><strong>Score:</strong> {job.match.score} ({job.match.band})</p>
                        <p><strong>Confidence:</strong> {job.match.confidence}</p>
                        <div className="fact-grid">
                          {Object.entries(job.match.breakdown).map(([key, value]) => (
                            <p key={key}><strong>{key.replaceAll("_", " ")}:</strong> {value}</p>
                          ))}
                        </div>
                        {job.match.reasons.length > 0 && (
                          <ul className="description-list">
                            {job.match.reasons.map((reason) => (
                              <li key={reason}>{reason}</li>
                            ))}
                          </ul>
                        )}
                      </div>
                    )}
                  </div>
                </>
              ) : (
                <p className="empty-text">Checklist unavailable because enrichment data is missing.</p>
              )}
            </section>

            <section className="detail-block">
              <h3>Enrichment</h3>
              {enrichmentPending && (
                <p className="empty-text detail-block-note">
                  Enrichment and markdown formatting are still processing in the background. This panel will update automatically.
                </p>
              )}
              {job.enrichment ? (
                <>
                  <div className="fact-grid">
                    <p><strong>Work mode:</strong> {valueOrDash(job.enrichment.work_mode)}</p>
                    <p><strong>Remote geo:</strong> {valueOrDash(job.enrichment.remote_geo)}</p>
                    <p><strong>Canada eligible:</strong> {valueOrDash(job.enrichment.canada_eligible)}</p>
                    <p><strong>Seniority:</strong> {valueOrDash(job.enrichment.seniority)}</p>
                    <p><strong>Role family:</strong> {valueOrDash(job.enrichment.role_family)}</p>
                    <p><strong>Experience:</strong> {valueOrDash(job.enrichment.years_exp_min)} - {valueOrDash(job.enrichment.years_exp_max)}</p>
                    <p><strong>Minimum degree:</strong> {valueOrDash(job.enrichment.minimum_degree)}</p>
                    <p><strong>Salary:</strong> {salaryLabel(job)}</p>
                    <p><strong>Visa:</strong> {valueOrDash(job.enrichment.visa_sponsorship)}</p>
                  </div>
                </>
              ) : (
                <p className="empty-text">No enrichment record available for this job.</p>
              )}
            </section>

            <section className="detail-block">
              <h3>Job Description</h3>
              {formatDescription(descriptionText)}
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
