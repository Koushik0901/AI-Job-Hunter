import { Navigate, useParams } from "react-router-dom";

function normalizeArtifactType(raw: string | undefined): "resume" | "cover_letter" {
  const next = (raw || "resume").trim().toLowerCase();
  return next === "cover_letter" ? "cover_letter" : "resume";
}

export function ArtifactsEditorPage() {
  const params = useParams();
  const jobId = params.jobId ?? "";
  const artifactType = normalizeArtifactType(params.artifactType);
  return <Navigate to={`/jobs/${encodeURIComponent(jobId)}/artifacts/${artifactType}/latex`} replace />;
}
