import { useCallback, useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowUpRight,
  ChevronRight,
  CircleCheck,
  Download,
  FileText,
  Pin,
  Sparkles,
} from "lucide-react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import {
  addToQueue,
  fetchJobDescriptionPdf,
  getJobDetail,
  getJobEvents,
  patchTracking,
  suppressJob,
} from "../api";
import { DescriptionMarkdown } from "../components/DescriptionMarkdown";
import { ThemedLoader } from "../components/ThemedLoader";
import { useDashboardData } from "../contexts/DashboardDataContext";
import { formatDateShort, formatDateTime } from "../dateUtils";
import {
  buildDescriptionFilename,
  buildJobFitAnalysis,
  buildRecommendationGuidance,
  fitIconFor,
  matchLabel,
  matchTone,
  recommendationLabel,
  salaryLabel,
  stagingSummary,
  titleCaseLabel,
  valueOrDash,
} from "../jobDetailUtils";
import type { JobDetail, JobEvent, Priority, TrackingStatus } from "../types";

const pageEase = [0.22, 0.84, 0.24, 1] as [number, number, number, number];

const STATUS_OPTIONS: Array<{ value: TrackingStatus; label: string }> = [
  { value: "not_applied", label: "Not Applied" },
  { value: "staging", label: "Staging" },
  { value: "applied", label: "Applied" },
  { value: "interviewing", label: "Interviewing" },
  { value: "offer", label: "Offer" },
  { value: "rejected", label: "Rejected" },
];

const PRIORITY_OPTIONS: Array<{ value: Priority; label: string }> = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
];

type DetailRouteState = {
  from?: string;
};

type AnalysisRow = {
  title: string;
  body: string;
  tone: "strength" | "gap";
};

function buildChipValues(job: JobDetail): string[] {
  const enrichment = job.enrichment;
  const required = enrichment?.required_skills ?? [];
  const preferred = enrichment?.preferred_skills ?? [];
  const meta = [
    enrichment?.role_family,
    enrichment?.work_mode,
    enrichment?.seniority,
    enrichment?.canada_eligible ? `Canada Eligible: ${enrichment.canada_eligible}` : null,
    enrichment?.visa_sponsorship ? `Visa: ${enrichment.visa_sponsorship}` : null,
    job.desired_title_match ? "Desired Title Match" : null,
  ];
  return [...required.slice(0, 3), ...preferred.slice(0, 1), ...meta].filter((value): value is string => Boolean(value && value.trim()));
}

function buildFacts(job: JobDetail): Array<{ label: string; value: string }> {
  return [
    { label: "ATS / Source", value: valueOrDash(job.ats) },
    { label: "Application Status", value: valueOrDash(job.application_status) },
    { label: "First Seen", value: formatDateTime(job.first_seen, "-") },
    { label: "Last Seen", value: formatDateTime(job.last_seen, "-") },
    { label: "Work Mode", value: valueOrDash(job.enrichment?.work_mode) },
    { label: "Role Family", value: valueOrDash(job.enrichment?.role_family) },
    { label: "Seniority", value: valueOrDash(job.enrichment?.seniority) },
    { label: "Experience Range", value: `${valueOrDash(job.enrichment?.years_exp_min)} - ${valueOrDash(job.enrichment?.years_exp_max)}` },
    { label: "Education", value: valueOrDash(job.enrichment?.minimum_degree) },
    { label: "Visa / Eligibility", value: valueOrDash(job.enrichment?.visa_sponsorship ?? job.enrichment?.canada_eligible) },
  ];
}

function buildAnalysisRows(job: JobDetail, guidanceSummary: string, fitData: ReturnType<typeof buildJobFitAnalysis>): AnalysisRow[] {
  const rows: AnalysisRow[] = [];

  if (fitData?.matchedRequired[0]) {
    rows.push({
      title: `Strength: ${fitData.matchedRequired[0].label}`,
      body: fitData.matchedRequired[0].detail,
      tone: "strength",
    });
  } else if (typeof job.match?.score === "number") {
    rows.push({
      title: `Strength: ${matchLabel(job)}`,
      body: guidanceSummary,
      tone: "strength",
    });
  }

  if (fitData?.coreChecks.find((item) => item.state === "pass")) {
    const pass = fitData.coreChecks.find((item) => item.state === "pass");
    if (pass) {
      rows.push({
        title: `Strength: ${pass.label}`,
        body: pass.detail,
        tone: "strength",
      });
    }
  }

  if (fitData?.missingRequiredChecks[0]) {
    rows.push({
      title: `Gap: ${fitData.missingRequiredChecks[0].label}`,
      body: fitData.missingRequiredChecks[0].detail,
      tone: "gap",
    });
  } else if (fitData?.coreChecks.find((item) => item.state === "fail")) {
    const fail = fitData.coreChecks.find((item) => item.state === "fail");
    if (fail) {
      rows.push({
        title: `Gap: ${fail.label}`,
        body: fail.detail,
        tone: "gap",
      });
    }
  }

  if (rows.length === 0) {
    rows.push({
      title: "Strength: Recommendation Context",
      body: guidanceSummary,
      tone: "strength",
    });
  }

  return rows.slice(0, 4);
}

function buildNarrative(job: JobDetail, guidanceSummary: string): string {
  const pieces = [
    guidanceSummary,
    job.next_best_action ? `Next step: ${job.next_best_action}` : null,
    job.enrichment?.remote_geo ? `Remote geography: ${job.enrichment.remote_geo}.` : null,
  ].filter((value): value is string => Boolean(value && value.trim()));
  return pieces.join(" ");
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function JobDetailPage() {
  const { jobId = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const routeState = (location.state ?? null) as DetailRouteState | null;
  const { profile, skillAliases, refreshData } = useDashboardData();

  const [job, setJob] = useState<JobDetail | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [draftStatus, setDraftStatus] = useState<TrackingStatus>("not_applied");
  const [draftPriority, setDraftPriority] = useState<Priority>("medium");
  const [draftAppliedAt, setDraftAppliedAt] = useState("");
  const [draftNextStep, setDraftNextStep] = useState("");
  const [draftCompensation, setDraftCompensation] = useState("");

  useEffect(() => {
    if (!jobId) {
      setError("Missing job id.");
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([getJobDetail(jobId), getJobEvents(jobId)])
      .then(([detail, timeline]) => {
        if (cancelled) return;
        setJob(detail);
        setEvents(timeline);
      })
      .catch((fetchError) => {
        if (cancelled) return;
        setError(fetchError instanceof Error ? fetchError.message : "Failed to load job detail");
        setJob(null);
        setEvents([]);
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  useEffect(() => {
    if (!job) return;
    setDraftStatus(job.tracking_status);
    setDraftPriority(job.priority ?? "medium");
    setDraftAppliedAt(job.applied_at ?? "");
    setDraftNextStep(job.next_step ?? "");
    setDraftCompensation(job.target_compensation ?? "");
  }, [job]);

  const guidance = useMemo(() => (job ? buildRecommendationGuidance(job) : null), [job]);
  const fitData = useMemo(() => buildJobFitAnalysis(job, profile, skillAliases), [job, profile, skillAliases]);
  const chipValues = useMemo(() => (job ? buildChipValues(job) : []), [job]);
  const facts = useMemo(() => (job ? buildFacts(job) : []), [job]);
  const description = useMemo(() => {
    if (!job) return "";
    return job.enrichment?.formatted_description?.trim() || job.description.trim();
  }, [job]);
  const postedLabel = useMemo(() => (job?.posted ? `Posted ${formatDateShort(job.posted, "-")}` : "Posted date unavailable"), [job]);
  const narrative = useMemo(() => {
    if (!job || !guidance) return "";
    return buildNarrative(job, guidance.summary);
  }, [guidance, job]);
  const analysisRows = useMemo(() => {
    if (!job || !guidance) return [];
    return buildAnalysisRows(job, guidance.summary, fitData);
  }, [fitData, guidance, job]);
  const summaryCards = useMemo(() => {
    if (!job || !guidance) return [];
    return [
      {
        label: "Rank",
        value: matchLabel(job),
        detail: guidance.title,
      },
      {
        label: "Health",
        value: titleCaseLabel(guidance.healthLabel),
        detail: guidance.nextBestAction,
      },
      {
        label: "Compensation",
        value: salaryLabel(job),
        detail: job.target_compensation ? `Target ${job.target_compensation}` : "Target compensation not set",
      },
      {
        label: "Tracking",
        value: titleCaseLabel(job.tracking_status),
        detail: job.applied_at ? `Applied ${formatDateShort(job.applied_at, "-")}` : postedLabel,
      },
    ];
  }, [guidance, job, postedLabel]);
  const trackingDirty = job
    ? draftStatus !== job.tracking_status
      || draftPriority !== (job.priority ?? "medium")
      || draftAppliedAt !== (job.applied_at ?? "")
      || draftNextStep !== (job.next_step ?? "")
      || draftCompensation !== (job.target_compensation ?? "")
    : false;

  const handleBack = useCallback(() => {
    if (routeState?.from) {
      navigate(routeState.from);
      return;
    }
    navigate("/board");
  }, [navigate, routeState?.from]);

  const updateTracking = useCallback(async (patch: {
    status?: TrackingStatus;
    priority?: Priority;
    pinned?: boolean;
    applied_at?: string | null;
    next_step?: string | null;
    target_compensation?: string | null;
  }, successMessage: string) => {
    if (!job) return;
    setBusyKey("tracking");
    try {
      const updated = await patchTracking(job.id, patch);
      setJob(updated);
      await refreshData({ background: true });
      toast.success(successMessage);
    } catch (fetchError) {
      toast.error(fetchError instanceof Error ? fetchError.message : "Failed to update job");
    } finally {
      setBusyKey(null);
    }
  }, [job, refreshData]);

  const handleSaveTracking = useCallback(async () => {
    await updateTracking(
      {
        status: draftStatus,
        priority: draftPriority,
        applied_at: draftAppliedAt || null,
        next_step: draftNextStep.trim() || null,
        target_compensation: draftCompensation.trim() || null,
      },
      "Pipeline details updated",
    );
  }, [draftAppliedAt, draftCompensation, draftNextStep, draftPriority, draftStatus, updateTracking]);

  const handleQueue = useCallback(async () => {
    if (!job) return;
    setBusyKey("queue");
    try {
      await addToQueue(job.id);
      await refreshData({ background: true });
      toast.success("Added to application queue");
    } catch (fetchError) {
      toast.error(fetchError instanceof Error ? fetchError.message : "Failed to add to queue");
    } finally {
      setBusyKey(null);
    }
  }, [job, refreshData]);

  const handleOpenAgent = useCallback(async () => {
    if (job) {
      try {
        await addToQueue(job.id);
      } catch {
        // Queueing is best-effort before Agent handoff.
      }
    }
    navigate("/agent");
  }, [job, navigate]);

  const handleDownloadPdf = useCallback(async () => {
    if (!job) return;
    setBusyKey("pdf");
    try {
      const { blob, filename } = await fetchJobDescriptionPdf(job.id, buildDescriptionFilename(job, "pdf"));
      downloadBlob(blob, filename);
    } catch (fetchError) {
      toast.error(fetchError instanceof Error ? fetchError.message : "Failed to download PDF");
    } finally {
      setBusyKey(null);
    }
  }, [job]);

  const handleSuppress = useCallback(async () => {
    if (!job) return;
    setBusyKey("suppress");
    try {
      await suppressJob(job.id, "Not a fit");
      await refreshData({ background: true });
      toast.success("Job suppressed");
      handleBack();
    } catch (fetchError) {
      toast.error(fetchError instanceof Error ? fetchError.message : "Failed to suppress job");
    } finally {
      setBusyKey(null);
    }
  }, [handleBack, job, refreshData]);

  if (loading) {
    return (
      <div className="job-detail-loading-shell">
        <ThemedLoader label="Loading job deep dive" />
      </div>
    );
  }

  if (!job || error) {
    return (
      <div className="dashboard-page job-detail-page">
        <div className="job-detail-error">
          <p className="job-detail-section-kicker">Job Detail</p>
          <h2>Unable to load this role</h2>
          <p>{error ?? "The requested job could not be found."}</p>
          <div className="job-detail-error-actions">
            <button type="button" className="job-detail-soft-button" onClick={handleBack}>Back</button>
            <button type="button" className="job-detail-gradient-button" onClick={() => navigate("/board")}>Open Board</button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <motion.div
      className="dashboard-page job-detail-page"
      initial={{ opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.36, ease: pageEase }}
    >
      <div className="job-detail-canvas">
        <div className="job-detail-layout">
          <div className="job-detail-main">
            <header className="job-detail-header">
              <div className="job-detail-header-meta">
                <div className="job-detail-status-row">
                  <span className="job-detail-state-pill">Job detail</span>
                  <span className="job-detail-posted-meta">{postedLabel}</span>
                </div>
                <h1>{job.title}</h1>
                <div className="job-detail-company-row">
                  <p className="job-detail-company-name">{job.company}</p>
                  <div className="job-detail-company-meta-row">
                    <span>{job.location || "Location TBD"}</span>
                    <span className="job-detail-meta-divider" aria-hidden="true" />
                    <span>{valueOrDash(job.ats)}</span>
                  </div>
                </div>
                <div className="job-detail-hero-chip-row">
                  <span className={`job-detail-meta-pill tone-${job.tracking_status.replaceAll("_", "-")}`}>{titleCaseLabel(job.tracking_status)}</span>
                  <span className="job-detail-meta-pill">{titleCaseLabel(job.priority ?? "medium")} priority</span>
                  {job.pinned ? <span className="job-detail-meta-pill">Pinned</span> : null}
                  {stagingSummary(job) ? <span className="job-detail-meta-pill">{stagingSummary(job)}</span> : null}
                </div>
              </div>
            </header>

            <div className="job-detail-summary-grid">
              {summaryCards.map((card) => (
                <article key={card.label} className="job-detail-summary-card">
                  <span>{card.label}</span>
                  <strong>{card.value}</strong>
                  <p>{card.detail}</p>
                </article>
              ))}
            </div>

            <section className="job-detail-copy-block job-detail-copy-block--hero">
              <div className="job-detail-section-head">
                <div>
                  <p className="job-detail-section-kicker">Narrative</p>
                  <h2>What matters now</h2>
                </div>
              </div>
              <p>{narrative || guidance?.summary || "No narrative is available yet."}</p>
            </section>

            <section className="job-detail-gap-panel">
              <div className="job-detail-gap-head">
                <div className="job-detail-gap-icon">
                  <Sparkles size={20} strokeWidth={2} />
                </div>
                <h2>AI Gap Analysis</h2>
              </div>
              <div className="job-detail-gap-list">
                {analysisRows.map((row) => (
                  <article key={`${row.tone}-${row.title}`} className="job-detail-gap-row">
                    <div className={`job-detail-gap-badge ${row.tone}`}>
                      {row.tone === "strength" ? <CircleCheck size={16} strokeWidth={2.4} /> : <AlertTriangle size={16} strokeWidth={2.2} />}
                    </div>
                    <div>
                      <p className="job-detail-gap-title">{row.title}</p>
                      <p className="job-detail-gap-body">{row.body}</p>
                    </div>
                  </article>
                ))}
              </div>
            </section>

            {chipValues.length > 0 ? (
              <div className="job-detail-tag-row">
                {chipValues.map((chip) => (
                  <span key={chip} className="job-detail-tag-chip">{chip}</span>
                ))}
              </div>
            ) : null}

            <section className="job-detail-secondary-section">
              <div className="job-detail-section-head">
                <div>
                  <p className="job-detail-section-kicker">Facts</p>
                  <h3>Structured job facts</h3>
                </div>
              </div>
              <div className="job-detail-facts-grid">
                {facts.map((fact) => (
                  <article key={fact.label} className="job-detail-fact-card">
                    <span>{fact.label}</span>
                    <strong>{fact.value}</strong>
                  </article>
                ))}
              </div>
            </section>

            <section className="job-detail-secondary-section">
              <div className="job-detail-section-head">
                <div>
                  <p className="job-detail-section-kicker">Timeline</p>
                  <h3>Latest activity</h3>
                </div>
              </div>
              {events.length > 0 ? (
                <div className="job-detail-timeline">
                  {events.map((event) => (
                    <article key={event.id} className="job-detail-timeline-item">
                      <div className="job-detail-timeline-marker" aria-hidden="true" />
                      <div className="job-detail-timeline-content">
                        <div className="job-detail-timeline-head">
                          <strong>{event.title}</strong>
                          <span>{formatDateTime(event.event_at, "-")}</span>
                        </div>
                        <p className="job-detail-timeline-type">{titleCaseLabel(event.event_type)}</p>
                        {event.body ? <p className="job-detail-timeline-body">{event.body}</p> : null}
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <p className="job-detail-secondary-copy">No event history has been recorded for this role yet.</p>
              )}
            </section>

            <section className="job-detail-secondary-section">
              <div className="job-detail-section-head">
                <div>
                  <p className="job-detail-section-kicker">Description</p>
                  <h3>Full role brief</h3>
                </div>
                <span className="job-detail-mini-pill">{job.enrichment?.formatted_description?.trim() ? "Formatted JD" : "Raw JD"}</span>
              </div>
              {description ? (
                <DescriptionMarkdown markdown={description} />
              ) : (
                <p className="job-detail-secondary-copy">No job description is available.</p>
              )}
            </section>
          </div>

          <aside className="job-detail-rail">
            <div className="job-detail-rail-sticky">
              <section className="job-detail-rail-card job-detail-rail-card--soft">
                <div className="job-detail-section-head compact">
                  <div>
                    <p className="job-detail-section-kicker">Tracking</p>
                    <h3>Pipeline controls</h3>
                  </div>
                </div>
                <div className="job-detail-form-grid">
                  <label>
                    <span>Status</span>
                    <select value={draftStatus} onChange={(event) => setDraftStatus(event.target.value as TrackingStatus)}>
                      {STATUS_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Priority</span>
                    <select value={draftPriority} onChange={(event) => setDraftPriority(event.target.value as Priority)}>
                      {PRIORITY_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Applied date</span>
                    <input type="date" value={draftAppliedAt} onChange={(event) => setDraftAppliedAt(event.target.value)} />
                  </label>
                  <label>
                    <span>Target compensation</span>
                    <input
                      type="text"
                      value={draftCompensation}
                      onChange={(event) => setDraftCompensation(event.target.value)}
                      placeholder="e.g. CAD 190k base"
                    />
                  </label>
                  <label className="full">
                    <span>Next step</span>
                    <textarea value={draftNextStep} rows={4} onChange={(event) => setDraftNextStep(event.target.value)} />
                  </label>
                </div>
                <div className="job-detail-tracking-actions">
                  <button type="button" className="job-detail-soft-button" onClick={() => void handleSaveTracking()} disabled={!trackingDirty || busyKey === "tracking"}>
                    {busyKey === "tracking" ? "Saving..." : "Save Tracking"}
                  </button>
                  <div className="job-detail-mini-actions">
                    <button type="button" className="job-detail-text-action" onClick={() => void updateTracking({ pinned: !job.pinned }, job.pinned ? "Job unpinned" : "Job pinned")}>
                      <Pin size={15} strokeWidth={2.1} />
                      {job.pinned ? "Remove pin" : "Pin role"}
                    </button>
                    {job.tracking_status === "staging" ? (
                      <>
                        <button type="button" className="job-detail-text-action" onClick={() => void updateTracking({ status: "applied" }, "Moved to Applied")}>
                          Mark applied
                        </button>
                        <button type="button" className="job-detail-text-action" onClick={() => void updateTracking({ status: "rejected" }, "Moved to Rejected")}>
                          Reject
                        </button>
                      </>
                    ) : null}
                  </div>
                </div>
              </section>

              <section className="job-detail-insider-card">
                <div className="job-detail-insider-copy">
                  <h4>Navigator Insight</h4>
                  <p>{guidance?.nextBestAction ?? "Use the Agent page when you are ready to tailor materials."}</p>
                  <p className="job-detail-insider-sub">Health: {titleCaseLabel(guidance?.healthLabel ?? job.tracking_status)}</p>
                  <button type="button" className="job-detail-insider-button" onClick={() => void handleQueue()}>
                    {busyKey === "queue" ? "Queueing..." : "Add to Queue"}
                  </button>
                </div>
              </section>

              <section className="job-detail-rail-card">
                <div className="job-detail-rail-head">
                  <h3>AI Application Tailor</h3>
                  <p>Open the agent workspace when you are ready to tailor materials for this role.</p>
                </div>
                <div className="job-detail-tailor-actions">
                  <button type="button" className="job-detail-tailor-row" onClick={() => void handleOpenAgent()}>
                    <div className="job-detail-tailor-icon tone-primary">
                      <FileText size={18} strokeWidth={2.2} />
                    </div>
                    <div className="job-detail-tailor-copy">
                      <strong>Smart Resume</strong>
                      <span>Update skills for ATS</span>
                    </div>
                    <ChevronRight size={18} strokeWidth={2.2} />
                  </button>
                  <button type="button" className="job-detail-tailor-row" onClick={() => void handleOpenAgent()}>
                    <div className="job-detail-tailor-icon tone-secondary">
                      <Sparkles size={18} strokeWidth={2.2} />
                    </div>
                    <div className="job-detail-tailor-copy">
                      <strong>Draft Elevator Pitch</strong>
                      <span>Generate a role-specific intro</span>
                    </div>
                    <ChevronRight size={18} strokeWidth={2.2} />
                  </button>
                </div>
                <button type="button" className="job-detail-gradient-button" onClick={() => void handleOpenAgent()} disabled={busyKey === "queue"}>
                  {busyKey === "queue" ? "Queueing..." : "Apply with Copilot"}
                </button>
                <p className="job-detail-safe-note">Safe & verified workflow</p>
              </section>

              <section className="job-detail-rail-card job-detail-rail-card--utility">
                <div className="job-detail-section-head compact">
                  <div>
                    <p className="job-detail-section-kicker">Utilities</p>
                    <h3>Posting and exports</h3>
                  </div>
                </div>
                <div className="job-detail-utility-list">
                  <a href={job.url} target="_blank" rel="noreferrer" className="job-detail-utility-link">
                    <ArrowUpRight size={16} strokeWidth={2.1} />
                    Open Posting
                  </a>
                  <button type="button" className="job-detail-utility-link" onClick={() => void handleDownloadPdf()} disabled={busyKey === "pdf"}>
                    <Download size={16} strokeWidth={2.1} />
                    {busyKey === "pdf" ? "Preparing PDF..." : "Download JD PDF"}
                  </button>
                </div>
              </section>

              <section className="job-detail-rail-card job-detail-rail-card--danger">
                <div className="job-detail-section-head compact">
                  <div>
                    <p className="job-detail-section-kicker">Scope</p>
                    <h3>Remove from rotation</h3>
                  </div>
                </div>
                <p className="job-detail-secondary-copy">
                  Hide the role if it is outside your target search. This keeps the recommendation engine clean.
                </p>
                <button type="button" className="job-detail-soft-button" onClick={() => void handleSuppress()} disabled={busyKey === "suppress"}>
                  {busyKey === "suppress" ? "Suppressing..." : "Mark Not a Fit"}
                </button>
              </section>
            </div>
          </aside>
        </div>
      </div>
    </motion.div>
  );
}
