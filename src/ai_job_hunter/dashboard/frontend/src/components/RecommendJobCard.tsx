import { memo } from "react";
import { motion } from "framer-motion";
import { ArrowUpRight, Pin, Sparkles } from "lucide-react";
import { addToQueue, prefetchJobDetail } from "../api";
import { formatDateShort } from "../dateUtils";
import type { CandidateProfile, JobSummary } from "../types";

interface RecommendJobCardProps {
  job: JobSummary;
  profile: CandidateProfile | null;
  onView: (jobId: string) => void;
  onStageApplied: (jobId: string) => void;
  onHover?: (jobId: string | null) => void;
  stagingBusy?: boolean;
}

function isSkillMatched(skill: string, profileSkills: string[]): boolean {
  const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");
  const target = norm(skill);
  return profileSkills.some((s) => norm(s) === target || norm(s).includes(target) || target.includes(norm(s)));
}

function recommendationTone(score: number | null): string {
  if (score == null) return "Unscored";
  if (score >= 85) return "Top band";
  if (score >= 70) return "Strong";
  return "Viable";
}

export const RecommendJobCard = memo(function RecommendJobCard({
  job,
  profile,
  onView,
  onHover,
}: RecommendJobCardProps) {
  const skills = (job.required_skills ?? []).slice(0, 4);
  const profileSkills = profile?.skills ?? [];
  const isNew = job.posted ? (Date.now() - new Date(job.posted).getTime()) < 3 * 24 * 60 * 60 * 1000 : false;

  async function handleQueue(e: React.MouseEvent) {
    e.stopPropagation();
    try {
      await addToQueue(job.id);
    } catch {
      // silent
    }
  }

  return (
    <motion.article
      className="discover-card"
      onClick={() => onView(job.id)}
      onMouseEnter={() => {
        onHover?.(job.id);
        void prefetchJobDetail(job.id);
      }}
      onMouseLeave={() => onHover?.(null)}
      onFocus={() => void prefetchJobDetail(job.id)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && onView(job.id)}
      whileHover={{ y: -3 }}
      transition={{ duration: 0.22, ease: [0.22, 0.84, 0.24, 1] }}
    >
      <div className="discover-card-head">
        <div className="discover-card-eyebrow">
          <span>{job.company}</span>
          {job.ats ? <small>{job.ats}</small> : null}
        </div>
        <div className="discover-card-badges">
          {job.pinned ? <span className="discover-card-badge"><Pin size={12} /> Pinned</span> : null}
          {isNew ? <span className="discover-card-badge">New</span> : null}
          {job.desired_title_match ? <span className="discover-card-badge discover-card-badge--accent">Title match</span> : null}
        </div>
      </div>

      <div className="discover-card-title-row">
        <div>
          <h3>{job.title}</h3>
          <p>{job.location || "Location not specified"}</p>
        </div>
        <div className="discover-card-score">
          <strong>{job.match_score != null ? Math.round(job.match_score) : "—"}</strong>
          <span>{recommendationTone(job.match_score)}</span>
        </div>
      </div>

      {job.guidance_summary ? (
        <div className="discover-card-guidance">
          <Sparkles size={14} />
          <p>{job.guidance_summary}</p>
        </div>
      ) : null}

      {skills.length > 0 ? (
        <div className="discover-card-skills">
          {skills.map((skill) => {
            const matched = profileSkills.length > 0 && isSkillMatched(skill, profileSkills);
            return (
              <span
                key={skill}
                className={`discover-skill-chip ${profileSkills.length > 0 ? (matched ? "discover-skill-chip--matched" : "discover-skill-chip--gap") : ""}`}
              >
                {skill}
              </span>
            );
          })}
        </div>
      ) : null}

      <div className="discover-card-foot">
        <span className="discover-card-date">{formatDateShort(job.posted)}</span>
        <div className="discover-card-actions" onClick={(e) => e.stopPropagation()}>
          <button type="button" className="discover-btn discover-btn--ghost" onClick={handleQueue}>
            Queue
          </button>
          <button type="button" className="discover-btn discover-btn--primary" onClick={() => onView(job.id)}>
            Review <ArrowUpRight size={14} />
          </button>
        </div>
      </div>
    </motion.article>
  );
});
