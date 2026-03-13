# 🚀 Quickstart

Get the system running fast, then tune.

---

## ✨ 1) Install

```bash
uv sync
```

Frontend dependencies:

```bash
cd src/dashboard/frontend
npm install
cd ../../..
```

---

## ✨ 2) Configure

```bash
cp .env.example .env
```

Minimum for dashboard + DB:
- No DB env vars if you want local SQLite.
- `TURSO_URL` and `TURSO_AUTH_TOKEN` only if you want Turso.

Minimum for AI/swarms:
- `OPENROUTER_API_KEY`

Optional:
- `REDIS_URL`
- `QDRANT_URL` + `QDRANT_API_KEY`
- Telegram settings if you want notifications

Local Qdrant option:

```powershell
./setup_qdrant_local.ps1
```

Then set these values in `.env`:
- `QDRANT_URL=http://127.0.0.1:6333`
- `QDRANT_API_KEY=` (leave empty for local dev)
- `QDRANT_EVIDENCE_COLLECTION=candidate_evidence_chunks`
- `EVIDENCE_RETRIEVAL_MODE=auto`

---

## ✨ 3) Start backend and frontend

Backend:

```bash
uv run python src/dashboard/backend/main.py
```

Frontend:

```bash
cd src/dashboard/frontend
npm run dev
```

Open:
- API: `http://127.0.0.1:8000`
- UI: `http://localhost:5173`

---

## ✨ 4) Validate core flow

Fresh clones should start empty:

1. Open Workspace and confirm the app loads with no pre-seeded sources or profile data.
2. Open Profile and save your own job titles, skills, and optional resume baseline.
3. Add or import one or more company sources from Workspace.
4. Run a scrape from Workspace and confirm jobs appear on the Board.
5. Open Artifacts Hub and create starter drafts only for the jobs you care about.
6. Recompile a resume PDF if you are using the artifact flow.
7. Run an AI swarm only after you have provided your own baseline resume/evidence.

If you enabled local Qdrant:
8. Open Profile and trigger evidence reindex once after saving evidence assets.

---

## ✨ 5) Run acceptance benchmark

```bash
uv run python eval/swarm_benchmark.py build-dataset --out eval/swarm_dataset.yaml --limit 50 --statuses staging applied interviewing not_applied offer rejected archived
uv run python eval/swarm_benchmark.py run --dataset eval/swarm_dataset.yaml --cycles 2 --compile-check --out-dir eval/results
```

Read the report in `eval/results/swarm_benchmark_*.md`.
