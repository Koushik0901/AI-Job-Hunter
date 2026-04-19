import { memo } from "react";
import { motion } from "framer-motion";
import { Pin } from "lucide-react";
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

interface CardInsight {
  eyebrow: string;
  body: string;
  tone: "default" | "warning" | "interviewing" | "offer" | "rejected";
}

interface CardChip {
  label: string;
  tone: "special" | "priority" | "match" | "skill";
  className?: string;
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
  if (job.match_score >= 85) return "high";
  if (job.match_score >= 70) return "medium";
  return "low";
}

function matchBadgeLabel(job: JobSummary): string {
  if (job.match_band) {
    return `${titleCaseLabel(job.match_band)} rank`;
  }
  if (typeof job.match_score === "number") {
    return `Rank ${job.match_score}`;
  }
  return "Rank pending";
}

function priorityLabel(priority: JobSummary["priority"]): string {
  if (priority === "high") return "High priority";
  if (priority === "low") return "Low priority";
  return "Priority set";
}

function firstNonEmpty(values: Array<string | null | undefined>): string | null {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return null;
}

function cardBadge(job: JobSummary): { label: string; tone: string } {
  if (job.status === "offer") {
    return { label: job.health_label ?? "Offer active", tone: "offer" };
  }
  if (job.status === "interviewing") {
    return { label: job.health_label ?? "Interviewing", tone: "interviewing" };
  }
  if (job.status === "rejected") {
    return { label: "Closed", tone: "rejected" };
  }
  if (job.match_score !== null || job.match_band) {
    const tone = matchTone(job);
    return { label: matchBadgeLabel(job), tone: `match-${tone}` };
  }
  return { label: priorityLabel(job.priority), tone: "neutral" };
}

function buildCardInsight(job: JobSummary, timeline: ReturnType<typeof stagingTimeline>): CardInsight {
  const insightBody = firstNonEmpty([
    job.next_best_action,
    job.guidance_summary,
    job.guidance_reasons[0],
    job.recommendation_reasons[0],
    job.health_label,
  ]);
  const fallbackBody = timeline?.detail ?? "Review in the drawer for full context.";

  if (job.status === "interviewing") {
    return {
      eyebrow: "Prep strategy",
      body: insightBody ?? fallbackBody,
      tone: "interviewing",
    };
  }

  if (job.status === "offer") {
    return {
      eyebrow: "Offer guidance",
      body: insightBody ?? fallbackBody,
      tone: "offer",
    };
  }

  if (job.status === "rejected") {
    return {
      eyebrow: "Outcome",
      body: insightBody ?? fallbackBody,
      tone: "rejected",
    };
  }

  if (timeline?.tone === "overdue") {
    return {
      eyebrow: "Urgent next step",
      body: insightBody ?? fallbackBody,
      tone: "warning",
    };
  }

  if (job.match_score !== null || job.match_band) {
    return {
      eyebrow: matchBadgeLabel(job),
      body: insightBody ?? fallbackBody,
      tone: "default",
    };
  }

  if (job.priority === "high" || job.priority === "low") {
    return {
      eyebrow: priorityLabel(job.priority),
      body: insightBody ?? fallbackBody,
      tone: "warning",
    };
  }

  return {
    eyebrow: job.guidance_title ?? cardBadge(job).label ?? "Next step",
    body: insightBody ?? fallbackBody,
    tone: "default",
  };
}

function buildCardChips(job: JobSummary, primarySignal: CardInsight | null): { chips: CardChip[]; overflowCount: number } {
  const chips: CardChip[] = [];
  const primaryLabel = primarySignal?.eyebrow.trim().toLowerCase() ?? "";

  if (job.desired_title_match) {
    chips.push({ label: "Title match", tone: "match", className: "match-high" });
  }

  if (job.priority === "high" || job.priority === "low") {
    const priorityText = priorityLabel(job.priority);
    if (!primaryLabel.includes(priorityText.toLowerCase())) {
      chips.push({
        label: priorityText,
        tone: "priority",
        className: `priority-${job.priority}`,
      });
    }
  }

  const skills = (job.required_skills ?? []).map((skill) => skill.trim()).filter(Boolean);
  if (skills.length > 0) {
    chips.push({ label: skills[0], tone: "skill" });
  }

  const visible = chips.slice(0, 3);
  const overflowCount = Math.max(0, chips.length - visible.length) + Math.max(0, skills.length - 1);

  return { chips: visible, overflowCount };
}

export const JobCard = memo(function JobCard({
  job,
  onSelect,
  onPrefetchStart,
  onPrefetchCancel,
  selected = false,
  preview = false,
}: JobCardProps) {
  const timeline = stagingTimeline(job);
  const stageClass = (job.status ?? "not_applied").replaceAll("_", "-");
  const postedLabel = formatDateShort(job.posted);
  const atsLabel = firstNonEmpty([job.ats ? titleCaseLabel(job.ats) : null]);
  const locationLabel = firstNonEmpty([job.location, "Location TBD"]);
  const timelineToneClass = timeline ? `has-${timeline.tone}` : "";
  const primarySignal = buildCardInsight(job, timeline);
  const footerChips = buildCardChips(job, primarySignal);

  return (
    <motion.div
      className={`job-card stage-${stageClass} ${timelineToneClass} ${selected ? "selected" : ""} ${preview ? "preview" : ""}`}
      whileHover={
        preview
          ? undefined
          : {
              y: -4,
              boxShadow: "0 14px 34px rgba(23, 28, 31, 0.08)",
            }
      }
      whileTap={preview ? undefined : { scale: 0.985 }}
      transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
      onMouseEnter={() => onPrefetchStart?.(job.id)}
      onMouseLeave={() => onPrefetchCancel?.(job.id)}
      onFocus={() => onPrefetchStart?.(job.id)}
      onBlur={() => onPrefetchCancel?.(job.id)}
    >
      <button type="button" className="job-card-btn" onClick={() => onSelect(job.id)}>
        <div className="job-card-topline">
          <div className="job-card-brand">
            <div className="job-card-companyline">
              <span className={`job-card-stage-dot stage-${stageClass}`} aria-hidden="true" />
              <p className="job-company">{job.company}</p>
              {job.pinned ? (
                <span className="job-pin-badge" title="Pinned" aria-label="Pinned">
                  <Pin size={10} strokeWidth={2.6} aria-hidden="true" />
                </span>
              ) : null}
            </div>
          </div>
          <div className="job-card-badges">
            <span className="job-meta-item job-meta-posted">{postedLabel}</span>
          </div>
        </div>

        <div className="job-card-heading">
          <h4>{job.title}</h4>
        </div>

        {primarySignal ? (
          <div className={`job-card-insight tone-${primarySignal.tone}`}>
            <span className="job-card-insight-eyebrow">{primarySignal.eyebrow}</span>
            <p>{primarySignal.body}</p>
          </div>
        ) : null}

        <div className="job-card-meta">
          {locationLabel ? <span className="job-meta-item">{locationLabel}</span> : null}
          {locationLabel && atsLabel ? <span className="job-meta-separator" aria-hidden="true" /> : null}
          {atsLabel ? <span className="job-meta-item">{atsLabel}</span> : null}
        </div>

        {timeline ? (
          <div className="job-card-submeta">
            <span className={`job-meta-item job-meta-timeline ${timeline.tone}`}>{timeline.detail}</span>
          </div>
        ) : null}

        <div className="job-card-footer">
          {footerChips.chips.map((chip) => (
            <span
              key={chip.label}
              className={[
                "job-chip",
                chip.tone === "priority" ? "tone-priority" : `tone-${chip.tone}`,
                chip.className ?? "",
              ]
                .filter(Boolean)
                .join(" ")}
            >
              {chip.label}
            </span>
          ))}
          {footerChips.overflowCount > 0 ? (
            <span className="job-chip tone-special">+{footerChips.overflowCount}</span>
          ) : null}
        </div>
      </button>
    </motion.div>
  );
});
