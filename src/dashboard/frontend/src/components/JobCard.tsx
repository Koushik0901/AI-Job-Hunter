import { motion } from "framer-motion";
import type { DragEvent } from "react";
import type { JobSummary } from "../types";
import { ShimmerTag } from "./reactbits/ShimmerTag";

interface JobCardProps {
  job: JobSummary;
  onSelect: (url: string) => void;
  onPrefetch?: (url: string) => void;
}

function formatDate(value: string): string {
  if (!value) return "Unknown";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleDateString();
}

export function JobCard({ job, onSelect, onPrefetch }: JobCardProps) {
  function onDragStart(event: DragEvent<HTMLDivElement>): void {
    event.dataTransfer.setData("text/job-url", job.url);
  }

  return (
    <motion.div
      className="job-card"
      whileHover={{ y: -3 }}
      whileTap={{ scale: 0.99 }}
      draggable
      onDragStartCapture={onDragStart}
      onMouseEnter={() => onPrefetch?.(job.url)}
      onFocus={() => onPrefetch?.(job.url)}
    >
      <button type="button" className="job-card-btn" onClick={() => onSelect(job.url)}>
        <div className="job-card-head">
          <h4>{job.title}</h4>
        </div>
        <p className="job-company">{job.company}</p>
        <p className="job-location">{job.location || "-"}</p>
        <div className="job-meta-row">
          <span className="job-date-chip">Posted {formatDate(job.posted)}</span>
          <ShimmerTag>{job.ats || "ATS"}</ShimmerTag>
        </div>
        <div className="job-meta-row job-meta-bottom">
          <ShimmerTag>
            {`Match ${job.match_score ?? "-"}${job.match_band ? ` (${job.match_band})` : ""}`}
          </ShimmerTag>
        </div>
      </button>
    </motion.div>
  );
}
