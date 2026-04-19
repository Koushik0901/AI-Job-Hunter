import { fuzzySkillsMatch, normalizeSkill } from "./skillUtils";
import type { CandidateProfile, JobDetail } from "./types";

export type FitState = "pass" | "fail" | "unknown";

export interface FitCheck {
  label: string;
  detail: string;
  state: FitState;
  impact?: "critical" | "important" | "nice";
}

export interface JobFitAnalysis {
  requiredChecks: FitCheck[];
  preferredChecks: FitCheck[];
  matchedRequired: FitCheck[];
  missingRequiredChecks: FitCheck[];
  matchedPreferred: FitCheck[];
  missingPreferredChecks: FitCheck[];
  requiredMet: number;
  preferredMet: number;
  coreChecks: FitCheck[];
  corePassCount: number;
  missingRequiredHighlights: Array<{ label: string; impact: "critical" | "important" | "nice" }>;
}

export interface RecommendationGuidanceData {
  mode: "evaluation" | "stage_narrative";
  title: string;
  summary: string;
  reasons: string[];
  nextBestAction: string;
  healthLabel: string;
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

function requiredImpact(index: number, total: number): "critical" | "important" {
  if (total <= 4) return "critical";
  return index < Math.ceil(total * 0.5) ? "critical" : "important";
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

function slugifyFilenamePart(value: string | null | undefined): string {
  const normalized = (value ?? "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return normalized;
}

export function valueOrDash(value: string | number | null | undefined): string {
  return value === null || value === undefined || value === "" ? "-" : String(value);
}

export function salaryLabel(job: JobDetail): string {
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

export function buildDescriptionFilename(job: JobDetail, extension: "md" | "pdf"): string {
  const parts = [
    slugifyFilenamePart(job.company),
    slugifyFilenamePart(job.title),
    "job-description",
  ].filter(Boolean);
  return parts.length > 0 ? `${parts.join("-")}.${extension}` : `job-description-${job.id}.${extension}`;
}

export function titleCaseLabel(value: string | null | undefined): string {
  if (!value) return "-";
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function recommendationLabel(value: string | null | undefined): string {
  if (!value) return "Unrated";
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function guidanceModeLabel(mode: "evaluation" | "stage_narrative" | null | undefined): string {
  if (mode === "stage_narrative") return "Active process";
  return "Opportunity review";
}

export function isStageNarrativeJob(job: JobDetail): boolean {
  return ["applied", "interviewing", "offer"].includes(job.tracking_status);
}

export function matchTone(job: JobDetail): "high" | "medium" | "low" | "pending" {
  if (typeof job.match?.score !== "number") return "pending";
  if (job.match.score >= 85) return "high";
  if (job.match.score >= 70) return "medium";
  return "low";
}

export function matchLabel(job: JobDetail): string {
  if (typeof job.match?.score !== "number") return "Rank pending";
  return `Rank ${job.match.score}${job.match.band ? ` • ${titleCaseLabel(job.match.band)}` : ""}`;
}

export function stagingSummary(job: JobDetail): string | null {
  if (job.tracking_status !== "staging" || typeof job.staging_age_hours !== "number") return null;
  if (job.staging_overdue) return `Overdue by ${Math.max(0, job.staging_age_hours - 48)}h`;
  return `Due in ${Math.max(0, 48 - job.staging_age_hours)}h`;
}

export function fitIconFor(state: FitState): string {
  if (state === "pass") return "✓";
  if (state === "fail") return "✕";
  return "•";
}

export function buildRecommendationGuidance(job: JobDetail): RecommendationGuidanceData {
  const mode = job.guidance_mode ?? (isStageNarrativeJob(job) ? "stage_narrative" : "evaluation");
  const title = job.guidance_title ?? (
    mode === "stage_narrative" ? `${titleCaseLabel(job.tracking_status)} stage` : recommendationLabel(job.recommendation)
  );
  const summary = job.guidance_summary ?? (
    mode === "stage_narrative"
      ? "Stay current on the active stage and the next touchpoint."
      : "Compare fit, urgency, friction, and confidence before acting."
  );
  const reasons = (job.guidance_reasons.length > 0 ? job.guidance_reasons : job.recommendation_reasons).slice(0, 4);
  const nextBestAction = job.next_best_action ?? (
    mode === "stage_narrative"
      ? "Keep the role moving."
      : job.recommendation
        ? `${recommendationLabel(job.recommendation)} it.`
        : "Wait for analysis to finish."
  );
  const healthLabel = job.health_label ?? (
    mode === "stage_narrative" ? titleCaseLabel(job.tracking_status) : recommendationLabel(job.recommendation)
  );
  return { mode, title, summary, reasons, nextBestAction, healthLabel };
}

export function buildJobFitAnalysis(
  job: JobDetail | null,
  profile: CandidateProfile | null,
  aliases: Record<string, string>,
  optimisticSkillAdds: Record<string, true> = {},
): JobFitAnalysis | null {
  if (!job?.enrichment) {
    return null;
  }

  const requiredSkills = cleanSkills(job.enrichment.required_skills);
  const preferredSkills = cleanSkills(job.enrichment.preferred_skills);
  const profileSkillSet = new Set([
    ...(profile?.skills ?? []).map((skill) => normalizeSkill(skill, aliases)),
    ...Object.keys(optimisticSkillAdds),
  ]);
  const normalizedProfileSkills = [...profileSkillSet];

  const requiredChecks: FitCheck[] = requiredSkills.map((skill, index) => {
    const matched = normalizedProfileSkills.some((profileSkill) => fuzzySkillsMatch(skill, profileSkill, aliases));
    return {
      label: skill,
      detail: matched ? "Matched from your profile" : "Missing from your profile",
      state: matched ? "pass" : "fail",
      impact: requiredImpact(index, requiredSkills.length),
    };
  });

  const preferredChecks: FitCheck[] = preferredSkills.map((skill) => {
    const matched = normalizedProfileSkills.some((profileSkill) => fuzzySkillsMatch(skill, profileSkill, aliases));
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

  const yearsMin = job.enrichment.years_exp_min;
  const candidateYears = profile?.years_experience;
  const experienceCheck: FitCheck = typeof yearsMin === "number" && typeof candidateYears === "number"
    ? {
        label: "Experience",
        detail: `${candidateYears} yrs vs min ${yearsMin} yrs`,
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
    requiredMet: matchedRequired.length,
    preferredMet: matchedPreferred.length,
    coreChecks,
    corePassCount,
    missingRequiredHighlights,
  };
}
