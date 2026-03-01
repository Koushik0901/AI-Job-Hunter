import { useEffect, useMemo, useState } from "react";
import { getProfile, getResumeProfile, importResumeProfileFromFile, putProfile, putResumeProfile } from "../api";
import { ScoreRecomputeStatus } from "../components/ScoreRecomputeStatus";
import { ThemedLoader } from "../components/ThemedLoader";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "../components/ui/accordion";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "../components/ui/alert-dialog";
import { Button } from "../components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { FileUpload } from "../components/ui/file-upload";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import type { CandidateProfile, ResumeProfile } from "../types";
import { toast } from "sonner";

type SaveState = "idle" | "dirty" | "saving" | "saved" | "error";

const EMPTY_PROFILE: CandidateProfile = {
  years_experience: 0,
  skills: [],
  target_role_families: [],
  requires_visa_sponsorship: false,
  education: [],
  degree: null,
  degree_field: null,
  updated_at: null,
};

const EMPTY_RESUME_PROFILE: ResumeProfile = {
  baseline_resume_json: {},
  template_id: "classic",
  updated_at: null,
};

function normalizeTags(values: string[]): string[] {
  const seen = new Set<string>();
  const output: string[] = [];
  for (const raw of values) {
    const cleaned = raw.trim();
    if (!cleaned) continue;
    const key = cleaned.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    output.push(cleaned);
  }
  return output;
}

function normalizeEducation(values: CandidateProfile["education"]): CandidateProfile["education"] {
  const seen = new Set<string>();
  const output: CandidateProfile["education"] = [];
  for (const raw of values) {
    const degree = (raw.degree ?? "").trim();
    const field = (raw.field ?? "").trim() || null;
    if (!degree) continue;
    const key = `${degree.toLowerCase()}::${(field ?? "").toLowerCase()}`;
    if (seen.has(key)) continue;
    seen.add(key);
    output.push({ degree, field });
  }
  return output;
}

function profileFingerprint(profile: CandidateProfile): string {
  const comparable = {
    years_experience: Math.max(0, Number(profile.years_experience || 0)),
    requires_visa_sponsorship: Boolean(profile.requires_visa_sponsorship),
    education: normalizeEducation(profile.education ?? []),
    degree: (profile.degree ?? "").trim(),
    degree_field: (profile.degree_field ?? "").trim(),
    skills: normalizeTags(profile.skills),
    target_role_families: normalizeTags(profile.target_role_families),
  };
  return JSON.stringify(comparable);
}

function pushToken(setter: (updater: (current: string[]) => string[]) => void, token: string): void {
  const parsed = token
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

  if (parsed.length === 0) return;

  setter((current) => normalizeTags([...current, ...parsed]));
}

function asObject(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  return value as Record<string, unknown>;
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asRecordArray(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    .map((item) => ({ ...item }));
}

function stripHtml(value: string): string {
  return value.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

function highlightsArrayFromHtml(html: string): string[] {
  const matches = [...html.matchAll(/<li[^>]*>([\s\S]*?)<\/li>/gi)];
  const items = matches.map((match) => stripHtml(String(match[1] ?? ""))).filter(Boolean);
  if (items.length > 0) return items;
  const fallback = stripHtml(html);
  return fallback ? [fallback] : [];
}

function highlightsHtmlFromLines(lines: string[]): string {
  const normalized = lines.map((line) => line.trim()).filter(Boolean);
  if (normalized.length === 0) {
    return "<ul><li></li></ul>";
  }
  return `<ul>${normalized.map((line) => `<li>${line.replaceAll("<", "&lt;").replaceAll(">", "&gt;")}</li>`).join("")}</ul>`;
}

export function ProfilePage() {
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"scoring" | "resume">("scoring");

  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [resumeSaveError, setResumeSaveError] = useState<string | null>(null);
  const [resumeSaveState, setResumeSaveState] = useState<SaveState>("idle");

  const [original, setOriginal] = useState<CandidateProfile>(EMPTY_PROFILE);
  const [draft, setDraft] = useState<CandidateProfile>(EMPTY_PROFILE);
  const [resumeOriginal, setResumeOriginal] = useState<ResumeProfile>(EMPTY_RESUME_PROFILE);
  const [resumeDraft, setResumeDraft] = useState<ResumeProfile>(EMPTY_RESUME_PROFILE);
  const [resumeJsonInput, setResumeJsonInput] = useState("{}");
  const [resumeEditorMode, setResumeEditorMode] = useState<"form" | "json">("form");
  const [resumeUploading, setResumeUploading] = useState(false);
  const [resumeImportDialogOpen, setResumeImportDialogOpen] = useState(false);
  const [resumeImportPreviewOpen, setResumeImportPreviewOpen] = useState(false);
  const [resumeImportSourcePath, setResumeImportSourcePath] = useState("");
  const [resumeImportPreviewJson, setResumeImportPreviewJson] = useState<Record<string, unknown> | null>(null);
  const [skillsInput, setSkillsInput] = useState("");
  const [familiesInput, setFamiliesInput] = useState("");
  const [educationDegreeInput, setEducationDegreeInput] = useState("");
  const [educationFieldInput, setEducationFieldInput] = useState("");

  const isDirty = useMemo(() => profileFingerprint(draft) !== profileFingerprint(original), [draft, original]);
  const parsedResumeJson = useMemo(() => {
    try {
      const parsed = JSON.parse(resumeJsonInput);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        return { value: null as Record<string, unknown> | null, error: "Baseline resume JSON must be an object." };
      }
      return { value: parsed as Record<string, unknown>, error: null as string | null };
    } catch {
      return { value: null as Record<string, unknown> | null, error: "Baseline resume JSON is invalid." };
    }
  }, [resumeJsonInput]);
  const resumeFingerprint = useMemo(() => {
    return JSON.stringify({
      template_id: (resumeDraft.template_id || "classic").trim() || "classic",
      baseline_resume_json: parsedResumeJson.value ?? resumeDraft.baseline_resume_json ?? {},
    });
  }, [parsedResumeJson.value, resumeDraft.baseline_resume_json, resumeDraft.template_id]);
  const resumeOriginalFingerprint = useMemo(() => {
    return JSON.stringify({
      template_id: (resumeOriginal.template_id || "classic").trim() || "classic",
      baseline_resume_json: resumeOriginal.baseline_resume_json ?? {},
    });
  }, [resumeOriginal.baseline_resume_json, resumeOriginal.template_id]);
  const isResumeDirty = resumeFingerprint !== resumeOriginalFingerprint;
  const resumeBaseline = useMemo<Record<string, unknown>>(() => (
    parsedResumeJson.value ?? (resumeDraft.baseline_resume_json ?? {})
  ), [parsedResumeJson.value, resumeDraft.baseline_resume_json]);
  const resumeBasics = useMemo(() => asObject(resumeBaseline.basics), [resumeBaseline.basics]);
  const resumeProfiles = useMemo(() => asRecordArray(resumeBasics.profiles), [resumeBasics.profiles]);
  const resumeWork = useMemo(() => asRecordArray(resumeBaseline.work), [resumeBaseline.work]);
  const resumeEducationEntries = useMemo(() => asRecordArray(resumeBaseline.education), [resumeBaseline.education]);
  const resumeProjects = useMemo(() => asRecordArray(resumeBaseline.projects), [resumeBaseline.projects]);
  const resumePublications = useMemo(() => asRecordArray(resumeBaseline.publications), [resumeBaseline.publications]);
  const resumeHighlightsLines = useMemo(() => {
    const highlightsHtml = asString(resumeBaseline.highlights_html);
    return highlightsArrayFromHtml(highlightsHtml);
  }, [resumeBaseline.highlights_html]);
  const resumeSkillsByCategory = useMemo(() => {
    const raw = resumeBaseline.skills_by_category;
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
      return {} as Record<string, string[]>;
    }
    const result: Record<string, string[]> = {};
    for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
      const items = Array.isArray(value) ? value.map((item) => String(item ?? "").trim()).filter(Boolean) : [];
      if (items.length > 0 || key.trim()) {
        result[key] = items;
      }
    }
    return result;
  }, [resumeBaseline.skills_by_category]);
  const resumeImportPreviewSummary = useMemo(() => {
    const value = resumeImportPreviewJson;
    if (!value) {
      return null;
    }
    const basics = asObject(value.basics);
    const skillCategories = asObject(value.skills_by_category);
    const skillsFlat = asRecordArray(value.skills).length;
    return {
      name: asString(basics.name),
      highlights: highlightsArrayFromHtml(asString(value.highlights_html)).length,
      skillCategoryCount: Object.keys(skillCategories).length,
      skillsFlat,
      work: asRecordArray(value.work).length,
      education: asRecordArray(value.education).length,
      projects: asRecordArray(value.projects).length,
      publications: asRecordArray(value.publications).length,
      basics,
      skillCategoryMap: skillCategories,
      workEntries: asRecordArray(value.work),
      educationEntries: asRecordArray(value.education),
      projectEntries: asRecordArray(value.projects),
      publicationEntries: asRecordArray(value.publications),
    };
  }, [resumeImportPreviewJson]);

  useEffect(() => {
    if (saveState !== "saving") {
      setSaveState(isDirty ? "dirty" : "idle");
    }
  }, [isDirty, saveState]);

  useEffect(() => {
    if (resumeSaveState !== "saving") {
      setResumeSaveState(isResumeDirty ? "dirty" : "idle");
    }
  }, [isResumeDirty, resumeSaveState]);

  useEffect(() => {
    let cancelled = false;

    async function loadProfile(): Promise<void> {
      setLoading(true);
      setLoadError(null);
      try {
        const [profile, resume] = await Promise.all([getProfile(), getResumeProfile()]);
        if (cancelled) return;
        setOriginal(profile);
        setDraft(profile);
        setResumeOriginal(resume);
        setResumeDraft(resume);
        setResumeJsonInput(JSON.stringify(resume.baseline_resume_json ?? {}, null, 2));
      } catch (error) {
        if (cancelled) return;
        setLoadError(error instanceof Error ? error.message : "Failed to load profile");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void loadProfile();
    return () => {
      cancelled = true;
    };
  }, []);

  async function saveProfile(): Promise<void> {
    setSaveError(null);
    setSaveState("saving");

    const payload: CandidateProfile = {
      ...draft,
      years_experience: Math.max(0, Math.min(60, Number(draft.years_experience || 0))),
      education: normalizeEducation(draft.education ?? []),
      degree: normalizeEducation(draft.education ?? [])[0]?.degree ?? null,
      degree_field: normalizeEducation(draft.education ?? [])[0]?.field ?? null,
      skills: normalizeTags(draft.skills),
      target_role_families: normalizeTags(draft.target_role_families),
      updated_at: draft.updated_at,
    };

    try {
      const saved = await putProfile(payload);
      setOriginal(saved);
      setDraft(saved);
      setSkillsInput("");
      setFamiliesInput("");
      setEducationDegreeInput("");
      setEducationFieldInput("");
      setSaveState("saved");
      toast.success("Profile saved");
      window.setTimeout(() => {
        setSaveState("idle");
      }, 1400);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "Failed to save profile");
      setSaveState("error");
      toast.error(error instanceof Error ? error.message : "Failed to save profile");
    }
  }

  async function saveResumeProfile(): Promise<void> {
    setResumeSaveError(null);
    setResumeSaveState("saving");
    if (parsedResumeJson.error || !parsedResumeJson.value) {
      setResumeSaveError(parsedResumeJson.error ?? "Invalid baseline resume JSON.");
      setResumeSaveState("error");
      return;
    }
    const payload: ResumeProfile = {
      baseline_resume_json: parsedResumeJson.value,
      template_id: (resumeDraft.template_id || "classic").trim() || "classic",
      updated_at: resumeDraft.updated_at,
    };
    try {
      const saved = await putResumeProfile(payload);
      setResumeOriginal(saved);
      setResumeDraft(saved);
      setResumeJsonInput(JSON.stringify(saved.baseline_resume_json ?? {}, null, 2));
      setResumeSaveState("saved");
      toast.success("Resume profile saved");
      window.setTimeout(() => {
        setResumeSaveState("idle");
      }, 1400);
    } catch (error) {
      setResumeSaveError(error instanceof Error ? error.message : "Failed to save resume profile");
      setResumeSaveState("error");
      toast.error(error instanceof Error ? error.message : "Failed to save resume profile");
    }
  }

  async function importUploadedResume(file: File): Promise<void> {
    setResumeUploading(true);
    setResumeImportDialogOpen(false);
    setResumeSaveError(null);
    try {
      const imported = await importResumeProfileFromFile(file);
      setResumeImportSourcePath(imported.source_path || file.name);
      setResumeImportPreviewJson(imported.baseline_resume_json);
      setResumeImportPreviewOpen(true);
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Failed to import uploaded resume";
      setResumeSaveError(detail);
      toast.error(detail);
    } finally {
      setResumeUploading(false);
    }
  }

  function applyResumeImportPreview(): void {
    if (!resumeImportPreviewJson) return;
    updateResumeBaseline(resumeImportPreviewJson);
    setResumeSaveState("dirty");
    setResumeImportPreviewOpen(false);
    toast.success("Imported resume data applied to draft");
  }

  function closeResumeImportPreview(): void {
    setResumeImportPreviewOpen(false);
    setResumeImportPreviewJson(null);
    setResumeImportSourcePath("");
  }

  function saveLabel(): string {
    switch (saveState) {
      case "saving":
        return "Saving...";
      case "saved":
        return "Saved";
      case "error":
        return "Retry Save";
      default:
        return "Save Profile";
    }
  }

  function resumeSaveLabel(): string {
    switch (resumeSaveState) {
      case "saving":
        return "Saving...";
      case "saved":
        return "Saved";
      case "error":
        return "Retry Save";
      default:
        return "Save Resume Profile";
    }
  }

  function updateResumeBaseline(next: Record<string, unknown>): void {
    setResumeDraft((current) => ({ ...current, baseline_resume_json: next }));
    setResumeJsonInput(JSON.stringify(next, null, 2));
  }

  function setResumeBasicsField(field: string, value: unknown): void {
    updateResumeBaseline({
      ...resumeBaseline,
      basics: {
        ...resumeBasics,
        [field]: value,
      },
    });
  }

  if (loading) {
    return (
      <div className="page-loader-shell">
        <ThemedLoader label="Loading profile" />
      </div>
    );
  }

  function addEducation(): void {
    const degree = educationDegreeInput.trim();
    const field = educationFieldInput.trim() || null;
    if (!degree) return;
    setDraft((current) => ({
      ...current,
      education: normalizeEducation([...(current.education ?? []), { degree, field }]),
    }));
    setEducationDegreeInput("");
    setEducationFieldInput("");
  }

  const currentSaveState = activeTab === "scoring" ? saveState : resumeSaveState;
  const currentSaveLabel = activeTab === "scoring" ? saveLabel() : resumeSaveLabel();
  const currentSaveDisabled = activeTab === "scoring"
    ? !isDirty || saveState === "saving"
    : !isResumeDirty || resumeSaveState === "saving" || Boolean(parsedResumeJson.error);

  function renderResumeBaselineForm() {
    function setArrayItem(key: string, index: number, nextValue: Record<string, unknown>): void {
      const rows = asRecordArray(resumeBaseline[key]);
      const next = rows.map((item, itemIndex) => (itemIndex === index ? nextValue : item));
      updateResumeBaseline({ ...resumeBaseline, [key]: next });
    }

    function removeArrayItem(key: string, index: number): void {
      const rows = asRecordArray(resumeBaseline[key]);
      const next = rows.filter((_, itemIndex) => itemIndex !== index);
      updateResumeBaseline({ ...resumeBaseline, [key]: next });
    }

    function appendArrayItem(key: string, nextValue: Record<string, unknown>): void {
      const rows = asRecordArray(resumeBaseline[key]);
      updateResumeBaseline({ ...resumeBaseline, [key]: [...rows, nextValue] });
    }

    return (
      <div className="resume-profile-form-stack">
        <section className="resume-profile-section">
          <h4>Basics</h4>
          <div className="profile-form-grid">
            <label>
              <span>Name</span>
              <input type="text" value={asString(resumeBasics.name)} onChange={(event) => setResumeBasicsField("name", event.target.value)} />
            </label>
            <label>
              <span>Headline</span>
              <input type="text" value={asString(resumeBasics.label)} onChange={(event) => setResumeBasicsField("label", event.target.value)} />
            </label>
            <label>
              <span>Email</span>
              <input type="text" value={asString(resumeBasics.email)} onChange={(event) => setResumeBasicsField("email", event.target.value)} />
            </label>
            <label>
              <span>Phone</span>
              <input type="text" value={asString(resumeBasics.phone)} onChange={(event) => setResumeBasicsField("phone", event.target.value)} />
            </label>
            <label>
              <span>Location</span>
              <input type="text" value={asString(resumeBasics.location)} onChange={(event) => setResumeBasicsField("location", event.target.value)} />
            </label>
            <label>
              <span>Website</span>
              <input type="text" value={asString(resumeBasics.website)} onChange={(event) => setResumeBasicsField("website", event.target.value)} />
            </label>
          </div>
          <div className="resume-inline-list">
            <p className="board-note">Links</p>
            {resumeProfiles.map((profile, index) => (
              <div key={`resume-profile-link-${index}`} className="resume-two-col-row">
                <input
                  type="text"
                  placeholder="Label (LinkedIn, Github, Portfolio)"
                  value={asString(profile.network || profile.label)}
                  onChange={(event) => {
                    const next = resumeProfiles.map((item, itemIndex) => (
                      itemIndex === index ? { ...item, network: event.target.value, label: event.target.value } : item
                    ));
                    setResumeBasicsField("profiles", next);
                  }}
                />
                <input
                  type="text"
                  placeholder="URL"
                  value={asString(profile.url)}
                  onChange={(event) => {
                    const next = resumeProfiles.map((item, itemIndex) => (
                      itemIndex === index ? { ...item, url: event.target.value } : item
                    ));
                    setResumeBasicsField("profiles", next);
                  }}
                />
                <button
                  type="button"
                  className="ghost-btn compact danger"
                  data-icon="✕"
                  onClick={() => {
                    const next = resumeProfiles.filter((_, itemIndex) => itemIndex !== index);
                    setResumeBasicsField("profiles", next);
                  }}
                >
                  Remove
                </button>
              </div>
            ))}
            <button
              type="button"
              className="ghost-btn compact"
              data-icon="+"
              onClick={() => setResumeBasicsField("profiles", [...resumeProfiles, { network: "", label: "", url: "" }])}
            >
              Add Link
            </button>
          </div>
        </section>

        <section className="resume-profile-section">
          <h4>Highlights</h4>
          <label className="full-width">
            <span>One highlight per line</span>
            <textarea
              rows={6}
              value={resumeHighlightsLines.join("\n")}
              onChange={(event) => {
                const lines = event.target.value.split(/\n+/g);
                updateResumeBaseline({
                  ...resumeBaseline,
                  highlights_html: highlightsHtmlFromLines(lines),
                });
              }}
            />
          </label>
        </section>

        <section className="resume-profile-section">
          <h4>Skills by Category</h4>
          <div className="resume-inline-list">
            {Object.entries(resumeSkillsByCategory).map(([category, items], index) => (
              <div key={`skills-category-${index}`} className="resume-two-col-row">
                <input
                  type="text"
                  placeholder="Category"
                  value={category}
                  onChange={(event) => {
                    const next: Record<string, string[]> = {};
                    Object.entries(resumeSkillsByCategory).forEach(([existingKey, existingItems]) => {
                      if (existingKey !== category) next[existingKey] = existingItems;
                    });
                    next[event.target.value] = items;
                    updateResumeBaseline({ ...resumeBaseline, skills_by_category: next });
                  }}
                />
                <textarea
                  rows={2}
                  placeholder="Comma-separated skills"
                  value={items.join(", ")}
                  onChange={(event) => {
                    const next: Record<string, string[]> = { ...resumeSkillsByCategory };
                    next[category] = event.target.value.split(",").map((item) => item.trim()).filter(Boolean);
                    updateResumeBaseline({ ...resumeBaseline, skills_by_category: next });
                  }}
                />
                <button
                  type="button"
                  className="ghost-btn compact danger"
                  data-icon="✕"
                  onClick={() => {
                    const next: Record<string, string[]> = {};
                    Object.entries(resumeSkillsByCategory).forEach(([key, value]) => {
                      if (key !== category) next[key] = value;
                    });
                    updateResumeBaseline({ ...resumeBaseline, skills_by_category: next });
                  }}
                >
                  Remove
                </button>
              </div>
            ))}
            <button
              type="button"
              className="ghost-btn compact"
              data-icon="+"
              onClick={() => {
                const next: Record<string, string[]> = { ...resumeSkillsByCategory };
                let name = "New Category";
                let i = 2;
                while (Object.prototype.hasOwnProperty.call(next, name)) {
                  name = `New Category ${i}`;
                  i += 1;
                }
                next[name] = [];
                updateResumeBaseline({ ...resumeBaseline, skills_by_category: next });
              }}
            >
              Add Category
            </button>
          </div>
        </section>

        <section className="resume-profile-section">
          <h4>Experience</h4>
          <div className="resume-inline-list">
            {resumeWork.map((entry, index) => (
              <article key={`resume-work-${index}`} className="resume-subcard">
                <div className="profile-form-grid">
                  <label>
                    <span>Company</span>
                    <input type="text" value={asString(entry.name)} onChange={(event) => setArrayItem("work", index, { ...entry, name: event.target.value })} />
                  </label>
                  <label>
                    <span>Position</span>
                    <input type="text" value={asString(entry.position)} onChange={(event) => setArrayItem("work", index, { ...entry, position: event.target.value })} />
                  </label>
                  <label>
                    <span>Location</span>
                    <input type="text" value={asString(entry.location)} onChange={(event) => setArrayItem("work", index, { ...entry, location: event.target.value })} />
                  </label>
                  <label>
                    <span>Website</span>
                    <input type="text" value={asString(entry.website)} onChange={(event) => setArrayItem("work", index, { ...entry, website: event.target.value })} />
                  </label>
                  <label>
                    <span>Start Date</span>
                    <input type="text" value={asString(entry.startDate)} onChange={(event) => setArrayItem("work", index, { ...entry, startDate: event.target.value })} />
                  </label>
                  <label>
                    <span>End Date</span>
                    <input type="text" value={asString(entry.endDate)} onChange={(event) => setArrayItem("work", index, { ...entry, endDate: event.target.value })} />
                  </label>
                  <label className="full-width">
                    <span>Highlights (one per line)</span>
                    <textarea
                      rows={5}
                      value={(Array.isArray(entry.highlights) ? entry.highlights : []).map((item) => String(item ?? "")).join("\n")}
                      onChange={(event) => {
                        const lines = event.target.value.split(/\n+/g).map((item) => item.trim()).filter(Boolean);
                        setArrayItem("work", index, { ...entry, highlights: lines, highlights_html: highlightsHtmlFromLines(lines) });
                      }}
                    />
                  </label>
                </div>
                <button type="button" className="ghost-btn compact danger" data-icon="✕" onClick={() => removeArrayItem("work", index)}>
                  Remove Experience
                </button>
              </article>
            ))}
            <button type="button" className="ghost-btn compact" data-icon="+" onClick={() => appendArrayItem("work", { name: "", position: "", location: "", startDate: "", endDate: "", website: "", highlights: [] })}>
              Add Experience
            </button>
          </div>
        </section>

        <section className="resume-profile-section">
          <h4>Education</h4>
          <div className="resume-inline-list">
            {resumeEducationEntries.map((entry, index) => (
              <article key={`resume-edu-${index}`} className="resume-subcard">
                <div className="profile-form-grid">
                  <label>
                    <span>Institution</span>
                    <input type="text" value={asString(entry.institution)} onChange={(event) => setArrayItem("education", index, { ...entry, institution: event.target.value })} />
                  </label>
                  <label>
                    <span>Degree</span>
                    <input type="text" value={asString(entry.studyType)} onChange={(event) => setArrayItem("education", index, { ...entry, studyType: event.target.value })} />
                  </label>
                  <label>
                    <span>Field</span>
                    <input type="text" value={asString(entry.area)} onChange={(event) => setArrayItem("education", index, { ...entry, area: event.target.value })} />
                  </label>
                  <label>
                    <span>Location</span>
                    <input type="text" value={asString(entry.location)} onChange={(event) => setArrayItem("education", index, { ...entry, location: event.target.value })} />
                  </label>
                  <label>
                    <span>Start Date</span>
                    <input type="text" value={asString(entry.startDate)} onChange={(event) => setArrayItem("education", index, { ...entry, startDate: event.target.value })} />
                  </label>
                  <label>
                    <span>End Date</span>
                    <input type="text" value={asString(entry.endDate)} onChange={(event) => setArrayItem("education", index, { ...entry, endDate: event.target.value })} />
                  </label>
                  <label className="full-width">
                    <span>Coursework (one per line)</span>
                    <textarea
                      rows={4}
                      value={(Array.isArray(entry.courses) ? entry.courses : []).map((item) => String(item ?? "")).join("\n")}
                      onChange={(event) => {
                        const courses = event.target.value.split(/\n+/g).map((item) => item.trim()).filter(Boolean);
                        setArrayItem("education", index, { ...entry, courses });
                      }}
                    />
                  </label>
                </div>
                <button type="button" className="ghost-btn compact danger" data-icon="✕" onClick={() => removeArrayItem("education", index)}>
                  Remove Education
                </button>
              </article>
            ))}
            <button type="button" className="ghost-btn compact" data-icon="+" onClick={() => appendArrayItem("education", { institution: "", studyType: "", area: "", location: "", startDate: "", endDate: "", courses: [] })}>
              Add Education
            </button>
          </div>
        </section>

        <section className="resume-profile-section">
          <h4>Projects</h4>
          <div className="resume-inline-list">
            {resumeProjects.map((entry, index) => (
              <article key={`resume-project-${index}`} className="resume-subcard">
                <div className="profile-form-grid">
                  <label>
                    <span>Name</span>
                    <input type="text" value={asString(entry.name)} onChange={(event) => setArrayItem("projects", index, { ...entry, name: event.target.value })} />
                  </label>
                  <label>
                    <span>Date</span>
                    <input type="text" value={asString(entry.date || entry.endDate)} onChange={(event) => setArrayItem("projects", index, { ...entry, date: event.target.value, endDate: event.target.value })} />
                  </label>
                  <label className="full-width">
                    <span>URL</span>
                    <input type="text" value={asString(entry.url || entry.website)} onChange={(event) => setArrayItem("projects", index, { ...entry, url: event.target.value, website: event.target.value })} />
                  </label>
                  <label className="full-width">
                    <span>Highlights (one per line)</span>
                    <textarea
                      rows={5}
                      value={(Array.isArray(entry.highlights) ? entry.highlights : []).map((item) => String(item ?? "")).join("\n")}
                      onChange={(event) => {
                        const lines = event.target.value.split(/\n+/g).map((item) => item.trim()).filter(Boolean);
                        setArrayItem("projects", index, { ...entry, highlights: lines });
                      }}
                    />
                  </label>
                </div>
                <button type="button" className="ghost-btn compact danger" data-icon="✕" onClick={() => removeArrayItem("projects", index)}>
                  Remove Project
                </button>
              </article>
            ))}
            <button type="button" className="ghost-btn compact" data-icon="+" onClick={() => appendArrayItem("projects", { name: "", date: "", url: "", highlights: [] })}>
              Add Project
            </button>
          </div>
        </section>

        <section className="resume-profile-section">
          <h4>Publications</h4>
          <div className="resume-inline-list">
            {resumePublications.map((entry, index) => (
              <article key={`resume-publication-${index}`} className="resume-subcard">
                <div className="profile-form-grid">
                  <label className="full-width">
                    <span>Title</span>
                    <input type="text" value={asString(entry.name)} onChange={(event) => setArrayItem("publications", index, { ...entry, name: event.target.value })} />
                  </label>
                  <label>
                    <span>Publisher</span>
                    <input type="text" value={asString(entry.publisher)} onChange={(event) => setArrayItem("publications", index, { ...entry, publisher: event.target.value })} />
                  </label>
                  <label>
                    <span>Release Date</span>
                    <input type="text" value={asString(entry.releaseDate)} onChange={(event) => setArrayItem("publications", index, { ...entry, releaseDate: event.target.value })} />
                  </label>
                  <label className="full-width">
                    <span>URL</span>
                    <input type="text" value={asString(entry.url)} onChange={(event) => setArrayItem("publications", index, { ...entry, url: event.target.value })} />
                  </label>
                </div>
                <button type="button" className="ghost-btn compact danger" data-icon="✕" onClick={() => removeArrayItem("publications", index)}>
                  Remove Publication
                </button>
              </article>
            ))}
            <button type="button" className="ghost-btn compact" data-icon="+" onClick={() => appendArrayItem("publications", { name: "", publisher: "", releaseDate: "", url: "" })}>
              Add Publication
            </button>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="profile-page">
      <section className="profile-hero">
        <div>
          <p className="page-kicker">Candidate Configuration</p>
          <h2>{activeTab === "scoring" ? "Scoring Profile" : "Resume Profile"}</h2>
          <p className="profile-hero-copy">
            {activeTab === "scoring"
              ? "Keep this profile up to date so match ranking reflects your real background and goals."
              : "Resume profile is separate from scoring and is only editable from this page."}
          </p>
        </div>
        <div className="profile-hero-actions">
          <span className={`save-badge ${currentSaveState}`}>{currentSaveState === "dirty" ? "Unsaved changes" : currentSaveState === "saved" ? "All changes saved" : currentSaveState === "saving" ? "Saving" : "Ready"}</span>
          <button
            type="button"
            className="primary-btn"
            data-icon="✓"
            disabled={currentSaveDisabled}
            onClick={() => {
              if (activeTab === "scoring") {
                void saveProfile();
                return;
              }
              void saveResumeProfile();
            }}
          >
            {currentSaveLabel}
          </button>
        </div>
      </section>

      {loadError && <div className="error-banner">{loadError}</div>}
      {saveError && <div className="error-banner">{saveError}</div>}
      {resumeSaveError && <div className="error-banner">{resumeSaveError}</div>}

      <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as "scoring" | "resume")}>
        <TabsList className="profile-tabs-list">
          <TabsTrigger className="profile-tabs-trigger" value="scoring">Scoring Profile</TabsTrigger>
          <TabsTrigger className="profile-tabs-trigger" value="resume">Resume Profile</TabsTrigger>
        </TabsList>

        <TabsContent value="scoring">
          <ScoreRecomputeStatus />
          <section className="profile-grid">
            <section className="profile-card">
              <h3>Core Inputs</h3>
              <div className="profile-form-grid">
                <label>
                  <span>Years Experience</span>
                  <input
                    type="number"
                    min={0}
                    max={60}
                    value={draft.years_experience}
                    onChange={(event) => setDraft((current) => ({ ...current, years_experience: Number(event.target.value || 0) }))}
                  />
                </label>
              </div>
            </section>

            <section className="profile-card">
              <h3>Education</h3>
              <div className="token-editor">
                <div className="token-list" role="list" aria-label="Education list">
                  {(draft.education ?? []).map((entry, index) => (
                    <span className="token-chip" role="listitem" key={`${entry.degree}-${entry.field ?? "none"}-${index}`}>
                      {entry.degree}{entry.field ? ` (${entry.field})` : ""}
                      <button
                        type="button"
                        aria-label={`Remove ${entry.degree}`}
                        onClick={() => {
                          setDraft((current) => ({
                            ...current,
                            education: current.education.filter((_, itemIndex) => itemIndex !== index),
                          }));
                        }}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
                <div className="profile-form-grid">
                  <label>
                    <span>Degree</span>
                    <input
                      type="text"
                      value={educationDegreeInput}
                      onChange={(event) => setEducationDegreeInput(event.target.value)}
                    />
                  </label>
                  <label>
                    <span>Field</span>
                    <input
                      type="text"
                      value={educationFieldInput}
                      onChange={(event) => setEducationFieldInput(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          addEducation();
                        }
                      }}
                    />
                  </label>
                </div>
                <button type="button" className="ghost-btn" data-icon="+" onClick={addEducation}>
                  Add Education
                </button>
              </div>
            </section>

            <section className="profile-card">
              <h3>Target Role Families</h3>
              <div className="token-editor">
                <div className="token-list" role="list" aria-label="Target role families">
                  {draft.target_role_families.map((family) => (
                    <span className="token-chip" role="listitem" key={family}>
                      {family}
                      <button
                        type="button"
                        aria-label={`Remove ${family}`}
                        onClick={() => {
                          setDraft((current) => ({
                            ...current,
                            target_role_families: current.target_role_families.filter((item) => item !== family),
                          }));
                        }}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
                <input
                  type="text"
                  value={familiesInput}
                  onChange={(event) => setFamiliesInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === ",") {
                      event.preventDefault();
                      pushToken((updater) => {
                        setDraft((current) => ({ ...current, target_role_families: updater(current.target_role_families) }));
                      }, familiesInput);
                      setFamiliesInput("");
                    }
                  }}
                  onBlur={() => {
                    pushToken((updater) => {
                      setDraft((current) => ({ ...current, target_role_families: updater(current.target_role_families) }));
                    }, familiesInput);
                    setFamiliesInput("");
                  }}
                />
              </div>
            </section>

            <section className="profile-card profile-card-wide">
              <h3>Skill Inventory</h3>
              <div className="token-editor">
                <div className="token-list" role="list" aria-label="Skills list">
                  {draft.skills.map((skill) => (
                    <span className="token-chip token-chip-accent" role="listitem" key={skill}>
                      {skill}
                      <button
                        type="button"
                        aria-label={`Remove ${skill}`}
                        onClick={() => {
                          setDraft((current) => ({
                            ...current,
                            skills: current.skills.filter((item) => item !== skill),
                          }));
                        }}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
                <input
                  type="text"
                  value={skillsInput}
                  onChange={(event) => setSkillsInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === ",") {
                      event.preventDefault();
                      pushToken((updater) => {
                        setDraft((current) => ({ ...current, skills: updater(current.skills) }));
                      }, skillsInput);
                      setSkillsInput("");
                    }
                  }}
                  onBlur={() => {
                    pushToken((updater) => {
                      setDraft((current) => ({ ...current, skills: updater(current.skills) }));
                    }, skillsInput);
                    setSkillsInput("");
                  }}
                />
              </div>
            </section>
          </section>

          <section className="profile-summary profile-card">
            <h3>Live Summary</h3>
            <p>
              <strong>{draft.years_experience}</strong> years experience,
              education entries: <strong>{draft.education.length}</strong>,
              <strong> {draft.skills.length}</strong> skills,
              <strong> {draft.target_role_families.length}</strong> role families.
            </p>
            <p className="board-note">Last updated: {draft.updated_at ?? "-"}</p>
          </section>
        </TabsContent>

        <TabsContent value="resume">
          <section className="profile-grid">
            <section className="profile-card">
              <h3>Resume Defaults</h3>
              <div className="profile-form-grid">
                <label>
                  <span>Template ID</span>
                  <input
                    type="text"
                    value={resumeDraft.template_id}
                    onChange={(event) => setResumeDraft((current) => ({ ...current, template_id: event.target.value }))}
                  />
                </label>
              </div>
              <p className="board-note">
                This profile is only used as a resume baseline and is never auto-modified by skill actions.
              </p>
              <Button
                type="button"
                variant="default"
                size="compact"
                className="info"
                data-icon="↑"
                disabled={resumeUploading}
                onClick={() => setResumeImportDialogOpen(true)}
              >
                {resumeUploading ? "Importing..." : "Import From Resume"}
              </Button>
              <Tabs value={resumeEditorMode} onValueChange={(value) => setResumeEditorMode(value as "form" | "json")}>
                <TabsList className="profile-tabs-list">
                  <TabsTrigger className="profile-tabs-trigger" value="form">Form</TabsTrigger>
                  <TabsTrigger className="profile-tabs-trigger" value="json">JSON</TabsTrigger>
                </TabsList>
              </Tabs>
            </section>

            <section className="profile-card profile-card-wide">
              {resumeEditorMode === "form" ? (
                <>
                  <h3>Baseline Resume Form</h3>
                  {renderResumeBaselineForm()}
                </>
              ) : (
                <>
                  <h3>Baseline Resume JSON</h3>
                  <textarea
                    className="artifact-code-editor"
                    value={resumeJsonInput}
                    rows={20}
                    onChange={(event) => setResumeJsonInput(event.target.value)}
                  />
                  {parsedResumeJson.error && <p className="artifact-message-err">{parsedResumeJson.error}</p>}
                </>
              )}
            </section>
          </section>
          <section className="profile-summary profile-card">
            <h3>Resume Profile Summary</h3>
            <p className="board-note">Last updated: {resumeDraft.updated_at ?? "-"}</p>
          </section>
        </TabsContent>
      </Tabs>

      <Dialog open={resumeImportPreviewOpen} onOpenChange={(open) => {
        if (!open) {
          closeResumeImportPreview();
        } else {
          setResumeImportPreviewOpen(true);
        }
      }}>
        <DialogContent className="resume-import-dialog">
          <DialogHeader>
            <DialogTitle>Preview Imported Resume Data</DialogTitle>
            <p className="board-note">Source: {resumeImportSourcePath || "uploaded PDF"}</p>
          </DialogHeader>
          {resumeImportPreviewSummary ? (
            <div className="resume-import-preview">
              <div className="resume-import-stats">
                <span className="soft-chip">Highlights: {resumeImportPreviewSummary.highlights}</span>
                <span className="soft-chip">Skill Categories: {resumeImportPreviewSummary.skillCategoryCount}</span>
                <span className="soft-chip">Skills: {resumeImportPreviewSummary.skillsFlat}</span>
                <span className="soft-chip">Experience: {resumeImportPreviewSummary.work}</span>
                <span className="soft-chip">Education: {resumeImportPreviewSummary.education}</span>
                <span className="soft-chip">Projects: {resumeImportPreviewSummary.projects}</span>
                <span className="soft-chip">Publications: {resumeImportPreviewSummary.publications}</span>
              </div>
              <Accordion type="single" collapsible className="resume-import-accordion">
                <AccordionItem value="basics">
                  <AccordionTrigger>Basics</AccordionTrigger>
                  <AccordionContent>
                    <div className="resume-import-grid">
                      <p><strong>Name:</strong> {resumeImportPreviewSummary.name || "-"}</p>
                      <p><strong>Email:</strong> {asString(resumeImportPreviewSummary.basics.email) || "-"}</p>
                      <p><strong>Phone:</strong> {asString(resumeImportPreviewSummary.basics.phone) || "-"}</p>
                      <p><strong>Location:</strong> {asString(resumeImportPreviewSummary.basics.location) || "-"}</p>
                    </div>
                  </AccordionContent>
                </AccordionItem>
                <AccordionItem value="skills">
                  <AccordionTrigger>Skills</AccordionTrigger>
                  <AccordionContent>
                    <div className="resume-import-grid">
                      {Object.entries(resumeImportPreviewSummary.skillCategoryMap).map(([category, values]) => (
                        <p key={category}>
                          <strong>{category}:</strong> {Array.isArray(values) ? values.join(", ") : ""}
                        </p>
                      ))}
                    </div>
                  </AccordionContent>
                </AccordionItem>
                <AccordionItem value="experience">
                  <AccordionTrigger>Experience</AccordionTrigger>
                  <AccordionContent>
                    <div className="resume-import-grid">
                      {resumeImportPreviewSummary.workEntries.map((entry, index) => (
                        <p key={`preview-work-${index}`}>
                          <strong>{asString(entry.position) || "Role"}</strong> at {asString(entry.name) || "Company"} ({asString(entry.startDate)} - {asString(entry.endDate)})
                        </p>
                      ))}
                    </div>
                  </AccordionContent>
                </AccordionItem>
                <AccordionItem value="education">
                  <AccordionTrigger>Education</AccordionTrigger>
                  <AccordionContent>
                    <div className="resume-import-grid">
                      {resumeImportPreviewSummary.educationEntries.map((entry, index) => (
                        <p key={`preview-edu-${index}`}>
                          <strong>{asString(entry.studyType)}</strong> at {asString(entry.institution)} ({asString(entry.startDate)} - {asString(entry.endDate)})
                        </p>
                      ))}
                    </div>
                  </AccordionContent>
                </AccordionItem>
                <AccordionItem value="projects">
                  <AccordionTrigger>Projects</AccordionTrigger>
                  <AccordionContent>
                    <div className="resume-import-grid">
                      {resumeImportPreviewSummary.projectEntries.map((entry, index) => (
                        <p key={`preview-project-${index}`}>
                          <strong>{asString(entry.name)}</strong> ({asString(entry.date || entry.endDate)})
                        </p>
                      ))}
                    </div>
                  </AccordionContent>
                </AccordionItem>
                <AccordionItem value="publications">
                  <AccordionTrigger>Publications</AccordionTrigger>
                  <AccordionContent>
                    <div className="resume-import-grid">
                      {resumeImportPreviewSummary.publicationEntries.map((entry, index) => (
                        <p key={`preview-publication-${index}`}>{asString(entry.name)}</p>
                      ))}
                    </div>
                  </AccordionContent>
                </AccordionItem>
              </Accordion>
            </div>
          ) : (
            <p className="board-note">No preview data available.</p>
          )}
          <DialogFooter>
            <Button type="button" variant="default" size="compact" onClick={closeResumeImportPreview}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              size="compact"
              data-icon="✓"
              onClick={applyResumeImportPreview}
              disabled={!resumeImportPreviewSummary}
            >
              Apply To Draft
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={resumeImportDialogOpen} onOpenChange={setResumeImportDialogOpen}>
        <AlertDialogContent className="resume-import-alert">
          <AlertDialogHeader>
            <AlertDialogTitle>Import From Resume</AlertDialogTitle>
            <AlertDialogDescription>
              Upload a resume PDF. We will parse it and show a preview before applying any changes.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <FileUpload
            disabled={resumeUploading}
            title={resumeUploading ? "Importing..." : "Import From Resume"}
            hint="Drop a PDF here or click Choose PDF"
            onFileSelect={(file) => importUploadedResume(file)}
          />
          <AlertDialogFooter>
            <AlertDialogCancel className="ghost-btn compact" data-icon="↗" disabled={resumeUploading}>
              Cancel
            </AlertDialogCancel>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
