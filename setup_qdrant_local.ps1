$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$composeFile = Join-Path $repoRoot "docker-compose.qdrant.yml"
$storageDir = Join-Path $repoRoot "artifacts_workspace\\qdrant"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is required for local Qdrant setup."
}

New-Item -ItemType Directory -Force $storageDir | Out-Null

docker compose -f $composeFile up -d

Write-Host ""
Write-Host "Local Qdrant is starting." -ForegroundColor Green
Write-Host "Use these .env values:" -ForegroundColor Cyan
Write-Host "QDRANT_URL=http://127.0.0.1:6333"
Write-Host "QDRANT_API_KEY="
Write-Host "QDRANT_EVIDENCE_COLLECTION=candidate_evidence_chunks"
Write-Host "EVIDENCE_RETRIEVAL_MODE=auto"
Write-Host ""
Write-Host "Then reindex evidence from the UI or POST /api/profile/evidence/reindex." -ForegroundColor Yellow
