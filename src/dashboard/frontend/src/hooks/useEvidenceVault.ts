import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { getEvidenceAssets, getEvidenceIndexStatus, getHealth, putEvidenceAssets, reindexEvidenceAssets } from "../api";
import type { AppHealthResponse, CandidateEvidenceAssets, CandidateEvidenceIndexStatus } from "../types";

export type SaveState = "idle" | "dirty" | "saving" | "saved" | "error";

export interface EvidenceIssue {
  level: "error" | "warning" | "info";
  field: "evidence_context" | "project_cards" | "brag_document_markdown" | "do_not_claim";
  message: string;
}

const EMPTY_EVIDENCE_ASSETS: CandidateEvidenceAssets = {
  evidence_context: {},
  brag_document_markdown: "",
  project_cards: [],
  do_not_claim: [],
  updated_at: null,
};

const EMPTY_EVIDENCE_INDEX_STATUS: CandidateEvidenceIndexStatus = {
  enabled: false,
  backend: "disabled",
  status: "idle",
  indexed_count: 0,
  message: "Not indexed yet.",
  updated_at: null,
  collection: null,
};

const EMPTY_HEALTH: AppHealthResponse = {
  status: "ok",
  services: {
    redis: {
      configured: false,
      healthy: false,
      message: "Unknown",
    },
    qdrant: {
      configured: false,
      healthy: false,
      message: "Unknown",
      collection: null,
      collection_exists: false,
    },
  },
};

const RECOMMENDED_EVIDENCE_KEYS = [
  "candidate_profile",
  "technical_skills",
  "work_experience",
  "selected_projects",
  "behavioral_evidence",
  "high_value_story_bank",
];

function normalizeBlockedClaims(values: string[]): string[] {
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

function parseObjectJson(value: string, errorMessage: string): { value: Record<string, unknown> | null; error: string | null } {
  try {
    const parsed = JSON.parse(value);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { value: null, error: errorMessage };
    }
    return { value: parsed as Record<string, unknown>, error: null };
  } catch {
    return { value: null, error: "Evidence context JSON is invalid." };
  }
}

function parseArrayJson(value: string, invalidMessage: string): { value: Array<Record<string, unknown>> | null; error: string | null } {
  try {
    const parsed = JSON.parse(value);
    if (!Array.isArray(parsed)) {
      return { value: null, error: invalidMessage };
    }
    return {
      value: parsed
        .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
        .map((item) => ({ ...item })),
      error: null,
    };
  } catch {
    return { value: null, error: "Project cards JSON is invalid." };
  }
}

export function useEvidenceVault() {
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [indexing, setIndexing] = useState(false);
  const [healthLoading, setHealthLoading] = useState(false);
  const [statusNotice, setStatusNotice] = useState<string | null>(null);

  const [original, setOriginal] = useState<CandidateEvidenceAssets>(EMPTY_EVIDENCE_ASSETS);
  const [draft, setDraft] = useState<CandidateEvidenceAssets>(EMPTY_EVIDENCE_ASSETS);
  const [indexStatus, setIndexStatus] = useState<CandidateEvidenceIndexStatus>(EMPTY_EVIDENCE_INDEX_STATUS);
  const [health, setHealth] = useState<AppHealthResponse>(EMPTY_HEALTH);

  const [evidenceContextInput, setEvidenceContextInput] = useState("{}");
  const [projectCardsInput, setProjectCardsInput] = useState("[]");
  const [bulkClaimsInput, setBulkClaimsInput] = useState("");

  const parsedEvidenceContext = useMemo(
    () => parseObjectJson(evidenceContextInput, "Evidence context JSON must be an object."),
    [evidenceContextInput],
  );
  const parsedProjectCards = useMemo(
    () => parseArrayJson(projectCardsInput, "Project cards JSON must be an array."),
    [projectCardsInput],
  );

  const blockedClaims = useMemo(
    () => normalizeBlockedClaims(draft.do_not_claim ?? []),
    [draft.do_not_claim],
  );

  const rawBlockedClaimCount = draft.do_not_claim.length;
  const duplicateBlockedClaimCount = Math.max(0, rawBlockedClaimCount - blockedClaims.length);

  const bragStats = useMemo(() => {
    const text = draft.brag_document_markdown ?? "";
    const headings = (text.match(/^#{1,6}\s.+$/gm) ?? []).length;
    const bullets = (text.match(/^\s*[-*]\s.+$/gm) ?? []).length;
    const chars = text.trim().length;
    const words = text.trim() ? text.trim().split(/\s+/).length : 0;
    return { headings, bullets, chars, words };
  }, [draft.brag_document_markdown]);

  const counts = useMemo(() => ({
    projectCards: parsedProjectCards.value?.length ?? draft.project_cards.length,
    blockedClaims: blockedClaims.length,
    evidenceKeys: parsedEvidenceContext.value ? Object.keys(parsedEvidenceContext.value).length : 0,
  }), [blockedClaims.length, draft.project_cards.length, parsedEvidenceContext.value, parsedProjectCards.value]);

  const evidenceFingerprint = useMemo(() => JSON.stringify({
    evidence_context: parsedEvidenceContext.value ?? draft.evidence_context ?? {},
    brag_document_markdown: draft.brag_document_markdown ?? "",
    project_cards: parsedProjectCards.value ?? draft.project_cards ?? [],
    do_not_claim: blockedClaims,
  }), [blockedClaims, draft.brag_document_markdown, draft.evidence_context, draft.project_cards, parsedEvidenceContext.value, parsedProjectCards.value]);

  const originalFingerprint = useMemo(() => JSON.stringify({
    evidence_context: original.evidence_context ?? {},
    brag_document_markdown: original.brag_document_markdown ?? "",
    project_cards: original.project_cards ?? [],
    do_not_claim: normalizeBlockedClaims(original.do_not_claim ?? []),
  }), [original]);

  const isDirty = evidenceFingerprint !== originalFingerprint;

  useEffect(() => {
    if (saveState !== "saving") {
      setSaveState(isDirty ? "dirty" : "idle");
    }
  }, [isDirty, saveState]);

  const issues = useMemo(() => {
    const next: EvidenceIssue[] = [];
    if (parsedEvidenceContext.error) {
      next.push({ level: "error", field: "evidence_context", message: parsedEvidenceContext.error });
    } else if (parsedEvidenceContext.value) {
      const keys = Object.keys(parsedEvidenceContext.value);
      if (keys.length === 0) {
        next.push({ level: "warning", field: "evidence_context", message: "Evidence context is empty. Saved indexing will produce zero chunks unless other sections are populated." });
      } else {
        const missing = RECOMMENDED_EVIDENCE_KEYS.filter((key) => !(key in parsedEvidenceContext.value!));
        if (missing.length > 0) {
          next.push({ level: "info", field: "evidence_context", message: `Recommended sections missing: ${missing.join(", ")}.` });
        }
      }
    }

    if (parsedProjectCards.error) {
      next.push({ level: "error", field: "project_cards", message: parsedProjectCards.error });
    } else if (parsedProjectCards.value) {
      if (parsedProjectCards.value.length === 0) {
        next.push({ level: "warning", field: "project_cards", message: "Project cards are empty." });
      }
      parsedProjectCards.value.slice(0, 4).forEach((card, index) => {
        const title = String(card.title ?? "").trim();
        const summary = String(card.summary ?? "").trim();
        if (!title) {
          next.push({ level: "warning", field: "project_cards", message: `Project card ${index + 1} is missing a title.` });
        }
        if (!summary) {
          next.push({ level: "warning", field: "project_cards", message: `Project card ${index + 1} is missing a summary.` });
        }
      });
    }

    if (!(draft.brag_document_markdown ?? "").trim()) {
      next.push({ level: "warning", field: "brag_document_markdown", message: "Brag document is empty." });
    } else {
      if (bragStats.headings === 0) {
        next.push({ level: "info", field: "brag_document_markdown", message: "Markdown preview will be easier to scan with section headings." });
      }
      if (bragStats.words < 120) {
        next.push({ level: "info", field: "brag_document_markdown", message: "Brag document is short. Add constraints, outcomes, and stakeholder context for stronger retrieval grounding." });
      }
    }

    if (blockedClaims.length === 0) {
      next.push({ level: "info", field: "do_not_claim", message: "Do Not Claim is empty. Add guardrails if there are sensitive or easy-to-hallucinate claims." });
    }
    if (duplicateBlockedClaimCount > 0) {
      next.push({ level: "warning", field: "do_not_claim", message: `${duplicateBlockedClaimCount} duplicate blocked-claim entr${duplicateBlockedClaimCount === 1 ? "y" : "ies"} will be normalized on save.` });
    }

    return next;
  }, [blockedClaims.length, bragStats.headings, bragStats.words, draft.brag_document_markdown, duplicateBlockedClaimCount, parsedEvidenceContext.error, parsedEvidenceContext.value, parsedProjectCards.error, parsedProjectCards.value]);

  const canUseQdrant = Boolean(health.services.qdrant.configured || health.services.qdrant.healthy || indexStatus.backend === "qdrant");
  const canSave = saveState !== "saving" && !parsedEvidenceContext.error && !parsedProjectCards.error;

  async function refreshHealth(): Promise<void> {
    setHealthLoading(true);
    try {
      const next = await getHealth();
      setHealth(next);
    } catch (error) {
      setLoadError((current) => current ?? (error instanceof Error ? error.message : "Failed to load system health"));
    } finally {
      setHealthLoading(false);
    }
  }

  async function loadEvidenceVault(): Promise<void> {
    setLoading(true);
    setLoadError(null);
    try {
      const [assets, nextIndexStatus, nextHealth] = await Promise.all([
        getEvidenceAssets(),
        getEvidenceIndexStatus(),
        getHealth(),
      ]);
      const normalized: CandidateEvidenceAssets = {
        evidence_context: (assets.evidence_context ?? {}) as Record<string, unknown>,
        brag_document_markdown: String(assets.brag_document_markdown ?? ""),
        project_cards: Array.isArray(assets.project_cards) ? assets.project_cards : [],
        do_not_claim: normalizeBlockedClaims(Array.isArray(assets.do_not_claim) ? assets.do_not_claim : []),
        updated_at: assets.updated_at ?? null,
      };
      setOriginal(normalized);
      setDraft(normalized);
      setIndexStatus(nextIndexStatus);
      setHealth(nextHealth);
      setEvidenceContextInput(JSON.stringify(normalized.evidence_context ?? {}, null, 2));
      setProjectCardsInput(JSON.stringify(normalized.project_cards ?? [], null, 2));
      setBulkClaimsInput("");
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Failed to load evidence vault");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadEvidenceVault();
  }, []);

  function setBragDocumentMarkdown(value: string): void {
    setDraft((current) => ({ ...current, brag_document_markdown: value }));
  }

  function setDoNotClaimItem(index: number, value: string): void {
    setDraft((current) => {
      const next = [...current.do_not_claim];
      next[index] = value;
      return { ...current, do_not_claim: next };
    });
  }

  function addDoNotClaimItem(): void {
    setDraft((current) => ({ ...current, do_not_claim: [...current.do_not_claim, ""] }));
  }

  function removeDoNotClaimItem(index: number): void {
    setDraft((current) => ({ ...current, do_not_claim: current.do_not_claim.filter((_, itemIndex) => itemIndex !== index) }));
  }

  function replaceDoNotClaimFromBulk(text: string): void {
    const next = normalizeBlockedClaims(text.split(/\n+/g));
    setDraft((current) => ({ ...current, do_not_claim: next }));
    setBulkClaimsInput("");
  }

  function formatEvidenceContext(): void {
    if (!parsedEvidenceContext.value) {
      toast.error("Evidence context JSON is invalid.");
      return;
    }
    setEvidenceContextInput(JSON.stringify(parsedEvidenceContext.value, null, 2));
  }

  function formatProjectCards(): void {
    if (!parsedProjectCards.value) {
      toast.error("Project cards JSON is invalid.");
      return;
    }
    setProjectCardsInput(JSON.stringify(parsedProjectCards.value, null, 2));
  }

  async function saveEvidenceVault(options?: { reindexAfterSave?: boolean }): Promise<boolean> {
    setSaveError(null);
    setStatusNotice(null);
    setSaveState("saving");

    if (parsedEvidenceContext.error || !parsedEvidenceContext.value) {
      const detail = parsedEvidenceContext.error ?? "Invalid evidence context JSON.";
      setSaveError(detail);
      setSaveState("error");
      toast.error(detail);
      return false;
    }
    if (parsedProjectCards.error || !parsedProjectCards.value) {
      const detail = parsedProjectCards.error ?? "Invalid project cards JSON.";
      setSaveError(detail);
      setSaveState("error");
      toast.error(detail);
      return false;
    }

    const payload: CandidateEvidenceAssets = {
      evidence_context: parsedEvidenceContext.value,
      brag_document_markdown: draft.brag_document_markdown ?? "",
      project_cards: parsedProjectCards.value,
      do_not_claim: blockedClaims,
      updated_at: draft.updated_at ?? null,
    };

    try {
      const saved = await putEvidenceAssets(payload);
      const normalizedSaved: CandidateEvidenceAssets = {
        evidence_context: (saved.evidence_context ?? {}) as Record<string, unknown>,
        brag_document_markdown: String(saved.brag_document_markdown ?? ""),
        project_cards: Array.isArray(saved.project_cards) ? saved.project_cards : [],
        do_not_claim: normalizeBlockedClaims(saved.do_not_claim ?? []),
        updated_at: saved.updated_at ?? null,
      };
      let nextIndexStatus = await getEvidenceIndexStatus();
      if (options?.reindexAfterSave) {
        nextIndexStatus = await reindexEvidenceAssets();
        setStatusNotice(nextIndexStatus.status === "ok" ? "Saved content indexed in the evidence backend." : "Saved content reindexed with warnings.");
      } else {
        setStatusNotice("Evidence vault saved. Index status refreshed.");
      }
      const nextHealth = await getHealth();
      setOriginal(normalizedSaved);
      setDraft(normalizedSaved);
      setIndexStatus(nextIndexStatus);
      setHealth(nextHealth);
      setEvidenceContextInput(JSON.stringify(normalizedSaved.evidence_context ?? {}, null, 2));
      setProjectCardsInput(JSON.stringify(normalizedSaved.project_cards ?? [], null, 2));
      setSaveState("saved");
      toast.success(options?.reindexAfterSave ? "Evidence vault saved and indexed" : "Evidence vault saved");
      window.setTimeout(() => setSaveState("idle"), 1400);
      return true;
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Failed to save evidence vault";
      setSaveError(detail);
      setSaveState("error");
      toast.error(detail);
      return false;
    }
  }

  async function reindexSavedEvidence(): Promise<boolean> {
    if (isDirty) {
      toast.error("Save the Evidence Vault before reindexing saved content.");
      return false;
    }
    setIndexing(true);
    setStatusNotice(null);
    try {
      const [nextIndexStatus, nextHealth] = await Promise.all([
        reindexEvidenceAssets(),
        getHealth(),
      ]);
      setIndexStatus(nextIndexStatus);
      setHealth(nextHealth);
      setStatusNotice(nextIndexStatus.status === "ok" ? "Saved content indexed in the evidence backend." : "Saved content reindexed with warnings.");
      toast.success(nextIndexStatus.status === "ok" ? "Evidence index refreshed" : "Evidence index update finished with warnings");
      return true;
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to reindex evidence");
      return false;
    } finally {
      setIndexing(false);
    }
  }

  return {
    loading,
    loadError,
    saveError,
    saveState,
    indexing,
    healthLoading,
    statusNotice,
    draft,
    original,
    indexStatus,
    health,
    evidenceContextInput,
    projectCardsInput,
    bulkClaimsInput,
    parsedEvidenceContext,
    parsedProjectCards,
    blockedClaims,
    bragStats,
    counts,
    issues,
    isDirty,
    canUseQdrant,
    canSave,
    setEvidenceContextInput,
    setProjectCardsInput,
    setBragDocumentMarkdown,
    setDoNotClaimItem,
    addDoNotClaimItem,
    removeDoNotClaimItem,
    setBulkClaimsInput,
    replaceDoNotClaimFromBulk,
    formatEvidenceContext,
    formatProjectCards,
    saveEvidenceVault,
    reindexSavedEvidence,
    refreshHealth,
    reload: loadEvidenceVault,
  };
}
