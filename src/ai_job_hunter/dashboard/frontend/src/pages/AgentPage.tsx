import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { memo, useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArrowUpRight, FileText, MessageSquareText, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";
import {
  addToQueue,
  agentChat,
  getArtifactPdfUrl,
  getJobArtifacts,
  getJobDetail,
  getJobsWithParams,
  getOperation,
  getQueue,
  listBaseDocuments,
  patchTracking,
  prefetchJobArtifacts,
  prefetchJobDetail,
  prefetchQueue,
  removeFromQueue,
  streamArtifact,
  subscribeToDashboardEvents,
  subscribeToOperation,
  updateArtifact,
  updateQueueItem,
} from "../api";
import { ArtifactEditor } from "../components/ArtifactEditor";
import { Button } from "../components/ui/button";
import type {
  AgentMessage,
  AgentOutputKind,
  AgentSkillInvocation,
  BaseDocument,
  JobArtifact,
  QueueItem,
  WorkspaceOperation,
} from "../types";

const pageEase = [0.22, 0.84, 0.24, 1] as [number, number, number, number];

const sectionRevealVariants = {
  hidden: { opacity: 0, y: 18 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.42, ease: pageEase },
  },
};

const clusterRevealVariants = {
  hidden: { opacity: 0, y: 12 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.32, ease: pageEase },
  },
};

const staggerRevealVariants = {
  hidden: {},
  visible: {
    transition: {
      staggerChildren: 0.05,
      delayChildren: 0.06,
    },
  },
};

const chipRevealVariants = {
  hidden: { opacity: 0, y: 8 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.26, ease: pageEase },
  },
};

const outputSwapVariants = {
  hidden: { opacity: 0, y: 18, scale: 0.985 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { duration: 0.32, ease: pageEase },
  },
  exit: {
    opacity: 0,
    y: -10,
    scale: 0.99,
    transition: { duration: 0.2, ease: pageEase },
  },
};

type MobilePane = "chat" | "output";

interface AgentSkillDefinition {
  name: AgentSkillInvocation["name"];
  slash: string;
  label: string;
  description: string;
  argumentHint: string;
  requiresSelectedJob: boolean;
  outputKind: AgentOutputKind;
  example: string;
}

interface DiscoveryOutputItem {
  id: string;
  job_id: string;
  url: string;
  company: string;
  title: string;
  location: string;
  posted: string;
  ats: string;
  status: string;
  priority: string;
  pinned: boolean;
  match_score: number | null;
  raw_score: number | null;
  fit_score: number | null;
  guidance_summary: string | null;
  health_label: string | null;
}

interface CritiqueOutputPayload {
  artifactId: number;
  artifactType: "resume" | "cover_letter";
  jobId: string;
  summary: string;
  strengths: string[];
  improvements: string[];
  instructions: string;
  reviewedContent: string;
}

type AgentOutputState =
  | { kind: "none" }
  | { kind: "discovery"; query: string; items: DiscoveryOutputItem[] }
  | { kind: "resume" | "cover_letter"; jobId: string; operationId: string | null; generating: boolean }
  | { kind: "critique"; payload: CritiqueOutputPayload };

const AGENT_SKILLS: AgentSkillDefinition[] = [
  {
    name: "discover",
    slash: "discover",
    label: "Discover jobs",
    description: "Curate matching roles from the current database.",
    argumentHint: "remote senior ML engineer",
    requiresSelectedJob: false,
    outputKind: "discovery",
    example: "/discover remote senior ml engineer",
  },
  {
    name: "resume",
    slash: "resume",
    label: "Tailor resume",
    description: "Generate a resume for the selected role.",
    argumentHint: "emphasize experimentation leadership",
    requiresSelectedJob: true,
    outputKind: "resume",
    example: "/resume emphasize experimentation leadership",
  },
  {
    name: "cover_letter",
    slash: "cover-letter",
    label: "Draft cover letter",
    description: "Generate a cover letter for the selected role.",
    argumentHint: "focus on applied AI impact",
    requiresSelectedJob: true,
    outputKind: "cover_letter",
    example: "/cover-letter focus on applied AI impact",
  },
  {
    name: "critique",
    slash: "critique",
    label: "Critique writing",
    description: "Review the current draft without rewriting it.",
    argumentHint: "tighten the opening and remove weak claims",
    requiresSelectedJob: false,
    outputKind: "critique",
    example: "/critique tighten the opening and remove weak claims",
  },
];

const EMPTY_OUTPUT: AgentOutputState = { kind: "none" };
const THINKING_LINES = [
  "Scanning the current workspace for the next move...",
  "Comparing this role against your active documents...",
  "Preparing what should land in the canvas...",
  "Checking whether this should stay advice-only or become a draft...",
];
const EMPTY_DISCOVERY_ACTIONS = [
  "/discover remote senior ml engineer",
  "/discover staff data scientist remote",
];

function buildComposerPlaceholder(selected: QueueItem | null): string {
  if (selected) {
    return `Try /resume or /cover-letter for ${selected.company}...`;
  }
  return "Type / to open skills or ask a question...";
}

function buildEmptyStateModel(selected: QueueItem | null): {
  title: string;
  body: string;
  note: string;
  actions: string[];
} {
  if (selected) {
    return {
      title: `Ready for ${selected.company}.`,
      body: `Run /resume, /cover-letter, or /critique and this canvas becomes the working table for ${selected.title}.`,
      note: "Tip: the last draft stays here while the conversation keeps moving on the left.",
      actions: [
        "/resume emphasize leadership for this role",
        "/cover-letter focus on mission alignment",
        "/critique tighten the opening",
      ],
    };
  }
  return {
    title: "Nothing has landed here yet.",
    body: "Start with /discover to pull in roles, or choose a queued job and this pane will hold the working draft.",
    note: "Tip: type / in the composer to open the skill launcher.",
    actions: EMPTY_DISCOVERY_ACTIONS,
  };
}

function syncTextareaHeight(element: HTMLTextAreaElement | null): void {
  if (!element) return;
  element.style.height = "auto";
  element.style.height = `${Math.min(element.scrollHeight, 180)}px`;
}

function parseSlashQuery(value: string): string | null {
  const match = value.match(/^\/([^\s]*)$/);
  return match ? match[1].toLowerCase() : null;
}

function resolveSkillDefinition(rawName: string | undefined): AgentSkillDefinition | null {
  const normalized = String(rawName || "").trim().toLowerCase();
  if (!normalized) return null;
  if (normalized === "cover_letter" || normalized === "cover-letter") {
    return AGENT_SKILLS.find((item) => item.name === "cover_letter") ?? null;
  }
  return AGENT_SKILLS.find((item) => item.slash === normalized || item.name === normalized) ?? null;
}

function parseSkillInvocation(
  text: string,
  selectedJobId: string | null,
  activeArtifactId: number | null,
  activeOutputKind: AgentOutputKind | null,
): AgentSkillInvocation | null {
  const match = text.trim().match(/^\/([a-zA-Z][\w-]*)(?:\s+(.*))?$/s);
  if (!match) return null;
  const skill = resolveSkillDefinition(match[1]);
  if (!skill) return null;
  return {
    name: skill.name,
    arguments: (match[2] || "").trim(),
    selected_job_id: selectedJobId,
    active_artifact_id: activeArtifactId,
    active_output_kind: activeOutputKind,
  };
}

function asDiscoveryItems(payload: Record<string, unknown> | null | undefined): DiscoveryOutputItem[] {
  const rawItems = Array.isArray(payload?.items) ? payload.items : [];
  return rawItems.flatMap((entry) => {
    if (!entry || typeof entry !== "object") return [];
    const item = entry as Record<string, unknown>;
    return [{
      id: String(item.id || item.job_id || ""),
      job_id: String(item.job_id || item.id || ""),
      url: String(item.url || ""),
      company: String(item.company || ""),
      title: String(item.title || ""),
      location: String(item.location || ""),
      posted: String(item.posted || ""),
      ats: String(item.ats || ""),
      status: String(item.status || ""),
      priority: String(item.priority || ""),
      pinned: Boolean(item.pinned),
      match_score: typeof item.match_score === "number" ? item.match_score : null,
      raw_score: typeof item.raw_score === "number" ? item.raw_score : null,
      fit_score: typeof item.fit_score === "number" ? item.fit_score : null,
      guidance_summary: typeof item.guidance_summary === "string" ? item.guidance_summary : null,
      health_label: typeof item.health_label === "string" ? item.health_label : null,
    }];
  });
}

function labelForOutput(kind: AgentOutputState["kind"]): string {
  if (kind === "discovery") return "Discovery";
  if (kind === "resume") return "Resume";
  if (kind === "cover_letter") return "Cover letter";
  if (kind === "critique") return "Critique";
  return "Output";
}

function titleForOutput(kind: AgentOutputState["kind"]): string {
  if (kind === "discovery") return "Recommended jobs";
  if (kind === "resume") return "Tailored resume";
  if (kind === "cover_letter") return "Cover letter draft";
  if (kind === "critique") return "Draft critique";
  return "Action canvas";
}

function captionForOutput(kind: AgentOutputState["kind"]): string {
  if (kind === "discovery") return "Results from the current job database.";
  if (kind === "resume") return "The latest generated resume stays here while you keep chatting.";
  if (kind === "cover_letter") return "The latest generated cover letter stays here while you keep chatting.";
  if (kind === "critique") return "Non-destructive review of the active writing.";
  return "Tangible results land here when the agent produces something worth reviewing.";
}

function rankSignal(item: DiscoveryOutputItem): string {
  if (typeof item.match_score === "number") return `Rank ${Math.round(item.match_score)}`;
  if (typeof item.fit_score === "number") return `Fit ${Math.round(item.fit_score)}`;
  if (typeof item.raw_score === "number") return `Raw ${Math.round(item.raw_score)}`;
  return "Review";
}

const AddJobModal = memo(function AddJobModal({
  onClose,
  onAdd,
}: {
  onClose: () => void;
  onAdd: (jobId: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Array<{ id: string; title: string; company: string }>>([]);
  const [loading, setLoading] = useState(false);

  const search = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults([]);
      return;
    }
    setLoading(true);
    try {
      const data = await getJobsWithParams({ q: q.trim(), limit: 20 });
      setResults(data.items.map((job) => ({
        id: job.id,
        title: job.title,
        company: job.company,
      })));
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void search(query);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [query, search]);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h3>Add a role to Apply</h3>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <input
          className="modal-search-input"
          placeholder="Search by title or company..."
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          autoFocus
        />
        <div className="modal-results">
          {loading ? <div className="modal-loading">Searching...</div> : null}
          {!loading && results.length === 0 && query.trim() ? <div className="modal-empty">No matching roles.</div> : null}
          {results.map((job) => (
            <button
              key={job.id}
              className="modal-result-item"
              onClick={() => {
                onAdd(job.id);
                onClose();
              }}
            >
              <span className="modal-result-title">{job.title}</span>
              <span className="modal-result-company">{job.company}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
});

const BaseDocPickerModal = memo(function BaseDocPickerModal({
  docs,
  label,
  onPick,
  onClose,
}: {
  docs: BaseDocument[];
  label: string;
  onPick: (id: number) => void;
  onClose: () => void;
}) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h3>Choose base {label.toLowerCase()}</h3>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-results">
          {docs.map((doc) => (
            <button
              key={doc.id}
              className="modal-result-item"
              onClick={() => {
                onPick(doc.id);
                onClose();
              }}
            >
              <span className="modal-result-title">{doc.filename}</span>
              {doc.is_default ? <span className="doc-default-badge">Default</span> : null}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
});

export function AgentPage() {
  const navigate = useNavigate();
  const prefersReducedMotion = useReducedMotion();
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [selected, setSelected] = useState<QueueItem | null>(null);
  const [artifacts, setArtifacts] = useState<JobArtifact[]>([]);
  const [baseDocs, setBaseDocs] = useState<BaseDocument[]>([]);

  const [showAddJobModal, setShowAddJobModal] = useState(false);
  const [showBaseDocPicker, setShowBaseDocPicker] = useState<"resume" | "cover_letter" | null>(null);
  const [showRoleList, setShowRoleList] = useState(false);

  const [resumeDraft, setResumeDraft] = useState("");
  const [resumeSaved, setResumeSaved] = useState(true);
  const [resumeSaving, setResumeSaving] = useState(false);
  const [resumeTab, setResumeTab] = useState<"edit" | "preview">("edit");
  const [generatingResume, setGeneratingResume] = useState(false);

  const [clDraft, setClDraft] = useState("");
  const [clSaved, setClSaved] = useState(true);
  const [clSaving, setClSaving] = useState(false);
  const [clTab, setClTab] = useState<"edit" | "preview">("edit");
  const [generatingCL, setGeneratingCL] = useState(false);

  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);

  const [agentOutput, setAgentOutput] = useState<AgentOutputState>(EMPTY_OUTPUT);
  const [activeMobilePane, setActiveMobilePane] = useState<MobilePane>("chat");
  const [slashMenuOpen, setSlashMenuOpen] = useState(false);
  const [slashQuery, setSlashQuery] = useState("");
  const [selectedSkillIndex, setSelectedSkillIndex] = useState(0);
  const [thinkingMessageIndex, setThinkingMessageIndex] = useState(0);

  const threadRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const liveRefreshTimerRef = useRef<number>(0);
  const artifactStreamRef = useRef<(() => void) | null>(null);

  const resumeArtifact = artifacts.find((item) => item.artifact_type === "resume") ?? null;
  const coverLetterArtifact = artifacts.find((item) => item.artifact_type === "cover_letter") ?? null;
  const activeQueue = queue.filter((item) => item.status === "queued" || item.status === "ready" || item.status === "processing");
  const selectedResumeReady = resumeArtifact !== null && resumeSaved;
  const selectedCoverLetterReady = coverLetterArtifact !== null && clSaved;
  const bothArtifactsReady = selectedResumeReady && selectedCoverLetterReady;

  const filteredSkills = !slashQuery
    ? AGENT_SKILLS
    : AGENT_SKILLS.filter((item) => item.slash.includes(slashQuery) || item.label.toLowerCase().includes(slashQuery));

  const outputMotionKey =
    agentOutput.kind === "discovery"
      ? `discovery-${agentOutput.query}-${agentOutput.items.length}`
      : agentOutput.kind === "resume" || agentOutput.kind === "cover_letter"
        ? `${agentOutput.kind}-${agentOutput.jobId}-${agentOutput.generating ? "loading" : "ready"}`
        : agentOutput.kind === "critique"
          ? `critique-${agentOutput.payload.artifactId}`
          : "none";
  const composerPlaceholder = buildComposerPlaceholder(selected);
  const emptyStateModel = buildEmptyStateModel(selected);
  const thinkingLabel = THINKING_LINES[thinkingMessageIndex % THINKING_LINES.length];

  const applyArtifacts = useCallback((items: JobArtifact[]) => {
    setArtifacts(items);
    const resume = items.find((item) => item.artifact_type === "resume");
    const coverLetter = items.find((item) => item.artifact_type === "cover_letter");
    setResumeDraft(resume?.content_md ?? "");
    setResumeSaved(true);
    setClDraft(coverLetter?.content_md ?? "");
    setClSaved(true);
  }, []);

  const pollOperation = useCallback(async (operation: WorkspaceOperation) => {
    let current = operation;
    for (let attempt = 0; attempt < 120; attempt += 1) {
      if (current.status === "completed" || current.status === "failed") {
        return current;
      }
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
      current = await getOperation(operation.id);
    }
    throw new Error("Generation timed out");
  }, []);

  const waitForOperation = useCallback((operation: WorkspaceOperation) => {
    return new Promise<WorkspaceOperation>((resolve, reject) => {
      let settled = false;
      const fallback = () => {
        void pollOperation(operation).then(resolve).catch(reject);
      };
      const unsubscribe = subscribeToOperation(operation.id, {
        onMessage: (next) => {
          if (settled) return;
          if (next.status === "completed" || next.status === "failed") {
            settled = true;
            unsubscribe();
            resolve(next);
          }
        },
        onError: () => {
          if (settled) return;
          settled = true;
          unsubscribe();
          fallback();
        },
      });
      window.setTimeout(() => {
        if (settled) return;
        settled = true;
        unsubscribe();
        fallback();
      }, 1500);
    });
  }, [pollOperation]);

  const ensureSelectedJob = useCallback((jobId: string | null | undefined) => {
    if (!jobId) return;
    setSelected((current) => {
      if (current?.job_id === jobId) return current;
      return queue.find((item) => item.job_id === jobId) ?? current;
    });
  }, [queue]);

  const loadQueue = useCallback(async () => {
    try {
      const items = await getQueue();
      setQueue(items);
      setSelected((current) => {
        if (current && items.some((item) => item.id === current.id)) {
          return items.find((item) => item.id === current.id) ?? current;
        }
        return null;
      });
    } catch {
      // silent
    }
  }, []);

  const finalizeArtifactOutput = useCallback(async (
    kind: "resume" | "cover_letter",
    jobId: string,
    operationId: string,
  ) => {
    try {
      const initial = await getOperation(operationId);
      const finalOperation = await waitForOperation(initial);
      if (finalOperation.status !== "completed") {
        throw new Error(finalOperation.error || "Generation failed");
      }
      ensureSelectedJob(jobId);
      const items = await getJobArtifacts(jobId, { force: true });
      if (selected?.job_id === jobId || !selected) {
        applyArtifacts(items);
      }
      setAgentOutput({ kind, jobId, generating: false, operationId });
    } catch (error) {
      setChatError(error instanceof Error ? error.message : "Generation failed");
      setAgentOutput((current) => {
        if (current.kind !== kind) return current;
        return { ...current, generating: false };
      });
    } finally {
      if (kind === "resume") setGeneratingResume(false);
      else setGeneratingCL(false);
    }
  }, [applyArtifacts, ensureSelectedJob, selected, waitForOperation]);

  useEffect(() => {
    void loadQueue();
    void prefetchQueue();
    listBaseDocuments().then(setBaseDocs).catch(() => {});
  }, [loadQueue]);

  useEffect(() => {
    const unsubscribe = subscribeToDashboardEvents({
      onMessage: () => {
        window.clearTimeout(liveRefreshTimerRef.current);
        liveRefreshTimerRef.current = window.setTimeout(() => {
          void loadQueue();
          if (selected?.job_id) {
            void getJobArtifacts(selected.job_id, { force: true }).then(applyArtifacts).catch(() => {});
          }
        }, 300);
      },
    });
    return () => {
      window.clearTimeout(liveRefreshTimerRef.current);
      unsubscribe();
    };
  }, [applyArtifacts, loadQueue, selected]);

  useEffect(() => {
    if (!selected?.job_id) {
      setArtifacts([]);
      setResumeDraft("");
      setClDraft("");
      return;
    }
    void getJobArtifacts(selected.job_id).then(applyArtifacts).catch(() => {});
  }, [applyArtifacts, selected]);

  useEffect(() => {
    if (threadRef.current) {
      threadRef.current.scrollTop = threadRef.current.scrollHeight;
    }
  }, [messages, thinking]);

  useEffect(() => {
    syncTextareaHeight(textareaRef.current);
    const nextQuery = parseSlashQuery(chatInput);
    if (nextQuery === null) {
      setSlashMenuOpen(false);
      setSlashQuery("");
      setSelectedSkillIndex(0);
      return;
    }
    setSlashMenuOpen(true);
    setSlashQuery(nextQuery);
    setSelectedSkillIndex(0);
  }, [chatInput]);

  useEffect(() => {
    if (!filteredSkills.length) {
      setSelectedSkillIndex(0);
      return;
    }
    setSelectedSkillIndex((current) => Math.min(current, filteredSkills.length - 1));
  }, [filteredSkills.length]);

  useEffect(() => {
    if (!thinking || prefersReducedMotion) {
      setThinkingMessageIndex(0);
      return;
    }
    const interval = window.setInterval(() => {
      setThinkingMessageIndex((current) => (current + 1) % THINKING_LINES.length);
    }, 1700);
    return () => window.clearInterval(interval);
  }, [prefersReducedMotion, thinking]);

  async function handleAddToQueue(jobId: string) {
    try {
      const item = await addToQueue(jobId);
      setQueue((prev) => {
        if (prev.some((queueItem) => queueItem.job_id === item.job_id)) return prev;
        return [...prev, item];
      });
      if (!selected) setSelected(item);
    } catch {
      // silent
    }
  }

  async function handleRemoveFromQueue(id: number) {
    try {
      await removeFromQueue(id);
      setQueue((prev) => prev.filter((item) => item.id !== id));
      if (selected?.id === id) setSelected(null);
    } catch {
      // silent
    }
  }

  function getBaseDocId(type: "resume" | "cover_letter"): number | null {
    const docsOfType = baseDocs.filter((doc) => doc.doc_type === type);
    if (!docsOfType.length) return null;
    return docsOfType.find((doc) => doc.is_default)?.id ?? docsOfType[0].id;
  }

  function handleGenerateResume(baseDocId: number) {
    if (!selected) return;
    artifactStreamRef.current?.();
    setGeneratingResume(true);
    setResumeDraft("");
    setResumeSaved(true);
    setAgentOutput({ kind: "resume", jobId: selected.job_id, generating: true, operationId: null });
    setActiveMobilePane("output");
    const jobId = selected.job_id;
    const stop = streamArtifact(jobId, "resume", baseDocId, {
      onChunk: (token) => setResumeDraft((prev) => prev + token),
      onArtifact: (artifact) => {
        setArtifacts((prev) => {
          const filtered = prev.filter((item) => item.artifact_type !== "resume");
          return [...filtered, artifact];
        });
        setResumeSaved(true);
        setAgentOutput({ kind: "resume", jobId, generating: false, operationId: null });
      },
      onError: (detail) => {
        setChatError(detail);
        setGeneratingResume(false);
        setAgentOutput((current) => (current.kind === "resume" ? { ...current, generating: false } : current));
      },
      onDone: () => setGeneratingResume(false),
    });
    artifactStreamRef.current = stop;
  }

  function handleGenerateCoverLetter(baseDocId: number) {
    if (!selected) return;
    artifactStreamRef.current?.();
    setGeneratingCL(true);
    setClDraft("");
    setClSaved(true);
    setAgentOutput({ kind: "cover_letter", jobId: selected.job_id, generating: true, operationId: null });
    setActiveMobilePane("output");
    const jobId = selected.job_id;
    const stop = streamArtifact(jobId, "cover_letter", baseDocId, {
      onChunk: (token) => setClDraft((prev) => prev + token),
      onArtifact: (artifact) => {
        setArtifacts((prev) => {
          const filtered = prev.filter((item) => item.artifact_type !== "cover_letter");
          return [...filtered, artifact];
        });
        setClSaved(true);
        setAgentOutput({ kind: "cover_letter", jobId, generating: false, operationId: null });
      },
      onError: (detail) => {
        setChatError(detail);
        setGeneratingCL(false);
        setAgentOutput((current) => (current.kind === "cover_letter" ? { ...current, generating: false } : current));
      },
      onDone: () => setGeneratingCL(false),
    });
    artifactStreamRef.current = stop;
  }

  function requestGenerate(type: "resume" | "cover_letter") {
    const docsOfType = baseDocs.filter((doc) => doc.doc_type === type);
    if (docsOfType.length > 1) {
      setShowBaseDocPicker(type);
      return;
    }
    const id = getBaseDocId(type);
    if (!id) {
      setChatError(`Upload a base ${type === "resume" ? "resume" : "cover letter"} in Settings first.`);
      return;
    }
    if (type === "resume") void handleGenerateResume(id);
    else void handleGenerateCoverLetter(id);
  }

  async function handleSaveResume() {
    if (!resumeArtifact) return;
    setResumeSaving(true);
    try {
      await updateArtifact(resumeArtifact.id, resumeDraft);
      setResumeSaved(true);
    } finally {
      setResumeSaving(false);
    }
  }

  async function handleSaveCoverLetter() {
    if (!coverLetterArtifact) return;
    setClSaving(true);
    try {
      await updateArtifact(coverLetterArtifact.id, clDraft);
      setClSaved(true);
    } finally {
      setClSaving(false);
    }
  }

  async function handleMarkApplied() {
    if (!selected) return;
    try {
      const updated = await updateQueueItem(selected.id, "applied");
      setQueue((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      setSelected(null);
    } catch {
      // silent
    }
  }

  async function handleSkip() {
    if (!selected) return;
    try {
      const updated = await updateQueueItem(selected.id, "skipped");
      setQueue((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      setSelected(null);
    } catch {
      // silent
    }
  }

  async function handlePinDiscovery(item: DiscoveryOutputItem) {
    try {
      await patchTracking(item.job_id, { pinned: !item.pinned });
      setAgentOutput((current) => {
        if (current.kind !== "discovery") return current;
        return {
          ...current,
          items: current.items.map((entry) => (
            entry.job_id === item.job_id
              ? { ...entry, pinned: !entry.pinned }
              : entry
          )),
        };
      });
    } catch {
      // silent
    }
  }

  function selectSkill(skill: AgentSkillDefinition) {
    setChatInput(`/${skill.slash} `);
    setSlashMenuOpen(false);
    setSlashQuery("");
    window.requestAnimationFrame(() => {
      textareaRef.current?.focus();
      syncTextareaHeight(textareaRef.current);
    });
  }

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || thinking) return;

    const activeArtifactId =
      agentOutput.kind === "cover_letter"
        ? coverLetterArtifact?.id ?? null
        : agentOutput.kind === "resume"
          ? resumeArtifact?.id ?? null
          : agentOutput.kind === "critique"
            ? agentOutput.payload.artifactId
            : resumeArtifact?.id ?? coverLetterArtifact?.id ?? null;

    const activeOutputKind = agentOutput.kind === "none" ? null : agentOutput.kind;
    const skillInvocation = parseSkillInvocation(
      trimmed,
      selected?.job_id ?? null,
      activeArtifactId,
      activeOutputKind,
    );

    const requestMessages: AgentMessage[] = [
      ...(!skillInvocation && selected
        ? [{ role: "assistant" as const, content: `[Context: Current role ${selected.company} — ${selected.title}]` }]
        : []),
      ...messages,
      { role: "user", content: trimmed },
    ];

    setMessages((prev) => [...prev, { role: "user", content: trimmed }]);
    setChatInput("");
    setThinking(true);
    setChatError(null);

    try {
      const response = await agentChat(requestMessages, skillInvocation);
      setMessages((prev) => [...prev, { role: "assistant", content: response.reply }]);

      if (response.output_kind === "discovery") {
        setAgentOutput({
          kind: "discovery",
          query: String((response.output_payload?.query as string | undefined) ?? skillInvocation?.arguments ?? ""),
          items: asDiscoveryItems(response.output_payload),
        });
        setActiveMobilePane("output");
      } else if (response.output_kind === "resume" || response.output_kind === "cover_letter") {
        const payload = (response.output_payload ?? {}) as Record<string, unknown>;
        const jobId = String(payload.job_id || skillInvocation?.selected_job_id || selected?.job_id || "");
        if (jobId) ensureSelectedJob(jobId);
        if (response.output_kind === "resume") setGeneratingResume(Boolean(response.operation_id));
        else setGeneratingCL(Boolean(response.operation_id));
        setAgentOutput({
          kind: response.output_kind,
          jobId,
          generating: Boolean(response.operation_id),
          operationId: response.operation_id ?? null,
        });
        setActiveMobilePane("output");
        if (jobId && response.operation_id) {
          void finalizeArtifactOutput(response.output_kind, jobId, response.operation_id);
        }
      } else if (response.output_kind === "critique") {
        const payload = (response.output_payload ?? {}) as Record<string, unknown>;
        const artifactId = Number(payload.artifact_id || 0);
        const artifactType = String(payload.artifact_type || "resume") === "cover_letter" ? "cover_letter" : "resume";
        const reviewedArtifact =
          artifacts.find((item) => item.id === artifactId)
          ?? (artifactType === "resume" ? resumeArtifact : coverLetterArtifact)
          ?? null;
        setAgentOutput({
          kind: "critique",
          payload: {
            artifactId,
            artifactType,
            jobId: String(payload.job_id || selected?.job_id || ""),
            summary: String(payload.summary || ""),
            strengths: Array.isArray(payload.strengths) ? payload.strengths.map(String) : [],
            improvements: Array.isArray(payload.improvements) ? payload.improvements.map(String) : [],
            instructions: String(payload.instructions || ""),
            reviewedContent: reviewedArtifact?.content_md ?? "",
          },
        });
        setActiveMobilePane("output");
      }
    } catch (error) {
      setChatError(error instanceof Error ? error.message : "Failed to reach the agent");
    } finally {
      setThinking(false);
    }
  }

  return (
    <motion.div
      className="dashboard-page apply-page"
      initial={{ opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.36, ease: pageEase }}
    >
      <div className="apply-mobile-tabs">
        <button
          type="button"
          className={`apply-mobile-tab${activeMobilePane === "chat" ? " is-active" : ""}`}
          onClick={() => setActiveMobilePane("chat")}
        >
          Chat
        </button>
        <button
          type="button"
          className={`apply-mobile-tab${activeMobilePane === "output" ? " is-active" : ""}`}
          onClick={() => setActiveMobilePane("output")}
        >
          Output
        </button>
      </div>

      <div className="apply-studio-shell">
        <div className="apply-shell-backdrop" />
        <div className="apply-workspace">
        <motion.section
          className={`apply-chat-pane${activeMobilePane === "chat" ? " is-mobile-active" : ""}`}
          initial={prefersReducedMotion ? false : "hidden"}
          animate="visible"
          variants={sectionRevealVariants}
        >
          <div className="apply-chat-shell">
            <motion.header
              className="apply-chat-hero"
              initial={prefersReducedMotion ? false : "hidden"}
              animate="visible"
              variants={clusterRevealVariants}
            >
              <p className="page-kicker">Apply</p>
              <h1 className="apply-chat-title">AI Co-pilot Studio</h1>
              <p className="apply-chat-subtitle">Intelligent job orchestration</p>
            </motion.header>

            <motion.div
              className="apply-context-strip"
              initial={prefersReducedMotion ? false : "hidden"}
              animate="visible"
              variants={clusterRevealVariants}
            >
              <div className="apply-context-strip-copy">
                <span className="apply-context-strip-label">Current task</span>
                {selected ? (
                  <>
                    <strong>{selected.title}</strong>
                    <p>{selected.company}{selected.location ? ` • ${selected.location}` : ""}</p>
                  </>
                ) : (
                  <>
                    <strong>No role selected</strong>
                    <p>Choose a queued role before running `/resume` or `/cover-letter`.</p>
                  </>
                )}
              </div>
              <div className="apply-context-strip-meta">
                <span className="apply-context-count">{activeQueue.length} queued</span>
                {selected?.match_score != null ? <span className="apply-context-rank">Rank {Math.round(selected.match_score)}</span> : null}
              </div>
            </motion.div>

            <motion.div
              className="apply-context-actions"
              initial={prefersReducedMotion ? false : "hidden"}
              animate="visible"
              variants={staggerRevealVariants}
            >
              <Button type="button" variant="default" size="compact" onClick={() => setShowRoleList((current) => !current)}>
                {showRoleList ? "Hide roles" : "Select role"}
              </Button>
              <Button type="button" variant="default" size="compact" onClick={() => setSelected(null)} disabled={!selected}>
                Clear role
              </Button>
              <Button type="button" variant="primary" size="compact" onClick={() => setShowAddJobModal(true)}>
                Add role
              </Button>
            </motion.div>

            <AnimatePresence initial={false}>
            {showRoleList ? (
              <motion.div
                className="apply-role-list"
                initial={prefersReducedMotion ? false : { opacity: 0, height: 0, y: -8 }}
                animate={prefersReducedMotion ? { opacity: 1, height: "auto" } : { opacity: 1, height: "auto", y: 0 }}
                exit={prefersReducedMotion ? { opacity: 0, height: 0 } : { opacity: 0, height: 0, y: -8 }}
                transition={{ duration: prefersReducedMotion ? 0 : 0.24, ease: pageEase }}
              >
                {activeQueue.length === 0 ? (
                  <div className="apply-role-empty">Nothing is queued yet.</div>
                ) : (
                  activeQueue.map((item) => (
                    <div
                      key={item.id}
                      className={`apply-role-item${selected?.id === item.id ? " is-active" : ""}`}
                      role="button"
                      tabIndex={0}
                      onClick={() => {
                        setSelected(item);
                        setShowRoleList(false);
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          setSelected(item);
                          setShowRoleList(false);
                        }
                      }}
                      onMouseEnter={() => {
                        void prefetchJobDetail(item.job_id);
                        void prefetchJobArtifacts(item.job_id);
                      }}
                    >
                      <div className="apply-role-item-copy">
                        <span>{item.company}</span>
                        <strong>{item.title}</strong>
                        <small>{item.location || "Location not specified"}</small>
                      </div>
                      <div className="apply-role-item-meta">
                        {item.match_score != null ? <span>Rank {Math.round(item.match_score)}</span> : null}
                        <button
                          type="button"
                          className="apply-role-remove"
                          onClick={(event) => {
                            event.stopPropagation();
                            void handleRemoveFromQueue(item.id);
                          }}
                        >
                          ×
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </motion.div>
            ) : null}
            </AnimatePresence>

            <div className="agent-thread apply-thread" ref={threadRef}>
              {messages.length === 0 && !thinking ? (
                <div className="agent-suggestions apply-suggestions">
                  {AGENT_SKILLS.map((skill) => (
                    <button key={skill.name} type="button" className="agent-suggestion-chip" onClick={() => void send(skill.example)}>
                      {skill.example}
                    </button>
                  ))}
                </div>
              ) : null}

              <AnimatePresence initial={false}>
                {messages.map((message, index) => (
                  <motion.div
                    key={`${message.role}-${index}`}
                    className={`agent-message agent-message--${message.role}`}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.28, ease: pageEase }}
                  >
                    <span className="agent-message-role">{message.role === "user" ? "You" : "Assistant"}</span>
                    <div className="agent-message-bubble">
                      {message.role === "assistant" ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown> : message.content}
                    </div>
                  </motion.div>
                ))}

                {thinking ? (
                  <motion.div
                    key="thinking"
                    className="agent-message agent-message--assistant"
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.22 }}
                  >
                    <span className="agent-message-role">Assistant</span>
                    <div className="agent-thinking apply-thinking">
                      <div className="apply-thinking-dots" aria-hidden="true">
                        <div className="agent-thinking-dot" />
                        <div className="agent-thinking-dot" />
                        <div className="agent-thinking-dot" />
                      </div>
                      <span className="apply-thinking-copy">{thinkingLabel}</span>
                    </div>
                  </motion.div>
                ) : null}
              </AnimatePresence>
            </div>

            {chatError ? <div className="error-banner">{chatError}</div> : null}

            <motion.div
              className="apply-command-row"
              initial={prefersReducedMotion ? false : "hidden"}
              animate="visible"
              variants={staggerRevealVariants}
            >
              {AGENT_SKILLS.map((skill) => (
                <motion.button
                  key={skill.name}
                  type="button"
                  className="apply-command-chip"
                  variants={chipRevealVariants}
                  whileHover={prefersReducedMotion ? undefined : { y: -1, scale: 1.01 }}
                  whileTap={prefersReducedMotion ? undefined : { scale: 0.985 }}
                  onClick={() => selectSkill(skill)}
                >
                  /{skill.slash}
                </motion.button>
              ))}
            </motion.div>

            <motion.div
              className="apply-composer-shell"
              initial={prefersReducedMotion ? false : "hidden"}
              animate="visible"
              variants={clusterRevealVariants}
            >
              <AnimatePresence initial={false}>
              {slashMenuOpen ? (
                <motion.div
                  className="apply-slash-picker"
                  initial={prefersReducedMotion ? false : { opacity: 0, y: 12, scale: 0.985 }}
                  animate={prefersReducedMotion ? { opacity: 1 } : { opacity: 1, y: 0, scale: 1 }}
                  exit={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, y: 10, scale: 0.99 }}
                  transition={{ duration: prefersReducedMotion ? 0 : 0.2, ease: pageEase }}
                >
                  {filteredSkills.length === 0 ? (
                    <div className="apply-slash-empty">No matching command.</div>
                  ) : (
                    filteredSkills.map((skill, index) => (
                      <button
                        key={skill.name}
                        type="button"
                        className={`apply-slash-item${selectedSkillIndex === index ? " is-active" : ""}`}
                        onMouseEnter={() => setSelectedSkillIndex(index)}
                        onClick={() => selectSkill(skill)}
                      >
                        <div className="apply-slash-item-main">
                          <strong>/{skill.slash}</strong>
                          <span>{skill.description}</span>
                        </div>
                        <small>{skill.argumentHint}</small>
                      </button>
                    ))
                  )}
                </motion.div>
              ) : null}
              </AnimatePresence>

              <div className="agent-input-bar apply-input-bar">
                <textarea
                  ref={textareaRef}
                  className="agent-textarea apply-textarea"
                  placeholder={composerPlaceholder}
                  value={chatInput}
                  disabled={thinking}
                  rows={1}
                  onChange={(event) => setChatInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (slashMenuOpen && filteredSkills.length > 0) {
                      if (event.key === "ArrowDown") {
                        event.preventDefault();
                        setSelectedSkillIndex((current) => (current + 1) % filteredSkills.length);
                        return;
                      }
                      if (event.key === "ArrowUp") {
                        event.preventDefault();
                        setSelectedSkillIndex((current) => (current - 1 + filteredSkills.length) % filteredSkills.length);
                        return;
                      }
                      if (event.key === "Enter" && !event.shiftKey) {
                        event.preventDefault();
                        selectSkill(filteredSkills[selectedSkillIndex]);
                        return;
                      }
                      if (event.key === "Escape") {
                        event.preventDefault();
                        setSlashMenuOpen(false);
                        return;
                      }
                    }
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      void send(chatInput);
                    }
                  }}
                />
                <Button type="button" variant="primary" disabled={thinking || !chatInput.trim()} onClick={() => void send(chatInput)}>
                  <MessageSquareText size={14} />
                  {thinking ? "..." : "Send"}
                </Button>
              </div>
            </motion.div>
          </div>
        </motion.section>

        <motion.section
          className={`apply-output-pane${activeMobilePane === "output" ? " is-mobile-active" : ""}`}
          initial={prefersReducedMotion ? false : "hidden"}
          animate="visible"
          variants={sectionRevealVariants}
          transition={prefersReducedMotion ? { duration: 0 } : { duration: 0.46, ease: pageEase, delay: 0.05 }}
        >
          <div className="apply-output-shell">
            <motion.div
              className="apply-output-head"
              initial={prefersReducedMotion ? false : "hidden"}
              animate="visible"
              variants={clusterRevealVariants}
            >
              <div>
                <p className="page-kicker">{labelForOutput(agentOutput.kind)}</p>
                <h2>{titleForOutput(agentOutput.kind)}</h2>
                <p className="apply-output-caption">{captionForOutput(agentOutput.kind)}</p>
              </div>
              {agentOutput.kind === "discovery" ? <span className="apply-output-badge">{agentOutput.items.length} roles</span> : null}
            </motion.div>

            <AnimatePresence mode="wait" initial={false}>
            {agentOutput.kind === "none" ? (
              <motion.div
                key={outputMotionKey}
                className="apply-output-empty"
                initial={prefersReducedMotion ? false : "hidden"}
                animate="visible"
                exit="exit"
                variants={outputSwapVariants}
              >
                <div className="apply-output-empty-orb"><Sparkles size={18} /></div>
                <div className="apply-output-empty-copy">
                  <strong>{emptyStateModel.title}</strong>
                  <p>{emptyStateModel.body}</p>
                </div>
                <div className="apply-output-empty-actions">
                  {emptyStateModel.actions.map((action) => (
                    <button
                      key={action}
                      type="button"
                      className="apply-output-empty-chip"
                      onClick={() => void send(action)}
                    >
                      {action}
                    </button>
                  ))}
                </div>
                <span className="apply-output-empty-note">{emptyStateModel.note}</span>
              </motion.div>
            ) : null}

            {agentOutput.kind === "discovery" ? (
              <motion.div
                key={outputMotionKey}
                initial={prefersReducedMotion ? false : "hidden"}
                animate="visible"
                exit="exit"
                variants={outputSwapVariants}
              >
                <motion.div
                  className="apply-discovery-list"
                  initial={prefersReducedMotion ? false : "hidden"}
                  animate="visible"
                  variants={staggerRevealVariants}
                >
                  {agentOutput.items.map((item) => (
                    <motion.article
                      key={item.job_id}
                      className="apply-discovery-card"
                      variants={prefersReducedMotion ? undefined : chipRevealVariants}
                      whileHover={prefersReducedMotion ? undefined : { y: -2 }}
                      transition={{ duration: 0.22, ease: pageEase }}
                    >
                      <div className="apply-discovery-card-head">
                        <div>
                          <strong>{item.title}</strong>
                          <span>{item.company}</span>
                        </div>
                        <span className="apply-discovery-rank">{rankSignal(item)}</span>
                      </div>
                      <div className="apply-discovery-card-meta">
                        <span>{item.location || "Location not specified"}</span>
                        {item.posted ? <span>{item.posted}</span> : null}
                        {item.health_label ? <span>{item.health_label}</span> : null}
                      </div>
                      {item.guidance_summary ? <p className="apply-discovery-card-copy">{item.guidance_summary}</p> : null}
                      <div className="apply-discovery-card-actions">
                        <Button type="button" variant="primary" size="compact" onClick={() => void handleAddToQueue(item.job_id)}>Queue</Button>
                        <Button type="button" variant="default" size="compact" onClick={() => navigate(`/jobs/${encodeURIComponent(item.job_id)}`)}>Open job</Button>
                        <Button type="button" variant="default" size="compact" onClick={() => void handlePinDiscovery(item)}>
                          {item.pinned ? "Pinned" : "Pin"}
                        </Button>
                      </div>
                    </motion.article>
                  ))}
                </motion.div>
              </motion.div>
            ) : null}

            {agentOutput.kind === "resume" ? (
              <motion.div
                key={outputMotionKey}
                className="apply-output-section"
                initial={prefersReducedMotion ? false : "hidden"}
                animate="visible"
                exit="exit"
                variants={outputSwapVariants}
              >
                {agentOutput.generating ? <div className="apply-output-generating">Generating tailored resume...</div> : null}
                <ArtifactEditor
                  label="Resume"
                  value={resumeDraft}
                  onChange={(value) => { setResumeDraft(value); setResumeSaved(false); }}
                  onSave={() => void handleSaveResume()}
                  onGenerate={() => requestGenerate("resume")}
                  onDownload={() => {
                    if (resumeArtifact) window.open(getArtifactPdfUrl(resumeArtifact.id), "_blank");
                  }}
                  generating={generatingResume}
                  saving={resumeSaving}
                  saved={resumeSaved}
                  artifactId={resumeArtifact?.id ?? null}
                  tab={resumeTab}
                  onTabChange={setResumeTab}
                  storiesGrounded={resumeArtifact?.story_ids_used?.length ?? 0}
                />
              </motion.div>
            ) : null}

            {agentOutput.kind === "cover_letter" ? (
              <motion.div
                key={outputMotionKey}
                className="apply-output-section"
                initial={prefersReducedMotion ? false : "hidden"}
                animate="visible"
                exit="exit"
                variants={outputSwapVariants}
              >
                {agentOutput.generating ? <div className="apply-output-generating">Generating tailored cover letter...</div> : null}
                <ArtifactEditor
                  label="Cover Letter"
                  value={clDraft}
                  onChange={(value) => { setClDraft(value); setClSaved(false); }}
                  onSave={() => void handleSaveCoverLetter()}
                  onGenerate={() => requestGenerate("cover_letter")}
                  onDownload={() => {
                    if (coverLetterArtifact) window.open(getArtifactPdfUrl(coverLetterArtifact.id), "_blank");
                  }}
                  generating={generatingCL}
                  saving={clSaving}
                  saved={clSaved}
                  artifactId={coverLetterArtifact?.id ?? null}
                  tab={clTab}
                  onTabChange={setClTab}
                  storiesGrounded={coverLetterArtifact?.story_ids_used?.length ?? 0}
                />
              </motion.div>
            ) : null}

            {agentOutput.kind === "critique" ? (
              <motion.div
                key={outputMotionKey}
                className="apply-critique-shell"
                initial={prefersReducedMotion ? false : "hidden"}
                animate="visible"
                exit="exit"
                variants={outputSwapVariants}
              >
                <div className="apply-critique-summary">
                  <strong>{agentOutput.payload.summary}</strong>
                  {agentOutput.payload.instructions ? <span>Requested focus: {agentOutput.payload.instructions}</span> : null}
                </div>
                <div className="apply-critique-grid">
                  <div className="apply-critique-card">
                    <h3>Strengths</h3>
                    <ul>
                      {agentOutput.payload.strengths.map((item) => <li key={item}>{item}</li>)}
                    </ul>
                  </div>
                  <div className="apply-critique-card">
                    <h3>Improvements</h3>
                    <ul>
                      {agentOutput.payload.improvements.map((item) => <li key={item}>{item}</li>)}
                    </ul>
                  </div>
                </div>
                {agentOutput.payload.reviewedContent ? (
                  <div className="apply-critique-preview">
                    <div className="apply-output-subhead">
                      <FileText size={14} />
                      <span>Reviewed draft</span>
                    </div>
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{agentOutput.payload.reviewedContent}</ReactMarkdown>
                  </div>
                ) : null}
              </motion.div>
            ) : null}
            </AnimatePresence>

            <AnimatePresence initial={false}>
            {selected && bothArtifactsReady ? (
              <motion.div
                className="apply-output-footer"
                initial={prefersReducedMotion ? false : { opacity: 0, y: 12 }}
                animate={prefersReducedMotion ? { opacity: 1 } : { opacity: 1, y: 0 }}
                exit={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, y: 8 }}
                transition={{ duration: prefersReducedMotion ? 0 : 0.22, ease: pageEase }}
              >
                <Button
                  type="button"
                  variant="primary"
                  onClick={async () => {
                    const job = await getJobDetail(selected.job_id);
                    window.open(job.url, "_blank");
                  }}
                >
                  Open application page
                </Button>
                <Button type="button" variant="default" onClick={() => void handleMarkApplied()}>
                  Mark applied
                </Button>
                <Button type="button" variant="default" onClick={() => void handleSkip()}>
                  Skip for now
                </Button>
                <Button type="button" variant="default" onClick={() => navigate(`/jobs/${encodeURIComponent(selected.job_id)}`)}>
                  Open job detail <ArrowUpRight size={14} />
                </Button>
              </motion.div>
            ) : null}
            </AnimatePresence>
          </div>
        </motion.section>
        </div>
      </div>

      {showAddJobModal ? (
        <AddJobModal onClose={() => setShowAddJobModal(false)} onAdd={(jobId) => void handleAddToQueue(jobId)} />
      ) : null}

      {showBaseDocPicker ? (
        <BaseDocPickerModal
          docs={baseDocs.filter((doc) => doc.doc_type === showBaseDocPicker)}
          label={showBaseDocPicker === "resume" ? "Resume" : "Cover Letter"}
          onPick={(id) => {
            if (showBaseDocPicker === "resume") void handleGenerateResume(id);
            else void handleGenerateCoverLetter(id);
          }}
          onClose={() => setShowBaseDocPicker(null)}
        />
      ) : null}
    </motion.div>
  );
}
