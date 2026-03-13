import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import Editor from "@monaco-editor/react";
import type { editor as MonacoEditor } from "monaco-editor";
import type * as Monaco from "monaco-editor";
import { registerLaTeXLanguage } from "monaco-latex";
import { toast } from "sonner";
import {
  addProfileSkill,
  cancelCoverLetterSwarmRun,
  confirmCoverLetterSwarmRunSave,
  deleteJob,
  getJobDetail,
  cancelResumeSwarmRun,
  getCoverLetterSwarmRunStatus,
  confirmResumeSwarmRunSave,
  fetchArtifactLatexPdf,
  generateStarterArtifacts,
  getArtifactLatexDocument,
  getJobArtifacts,
  getJobEvents,
  getProfile,
  prewarmJobCache,
  getResumeSwarmRunStatus,
  startCoverLetterSwarmRun,
  startResumeSwarmRun,
  getTemplatesByType,
  patchTracking,
  recompileArtifactLatexDocument,
  saveArtifactLatexDocument,
  suppressJob,
  validateTemplate,
} from "../api";
import type { ArtifactSummary, CandidateProfile, JobDetail, JobEvent } from "../types";
import { DetailDrawer } from "../components/DetailDrawer";
import { ThemedLoader } from "../components/ThemedLoader";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "../components/ui/alert-dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Badge } from "../components/ui/badge";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { Progress } from "../components/ui/progress";

type ArtifactKind = "resume" | "cover_letter";

type CompileDiagnostic = {
  severity: string;
  file: string;
  line: number;
  message: string;
  raw: string;
};

type SwarmRunStatus =
  | "queued"
  | "running"
  | "awaiting_confirmation"
  | "saving"
  | "completed"
  | "failed"
  | "cancelled";

interface SwarmRunState {
  runId: string;
  status: SwarmRunStatus;
  currentStage: string;
  stageIndex: number;
  cyclesDone: number;
  cyclesTarget: number;
  events: Array<Record<string, unknown>>;
  latestScore: Record<string, unknown> | null;
  latestRewrite: Record<string, unknown> | null;
  latestApply: Record<string, unknown> | null;
  finalScore: Record<string, unknown> | null;
  candidateLatex: string | null;
  error: string | null;
}

interface ResumeLatexEditorPageProps {
  defaultArtifactType?: ArtifactKind;
}

const SWARM_TIMELINE_FILTER_KEY = "swarm_timeline_filter_v1";

type SwarmEvent = {
  ts?: string;
  seq?: number;
  stage?: string;
  message?: string;
  data?: Record<string, unknown>;
};

type EvidenceChunk = {
  chunk_id: string;
  source_type: string;
  source_key: string;
  score: number | null;
  text: string;
};

type DecideTelemetry = {
  scoreDelta: number | null;
  remainingNonNegotiables: number;
  remainingExpectedGain: number;
  changedRatio: number;
  lowDeltaStop: boolean;
  budgetStop: boolean;
  forceContinue: boolean;
};

function normalizeArtifactType(raw: string | undefined): ArtifactKind {
  const next = (raw || "resume").trim().toLowerCase();
  return next === "cover_letter" ? "cover_letter" : "resume";
}

function toDiagnostics(value: unknown): CompileDiagnostic[] {
  if (!Array.isArray(value)) return [];
  const out: CompileDiagnostic[] = [];
  for (const item of value) {
    if (!item || typeof item !== "object") continue;
    const entry = item as Record<string, unknown>;
    const lineRaw = entry.line;
    const line = typeof lineRaw === "number" ? lineRaw : Number(lineRaw ?? 0);
    out.push({
      severity: String(entry.severity ?? "warning"),
      file: String(entry.file ?? "source.tex"),
      line: Number.isFinite(line) ? Math.max(1, Math.floor(line)) : 1,
      message: String(entry.message ?? ""),
      raw: String(entry.raw ?? ""),
    });
  }
  return out;
}

function stageLabel(stage: string): string {
  const normalized = stage.trim().toLowerCase();
  if (normalized === "evidence_retrieval") return "Evidence Retrieval";
  if (normalized === "prepare_edit_context") return "Edit Context";
  if (normalized === "verify_moves") return "Move Verification";
  if (normalized === "final_score") return "Final Score";
  if (normalized === "decide_next") return "Cycle Decision";
  if (normalized === "preview_ready") return "Preview Ready";
  return normalized
    .split("_")
    .filter(Boolean)
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
}

function runStatusLabel(status: string): string {
  const normalized = status.trim().toLowerCase();
  if (normalized === "awaiting_confirmation") return "Review Ready";
  if (normalized === "queued") return "Queued";
  if (normalized === "running") return "Running";
  if (normalized === "saving") return "Saving";
  if (normalized === "completed") return "Completed";
  if (normalized === "failed") return "Failed";
  if (normalized === "cancelled") return "Stopped";
  return status;
}

function extractEvidenceChunks(data: Record<string, unknown> | null | undefined): EvidenceChunk[] {
  if (!data) return [];
  const pack = data.evidence_pack;
  if (!pack || typeof pack !== "object") return [];
  const chunksRaw = (pack as Record<string, unknown>).selected_chunks;
  if (!Array.isArray(chunksRaw)) return [];
  const chunks: EvidenceChunk[] = [];
  for (const item of chunksRaw) {
    if (!item || typeof item !== "object") continue;
    const row = item as Record<string, unknown>;
    const scoreRaw = row.score;
    const score = typeof scoreRaw === "number" ? scoreRaw : Number(scoreRaw ?? NaN);
    chunks.push({
      chunk_id: String(row.chunk_id ?? ""),
      source_type: String(row.source_type ?? "evidence"),
      source_key: String(row.source_key ?? ""),
      score: Number.isFinite(score) ? score : null,
      text: String(row.text ?? ""),
    });
  }
  return chunks;
}

function extractDecideTelemetry(data: Record<string, unknown> | null | undefined): DecideTelemetry | null {
  if (!data) return null;
  const scoreDeltaRaw = data.score_delta;
  const scoreDeltaNum = typeof scoreDeltaRaw === "number" ? scoreDeltaRaw : Number(scoreDeltaRaw ?? NaN);
  const remainingNonNegotiables = Number(data.remaining_non_negotiables ?? 0);
  const remainingExpectedGain = Number(data.remaining_expected_gain ?? 0);
  const changedRatio = Number(data.changed_ratio ?? 0);
  const lowDeltaStop = Boolean(data.low_delta_stop);
  const budgetStop = Boolean(data.budget_stop);
  const forceContinue = Boolean(data.force_continue);
  return {
    scoreDelta: Number.isFinite(scoreDeltaNum) ? scoreDeltaNum : null,
    remainingNonNegotiables: Number.isFinite(remainingNonNegotiables) ? remainingNonNegotiables : 0,
    remainingExpectedGain: Number.isFinite(remainingExpectedGain) ? remainingExpectedGain : 0,
    changedRatio: Number.isFinite(changedRatio) ? changedRatio : 0,
    lowDeltaStop,
    budgetStop,
    forceContinue,
  };
}

export function ResumeLatexEditorPage({ defaultArtifactType }: ResumeLatexEditorPageProps = {}) {
  const params = useParams();
  const navigate = useNavigate();
  const jobId = params.jobId ?? "";
  const artifactType = defaultArtifactType ?? normalizeArtifactType(params.artifactType);

  const editorRef = useRef<MonacoEditor.IStandaloneCodeEditor | null>(null);
  const decorationIdsRef = useRef<string[]>([]);

  const [loading, setLoading] = useState(true);
  const [artifact, setArtifact] = useState<ArtifactSummary | null>(null);
  const [sourceText, setSourceText] = useState("");
  const [savedText, setSavedText] = useState("");
  const [templateId, setTemplateId] = useState("classic");
  const [templates, setTemplates] = useState<Array<{ id: string; name: string }>>([]);
  const [templateWarnings, setTemplateWarnings] = useState<string[]>([]);
  const [compileStatus, setCompileStatus] = useState("never");
  const [compileError, setCompileError] = useState<string | null>(null);
  const [logTail, setLogTail] = useState<string | null>(null);
  const [compiledAt, setCompiledAt] = useState<string | null>(null);
  const [diagnostics, setDiagnostics] = useState<CompileDiagnostic[]>([]);
  const [saving, setSaving] = useState(false);
  const [compiling, setCompiling] = useState(false);
  const [optimizing, setOptimizing] = useState(false);
  const [aiRunModalOpen, setAiRunModalOpen] = useState(false);
  const [swarmRun, setSwarmRun] = useState<SwarmRunState | null>(null);
  const [swarmRunId, setSwarmRunId] = useState<string | null>(null);
  const [aiRunConfirmSaving, setAiRunConfirmSaving] = useState(false);
  const [timelineFilter, setTimelineFilter] = useState<"all" | "evidence">(() => {
    if (typeof window === "undefined") return "all";
    const raw = window.localStorage.getItem(SWARM_TIMELINE_FILTER_KEY);
    return raw === "evidence" ? "evidence" : "all";
  });
  const [leaveOpen, setLeaveOpen] = useState(false);
  const [pendingLeave, setPendingLeave] = useState<string | null>(null);
  const [jobDrawerOpen, setJobDrawerOpen] = useState(false);
  const [jobDrawerLoading, setJobDrawerLoading] = useState(false);
  const [jobDetail, setJobDetail] = useState<JobDetail | null>(null);
  const [jobEvents, setJobEvents] = useState<JobEvent[]>([]);
  const [jobProfile, setJobProfile] = useState<CandidateProfile | null>(null);
  const [jobArtifacts, setJobArtifacts] = useState<ArtifactSummary[]>([]);

  const isDirty = sourceText !== savedText;
  const noun = artifactType === "resume" ? "Resume" : "Cover Letter";

  const pdfUrl = useMemo(() => {
    if (!artifact?.id || compileStatus !== "ok") return null;
    const stamp = compiledAt ? encodeURIComponent(compiledAt) : Date.now();
    return `${import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000"}/api/artifacts/${encodeURIComponent(artifact.id)}/latex/pdf?t=${stamp}`;
  }, [artifact?.id, compileStatus, compiledAt]);

  useEffect(() => {
    const handler = (event: BeforeUnloadEvent) => {
      if (!isDirty) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isDirty]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const [list, templateOptions] = await Promise.all([getJobArtifacts(jobId), getTemplatesByType(artifactType)]);
        if (cancelled) return;
        setTemplates(templateOptions);
        let current = list.find((item) => item.artifact_type === artifactType) ?? null;
        if (!current) {
          const created = await generateStarterArtifacts(jobId, false);
          current = created.find((item) => item.artifact_type === artifactType) ?? null;
        }
        if (!current) {
          throw new Error(`${noun} artifact could not be created.`);
        }
        const document = await getArtifactLatexDocument(current.id);
        if (cancelled) return;
        setArtifact(current);
        setSourceText(document.source_text);
        setSavedText(document.source_text);
        setTemplateId(document.template_id || "classic");
        setCompileStatus(document.compile_status);
        setCompileError(document.compile_error);
        setLogTail(document.log_tail);
        setCompiledAt(document.compiled_at);
        setDiagnostics(toDiagnostics(document.diagnostics));
        void prewarmJobCache(jobId).catch(() => undefined);
      } catch (error) {
        toast.error(error instanceof Error ? error.message : `Failed to load ${noun.toLowerCase()} editor`);
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [jobId, artifactType, noun]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(SWARM_TIMELINE_FILTER_KEY, timelineFilter);
  }, [timelineFilter]);

  useEffect(() => {
    let cancelled = false;
    async function runValidation() {
      if (!templateId) {
        setTemplateWarnings([]);
        return;
      }
      try {
        const result = await validateTemplate(artifactType, templateId);
        if (cancelled) return;
        setTemplateWarnings(result.warnings ?? []);
      } catch {
        if (!cancelled) setTemplateWarnings([]);
      }
    }
    void runValidation();
    return () => {
      cancelled = true;
    };
  }, [artifactType, templateId]);

  async function loadDrawerData(): Promise<void> {
    if (!jobId) return;
    setJobDrawerLoading(true);
    try {
      const [detail, events, profile, artifacts] = await Promise.all([
        getJobDetail(jobId),
        getJobEvents(jobId),
        getProfile(),
        getJobArtifacts(jobId),
      ]);
      setJobDetail(detail);
      setJobEvents(events);
      setJobProfile(profile);
      setJobArtifacts(artifacts);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to load job details");
    } finally {
      setJobDrawerLoading(false);
    }
  }

  async function handleSave(): Promise<boolean> {
    if (!artifact) return false;
    try {
      setSaving(true);
      await saveArtifactLatexDocument(artifact.id, {
        source_text: sourceText,
        template_id: templateId,
        label: "draft",
      });
      setSavedText(sourceText);
      setCompileStatus("never");
      setCompileError(null);
      setDiagnostics([]);
      toast.success("Draft saved");
      return true;
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to save draft");
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function handleRecompile(): Promise<void> {
    if (!artifact) return;
    try {
      setCompiling(true);
      const doc = await recompileArtifactLatexDocument(artifact.id, {
        source_text: sourceText,
        template_id: templateId,
      });
      setSavedText(sourceText);
      setCompileStatus(doc.compile_status);
      setCompileError(doc.compile_error);
      setLogTail(doc.log_tail);
      setCompiledAt(doc.compiled_at);
      setDiagnostics(toDiagnostics(doc.diagnostics));
      if (doc.compile_status === "ok") {
        toast.success("Recompiled successfully");
      } else {
        toast.error("Compile failed. Check diagnostics below.");
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Compile failed");
    } finally {
      setCompiling(false);
    }
  }

  async function handleDownload(): Promise<void> {
    if (!artifact) return;
    try {
      const blob = await fetchArtifactLatexPdf(artifact.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${artifactType.replace("_", "-")}-${artifact.id}.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Download failed");
    }
  }

  async function handleSwarmOptimize(): Promise<void> {
    if (!artifact) return;
    try {
      setOptimizing(true);
      const started = artifactType === "resume"
        ? await startResumeSwarmRun(artifact.id, { cycles: 2, source_text: sourceText, template_id: templateId })
        : await startCoverLetterSwarmRun(artifact.id, { cycles: 2, source_text: sourceText, template_id: templateId });
      setSwarmRunId(started.run_id);
      setSwarmRun(null);
      setAiRunModalOpen(true);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "AI rewrite failed");
    } finally {
      setOptimizing(false);
    }
  }

  async function openJobDrawer(): Promise<void> {
    setJobDrawerOpen(true);
    if (!jobDetail) {
      await loadDrawerData();
    }
  }

  useEffect(() => {
    if (!artifact || !swarmRunId || !aiRunModalOpen) return;
    let cancelled = false;
    let timer: number | null = null;
    const poll = async () => {
      try {
        const status = artifactType === "resume"
          ? await getResumeSwarmRunStatus(artifact.id, swarmRunId)
          : await getCoverLetterSwarmRunStatus(artifact.id, swarmRunId);
        if (cancelled) return;
        setSwarmRun({
          runId: status.run_id,
          status: status.status as SwarmRunStatus,
          currentStage: status.current_stage,
          stageIndex: status.stage_index,
          cyclesDone: status.cycles_done,
          cyclesTarget: status.cycles_target,
          events: status.events ?? [],
          latestScore: status.latest_score ?? null,
          latestRewrite: status.latest_rewrite ?? null,
          latestApply: status.latest_apply_report ?? null,
          finalScore: status.final_score ?? null,
          candidateLatex: status.candidate_latex ?? null,
          error: status.error ?? null,
        });
        const terminal = ["awaiting_confirmation", "completed", "failed", "cancelled"].includes(status.status);
        if (!terminal) {
          timer = window.setTimeout(() => void poll(), 700);
        }
      } catch {
        if (!cancelled) {
          timer = window.setTimeout(() => void poll(), 1200);
        }
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [artifact, artifactType, swarmRunId, aiRunModalOpen]);

  async function handleCancelSwarmRun(): Promise<void> {
    if (!artifact || !swarmRunId) return;
    try {
      if (artifactType === "resume") {
        await cancelResumeSwarmRun(artifact.id, swarmRunId);
      } else {
        await cancelCoverLetterSwarmRun(artifact.id, swarmRunId);
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to cancel run");
    }
  }

  async function handleConfirmAiSave(): Promise<void> {
    if (!artifact || !swarmRunId) return;
    try {
      setAiRunConfirmSaving(true);
      const result = artifactType === "resume"
        ? await confirmResumeSwarmRunSave(artifact.id, swarmRunId, { created_by: "ui", label: "draft" })
        : await confirmCoverLetterSwarmRunSave(artifact.id, swarmRunId, { created_by: "ui", label: "draft" });
      const refreshed = await getArtifactLatexDocument(artifact.id);
      const recompiled = await recompileArtifactLatexDocument(artifact.id, {
        source_text: refreshed.source_text,
        template_id: refreshed.template_id || templateId,
      });
      setSourceText(recompiled.source_text);
      setSavedText(recompiled.source_text);
      setCompileStatus(recompiled.compile_status);
      setCompileError(recompiled.compile_error);
      setLogTail(recompiled.log_tail);
      setCompiledAt(recompiled.compiled_at);
      setDiagnostics(toDiagnostics(recompiled.diagnostics));
      setAiRunModalOpen(false);
      const total = Number(result.final_score?.Total_Score ?? 0);
      toast.success(`Saved AI-optimized ${noun.toLowerCase()} draft v${result.version}. Score: ${total}/100`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to save AI draft");
    } finally {
      setAiRunConfirmSaving(false);
    }
  }

  async function copyCitationId(value: string): Promise<void> {
    const next = value.trim();
    if (!next) return;
    try {
      await navigator.clipboard.writeText(next);
      toast.success(`Copied citation: ${next}`);
    } catch {
      toast.error("Unable to copy citation ID");
    }
  }

  function requestLeave(target: string): void {
    if (!isDirty) {
      navigate(target);
      return;
    }
    setPendingLeave(target);
    setLeaveOpen(true);
  }

  async function saveAndLeave(): Promise<void> {
    const ok = await handleSave();
    if (!ok) return;
    setLeaveOpen(false);
    if (pendingLeave) {
      navigate(pendingLeave);
    }
  }

  function jumpToDiagnostic(line: number): void {
    const editor = editorRef.current;
    if (!editor) return;
    const lineNumber = Math.max(1, Math.floor(line));
    editor.revealLineInCenter(lineNumber);
    editor.setPosition({ lineNumber, column: 1 });
    editor.focus();
    decorationIdsRef.current = editor.deltaDecorations(decorationIdsRef.current, [
      {
        range: {
          startLineNumber: lineNumber,
          startColumn: 1,
          endLineNumber: lineNumber,
          endColumn: 1,
        },
        options: {
          isWholeLine: true,
          className: "latex-line-highlight",
          glyphMarginClassName: "latex-line-highlight-glyph",
        },
      },
    ]);
  }

  if (loading) {
    return <ThemedLoader label={`Loading ${noun.toLowerCase()} editor`} />;
  }

  const estimatedStageCount = swarmRun
    ? artifactType === "resume"
      ? (swarmRun.cyclesTarget * 6) + 3
      : (swarmRun.cyclesTarget * 7) + 6
    : 0;
  const runProgress = swarmRun
    ? Math.max(2, Math.min(100, Math.round((swarmRun.stageIndex / Math.max(1, estimatedStageCount)) * 100)))
    : 0;
  const baselineScore = Number((swarmRun?.events ?? [])
    .map((event) => (event?.data && typeof event.data === "object" ? (event.data as Record<string, unknown>) : null))
    .map((data) => Number((data?.score as Record<string, unknown> | undefined)?.Total_Score ?? NaN))
    .find((value) => Number.isFinite(value)) ?? NaN);
  const latestScore = Number(swarmRun?.finalScore?.Total_Score ?? swarmRun?.latestScore?.Total_Score ?? NaN);
  const scoreDelta = Number.isFinite(baselineScore) && Number.isFinite(latestScore) ? latestScore - baselineScore : null;
  const rewriteMoves = Array.isArray((swarmRun?.latestRewrite as Record<string, unknown> | null)?.moves)
    ? ((swarmRun?.latestRewrite as Record<string, unknown>).moves as Array<Record<string, unknown>>)
    : [];
  const applySummary = (swarmRun?.latestApply as Record<string, unknown> | null) ?? null;
  const appliedMoves = Array.isArray(applySummary?.applied_moves)
    ? (applySummary?.applied_moves as Array<Record<string, unknown>>)
    : [];
  const failedMoves = Array.isArray(applySummary?.failed_moves)
    ? (applySummary?.failed_moves as Array<Record<string, unknown>>)
    : [];
  const policyFailures = failedMoves.filter((item) => typeof item.policy_reason === "string");
  const policyFailureCounts = policyFailures.reduce<Record<string, number>>((acc, item) => {
    const key = String(item.policy_reason ?? "unknown");
    acc[key] = (acc[key] ?? 0) + 1;
    return acc;
  }, {});
  const timelineEvents = ((swarmRun?.events ?? []) as SwarmEvent[]).map((event, index) => {
    const data = event.data && typeof event.data === "object" ? event.data : undefined;
    const chunks = extractEvidenceChunks(data);
    const decideTelemetry = extractDecideTelemetry(data);
    return {
      key: `${event.seq ?? index}-${event.ts ?? index}-${event.stage ?? "stage"}`,
      ts: String(event.ts ?? ""),
      seq: Number(event.seq ?? index + 1),
      stage: String(event.stage ?? "stage"),
      message: String(event.message ?? ""),
      data,
      evidenceChunks: chunks,
      decideTelemetry,
    };
  });
  const filteredTimelineEvents = timelineFilter === "evidence"
    ? timelineEvents.filter((event) => event.evidenceChunks.length > 0)
    : timelineEvents;
  const latestEvidenceEvent = [...timelineEvents].reverse().find((event) => event.evidenceChunks.length > 0) ?? null;
  const latestTargetSpecEvent = [...timelineEvents].reverse().find((event) => event.data?.jd_target_spec && typeof event.data.jd_target_spec === "object") ?? null;
  const latestPlanEvent = [...timelineEvents].reverse().find((event) => event.data?.edit_plan && typeof event.data.edit_plan === "object") ?? null;
  const latestNarrativePlanEvent = [...timelineEvents].reverse().find((event) => event.data?.narrative_plan && typeof event.data.narrative_plan === "object") ?? null;
  const latestToneGuardEvent = [...timelineEvents].reverse().find((event) => event.data?.tone_guard && typeof event.data.tone_guard === "object") ?? null;
  const evidenceChunks = latestEvidenceEvent?.evidenceChunks ?? [];
  const evidenceSources = latestEvidenceEvent?.data?.evidence_pack && typeof latestEvidenceEvent.data.evidence_pack === "object"
    ? ((latestEvidenceEvent.data.evidence_pack as Record<string, unknown>).sources as Record<string, unknown> | undefined)
    : undefined;
  const evidenceAlgorithm = latestEvidenceEvent?.data?.evidence_pack && typeof latestEvidenceEvent.data.evidence_pack === "object"
    ? String((latestEvidenceEvent.data.evidence_pack as Record<string, unknown>).algorithm ?? "")
    : "";
  const latestDecideTelemetry = [...timelineEvents].reverse().find((event) => event.stage === "decide_next" && event.decideTelemetry)?.decideTelemetry ?? null;
  const latestTargetSpec = latestTargetSpecEvent?.data?.jd_target_spec && typeof latestTargetSpecEvent.data.jd_target_spec === "object"
    ? latestTargetSpecEvent.data.jd_target_spec as Record<string, unknown>
    : null;
  const latestEditPlan = latestPlanEvent?.data?.edit_plan && typeof latestPlanEvent.data.edit_plan === "object"
    ? latestPlanEvent.data.edit_plan as Record<string, unknown>
    : null;
  const latestNarrativePlan = latestNarrativePlanEvent?.data?.narrative_plan && typeof latestNarrativePlanEvent.data.narrative_plan === "object"
    ? latestNarrativePlanEvent.data.narrative_plan as Record<string, unknown>
    : null;
  const latestToneGuard = latestToneGuardEvent?.data?.tone_guard && typeof latestToneGuardEvent.data.tone_guard === "object"
    ? latestToneGuardEvent.data.tone_guard as Record<string, unknown>
    : null;
  const gateReason = (() => {
    if (!latestDecideTelemetry) return null;
    if (latestDecideTelemetry.forceContinue) return "Forced cycle due to remaining non-negotiables";
    if (latestDecideTelemetry.budgetStop) return "Stopped by edit budget gate";
    if (latestDecideTelemetry.lowDeltaStop) return "Stopped by low score-delta gate";
    return "Continuing to next cycle";
  })();
  const hashBefore = typeof applySummary?.doc_version_hash_before === "string" ? applySummary.doc_version_hash_before : "";
  const hashAfter = typeof applySummary?.doc_version_hash_after === "string" ? applySummary.doc_version_hash_after : "";

  return (
    <section className="latex-resume-page">
      <header className="latex-resume-header">
        <div>
          <Button variant="default" onClick={() => requestLeave("/artifacts")}>Back</Button>
          <h1>{noun} (LaTeX)</h1>
          <p className="muted">Manual save + manual recompile workflow</p>
        </div>
        <div className="latex-resume-actions">
          <Button variant="default" onClick={() => void openJobDrawer()}>
            View JD
          </Button>
          <Select value={templateId} onValueChange={setTemplateId}>
            <SelectTrigger className="w-[210px]">
              <SelectValue placeholder="Template" />
            </SelectTrigger>
            <SelectContent>
              {templates.map((item) => (
                <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="warn" onClick={handleDownload} disabled={!artifact || compileStatus !== "ok"}>Download PDF</Button>
          <Button variant="default" onClick={handleSwarmOptimize} disabled={!artifact || optimizing || saving || compiling}>
            {optimizing ? "Rewriting..." : "AI Rewrite"}
          </Button>
          <Button variant="primary" onClick={() => void handleSave()} disabled={saving}>{saving ? "Saving..." : "Save Draft"}</Button>
          <Button variant="success" onClick={handleRecompile} disabled={compiling}>{compiling ? "Compiling..." : "Recompile"}</Button>
        </div>
      </header>
      <div className="latex-resume-status-row">
        <Badge>{isDirty ? "Unsaved changes" : "Saved"}</Badge>
        <Badge>{`Compile: ${compileStatus}`}</Badge>
        {compileError ? <Badge className="kanban-pill-danger">{compileError}</Badge> : null}
      </div>
      {templateWarnings.length > 0 ? (
        <div className="latex-template-warnings" role="status" aria-live="polite">
          {templateWarnings.map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
        </div>
      ) : null}
      <div className="latex-resume-grid">
        <Card className="latex-editor-card">
          <CardHeader>
            <CardTitle>LaTeX Source</CardTitle>
          </CardHeader>
          <CardContent>
            <Editor
              height="72vh"
              language="latex"
              beforeMount={(monaco: typeof Monaco) => {
                registerLaTeXLanguage(monaco);
              }}
              value={sourceText}
              onMount={(editor) => {
                editorRef.current = editor;
              }}
              onChange={(value) => setSourceText(value ?? "")}
              theme="vs-dark"
              options={{
                minimap: { enabled: false },
                wordWrap: "on",
                fontSize: 14,
                scrollBeyondLastLine: false,
              }}
            />
          </CardContent>
        </Card>
        <Card className="latex-preview-card">
          <CardHeader>
            <CardTitle>Compiled PDF Preview</CardTitle>
          </CardHeader>
          <CardContent>
            {pdfUrl ? (
              <iframe title={`${noun} PDF preview`} src={pdfUrl} className="latex-pdf-frame" />
            ) : (
              <div className="latex-preview-empty">
                <p>No compiled PDF yet.</p>
                <p>Click <strong>Recompile</strong> to generate preview.</p>
              </div>
            )}
            {diagnostics.length > 0 ? (
              <div className="latex-diagnostics-panel">
                <h3>Compile diagnostics</h3>
                <ul>
                  {diagnostics.map((diag, index) => (
                    <li key={`${diag.file}:${diag.line}:${index}`}>
                      <button type="button" onClick={() => jumpToDiagnostic(diag.line)}>
                        <span>{diag.severity.toUpperCase()}</span>
                        <span>{diag.file}:{diag.line}</span>
                        <span>{diag.message}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : logTail ? (
              <details className="latex-log">
                <summary>Compile diagnostics</summary>
                <pre>{logTail}</pre>
              </details>
            ) : null}
          </CardContent>
        </Card>
      </div>

      <Dialog open={aiRunModalOpen} onOpenChange={(next) => {
        if (swarmRun && ["running", "queued", "saving"].includes(swarmRun.status) && !next) return;
        setAiRunModalOpen(next);
      }}>
        <DialogContent className="max-w-5xl">
          <DialogHeader>
            <DialogTitle>{artifactType === "resume" ? "Resume AI Rewrite" : "Cover Letter AI Rewrite"}</DialogTitle>
          </DialogHeader>
          <div className="resume-swarm-modal-body">
            <div className="resume-swarm-status-row">
              <Badge>{runStatusLabel(swarmRun?.status ?? "starting")}</Badge>
              <Badge>{stageLabel(swarmRun?.currentStage ?? "queued")}</Badge>
              {Number.isFinite(latestScore) ? <Badge>{`Score ${latestScore}/100`}</Badge> : null}
              {scoreDelta !== null ? <Badge>{`Delta ${scoreDelta >= 0 ? "+" : ""}${scoreDelta}`}</Badge> : null}
              {gateReason ? <Badge>{gateReason}</Badge> : null}
            </div>
            <Progress value={runProgress} />
            <div className="resume-swarm-grid">
              <section className="resume-swarm-events">
                <div className="resume-swarm-events-header">
                  <h3>AI Timeline</h3>
                  <div className="resume-swarm-events-filters">
                    <Button
                      type="button"
                      size="compact"
                      variant={timelineFilter === "all" ? "primary" : "default"}
                      onClick={() => setTimelineFilter("all")}
                    >
                      All
                    </Button>
                    <Button
                      type="button"
                      size="compact"
                      variant={timelineFilter === "evidence" ? "primary" : "default"}
                      onClick={() => setTimelineFilter("evidence")}
                    >
                      Evidence Only
                    </Button>
                  </div>
                </div>
                <div className="resume-swarm-events-list">
                  {filteredTimelineEvents.map((event) => (
                    <article key={event.key} className="resume-swarm-event-item">
                      <div className="resume-swarm-event-meta">
                        <p className="resume-swarm-event-stage">{stageLabel(event.stage)}</p>
                        <span>{`#${event.seq}`}</span>
                      </div>
                      <p>{event.message}</p>
                      {event.data?.jd_target_spec && typeof event.data.jd_target_spec === "object" ? (
                        <div className="resume-swarm-gate-telemetry">
                          {Object.entries(event.data.jd_target_spec as Record<string, unknown>).slice(0, 4).map(([key, value]) => (
                            <span key={`${event.key}-${key}`}>
                              {Array.isArray(value) ? `${key}: ${value.length}` : `${key}: ${String(value).slice(0, 48)}`}
                            </span>
                          ))}
                        </div>
                      ) : null}
                      {event.data?.edit_plan && typeof event.data.edit_plan === "object" ? (
                        <div className="resume-swarm-gate-telemetry">
                          <span>{`Planned fixes: ${Array.isArray((event.data.edit_plan as Record<string, unknown>).selected_fixes) ? ((event.data.edit_plan as Record<string, unknown>).selected_fixes as unknown[]).length : 0}`}</span>
                          <span>{`Deferred: ${Array.isArray((event.data.edit_plan as Record<string, unknown>).deferred_fix_ids) ? ((event.data.edit_plan as Record<string, unknown>).deferred_fix_ids as unknown[]).length : 0}`}</span>
                        </div>
                      ) : null}
                      {event.data?.tone_guard && typeof event.data.tone_guard === "object" ? (
                        <div className="resume-swarm-gate-telemetry">
                          <span>{`Triggered: ${Boolean((event.data.tone_guard as Record<string, unknown>).triggered) ? "yes" : "no"}`}</span>
                          <span>{`Signals: ${Array.isArray((event.data.tone_guard as Record<string, unknown>).reasons) ? ((event.data.tone_guard as Record<string, unknown>).reasons as unknown[]).length : 0}`}</span>
                        </div>
                      ) : null}
                      {event.evidenceChunks.length > 0 ? (
                        <div className="resume-swarm-citations">
                          {event.evidenceChunks.slice(0, 4).map((chunk) => (
                            <article key={`${event.key}-${chunk.chunk_id || chunk.source_key}`} className="resume-swarm-citation">
                              <div className="resume-swarm-citation-meta">
                                <strong>{chunk.chunk_id || "chunk"}</strong>
                                {chunk.chunk_id ? (
                                  <Button
                                    type="button"
                                    size="compact"
                                    variant="default"
                                    onClick={() => void copyCitationId(chunk.chunk_id)}
                                  >
                                    Copy ID
                                  </Button>
                                ) : null}
                                <span>{`${chunk.source_type}${chunk.source_key ? ` · ${chunk.source_key}` : ""}`}</span>
                                {chunk.score !== null ? <span>{`score ${chunk.score.toFixed(2)}`}</span> : null}
                              </div>
                              <p>{chunk.text.slice(0, 220)}</p>
                            </article>
                          ))}
                        </div>
                      ) : null}
                      {event.stage === "decide_next" && event.decideTelemetry ? (
                        <div className="resume-swarm-gate-telemetry">
                          <span>{`Delta: ${event.decideTelemetry.scoreDelta === null ? "n/a" : event.decideTelemetry.scoreDelta >= 0 ? `+${event.decideTelemetry.scoreDelta}` : event.decideTelemetry.scoreDelta}`}</span>
                          <span>{`Non-negotiables: ${event.decideTelemetry.remainingNonNegotiables}`}</span>
                          <span>{`Expected gain: ${event.decideTelemetry.remainingExpectedGain}`}</span>
                          <span>{`Changed ratio: ${(event.decideTelemetry.changedRatio * 100).toFixed(1)}%`}</span>
                          {event.decideTelemetry.lowDeltaStop ? <Badge className="kanban-pill-warning">low-delta-stop</Badge> : null}
                          {event.decideTelemetry.budgetStop ? <Badge className="kanban-pill-danger">budget-stop</Badge> : null}
                          {event.decideTelemetry.forceContinue ? <Badge className="kanban-pill-success">force-continue</Badge> : null}
                        </div>
                      ) : null}
                    </article>
                  ))}
                </div>
              </section>
              <section className="resume-swarm-panels">
                <article className="resume-swarm-panel">
                  <h4>Retrieved Evidence</h4>
                  {evidenceAlgorithm ? (
                    <div className="resume-swarm-apply-summary">
                      <Badge>{`Algorithm: ${evidenceAlgorithm}`}</Badge>
                      {evidenceSources ? (
                        Object.entries(evidenceSources).map(([key, value]) => (
                          <Badge key={key}>{`${key}: ${String(value)}`}</Badge>
                        ))
                      ) : null}
                    </div>
                  ) : null}
                  {evidenceChunks.length > 0 ? (
                    <ul className="resume-swarm-move-list">
                      {evidenceChunks.slice(0, 6).map((chunk) => (
                        <li key={`evidence-${chunk.chunk_id || chunk.source_key}`}>
                          <div className="resume-swarm-inline-actions">
                            <strong>{chunk.chunk_id || "chunk"}</strong>
                            {chunk.chunk_id ? (
                              <Button
                                type="button"
                                size="compact"
                                variant="default"
                                onClick={() => void copyCitationId(chunk.chunk_id)}
                              >
                                Copy
                              </Button>
                            ) : null}
                          </div>
                          <span>{`${chunk.source_type}${chunk.source_key ? ` · ${chunk.source_key}` : ""}`}</span>
                          <span>{chunk.text.slice(0, 180)}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="muted">No evidence snippets surfaced yet.</p>
                  )}
                </article>
                <article className="resume-swarm-panel">
                  <h4>Target Spec</h4>
                  {latestTargetSpec ? (
                    <pre>{JSON.stringify(latestTargetSpec, null, 2)}</pre>
                  ) : (
                    <p className="muted">Waiting for JD decomposition...</p>
                  )}
                </article>
                {artifactType === "cover_letter" ? (
                  <article className="resume-swarm-panel">
                    <h4>Narrative Plan</h4>
                    {latestNarrativePlan ? (
                      <pre>{JSON.stringify(latestNarrativePlan, null, 2)}</pre>
                    ) : (
                      <p className="muted">Waiting for narrative planner...</p>
                    )}
                  </article>
                ) : null}
                <article className="resume-swarm-panel">
                  <h4>Edit Plan</h4>
                  {latestEditPlan ? (
                    <pre>{JSON.stringify(latestEditPlan, null, 2)}</pre>
                  ) : (
                    <p className="muted">Waiting for edit planner...</p>
                  )}
                </article>
                <article className="resume-swarm-panel">
                  <h4>Latest Score</h4>
                  {swarmRun?.latestScore ? (
                    <pre>{JSON.stringify(swarmRun.latestScore, null, 2)}</pre>
                  ) : (
                    <p className="muted">Waiting for scoring result...</p>
                  )}
                </article>
                <article className="resume-swarm-panel">
                  <h4>Latest AI Rewrite</h4>
                  {swarmRun?.latestRewrite ? (
                    <>
                      {rewriteMoves.length > 0 ? (
                        <ul className="resume-swarm-move-list">
                          {rewriteMoves.map((move, idx) => (
                            <li key={`move-${idx}`}>
                              <strong>{String(move.fix_id ?? "fix")}</strong>
                              <span>{String(move.op ?? "op")}</span>
                              <div className="resume-swarm-rewrite-cell">
                                <span>{String(move.reason ?? "")}</span>
                                {Array.isArray(move.supported_by) && move.supported_by.length > 0 ? (
                                  <div className="resume-swarm-supported-by">
                                    {(move.supported_by as unknown[])
                                      .map((item) => String(item).trim())
                                      .filter(Boolean)
                                      .slice(0, 4)
                                      .map((citationId) => (
                                        <button
                                          key={`${idx}-${citationId}`}
                                          type="button"
                                          className="resume-swarm-citation-pill"
                                          onClick={() => void copyCitationId(citationId)}
                                          title={`Copy citation ${citationId}`}
                                        >
                                          {citationId}
                                        </button>
                                      ))}
                                  </div>
                                ) : null}
                              </div>
                            </li>
                          ))}
                        </ul>
                      ) : null}
                      <pre>{JSON.stringify(swarmRun.latestRewrite, null, 2)}</pre>
                    </>
                  ) : (
                    <p className="muted">Waiting for rewrite output...</p>
                  )}
                </article>
                {artifactType === "cover_letter" ? (
                  <article className="resume-swarm-panel">
                    <h4>Tone Guard</h4>
                    {latestToneGuard ? (
                      <pre>{JSON.stringify(latestToneGuard, null, 2)}</pre>
                    ) : (
                      <p className="muted">Waiting for tone guard...</p>
                    )}
                  </article>
                ) : null}
                <article className="resume-swarm-panel">
                  <h4>Latest Apply Report</h4>
                  {swarmRun?.latestApply ? (
                    <>
                      <div className="resume-swarm-apply-summary">
                        <Badge>{`Applied moves: ${appliedMoves.length}`}</Badge>
                        <Badge>{`Failed moves: ${failedMoves.length}`}</Badge>
                        <Badge>{`Policy failures: ${policyFailures.length}`}</Badge>
                      </div>
                      {Object.keys(policyFailureCounts).length > 0 ? (
                        <div className="resume-swarm-apply-summary">
                          {Object.entries(policyFailureCounts).map(([reason, count]) => (
                            <Badge key={reason} className="kanban-pill-danger">{`${reason} (${count})`}</Badge>
                          ))}
                        </div>
                      ) : null}
                      {(hashBefore || hashAfter) ? (
                        <p className="muted">{`Doc hash: ${hashBefore.slice(0, 8)} -> ${hashAfter.slice(0, 8)}`}</p>
                      ) : null}
                      {(appliedMoves.length > 0 || failedMoves.length > 0) ? (
                        <ul className="resume-swarm-move-list">
                          {appliedMoves.map((entry, idx) => (
                            <li key={`applied-${idx}`}>
                              <strong>{String(entry.fix_id ?? "fix")}</strong>
                              <span>{String(entry.op ?? "applied")}</span>
                              <span>applied</span>
                            </li>
                          ))}
                          {failedMoves.map((entry, idx) => (
                            <li key={`failed-${idx}`} className="resume-swarm-move-failed">
                              <strong>{String(entry.fix_id ?? "fix")}</strong>
                              <span>{String(entry.policy_reason ?? entry.reason ?? "failed")}</span>
                              <span>failed</span>
                            </li>
                          ))}
                        </ul>
                      ) : null}
                      <pre>{JSON.stringify(swarmRun.latestApply, null, 2)}</pre>
                    </>
                  ) : (
                    <p className="muted">Waiting for apply step...</p>
                  )}
                </article>
              </section>
            </div>
            {swarmRun?.error ? <p className="resume-swarm-error">{swarmRun.error}</p> : null}
          </div>
          <DialogFooter>
            {swarmRun && ["running", "queued"].includes(swarmRun.status) ? (
              <Button variant="danger" onClick={() => void handleCancelSwarmRun()}>Stop Rewrite</Button>
            ) : null}
            {swarmRun?.status === "awaiting_confirmation" ? (
              <>
                <Button variant="default" onClick={() => setAiRunModalOpen(false)}>Close Preview</Button>
                <Button variant="primary" onClick={() => void handleConfirmAiSave()} disabled={aiRunConfirmSaving}>
                  {aiRunConfirmSaving ? "Saving..." : "Save AI Draft"}
                </Button>
              </>
            ) : null}
            {swarmRun && ["failed", "cancelled", "completed"].includes(swarmRun.status) ? (
              <Button variant="default" onClick={() => setAiRunModalOpen(false)}>Close</Button>
            ) : null}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={leaveOpen} onOpenChange={setLeaveOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>You have unsaved changes</AlertDialogTitle>
            <AlertDialogDescription>
              Save your LaTeX draft before leaving this page?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setPendingLeave(null)}>Stay</AlertDialogCancel>
            <AlertDialogAction onClick={() => {
              setLeaveOpen(false);
              if (pendingLeave) {
                navigate(pendingLeave);
              }
            }}>
              Leave without saving
            </AlertDialogAction>
            <Button variant="primary" onClick={() => void saveAndLeave()}>
              Save and leave
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <DetailDrawer
        open={jobDrawerOpen}
        loading={jobDrawerLoading}
        job={jobDetail}
        profile={jobProfile}
        events={jobEvents}
        artifacts={jobArtifacts}
        artifactsLoading={jobDrawerLoading}
        artifactsGenerating={false}
        onClose={() => setJobDrawerOpen(false)}
        onAddSkillToProfile={async (skill) => {
          await addProfileSkill(skill);
          const profile = await getProfile();
          setJobProfile(profile);
        }}
        onDeleteJob={async (nextJobId) => {
          await deleteJob(nextJobId);
          toast.success("Job deleted");
          setJobDrawerOpen(false);
          navigate("/artifacts");
        }}
        onSuppressJob={async (nextJobId, reason) => {
          await suppressJob(nextJobId, reason);
          toast.success("Job suppressed");
          setJobDrawerOpen(false);
          navigate("/artifacts");
        }}
        onGenerateArtifacts={async (nextJobId) => {
          const artifacts = await generateStarterArtifacts(nextJobId, false);
          setJobArtifacts(artifacts);
        }}
        onChangeTracking={async (patch) => {
          await patchTracking(jobId, patch);
          const detail = await getJobDetail(jobId);
          setJobDetail(detail);
        }}
      />
    </section>
  );
}
