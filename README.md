# AI Job Hunter

An open-source, single-user job search workspace that starts blank and adapts to the person running it.

You add your own targets, sources, profile data, resume baseline, and evidence. Nothing in a fresh clone should assume a specific job title, company list, resume, or personal history.

---

## ✨ What This Project Actually Does

You get one system with three practical layers:

1. Discovery and lifecycle
- Scrape ATS boards + HN hiring threads.
- Normalize and store jobs.
- Track each job across `not_applied -> staging -> applied -> interviewing -> offer/rejected`.

2. Dashboard and artifacts
- Kanban board with detail drawer.
- Resume and cover-letter artifact editors.
- Versioned artifact storage.
- PDF compile + preview.

3. Agentic optimization
- Resume swarm pipeline.
- Cover-letter swarm pipeline.
- Legal-move editing, claim validation, and compile-safe rollback.

---

## Quick Start

### 🔹 1) Install

Requires Python `3.12+` and `uv`.

```bash
uv sync
```

### 2) Configure

```bash
cp .env.example .env
```

Fill in only what you plan to use.

Minimum startup options:
- Local mode: no DB env vars required; the app will create a local SQLite database.
- Turso mode: set `TURSO_URL` and `TURSO_AUTH_TOKEN`.

Optional services:
- `REDIS_URL` for API caching.
- `OPENROUTER_API_KEY` for enrichment and swarm features.
- `QDRANT_URL` and `QDRANT_API_KEY` for evidence retrieval.
- Telegram variables only if you want notifications.

### 3) Run backend + frontend

```bash
uv run python src/dashboard/backend/main.py
```

```bash
cd src/dashboard/frontend
npm install
npm run dev
```

Backend: `http://127.0.0.1:8000`
Frontend: `http://localhost:5173`

### 4) First-run flow

Fresh clones should start blank:
1. Open `/workspace` and confirm service health.
2. Open `/profile` and enter your desired job titles, skills, and optional resume baseline.
3. Add or import company sources from `/workspace`.
4. Run a scrape from `/workspace`.
5. Use the board and artifacts UI for the jobs relevant to your own search.

---

## Most Used Commands

```bash
# 🚀 Daily scrape pipeline
uv run python src/cli.py scrape

# 🚀 Source management
uv run python src/cli.py sources list
uv run python src/cli.py sources check example-company
uv run python src/cli.py sources enable example-company
uv run python src/cli.py sources disable example-company

# 🚀 Lifecycle
uv run python src/cli.py lifecycle set-status --url <job_url> --status applied
uv run python src/cli.py lifecycle prune --days 28 --apply

# 🚀 Eval framework
uv run python eval/eval.py crawl
uv run python eval/eval.py build
uv run python eval/eval.py run
uv run python eval/eval.py report

# 🚀 Swarm acceptance benchmark
uv run python eval/swarm_benchmark.py build-dataset --out eval/swarm_dataset.yaml --limit 50 --statuses staging applied interviewing not_applied offer rejected archived
uv run python eval/swarm_benchmark.py run --dataset eval/swarm_dataset.yaml --cycles 2 --compile-check --out-dir eval/results
```

---

## ✨ Resume Swarm Pipeline (How It Works)

This is a bounded optimization loop, not open-ended rewriting.

Flow:

1. `score_node`
- LLM scorer reads JD + resume text + evidence context.
- Outputs strict JSON: score breakdown, risks, `Fix_Plan`, non-negotiables.

2. `rewrite_node`
- LLM rewriter reads JD + scorer JSON + current resume LaTeX.
- Outputs legal operations (`moves`) with fix linkage.

3. `verify_moves_node` (deterministic)
- Confirms targets exist and are editable.
- Applies conflict policy (priority-first, skip collisions).
- Enforces op budget and change budget.

4. `apply_node` (deterministic)
- Applies legal moves to LaTeX.
- Emits applied/failed/no-op details and policy reasons.

5. `decide_next`
- Controller loop gate only (LLM never sees cycle counters).
- Stops by gate rules or continues to next cycle.

6. `final_score_node`
- Produces final score JSON for result + timeline.

Output:
- Final resume LaTeX.
- Final score JSON.
- Full event history for UI timeline.

---

## ✨ Cover-Letter Swarm Pipeline (How It Works)

Cover-letter flow is similar, but includes drafting and tone controls.

Flow:

1. `draft_node`
- Generates an initial grounded draft in LaTeX body context.

2. `score_node`
- Scores the draft against JD and evidence constraints.

3. `rewrite_node`
- Produces legal cover-letter edits (line/block bounded).

4. `verify_moves_node`
- Deterministic target validation + conflict filtering.

5. `apply_node`
- Deterministic LaTeX apply with policy checks.

6. `decide_next` + `final_score_node`
- Gate-based loop and final scoring.

Tone guard:
- Deterministic heuristic path can force another cycle when writing drifts into low-quality style patterns.

---

## ✨ How LaTeX Is Handled Safely

This is where reliability comes from.

1. Parse first
- Source is parsed into `line_id`, `block_id`, `region_id`, `editable`, `line_kind`.

2. Legal moves only
- Resume supports bounded operations like `replace_line`, `insert_line_after`, `delete_line`, `replace_block`, `swap_blocks`.
- Cover letter supports the bounded subset for its tagged structure.

3. Deterministic apply
- No fuzzy patching.
- Exact target resolution with controlled fallback.
- Conflicts are skipped and logged.

4. Safety guards
- Claim validator blocks unsupported claim introduction.
- `supported_by` citations can be required for claim-adding edits.
- LaTeX safety checks catch brace/environment/special-char issues.

5. Compile guard rollback
- If input compiled and edited output does not, output is automatically reverted.
- This guarantees zero compile regressions in accepted final output.

---

## ✨ Documentation Map

Start here:
- [docs/INDEX.md](docs/INDEX.md)

High-traffic docs:
- [docs/dashboard/overview.md](docs/dashboard/overview.md)
- [docs/dashboard/backend-api.md](docs/dashboard/backend-api.md)
- [eval/README.md](eval/README.md)
- [docs/evaluation/eval-framework.md](docs/evaluation/eval-framework.md)

---

## ✨ Runtime Controls (Swarm)

Key env vars:
- `OPENROUTER_API_KEY`
- `RESUME_SWARM_SCORING_MODEL`, `RESUME_SWARM_REWRITE_MODEL`
- `COVER_LETTER_SWARM_DRAFT_MODEL`, `COVER_LETTER_SWARM_SCORING_MODEL`, `COVER_LETTER_SWARM_REWRITE_MODEL`
- `SWARM_MIN_SCORE_DELTA`
- `SWARM_MAX_OPS_PER_CYCLE`
- `SWARM_MAX_CHANGED_LINE_RATIO`
- `SWARM_FORCE_ON_NON_NEGOTIABLES`
- `SWARM_COMPILE_ROLLBACK`

Evidence retrieval controls:
- `EVIDENCE_RETRIEVAL_MODE`
- `EVIDENCE_MAX_TOP_K`
- `EVIDENCE_MIN_LEXICAL_OVERLAP`
- `EVIDENCE_MIN_VECTOR_SCORE`
- `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_EVIDENCE_COLLECTION`

---

## ✨ Current Reliability Snapshot

On the 50-case swarm benchmark:
- Apply success: `83.29%`
- Out-of-region violations: `0`
- Compile regressions: `0/100`
- Acceptance gates: all pass

(See `eval/results/swarm_benchmark_*.md` for latest run.)
