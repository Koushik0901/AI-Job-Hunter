# 🚀 End-to-End Data Flow

This is the actual runtime path from raw jobs to optimized LaTeX outputs.

---

## ✨ A) Discovery and Storage

1. `cli scrape` loads enabled company sources.
2. ATS/HN fetchers normalize listings.
3. Filters apply (title/location rules).
4. Jobs are upserted.
5. Optional enrichment runs.
6. Optional notifications fire.

Output: normalized jobs + enrichment rows in DB.

---

## ✨ B) Dashboard Tracking

1. Frontend loads jobs + stats.
2. User updates tracking via drawer or drag-drop.
3. Backend persists `job_tracking` and mirrors `jobs.application_status`.
4. Events/timeline are persisted and reloaded.

Output: reliable pipeline state for board and analytics.

---

## ✨ C) Artifact Lifecycle

1. Job enters staging (or artifact created manually).
2. Resume + cover-letter artifacts exist as versioned records.
3. Editor loads active version.
4. User edits LaTeX and compiles preview.

Output: versioned artifact source + compiled PDF outputs.

---

## ✨ D) Swarm Optimization

Resume:
- `score -> rewrite -> verify_moves -> apply -> decide -> final_score`

Cover letter:
- `draft -> score -> rewrite -> verify_moves -> apply -> decide -> final_score`

Safety at apply time:
- legal region checks
- claim-policy checks
- LaTeX syntax guards
- compile-guard rollback in runner

Output: improved final LaTeX + full event timeline.

---

## ✨ E) Evaluation and Gates

`eval/swarm_benchmark.py` runs pipelines over dataset cases and computes:
- apply success
- out-of-region violations
- compile regressions
- score deltas

Acceptance gates:
- apply success > 70%
- out-of-region = 0
- compile regressions = 0
