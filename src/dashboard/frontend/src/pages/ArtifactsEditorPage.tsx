import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import {
  acceptArtifactSuggestion,
  createArtifactVersion,
  deleteJobArtifact,
  exportArtifactPdf,
  generateArtifactSuggestions,
  generateStarterArtifacts,
  getArtifactSuggestions,
  getArtifactVersions,
  getJobArtifacts,
  rejectArtifactSuggestion,
} from "../api";
import type { ArtifactSuggestion, ArtifactSummary, ArtifactVersion } from "../types";
import { ThemedLoader } from "../components/ThemedLoader";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "../components/ui/accordion";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "../components/ui/breadcrumb";
import { Badge } from "../components/ui/badge";
import { Sheet, SheetClose, SheetContent, SheetHeader, SheetTitle } from "../components/ui/sheet";
import { Tabs, TabsList, TabsTrigger } from "../components/ui/tabs";
import { TooltipProvider } from "../components/ui/tooltip";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Separator } from "../components/ui/separator";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { Switch } from "../components/ui/switch";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { RichTextEditor } from "../components/RichTextEditor";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "../components/ui/alert-dialog";
import { toast } from "sonner";

type EditorMode = "form" | "json" | "ai";
const ARTIFACT_SPLIT_KEY = "artifact-editor-split-left";

type ResumeSectionId =
  | "basics"
  | "highlights"
  | "experience"
  | "education"
  | "skills";

const RESUME_SECTIONS: Array<{ id: ResumeSectionId; label: string }> = [
  { id: "basics", label: "Basics" },
  { id: "highlights", label: "Highlights" },
  { id: "experience", label: "Experience" },
  { id: "education", label: "Education" },
  { id: "skills", label: "Skills" },
];

const SECTION_ICONS: Record<ResumeSectionId, string> = {
  basics: "◌",
  highlights: "≡",
  experience: "◧",
  education: "◫",
  skills: "◍",
};

function decodeJobUrl(raw: string | undefined): string {
  if (!raw) return "";
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

function pretty(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}

function stableFingerprint(value: Record<string, unknown>): string {
  return JSON.stringify(value);
}

function parseJson(raw: string): Record<string, unknown> {
  const parsed = JSON.parse(raw);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("JSON must be an object");
  }
  return parsed as Record<string, unknown>;
}

function getContent(version: ArtifactVersion | null): Record<string, unknown> {
  if (!version || !version.content_json || typeof version.content_json !== "object") {
    return {};
  }
  return { ...(version.content_json as Record<string, unknown>) };
}

function normalizeResumeInput(content: Record<string, unknown>): Record<string, unknown> {
  const basics = (content.basics && typeof content.basics === "object") ? content.basics as Record<string, unknown> : {};
  const skillsRaw = Array.isArray(content.skills) ? content.skills : [];
  const skillNames = skillsRaw
    .map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object") return String((item as Record<string, unknown>).name ?? "");
      return "";
    })
    .map((value) => value.trim())
    .filter(Boolean);
  return {
    ...content,
    basics: {
      name: String(basics.name ?? ""),
      label: String(basics.label ?? ""),
      summary: String(basics.summary ?? ""),
      email: String(basics.email ?? ""),
      phone: String(basics.phone ?? ""),
      location: String(basics.location ?? ""),
    },
    skills: skillNames.map((name) => ({ name })),
  };
}

function normalizeCoverInput(content: Record<string, unknown>): Record<string, unknown> {
  const frontmatter = (content.frontmatter && typeof content.frontmatter === "object")
    ? content.frontmatter as Record<string, unknown>
    : {};
  const blocks = Array.isArray(content.blocks) ? content.blocks : [];
  return {
    frontmatter: {
      tone: String(frontmatter.tone ?? "neutral"),
      recipient: String(frontmatter.recipient ?? "Hiring Team"),
      subject: String(frontmatter.subject ?? "Cover Letter"),
    },
    blocks: blocks.map((block, index) => {
      if (!block || typeof block !== "object") {
        return { id: `p${index + 1}`, type: "paragraph", text: "" };
      }
      const row = block as Record<string, unknown>;
      return {
        id: String(row.id ?? `p${index + 1}`),
        type: String(row.type ?? "paragraph"),
        text: String(row.text ?? ""),
      };
    }),
  };
}

function sectionItemCount(section: ResumeSectionId, content: Record<string, unknown>): number | null {
  const toCount = (value: unknown): number => (Array.isArray(value) ? value.length : 0);
  switch (section) {
    case "experience":
      return toCount(content.work);
    case "education":
      return toCount(content.education);
    case "skills":
      return toCount(content.skills);
    default:
      return null;
  }
}

function ensureWorkEntries(content: Record<string, unknown>): Array<Record<string, unknown>> {
  if (!Array.isArray(content.work)) return [];
  return content.work
    .filter((entry): entry is Record<string, unknown> => Boolean(entry) && typeof entry === "object")
    .map((entry) => ({ ...entry }));
}

function ensureProfiles(basics: Record<string, unknown>): Array<Record<string, unknown>> {
  if (!Array.isArray(basics.profiles)) return [];
  return basics.profiles
    .filter((entry): entry is Record<string, unknown> => Boolean(entry) && typeof entry === "object")
    .map((entry) => ({ ...entry }));
}

function ensureCustomFields(basics: Record<string, unknown>): Array<Record<string, unknown>> {
  const raw = basics.customFields;
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((entry): entry is Record<string, unknown> => Boolean(entry) && typeof entry === "object")
    .map((entry) => ({ ...entry }));
}

function highlightsHtmlFromWork(entry: Record<string, unknown>): string {
  const existing = entry.highlights_html;
  if (typeof existing === "string" && existing.trim()) {
    return existing;
  }
  const bullets = Array.isArray(entry.highlights) ? entry.highlights.map((item) => String(item ?? "").trim()).filter(Boolean) : [];
  if (bullets.length === 0) {
    return "<ul><li></li></ul>";
  }
  return `<ul>${bullets.map((item) => `<li>${item.replaceAll("<", "&lt;").replaceAll(">", "&gt;")}</li>`).join("")}</ul>`;
}

function stripHtml(value: string): string {
  return value.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

function highlightsArrayFromHtml(html: string): string[] {
  const matches = [...html.matchAll(/<li[^>]*>([\s\S]*?)<\/li>/gi)];
  const items = matches.map((match) => stripHtml(String(match[1] ?? ""))).filter(Boolean);
  if (items.length > 0) return items;
  const text = stripHtml(html);
  return text ? [text] : [];
}

interface ExperienceDraft {
  index: number;
  company: string;
  position: string;
  location: string;
  period: string;
  website: string;
  showLinkInTitle: boolean;
  descriptionHtml: string;
}

function renderResumePreview(content: Record<string, unknown>) {
  const normalized = normalizeResumeInput(content);
  const basics = normalized.basics as Record<string, unknown>;
  const skills = Array.isArray(normalized.skills) ? normalized.skills : [];
  const work = Array.isArray(normalized.work) ? normalized.work : [];
  const education = Array.isArray(normalized.education) ? normalized.education : [];
  const projects = Array.isArray(normalized.projects) ? normalized.projects : [];
  const publications = Array.isArray(normalized.publications) ? normalized.publications : [];
  const skillLabels = skills
    .map((item) => {
      if (item && typeof item === "object") return String((item as Record<string, unknown>).name ?? "");
      return "";
    })
    .map((value) => value.trim())
    .filter(Boolean);
  const profiles = Array.isArray(basics.profiles) ? basics.profiles : [];
  const highlightsRaw = typeof normalized.highlights_html === "string" ? normalized.highlights_html : "";
  const highlights = highlightsArrayFromHtml(highlightsRaw);
  const summaryText = String(basics.summary || "").trim();
  const summaryBullets = summaryText
    ? summaryText.split(/\n+/g).map((item) => item.trim()).filter(Boolean)
    : [];

  const groupedSkills = (() => {
    const byCategory = normalized.skills_by_category;
    if (byCategory && typeof byCategory === "object" && !Array.isArray(byCategory)) {
      const rows = Object.entries(byCategory as Record<string, unknown>)
        .map(([key, value]) => {
          const items = Array.isArray(value) ? value.map((v) => String(v).trim()).filter(Boolean) : [];
          return { category: key, items };
        })
        .filter((row) => row.items.length > 0);
      if (rows.length > 0) return rows;
    }
    const buckets: Record<string, string[]> = {
      "Programming Languages": [],
      "Machine Learning": [],
      "Natural Language Processing": [],
      "Cloud Computing": [],
    };
    for (const skill of skillLabels) {
      const key = skill.toLowerCase();
      if (/(python|java|c\+\+|sql|bash|cuda|javascript|typescript|go|rust)/.test(key)) {
        buckets["Programming Languages"].push(skill);
      } else if (/(pytorch|tensorflow|scikit|xgboost|opencv|mlflow|weights|bias|cv|model)/.test(key)) {
        buckets["Machine Learning"].push(skill);
      } else if (/(langchain|rag|nlp|openai|crewai|prompt|agent|mcp|embedding|retrieval|llm)/.test(key)) {
        buckets["Natural Language Processing"].push(skill);
      } else {
        buckets["Cloud Computing"].push(skill);
      }
    }
    return Object.entries(buckets)
      .map(([category, items]) => ({ category, items }))
      .filter((row) => row.items.length > 0);
  })();

  return (
    <article className="artifact-paper-sheet">
      <header className="artifact-template-header">
        <h1>{String(basics.name || "Candidate Name")}</h1>
        <div className="artifact-template-contact">
          <span>{String(basics.phone || "")}</span>
          <span>{String(basics.email || "")}</span>
          <span>{String(basics.location || "")}</span>
        </div>
        {profiles.length > 0 && (
          <div className="artifact-template-links">
            {profiles.map((item, index) => {
              if (!item || typeof item !== "object") return null;
              const row = item as Record<string, unknown>;
              const label = String(row.network || row.label || "Link");
              const url = String(row.url || "");
              return <span key={`p-${index}`}>{label}{url ? "" : ""}</span>;
            })}
          </div>
        )}
      </header>
      <section className="artifact-template-section">
        <h2>Highlights</h2>
        <ul>
          {(highlights.length > 0 ? highlights : summaryBullets).map((item, index) => (
            <li key={`hl-${index}`}>{item}</li>
          ))}
        </ul>
      </section>
      <section className="artifact-template-section">
        <h2>Skills</h2>
        <div className="artifact-template-skills-grid">
          {groupedSkills.map((row) => (
            <div key={row.category} className="artifact-template-skill-row">
              <strong>{row.category}</strong>
              <span>{row.items.join(", ")}</span>
            </div>
          ))}
        </div>
      </section>
      <section className="artifact-template-section">
        <h2>Experience</h2>
        {work.length === 0 && <p className="artifact-paper-muted">No experience entries yet.</p>}
        {work.map((item, index) => {
          if (!item || typeof item !== "object") return null;
          const row = item as Record<string, unknown>;
          const bullets = Array.isArray(row.highlights) ? row.highlights.map((v) => String(v)) : [];
          const period = `${String(row.startDate ?? "")}${row.endDate ? ` - ${String(row.endDate)}` : ""}`;
          return (
            <div key={`work-${index}`} className="artifact-template-experience-item">
              <div className="artifact-template-experience-top">
                <strong>{String(row.position ?? "Role")}</strong>
                <span>{period}</span>
              </div>
              <div className="artifact-template-experience-sub">
                <span>{String(row.name ?? "Company")}</span>
                <em>{String(row.location ?? "")}</em>
              </div>
              {bullets.length > 0 ? (
                <ul>
                  {bullets.map((bullet, bulletIndex) => <li key={`work-b-${bulletIndex}`}>{String(bullet)}</li>)}
                </ul>
              ) : (
                <p className="artifact-paper-muted">No bullet points yet.</p>
              )}
            </div>
          );
        })}
      </section>
      {education.length > 0 && (
        <section className="artifact-template-section">
          <h2>Education</h2>
          {education.map((item, index) => {
            if (!item || typeof item !== "object") return null;
            const row = item as Record<string, unknown>;
            const degree = String(row.studyType ?? "");
            const field = String(row.area ?? "");
            const institution = String(row.institution ?? "");
            const period = `${String(row.startDate ?? "")}${row.endDate ? ` - ${String(row.endDate)}` : ""}`.trim();
            const courses = Array.isArray(row.courses) ? row.courses.map((entry) => String(entry ?? "")).filter(Boolean) : [];
            return (
              <div key={`edu-${index}`} className="artifact-template-experience-item">
                <div className="artifact-template-experience-top">
                  <strong>{[degree, field].filter(Boolean).join(" in ") || "Education"}</strong>
                  <span>{period}</span>
                </div>
                <div className="artifact-template-experience-sub">
                  <span>{institution}</span>
                  <em>{String(row.location ?? "")}</em>
                </div>
                {courses.length > 0 && <p className="artifact-template-inline-list">Coursework: {courses.join(", ")}</p>}
              </div>
            );
          })}
        </section>
      )}
      {projects.length > 0 && (
        <section className="artifact-template-section">
          <h2>Projects</h2>
          {projects.map((item, index) => {
            if (!item || typeof item !== "object") return null;
            const row = item as Record<string, unknown>;
            const highlights = Array.isArray(row.highlights) ? row.highlights.map((entry) => String(entry ?? "")).filter(Boolean) : [];
            return (
              <div key={`proj-${index}`} className="artifact-template-experience-item">
                <div className="artifact-template-experience-top">
                  <strong>{String(row.name ?? "Project")}</strong>
                  <span>{String(row.date ?? row.endDate ?? "")}</span>
                </div>
                {highlights.length > 0 && (
                  <ul>
                    {highlights.map((bullet, bulletIndex) => <li key={`proj-b-${bulletIndex}`}>{bullet}</li>)}
                  </ul>
                )}
              </div>
            );
          })}
        </section>
      )}
      {publications.length > 0 && (
        <section className="artifact-template-section">
          <h2>Publications</h2>
          <ul>
            {publications.map((item, index) => {
              if (!item || typeof item !== "object") return null;
              const row = item as Record<string, unknown>;
              const title = String(row.name ?? "").trim();
              const publisher = String(row.publisher ?? "").trim();
              const date = String(row.releaseDate ?? "").trim();
              return <li key={`pub-${index}`}>{[title, publisher, date].filter(Boolean).join(" - ")}</li>;
            })}
          </ul>
        </section>
      )}
      {skillLabels.length > 0 && groupedSkills.length === 0 && (
        <section className="artifact-template-section">
          <h2>Skills</h2>
          <p className="artifact-template-inline-list">{skillLabels.join(" • ")}</p>
        </section>
      )}
    </article>
  );
}

function renderCoverPreview(content: Record<string, unknown>) {
  const normalized = normalizeCoverInput(content);
  const frontmatter = normalized.frontmatter as Record<string, unknown>;
  const blocks = Array.isArray(normalized.blocks) ? normalized.blocks : [];
  return (
    <article className="artifact-paper-sheet">
      <header className="artifact-paper-header left">
        <h1>{String(frontmatter.subject || "Cover Letter")}</h1>
        <p>To: {String(frontmatter.recipient || "Hiring Team")}</p>
        <p>Tone: {String(frontmatter.tone || "neutral")}</p>
      </header>
      {blocks.map((block, index) => {
        if (!block || typeof block !== "object") return null;
        return <p key={`cl-${index}`}>{String((block as Record<string, unknown>).text ?? "")}</p>;
      })}
    </article>
  );
}

export function ArtifactsEditorPage() {
  const params = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const jobUrl = decodeJobUrl(params.jobUrl);
  const routeArtifactType = (params.artifactType ?? "resume").toLowerCase();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [mode, setMode] = useState<EditorMode>("form");
  const [artifacts, setArtifacts] = useState<ArtifactSummary[]>([]);
  const [activeArtifact, setActiveArtifact] = useState<ArtifactSummary | null>(null);
  const [versions, setVersions] = useState<ArtifactVersion[]>([]);
  const [suggestions, setSuggestions] = useState<ArtifactSuggestion[]>([]);
  const [jsonEditor, setJsonEditor] = useState("{}");
  const [aiPrompt, setAiPrompt] = useState("Tailor this artifact to the linked job description.");
  const [openSection, setOpenSection] = useState<ResumeSectionId | "">("basics");
  const [isReviewOpen, setIsReviewOpen] = useState(false);
  const [experienceDialogOpen, setExperienceDialogOpen] = useState(false);
  const [experienceDraft, setExperienceDraft] = useState<ExperienceDraft | null>(null);
  const [leaveDialogOpen, setLeaveDialogOpen] = useState(false);
  const [pendingLeaveHref, setPendingLeaveHref] = useState<string | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deletingArtifact, setDeletingArtifact] = useState(false);
  const [leftPanePercent, setLeftPanePercent] = useState<number>(() => {
    const raw = window.localStorage.getItem(ARTIFACT_SPLIT_KEY);
    if (!raw) return 47;
    const parsed = Number(raw);
    if (!Number.isFinite(parsed)) return 47;
    return Math.max(35, Math.min(62, parsed));
  });
  const [isResizing, setIsResizing] = useState(false);
  const [lastSavedFingerprint, setLastSavedFingerprint] = useState("{}");
  const mainGridRef = useRef<HTMLDivElement | null>(null);

  const activeVersion = versions[0] ?? activeArtifact?.active_version ?? null;
  const artifactType = activeArtifact?.artifact_type ?? routeArtifactType;
  const pendingSuggestions = useMemo(() => suggestions.filter((item) => item.state === "pending"), [suggestions]);

  const parsedEditor = useMemo(() => {
    try {
      return parseJson(jsonEditor);
    } catch {
      return null;
    }
  }, [jsonEditor]);
  const currentFingerprint = useMemo(() => (parsedEditor ? stableFingerprint(parsedEditor) : null), [parsedEditor]);
  const hasUnsavedChanges = Boolean(currentFingerprint && currentFingerprint !== lastSavedFingerprint);

  async function refreshAll(preferredType = routeArtifactType): Promise<void> {
    if (!jobUrl) return;
    setLoading(true);
    setError(null);
    try {
      const rows = await getJobArtifacts(jobUrl);
      setArtifacts(rows);
      const selected = rows.find((item) => item.artifact_type === preferredType) ?? rows[0] ?? null;
      setActiveArtifact(selected);
      if (selected) {
        const [history, queue] = await Promise.all([
          getArtifactVersions(selected.id, 200),
          getArtifactSuggestions(selected.id, false),
        ]);
        setVersions(history);
        setSuggestions(queue);
        const loadedContent = getContent(history[0] ?? selected.active_version);
        setJsonEditor(pretty(loadedContent));
        setLastSavedFingerprint(stableFingerprint(loadedContent));
        setSaveState("idle");
      } else {
        setVersions([]);
        setSuggestions([]);
        setJsonEditor("{}");
        setLastSavedFingerprint("{}");
        setSaveState("idle");
      }
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load artifacts");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refreshAll(routeArtifactType);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobUrl, routeArtifactType]);

  useEffect(() => {
    if (!isResizing) {
      return;
    }
    function onMove(event: MouseEvent): void {
      const host = mainGridRef.current;
      if (!host) return;
      const rect = host.getBoundingClientRect();
      const raw = ((event.clientX - rect.left) / rect.width) * 100;
      const bounded = Math.max(35, Math.min(62, raw));
      setLeftPanePercent(bounded);
    }
    function onUp(): void {
      setIsResizing(false);
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    document.body.classList.add("modal-open");
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      document.body.classList.remove("modal-open");
    };
  }, [isResizing]);

  useEffect(() => {
    window.localStorage.setItem(ARTIFACT_SPLIT_KEY, String(leftPanePercent));
  }, [leftPanePercent]);

  useEffect(() => {
    if (saveState === "saving") return;
    if (hasUnsavedChanges && saveState === "saved") {
      setSaveState("idle");
    }
  }, [hasUnsavedChanges, saveState]);

  async function saveDraft(content: Record<string, unknown>, options: { silent?: boolean } = {}): Promise<void> {
    if (!activeArtifact || !activeVersion) return;
    setSaving(true);
    setSaveState("saving");
    setError(null);
    setMessage(null);
    try {
      const created = await createArtifactVersion(activeArtifact.id, {
        label: "draft",
        content_json: content,
        meta_json: activeVersion.meta_json ?? {},
        base_version_id: activeVersion.id,
        created_by: "ui",
      });
      setVersions((current) => [created, ...current]);
      setActiveArtifact((current) => (current ? { ...current, active_version_id: created.id, active_version: created } : current));
      const savedContent = getContent(created);
      setJsonEditor(pretty(savedContent));
      setLastSavedFingerprint(stableFingerprint(savedContent));
      if (!options.silent) {
        setMessage(`Saved draft v${created.version}`);
      }
      setSaveState("saved");
      if (!options.silent) {
        toast.success(`Saved draft v${created.version}`);
      }
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Failed to save artifact");
      setSaveState("error");
      if (!options.silent) {
        toast.error(saveError instanceof Error ? saveError.message : "Failed to save artifact");
      }
    } finally {
      setSaving(false);
    }
  }

  async function handleSave(): Promise<void> {
    try {
      const parsed = parseJson(jsonEditor);
      await saveDraft(parsed, { silent: false });
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Invalid JSON content");
      setSaveState("error");
    }
  }

  async function handleGenerateSuggestions(): Promise<void> {
    if (!activeArtifact || !aiPrompt.trim()) return;
    setError(null);
    try {
      const created = await generateArtifactSuggestions(activeArtifact.id, {
        prompt: aiPrompt.trim(),
        max_suggestions: 6,
      });
      setSuggestions((current) => [...created, ...current]);
      setMessage(`Generated ${created.length} suggestion(s)`);
      toast.success(`Generated ${created.length} suggestion(s)`);
    } catch (generateError) {
      setError(generateError instanceof Error ? generateError.message : "Failed to generate suggestions");
      toast.error(generateError instanceof Error ? generateError.message : "Failed to generate suggestions");
    }
  }

  async function handleAcceptSuggestion(suggestionId: string): Promise<void> {
    try {
      const next = await acceptArtifactSuggestion(suggestionId, { created_by: "ui" });
      setVersions((current) => [next, ...current]);
      setActiveArtifact((current) => (current ? { ...current, active_version: next, active_version_id: next.id } : current));
      setSuggestions((current) => current.map((item) => (item.id === suggestionId ? { ...item, state: "accepted", resolved_at: new Date().toISOString() } : item)));
      setJsonEditor(pretty(getContent(next)));
      setMessage(`Accepted suggestion into draft v${next.version}`);
      toast.success(`Accepted suggestion into draft v${next.version}`);
    } catch (acceptError) {
      setError(acceptError instanceof Error ? acceptError.message : "Failed to accept suggestion");
      toast.error(acceptError instanceof Error ? acceptError.message : "Failed to accept suggestion");
    }
  }

  async function handleRejectSuggestion(suggestionId: string): Promise<void> {
    try {
      await rejectArtifactSuggestion(suggestionId);
      setSuggestions((current) => current.map((item) => (item.id === suggestionId ? { ...item, state: "rejected", resolved_at: new Date().toISOString() } : item)));
      toast.success("Suggestion rejected");
    } catch (rejectError) {
      setError(rejectError instanceof Error ? rejectError.message : "Failed to reject suggestion");
      toast.error(rejectError instanceof Error ? rejectError.message : "Failed to reject suggestion");
    }
  }

  async function handleExportPdf(): Promise<void> {
    if (!activeArtifact) return;
    try {
      const blob = await exportArtifactPdf(activeArtifact.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${activeArtifact.artifact_type}-v${activeVersion?.version ?? "latest"}.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      URL.revokeObjectURL(url);
      toast.success("PDF exported");
    } catch (exportError) {
      setError(exportError instanceof Error ? exportError.message : "Export failed");
      toast.error(exportError instanceof Error ? exportError.message : "Export failed");
    }
  }

  async function handleDeleteArtifact(): Promise<void> {
    if (!activeArtifact) return;
    setDeletingArtifact(true);
    setError(null);
    setMessage(null);
    try {
      const deleteKind = activeArtifact.artifact_type === "cover_letter" ? "cover_letter" : "resume";
      await deleteJobArtifact(jobUrl, deleteKind);
      const removedType = activeArtifact.artifact_type;
      const remaining = artifacts.filter((item) => item.id !== activeArtifact.id);
      setArtifacts(remaining);
      if (remaining.length === 0) {
        setActiveArtifact(null);
        setVersions([]);
        setSuggestions([]);
        setJsonEditor("{}");
        setLastSavedFingerprint("{}");
        setSaveState("idle");
      } else {
        const nextArtifact = remaining.find((item) => item.artifact_type === removedType) ?? remaining[0];
        setActiveArtifact(nextArtifact);
        const [history, queue] = await Promise.all([
          getArtifactVersions(nextArtifact.id, 200),
          getArtifactSuggestions(nextArtifact.id, false),
        ]);
        setVersions(history);
        setSuggestions(queue);
        const loadedContent = getContent(history[0] ?? nextArtifact.active_version);
        setJsonEditor(pretty(loadedContent));
        setLastSavedFingerprint(stableFingerprint(loadedContent));
        navigate(`/jobs/${encodeURIComponent(jobUrl)}/artifacts/${nextArtifact.artifact_type}`, { replace: true });
      }
      setMessage(`${removedType === "resume" ? "Resume" : "Cover letter"} deleted`);
      toast.success(`${removedType === "resume" ? "Resume" : "Cover letter"} deleted`);
      setDeleteDialogOpen(false);
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Failed to delete artifact");
      toast.error(deleteError instanceof Error ? deleteError.message : "Failed to delete artifact");
    } finally {
      setDeletingArtifact(false);
    }
  }

  function updateResumeContent(next: Record<string, unknown>): void {
    setJsonEditor(pretty(next));
  }

  function openExperienceEditor(index: number, entry: Record<string, unknown>): void {
    setExperienceDraft({
      index,
      company: String(entry.name ?? ""),
      position: String(entry.position ?? ""),
      location: String(entry.location ?? ""),
      period: `${String(entry.startDate ?? "")}${String(entry.endDate ?? "") ? ` - ${String(entry.endDate ?? "")}` : ""}`,
      website: String(entry.website ?? ""),
      showLinkInTitle: Boolean(entry.showLinkInTitle),
      descriptionHtml: highlightsHtmlFromWork(entry),
    });
    setExperienceDialogOpen(true);
  }

  function saveExperienceDraft(resumeContent: Record<string, unknown>, workEntries: Array<Record<string, unknown>>): void {
    if (!experienceDraft) return;
    const [startDateRaw, endDateRaw] = experienceDraft.period.includes(" - ")
      ? experienceDraft.period.split(" - ", 2)
      : experienceDraft.period.split("/", 2);
    const startDate = startDateRaw?.trim() ?? "";
    const endDate = endDateRaw?.trim() ?? "";
    const nextWork = workEntries.map((entry, index) => {
      if (index !== experienceDraft.index) return entry;
      return {
        ...entry,
        name: experienceDraft.company,
        position: experienceDraft.position,
        location: experienceDraft.location,
        startDate,
        endDate,
        website: experienceDraft.website,
        showLinkInTitle: experienceDraft.showLinkInTitle,
        highlights_html: experienceDraft.descriptionHtml,
        highlights: highlightsArrayFromHtml(experienceDraft.descriptionHtml),
      };
    });
    updateResumeContent({ ...resumeContent, work: nextWork });
    setExperienceDialogOpen(false);
    setExperienceDraft(null);
  }

  useEffect(() => {
    function onBeforeUnload(event: BeforeUnloadEvent): void {
      if (!hasUnsavedChanges) {
        return;
      }
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [hasUnsavedChanges]);

  useEffect(() => {
    function onDocumentClick(event: MouseEvent): void {
      if (!hasUnsavedChanges || leaveDialogOpen) return;
      const target = event.target as HTMLElement | null;
      const anchor = target?.closest("a[href]") as HTMLAnchorElement | null;
      if (!anchor) return;
      if (anchor.target === "_blank") return;
      let url: URL;
      try {
        url = new URL(anchor.href, window.location.href);
      } catch {
        return;
      }
      if (url.origin !== window.location.origin) return;
      const nextHref = `${url.pathname}${url.search}${url.hash}`;
      const currentHref = `${location.pathname}${location.search}${location.hash}`;
      if (nextHref === currentHref) return;
      event.preventDefault();
      setPendingLeaveHref(nextHref);
      setLeaveDialogOpen(true);
    }
    document.addEventListener("click", onDocumentClick, true);
    return () => document.removeEventListener("click", onDocumentClick, true);
  }, [hasUnsavedChanges, leaveDialogOpen, location.hash, location.pathname, location.search]);

  if (loading) {
    return <ThemedLoader label="Loading artifact editor" />;
  }

  const currentContent = parsedEditor ?? getContent(activeVersion);
  const resumeContent = normalizeResumeInput(currentContent);
  const coverContent = normalizeCoverInput(currentContent);
  const basics = resumeContent.basics as Record<string, unknown>;
  const workEntries = ensureWorkEntries(resumeContent);

  async function saveAndLeave(): Promise<void> {
    if (!pendingLeaveHref) return;
    if (!parsedEditor) {
      setSaveState("error");
      return;
    }
    await saveDraft(parsedEditor, { silent: false });
    setLeaveDialogOpen(false);
    navigate(pendingLeaveHref);
    setPendingLeaveHref(null);
  }

  function leaveWithoutSaving(): void {
    if (!pendingLeaveHref) return;
    setLeaveDialogOpen(false);
    navigate(pendingLeaveHref);
    setPendingLeaveHref(null);
  }

  return (
    <TooltipProvider delayDuration={120}>
      <section className="artifact-editor-page">
      <header className="artifact-editor-topbar">
        <div className="artifact-top-left">
          <Link to="/" className="ghost-btn compact" data-icon="←" style={{ textDecoration: "none" }}>
            ← Job Pipeline
          </Link>
          <Breadcrumb className="artifact-breadcrumb">
            <BreadcrumbList>
              <BreadcrumbItem>
                <Link to="/" className="ui-breadcrumb-link">Job Pipeline</Link>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
              <BreadcrumbItem>
                <BreadcrumbPage>Staging</BreadcrumbPage>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
              <BreadcrumbItem>
                <BreadcrumbPage>{artifactType === "resume" ? "Resume Editor" : "Cover Letter Editor"}</BreadcrumbPage>
              </BreadcrumbItem>
            </BreadcrumbList>
          </Breadcrumb>
        </div>
        <div className="artifact-top-right">
          <button
            type="button"
            className="ghost-btn compact danger"
            data-icon="🗑"
            onClick={() => setDeleteDialogOpen(true)}
            disabled={!activeArtifact || deletingArtifact}
          >
            {deletingArtifact ? "Deleting..." : "Delete"}
          </button>
          <button type="button" className="ghost-btn compact info" data-icon="↓" onClick={() => void handleExportPdf()} disabled={!activeArtifact}>Download PDF</button>
          <button type="button" className="primary-btn compact" data-icon="✓" onClick={() => void handleSave()} disabled={saving}>{saving ? "Saving..." : "Save"}</button>
          <span className="artifact-save-status">
            {saveState === "saving" && "Saving..."}
            {saveState === "saved" && "Saved"}
            {saveState === "error" && "Save failed"}
            {saveState === "idle" && (hasUnsavedChanges ? "Unsaved changes" : "Saved")}
          </span>
        </div>
      </header>

      <div className="artifact-toolbar-row">
        <div className="artifact-switcher segmented">
          {(["resume", "cover_letter"] as const).map((kind) => {
            const label = kind === "resume" ? "Resume" : "Cover Letter";
            return (
              <Link
                key={kind}
                to={`/jobs/${encodeURIComponent(jobUrl)}/artifacts/${kind}`}
                className={`segmented-btn ${artifactType === kind ? "active" : ""}`}
                onClick={() => setActiveArtifact(artifacts.find((item) => item.artifact_type === kind) ?? null)}
              >
                {label}
              </Link>
            );
          })}
        </div>

        <Tabs value={mode} onValueChange={(value) => setMode(value as EditorMode)}>
          <TabsList className="artifact-mode-tabs segmented">
            <TabsTrigger className="segmented-btn" value="json">{"</> JSON"}</TabsTrigger>
            <TabsTrigger className="segmented-btn" value="form">Form</TabsTrigger>
            <TabsTrigger className="segmented-btn" value="ai">AI Chat</TabsTrigger>
          </TabsList>
        </Tabs>

        <button type="button" className="artifact-review-pill" onClick={() => setIsReviewOpen(true)}>
          AI Suggestions ({pendingSuggestions.length})
        </button>
      </div>

      <div
        ref={mainGridRef}
        className="artifact-main-grid"
        style={{ gridTemplateColumns: `${leftPanePercent}% 8px minmax(320px, 1fr)` }}
      >
        <section className="artifact-editor-pane">
          {!activeArtifact ? (
            <div className="artifact-form-card">
              <p className="artifact-empty-note">No artifacts exist for this job yet.</p>
              <button
                type="button"
                className="primary-btn compact"
                data-icon="+"
                onClick={() => void refreshAll(routeArtifactType)}
              >
                Refresh
              </button>
              <button
                type="button"
                className="ghost-btn compact"
                data-icon="⚙"
                onClick={async () => {
                  if (!jobUrl) return;
                  try {
                    setLoading(true);
                    await generateStarterArtifacts(jobUrl, false);
                    await refreshAll(routeArtifactType);
                  } catch (starterError) {
                    setError(starterError instanceof Error ? starterError.message : "Failed to generate starter artifacts");
                    toast.error(starterError instanceof Error ? starterError.message : "Failed to generate starter artifacts");
                  } finally {
                    setLoading(false);
                  }
                }}
              >
                Generate starter drafts
              </button>
            </div>
          ) : null}
          {activeArtifact && mode === "form" && artifactType === "resume" && (
            <Accordion
              type="single"
              collapsible
              value={openSection}
              onValueChange={(value) => setOpenSection((value || "") as ResumeSectionId | "")}
              className="artifact-accordion-list"
            >
              {RESUME_SECTIONS.map((section) => (
                <AccordionItem key={section.id} value={section.id} className="artifact-accordion-item">
                  <AccordionTrigger className="artifact-accordion-btn artifact-nav-trigger">
                    <span className="artifact-accordion-title">
                      <span className="artifact-section-icon" aria-hidden="true">{SECTION_ICONS[section.id]}</span>
                      <span>{section.label}</span>
                      {typeof sectionItemCount(section.id, resumeContent) === "number" && (
                        <span className="artifact-section-count">({sectionItemCount(section.id, resumeContent)})</span>
                      )}
                    </span>
                  </AccordionTrigger>
                  <AccordionContent className="artifact-accordion-panel">
                    {section.id === "basics" && (
                      <Card className="artifact-dark-card">
                        <CardContent className="artifact-form-card">
                          <div className="artifact-field-stack">
                            <Label>Name</Label>
                            <Input
                              value={String(basics.name ?? "")}
                              onChange={(event) => updateResumeContent({ ...resumeContent, basics: { ...basics, name: event.target.value } })}
                            />
                            <Label>Headline</Label>
                            <Input
                              value={String(basics.label ?? "")}
                              onChange={(event) => updateResumeContent({ ...resumeContent, basics: { ...basics, label: event.target.value } })}
                            />
                            <Label>Email</Label>
                            <Input
                              value={String(basics.email ?? "")}
                              onChange={(event) => updateResumeContent({ ...resumeContent, basics: { ...basics, email: event.target.value } })}
                            />
                            <Label>Phone</Label>
                            <Input
                              value={String(basics.phone ?? "")}
                              onChange={(event) => updateResumeContent({ ...resumeContent, basics: { ...basics, phone: event.target.value } })}
                            />
                            <Label>Location</Label>
                            <Input
                              value={String(basics.location ?? "")}
                              onChange={(event) => updateResumeContent({ ...resumeContent, basics: { ...basics, location: event.target.value } })}
                            />
                            <Label>Website</Label>
                            <Input
                              value={String(basics.website ?? "")}
                              onChange={(event) => updateResumeContent({ ...resumeContent, basics: { ...basics, website: event.target.value } })}
                            />
                            {ensureProfiles(basics).map((profile, index) => (
                              <div key={`profile-link-${index}`} className="artifact-inline-link-row">
                                <Input
                                  value={String(profile.url ?? "")}
                                  onChange={(event) => {
                                    const profiles = ensureProfiles(basics).map((item, itemIndex) => (
                                      itemIndex === index ? { ...item, url: event.target.value } : item
                                    ));
                                    updateResumeContent({ ...resumeContent, basics: { ...basics, profiles } });
                                  }}
                                />
                                <button
                                  type="button"
                                  className="ghost-btn compact danger"
                                  data-icon="✕"
                                  onClick={() => {
                                    const profiles = ensureProfiles(basics).filter((_, itemIndex) => itemIndex !== index);
                                    updateResumeContent({ ...resumeContent, basics: { ...basics, profiles } });
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
                                const profiles = [...ensureProfiles(basics), { network: "link", url: "https://" }];
                                updateResumeContent({ ...resumeContent, basics: { ...basics, profiles } });
                              }}
                            >
                              Add link
                            </button>
                            <Separator />
                            {ensureCustomFields(basics).map((field, index) => (
                              <div key={`custom-field-${index}`} className="artifact-custom-row">
                                <Input
                                  value={String(field.label ?? "")}
                                  placeholder="Label"
                                  onChange={(event) => {
                                    const customFields = ensureCustomFields(basics).map((item, itemIndex) => (
                                      itemIndex === index ? { ...item, label: event.target.value } : item
                                    ));
                                    updateResumeContent({ ...resumeContent, basics: { ...basics, customFields } });
                                  }}
                                />
                                <Input
                                  value={String(field.value ?? "")}
                                  placeholder="Value"
                                  onChange={(event) => {
                                    const customFields = ensureCustomFields(basics).map((item, itemIndex) => (
                                      itemIndex === index ? { ...item, value: event.target.value } : item
                                    ));
                                    updateResumeContent({ ...resumeContent, basics: { ...basics, customFields } });
                                  }}
                                />
                              </div>
                            ))}
                            <button
                              type="button"
                              className="ghost-btn compact"
                              data-icon="+"
                              onClick={() => {
                                const customFields = [...ensureCustomFields(basics), { label: "", value: "" }];
                                updateResumeContent({ ...resumeContent, basics: { ...basics, customFields } });
                              }}
                            >
                              Add a custom field
                            </button>
                          </div>
                        </CardContent>
                      </Card>
                    )}
                    {section.id === "highlights" && (
                      <Card className="artifact-dark-card">
                        <CardHeader>
                          <CardTitle>Highlights</CardTitle>
                        </CardHeader>
                        <CardContent className="artifact-form-card">
                          <RichTextEditor
                            value={typeof resumeContent.highlights_html === "string" ? resumeContent.highlights_html : "<ul><li></li></ul>"}
                            onChange={(html) => updateResumeContent({ ...resumeContent, highlights_html: html })}
                            minHeight={220}
                          />
                        </CardContent>
                      </Card>
                    )}
                    {section.id === "experience" && (
                      <Card className="artifact-dark-card">
                        <CardContent className="artifact-form-card">
                          <div className="artifact-experience-list">
                            {workEntries.map((entry, index) => (
                              <button
                                type="button"
                                key={`exp-${index}`}
                                className="artifact-experience-item"
                                onClick={() => openExperienceEditor(index, entry)}
                              >
                                <strong>{String(entry.name ?? "Company")}</strong>
                                <span>{String(entry.position ?? "Position")}</span>
                              </button>
                            ))}
                          </div>
                          <button
                            type="button"
                            className="ghost-btn compact primary"
                            data-icon="+"
                            onClick={() => {
                              const nextWork = [...workEntries, { name: "Company", position: "Position", highlights: [""], highlights_html: "<ul><li></li></ul>" }];
                              updateResumeContent({ ...resumeContent, work: nextWork });
                              openExperienceEditor(nextWork.length - 1, nextWork[nextWork.length - 1] as Record<string, unknown>);
                            }}
                          >
                            Add a new experience
                          </button>
                        </CardContent>
                      </Card>
                    )}
                    {section.id === "skills" && (
                      <Card className="artifact-dark-card">
                        <CardContent className="artifact-form-card">
                          <Label>Skills (one per line)</Label>
                          <Textarea
                            rows={8}
                            value={(Array.isArray(resumeContent.skills) ? resumeContent.skills : [])
                              .map((item) => {
                                if (!item || typeof item !== "object") return "";
                                return String((item as Record<string, unknown>).name ?? "");
                              })
                              .filter(Boolean)
                              .join("\n")}
                            onChange={(event) => {
                              const nextSkills = event.target.value
                                .split(/\n+/g)
                                .map((value) => value.trim())
                                .filter(Boolean)
                                .map((name) => ({ name }));
                              updateResumeContent({ ...resumeContent, skills: nextSkills });
                            }}
                          />
                        </CardContent>
                      </Card>
                    )}
                    {!["basics", "highlights", "experience", "skills"].includes(section.id) && (
                      <div className="artifact-form-card">
                        <p className="artifact-empty-note">{section.label} editor will be expanded in the next iteration. Use JSON mode for full control today.</p>
                      </div>
                    )}
                  </AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          )}

          {activeArtifact && mode === "form" && artifactType === "cover_letter" && (
            <div className="artifact-form-card">
              <div className="artifact-field-grid">
                <label>
                  <span>Recipient</span>
                  <input
                    type="text"
                    value={String((coverContent.frontmatter as Record<string, unknown>).recipient ?? "")}
                    onChange={(event) => {
                      const frontmatter = {
                        ...(coverContent.frontmatter as Record<string, unknown>),
                        recipient: event.target.value,
                      };
                      const next = { ...coverContent, frontmatter };
                      setJsonEditor(pretty(next));
                    }}
                  />
                </label>
                <label>
                  <span>Tone</span>
                  <input
                    type="text"
                    value={String((coverContent.frontmatter as Record<string, unknown>).tone ?? "")}
                    onChange={(event) => {
                      const frontmatter = {
                        ...(coverContent.frontmatter as Record<string, unknown>),
                        tone: event.target.value,
                      };
                      const next = { ...coverContent, frontmatter };
                      setJsonEditor(pretty(next));
                    }}
                  />
                </label>
              </div>
              {Array.isArray(coverContent.blocks) && coverContent.blocks.map((block, index) => {
                if (!block || typeof block !== "object") return null;
                const row = block as Record<string, unknown>;
                return (
                  <label key={String(row.id ?? index)}>
                    <span>Paragraph {index + 1}</span>
                    <textarea
                      rows={4}
                      value={String(row.text ?? "")}
                      onChange={(event) => {
                        const blocks = [...(coverContent.blocks as Array<Record<string, unknown>>)].map((item, itemIndex) => (
                          itemIndex === index ? { ...item, text: event.target.value } : item
                        ));
                        const next = { ...coverContent, blocks };
                        setJsonEditor(pretty(next));
                      }}
                    />
                  </label>
                );
              })}
            </div>
          )}

          {activeArtifact && mode === "json" && (
            <textarea
              className="artifact-code-editor"
              value={jsonEditor}
              onChange={(event) => setJsonEditor(event.target.value)}
              rows={26}
            />
          )}

          {activeArtifact && mode === "ai" && (
            <div className="artifact-form-card">
              <label>
                <span>Prompt</span>
                <textarea value={aiPrompt} rows={8} onChange={(event) => setAiPrompt(event.target.value)} />
              </label>
              <button type="button" className="primary-btn compact artifact-ai-action-btn" data-icon="✨" onClick={() => void handleGenerateSuggestions()}>
                Tailor
              </button>
            </div>
          )}
        </section>

        <div
          role="separator"
          aria-orientation="vertical"
          className={`artifact-divider ${isResizing ? "dragging" : ""}`}
          onMouseDown={() => setIsResizing(true)}
        />

        <section className="artifact-preview-pane">
          <header className="artifact-preview-head">
            <div>
              <h3>Preview</h3>
              <p>Template: Classic</p>
            </div>
            <div className="artifact-preview-actions">
              <Badge>Fit width</Badge>
              <Badge>Page breaks</Badge>
            </div>
          </header>
          <div className="artifact-paper-canvas">
            {artifactType === "resume" ? renderResumePreview(currentContent) : renderCoverPreview(currentContent)}
          </div>
        </section>
      </div>

      <Dialog
        open={experienceDialogOpen}
        onOpenChange={(open) => {
          setExperienceDialogOpen(open);
          if (!open) {
            setExperienceDraft(null);
          }
        }}
      >
        <DialogContent className="artifact-experience-dialog">
          <DialogHeader>
            <DialogTitle>
              <span className="artifact-dialog-title-icon" aria-hidden="true">✎</span>
              Update an existing experience
            </DialogTitle>
          </DialogHeader>
          {experienceDraft && (
            <div className="artifact-form-card">
              <div className="artifact-field-grid">
                <div>
                  <Label>Company</Label>
                  <Input value={experienceDraft.company} onChange={(event) => setExperienceDraft((current) => current ? { ...current, company: event.target.value } : current)} />
                </div>
                <div>
                  <Label>Position</Label>
                  <Input value={experienceDraft.position} onChange={(event) => setExperienceDraft((current) => current ? { ...current, position: event.target.value } : current)} />
                </div>
                <div>
                  <Label>Location</Label>
                  <Input value={experienceDraft.location} onChange={(event) => setExperienceDraft((current) => current ? { ...current, location: event.target.value } : current)} />
                </div>
                <div>
                  <Label>Period</Label>
                  <Input value={experienceDraft.period} onChange={(event) => setExperienceDraft((current) => current ? { ...current, period: event.target.value } : current)} />
                </div>
              </div>
              <div>
                <Label>Website</Label>
                <Input value={experienceDraft.website} onChange={(event) => setExperienceDraft((current) => current ? { ...current, website: event.target.value } : current)} />
              </div>
              <div className="artifact-switch-row">
                <Switch
                  checked={experienceDraft.showLinkInTitle}
                  onCheckedChange={(checked) => setExperienceDraft((current) => current ? { ...current, showLinkInTitle: checked } : current)}
                />
                <Label>Show link in title</Label>
              </div>
              <div>
                <Label>Description</Label>
                <RichTextEditor
                  value={experienceDraft.descriptionHtml}
                  onChange={(html) => setExperienceDraft((current) => current ? { ...current, descriptionHtml: html } : current)}
                  minHeight={210}
                />
              </div>
            </div>
          )}
          <DialogFooter>
            <button type="button" className="ghost-btn compact" data-icon="×" onClick={() => setExperienceDialogOpen(false)}>Cancel</button>
            <button
              type="button"
              className="primary-btn compact"
              data-icon="✓"
              onClick={() => saveExperienceDraft(resumeContent, workEntries)}
            >
              Save Changes
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {message && <p className="artifact-message-ok">{message}</p>}
      {error && <p className="artifact-message-err">{error}</p>}

      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {artifactType === "resume" ? "resume" : "cover letter"}?</AlertDialogTitle>
            <AlertDialogDescription>
              This deletes only the current {artifactType === "resume" ? "resume" : "cover letter"} artifact, including its versions and suggestions.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="ghost-btn compact" data-icon="×">Cancel</AlertDialogCancel>
            <button
              type="button"
              className="ghost-btn compact danger"
              data-icon="🗑"
              onClick={() => void handleDeleteArtifact()}
              disabled={deletingArtifact || !activeArtifact}
            >
              {deletingArtifact ? "Deleting..." : "Delete"}
            </button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={leaveDialogOpen} onOpenChange={setLeaveDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Unsaved changes</AlertDialogTitle>
            <AlertDialogDescription>
              You have unsaved edits in this artifact. Do you want to save before leaving this page?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="ghost-btn compact" data-icon="×">Stay</AlertDialogCancel>
            <button type="button" className="ghost-btn compact warn" data-icon="↗" onClick={leaveWithoutSaving}>Leave without saving</button>
            <button type="button" className="primary-btn compact" data-icon="✓" onClick={() => void saveAndLeave()} disabled={saving || !parsedEditor}>
              {saving ? "Saving..." : "Save & Leave"}
            </button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Sheet open={isReviewOpen} onOpenChange={setIsReviewOpen}>
        <SheetContent side="right" className="artifact-review-drawer">
          <SheetHeader className="artifact-review-head">
            <SheetTitle>AI Suggestions</SheetTitle>
            <SheetClose asChild>
              <button type="button" className="ghost-btn compact" data-icon="×">Close</button>
            </SheetClose>
          </SheetHeader>
          {suggestions.length === 0 ? (
            <p className="artifact-empty-note">No suggestions yet.</p>
          ) : (
            <div className="artifact-suggestion-list">
              {suggestions.map((item) => (
                <article key={item.id} className="artifact-suggestion-card">
                  <div>
                    <p className="artifact-suggestion-title">{item.summary ?? "Suggestion"}</p>
                    <p className="artifact-suggestion-meta">{item.target_path ?? "(no target path)"} • {item.state}</p>
                  </div>
                  {item.state === "pending" && (
                    <div className="artifact-suggestion-actions">
                      <button type="button" className="ghost-btn compact success" data-icon="✓" onClick={() => void handleAcceptSuggestion(item.id)}>Accept</button>
                      <button type="button" className="ghost-btn compact danger" data-icon="✕" onClick={() => void handleRejectSuggestion(item.id)}>Reject</button>
                    </div>
                  )}
                </article>
              ))}
            </div>
          )}
        </SheetContent>
      </Sheet>
    </section>
    </TooltipProvider>
  );
}
