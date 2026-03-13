# 🚀 Dashboard Overview

This dashboard is your command center for the full job workflow:
- discover jobs
- track lifecycle in Kanban
- manage resume/cover-letter artifacts
- run swarm optimization with guardrails

Fresh clones are expected to start blank. Users define their own profile, sources, resume baseline, and evidence from the UI.

---

## ✨ Stack at a Glance

- Backend API: FastAPI (`src/dashboard/backend/`)
- Frontend: React + Vite (`src/dashboard/frontend/`)
- Routing: `react-router-dom`
- Data store: Turso/libSQL tables for jobs, tracking, events, artifacts, run events
- Optional acceleration: Redis cache + Qdrant evidence retrieval

---

## ✨ Routes You Actually Use

- `/` Board
- `/workspace` Setup, source registry, pipeline runs, and maintenance
- `/profile` Profile + Evidence Vault
- `/artifacts` Artifacts Hub
- `/artifacts/editor/:jobUrl/:artifactType` LaTeX editor + preview + swarm modal
- `/analytics` Funnel/cohort/velocity analytics

---

## ✨ Kanban Workflow

Pipeline states:
- `not_applied`
- `staging`
- `applied`
- `interviewing`
- `offer`
- `rejected`

Common first-run path:
- open `/workspace`
- add desired titles and skills in `/profile`
- add or import sources
- run scrape
- review jobs on the board

What happens here:
- Drag/drop status updates are persisted.
- Detail drawer lets you update tracking fields inline.
- Job description, enrichment fields, and timeline are visible together.
- Status sync keeps `jobs.application_status` and tracking state aligned.

---

## ✨ Artifact Workflow

Artifacts are job-linked and versioned.

Resume + cover letter editor supports:
- LaTeX source editing
- compile to PDF
- side-by-side preview
- swarm AI optimization run modal

Swarm run UX shows:
- stage timeline
- score deltas per cycle
- evidence retrieval snippets/citations
- applied vs failed move outcomes
- rollback events when compile safety triggers

---

## ✨ Resume Swarm (Operational Flow)

`score -> rewrite -> verify_moves -> apply -> decide_next -> final_score`

Key behavior:
- LLM proposes bounded legal edits.
- Deterministic verifier removes invalid/conflicting edits.
- Deterministic apply enforces region safety + claim policy.
- Controller gates decide whether to continue cycles.
- Final score is produced after optimization.

---

## ✨ Cover-Letter Swarm (Operational Flow)

`draft -> score -> rewrite -> verify_moves -> apply -> decide_next -> final_score`

Key behavior:
- Draft starts from JD + resume context.
- Scoring and rewriting are bounded by legal move policy.
- Tone guard can force a second pass if writing quality degrades.

---

## ✨ LaTeX Safety Model

Why this is stable in production:

1. Parse first
- LaTeX is parsed into line/block IDs and editable regions.

2. Legal moves only
- No unrestricted text replacement.

3. Claim validation
- Unsupported claim introduction is blocked.
- Citation-backed (`supported_by`) edits can be required.

4. Compile guard rollback
- If input compiles and post-edit output does not, final output reverts.

---

## ✨ Local Run

Backend:

```bash
uv run python src/dashboard/backend/main.py
```

Frontend:

```bash
cd src/dashboard/frontend
npm install
npm run dev
```

Frontend URL: `http://localhost:5173`
Backend URL: `http://127.0.0.1:8000`

---

## ✨ Related Docs

- [backend-api.md](backend-api.md)
- [frontend-ui.md](frontend-ui.md)
- [match-scoring.md](match-scoring.md)
- [../evaluation/eval-framework.md](../evaluation/eval-framework.md)
