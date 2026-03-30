import { motion } from "framer-motion";
import { formatDateShort } from "../dateUtils";
import type { JobSummary } from "../types";

interface JobCardProps {
  job: JobSummary;
  onSelect: (jobId: string) => void;
  onPrefetchStart?: (jobId: string) => void;
  onPrefetchCancel?: (jobId: string) => void;
  selected?: boolean;
  preview?: boolean;
}

function stagingTimeline(job: JobSummary): { tone: "overdue" | "due-soon"; detail: string } | null {
  if (job.status !== "staging") return null;
  const ageHours = job.staging_age_hours;
  if (typeof ageHours !== "number") return null;
  if (job.staging_overdue) {
    return {
      tone: "overdue",
      detail: `${Math.max(0, ageHours - 48)}h past staging target`,
    };
  }
  return {
    tone: "due-soon",
    detail: `Staging target in ${Math.max(0, 48 - ageHours)}h`,
  };
}

function titleCaseLabel(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function matchTone(job: JobSummary): "high" | "medium" | "low" | "pending" {
  if (typeof job.match_score !== "number") return "pending";
  if (job.match_score >= 80) return "high";
  if (job.match_score >= 60) return "medium";
  return "low";
}

function matchLabel(job: JobSummary): string {
  if (typeof job.match_score !== "number") return "Match pending";
  return `Match ${job.match_score}${job.match_band ? ` • ${titleCaseLabel(job.match_band)}` : ""}`;
}

export function JobCard({ job, onSelect, onPrefetchStart, onPrefetchCancel, selected = false, preview = false }: JobCardProps) {
  const timeline = stagingTimeline(job);
  const stageClass = (job.status ?? "not_applied").replaceAll("_", "-");
  const priorityLabel = titleCaseLabel(job.priority ?? "medium");
  const postedLabel = formatDateShort(job.posted);
  const timelineToneClass = timeline ? `has-${timeline.tone}` : "";
  return (
    <motion.div
      className={`job-card stage-${stageClass} ${timelineToneClass} ${selected ? "selected" : ""} ${preview ? "preview" : ""}`}
      whileHover={preview ? undefined : { y: -4 }}
      whileTap={preview ? undefined : { scale: 0.992 }}
      onMouseEnter={() => onPrefetchStart?.(job.id)}
      onMouseLeave={() => onPrefetchCancel?.(job.id)}
      onFocus={() => onPrefetchStart?.(job.id)}
      onBlur={() => onPrefetchCancel?.(job.id)}
    >
      <button type="button" className="job-card-btn" onClick={() => onSelect(job.id)}>
        <div className="job-card-topline">
          <div className="job-card-companyline">
            <span className={`job-card-stage-dot stage-${stageClass}`} aria-hidden="true" />
            <p className="job-company">{job.company}</p>
          </div>
          <span className={`job-priority-badge priority-${job.priority ?? "medium"}`}>{priorityLabel}</span>
        </div>
        <h4>{job.title}</h4>
        <div className="job-card-meta">
          <span className="job-meta-item">{job.location || "Location TBD"}</span>
        </div>
        <div className="job-card-submeta">
          <span className="job-meta-item">Posted {postedLabel}</span>
          <span className={`job-meta-item job-meta-timeline ${timeline?.tone ?? "default"}`}>
            {timeline?.detail ?? "\u00A0"}
          </span>
        </div>
        <div className="job-card-footer">
          <span className={`job-chip tone-match match-${matchTone(job)}`}>{matchLabel(job)}</span>
          {job.desired_title_match ? <span className="job-chip tone-match match-high">Title match</span> : null}
        </div>
      </button>
    </motion.div>
  );
}
