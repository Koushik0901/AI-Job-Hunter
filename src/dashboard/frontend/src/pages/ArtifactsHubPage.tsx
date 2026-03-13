import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { deleteJobArtifact, generateStarterArtifacts, getArtifactsHub } from "../api";
import type { ArtifactsHubItem, TrackingStatus } from "../types";
import { ThemedLoader } from "../components/ThemedLoader";
import { ThemedSelect } from "../components/ThemedSelect";
import { Input } from "../components/ui/input";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
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

type SortOption = "updated_desc" | "company_asc";
type StatusFilter = TrackingStatus | "all";
type ArtifactType = "resume" | "cover_letter";

const STATUS_OPTIONS: Array<{ value: StatusFilter; label: string }> = [
  { value: "all", label: "All statuses" },
  { value: "staging", label: "Staging" },
  { value: "applied", label: "Applied" },
  { value: "interviewing", label: "Interviewing" },
  { value: "offer", label: "Offer" },
  { value: "rejected", label: "Rejected" },
  { value: "not_applied", label: "Backlog" },
];

const SORT_OPTIONS: Array<{ value: SortOption; label: string }> = [
  { value: "updated_desc", label: "Recently updated" },
  { value: "company_asc", label: "Company (A-Z)" },
];

function formatStamp(raw: string | null | undefined): string {
  if (!raw) return "—";
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.valueOf())) return "—";
  return parsed.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function artifactLabel(item: ArtifactsHubItem, type: ArtifactType): string {
  const artifact = type === "resume" ? item.resume : item.cover_letter;
  const version = artifact?.active_version;
  if (!artifact || !version) return "Not created";
  return `${version.label} v${version.version}`;
}

export function ArtifactsHubPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rows, setRows] = useState<ArtifactsHubItem[]>([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<StatusFilter>("staging");
  const [sort, setSort] = useState<SortOption>("updated_desc");
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<{ jobId: string; jobUrl: string; type: ArtifactType; jobLabel: string } | null>(null);
  const [creatingKey, setCreatingKey] = useState<string | null>(null);

  const queryKey = useMemo(() => JSON.stringify({ query: query.trim(), status, sort }), [query, status, sort]);

  async function refreshHub(): Promise<void> {
    const response = await getArtifactsHub({
      q: query.trim() || undefined,
      status,
      sort,
      limit: 300,
      offset: 0,
    });
    setRows(response.items);
    setTotal(response.total);
  }

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void (async () => {
        setLoading((current) => (rows.length === 0 ? true : current));
        setError(null);
        try {
          const response = await getArtifactsHub({
            q: query.trim() || undefined,
            status,
            sort,
            limit: 300,
            offset: 0,
          });
          if (cancelled) return;
          setRows(response.items);
          setTotal(response.total);
        } catch (loadError) {
          if (cancelled) return;
          setError(loadError instanceof Error ? loadError.message : "Failed to load artifacts");
        } finally {
          if (!cancelled) {
            setLoading(false);
          }
        }
      })();
    }, 180);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryKey]);

  async function handleDeleteConfirmed(): Promise<void> {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await deleteJobArtifact(pendingDelete.jobId, pendingDelete.type);
      let rowRemoved = false;
      setRows((current) => {
        const next: ArtifactsHubItem[] = [];
        for (const row of current) {
          if (row.job_url !== pendingDelete.jobUrl) {
            next.push(row);
            continue;
          }
          const updated: ArtifactsHubItem = {
            ...row,
            resume: pendingDelete.type === "resume" ? null : row.resume,
            cover_letter: pendingDelete.type === "cover_letter" ? null : row.cover_letter,
          };
          if (updated.resume || updated.cover_letter) {
            next.push(updated);
          } else {
            rowRemoved = true;
          }
        }
        return next;
      });
      if (rowRemoved) {
        setTotal((current) => Math.max(0, current - 1));
      }
      toast.success(`${pendingDelete.type === "resume" ? "Resume" : "Cover letter"} deleted`);
      setDeleteDialogOpen(false);
      setPendingDelete(null);
    } catch (deleteError) {
      toast.error(deleteError instanceof Error ? deleteError.message : "Failed to delete artifact");
    } finally {
      setDeleting(false);
    }
  }

  async function handleCreateMissing(row: ArtifactsHubItem, type: ArtifactType): Promise<void> {
    const key = `${row.job_id}::${type}`;
    setCreatingKey(key);
    try {
      const artifacts = await generateStarterArtifacts(row.job_id, false);
      const created = artifacts.find((item) => item.artifact_type === type);
      await refreshHub();
      toast.success(`${type === "resume" ? "Resume" : "Cover letter"} created`);
      if (created) {
        if (type === "resume") {
          navigate(`/jobs/${encodeURIComponent(row.job_id)}/artifacts/resume`);
        } else {
          navigate(`/jobs/${encodeURIComponent(row.job_id)}/artifacts/cover-letter`);
        }
      }
    } catch (createError) {
      toast.error(createError instanceof Error ? createError.message : "Failed to create artifact");
    } finally {
      setCreatingKey(null);
    }
  }

  if (loading && rows.length === 0) {
    return <ThemedLoader label="Loading artifacts hub" />;
  }

  return (
    <section className="artifacts-hub-page">
      <header className="artifacts-hub-head">
        <div>
          <p className="eyebrow">Artifacts</p>
          <h1>Artifact Library</h1>
          <p className="artifacts-hub-sub">Resume and cover letter artifacts organized per job.</p>
        </div>
        <Badge>{total} jobs</Badge>
      </header>

      <div className="artifacts-hub-controls">
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search by company, role, or URL"
          className="artifacts-hub-search"
        />
        <ThemedSelect
          value={status}
          options={STATUS_OPTIONS}
          onChange={(value) => setStatus(value as StatusFilter)}
          ariaLabel="Artifacts status filter"
        />
        <ThemedSelect
          value={sort}
          options={SORT_OPTIONS}
          onChange={(value) => setSort(value as SortOption)}
          ariaLabel="Artifacts sort"
        />
      </div>

      {error && <p className="artifacts-hub-error">{error}</p>}

      {rows.length === 0 ? (
        <div className="artifacts-hub-empty">
          <p>No artifacts yet. Add sources, scrape jobs, then create starter drafts for the roles you want to pursue.</p>
          <Button asChild variant="primary" size="compact" data-icon="←">
            <Link to="/">Back to Board</Link>
          </Button>
        </div>
      ) : (
        <div className="artifacts-hub-list" role="table" aria-label="Artifacts grouped by job">
          <div className="artifacts-hub-row artifacts-hub-row-head" role="row">
            <div role="columnheader">Job</div>
            <div role="columnheader">Status</div>
            <div role="columnheader">Resume</div>
            <div role="columnheader">Cover Letter</div>
            <div role="columnheader">Updated</div>
          </div>
          {rows.map((row) => (
            <div key={row.job_id} className="artifacts-hub-row" role="row">
              <div className="artifacts-hub-job-cell">
                <p className="artifacts-hub-company">{row.company || "Unknown company"}</p>
                <p className="artifacts-hub-title">{row.title || row.job_url}</p>
              </div>
              <div>
                <Badge>{row.tracking_status}</Badge>
              </div>
              <div className="artifacts-hub-artifact-cell">
                <span className="artifacts-hub-meta">{artifactLabel(row, "resume")}</span>
                {row.resume ? (
                  <div className="artifacts-hub-actions">
                    <Button asChild variant="warn" size="compact" data-icon="↗">
                      <Link to={`/jobs/${encodeURIComponent(row.job_id)}/artifacts/resume`}>Open</Link>
                    </Button>
                    <Button
                      type="button"
                      variant="danger"
                      size="compact"
                      data-icon="🗑"
                      onClick={() => {
                        setPendingDelete({ jobId: row.job_id, jobUrl: row.job_url, type: "resume", jobLabel: `${row.company} — ${row.title}` });
                        setDeleteDialogOpen(true);
                      }}
                    >
                      Delete
                    </Button>
                  </div>
                ) : (
                  <div className="artifacts-hub-actions">
                    <span className="artifacts-hub-missing">Not created</span>
                    <Button
                      type="button"
                      variant="primary"
                      size="compact"
                      data-icon="+"
                      onClick={() => void handleCreateMissing(row, "resume")}
                      disabled={creatingKey === `${row.job_id}::resume`}
                    >
                      {creatingKey === `${row.job_id}::resume` ? "Creating..." : "Create"}
                    </Button>
                  </div>
                )}
              </div>
              <div className="artifacts-hub-artifact-cell">
                <span className="artifacts-hub-meta">{artifactLabel(row, "cover_letter")}</span>
                {row.cover_letter ? (
                  <div className="artifacts-hub-actions">
                    <Button asChild variant="warn" size="compact" data-icon="↗">
                      <Link to={`/jobs/${encodeURIComponent(row.job_id)}/artifacts/cover-letter`}>Open</Link>
                    </Button>
                    <Button
                      type="button"
                      variant="danger"
                      size="compact"
                      data-icon="🗑"
                      onClick={() => {
                        setPendingDelete({ jobId: row.job_id, jobUrl: row.job_url, type: "cover_letter", jobLabel: `${row.company} — ${row.title}` });
                        setDeleteDialogOpen(true);
                      }}
                    >
                      Delete
                    </Button>
                  </div>
                ) : (
                  <div className="artifacts-hub-actions">
                    <span className="artifacts-hub-missing">Not created</span>
                    <Button
                      type="button"
                      variant="primary"
                      size="compact"
                      data-icon="+"
                      onClick={() => void handleCreateMissing(row, "cover_letter")}
                      disabled={creatingKey === `${row.job_id}::cover_letter`}
                    >
                      {creatingKey === `${row.job_id}::cover_letter` ? "Creating..." : "Create"}
                    </Button>
                  </div>
                )}
              </div>
              <div className="artifacts-hub-updated">{formatStamp(row.latest_artifact_updated_at ?? row.tracking_updated_at)}</div>
            </div>
          ))}
        </div>
      )}

      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Delete {pendingDelete?.type === "resume" ? "resume" : "cover letter"}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              This deletes only that artifact for {pendingDelete?.jobLabel ?? "this job"} and keeps the other artifact intact.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel asChild>
              <Button type="button" variant="default" size="compact" data-icon="×">Cancel</Button>
            </AlertDialogCancel>
            <Button
              type="button"
              variant="danger"
              size="compact"
              data-icon="🗑"
              onClick={() => void handleDeleteConfirmed()}
              disabled={deleting || !pendingDelete}
            >
              {deleting ? "Deleting..." : "Delete"}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
