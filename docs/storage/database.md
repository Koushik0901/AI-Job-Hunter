# 🚀 Database Storage

This project uses Turso/libSQL (primary) with SQLite-compatible schema logic.

---

## ✨ Core Table Groups

Jobs and tracking:
- `jobs`
- `job_tracking`
- `job_events`
- `job_enrichments`

Profile and grounding:
- `candidate_profile`
- evidence asset/index tables used by dashboard backend

Artifacts:
- `job_artifacts`
- `artifact_versions`
- `artifact_suggestions`

Swarm runs:
- `artifact_ai_runs`
- `artifact_ai_run_events`

---

## ✨ Artifact Model

- `job_artifacts`: stable identity per `(job_url, artifact_type)`
- `artifact_versions`: immutable version history
- active version pointer lives on artifact identity

This gives safe history + predictable current state.

---

## ✨ Deletion Semantics

Job deletion removes linked tracking/events/enrichment/artifact data through repository-level cascade logic.

---

## ✨ Operational Notes

- Keep indexes healthy for board/list and artifact lookups.
- For benchmark/eval runs, prefer Turso dataset over local SQLite snapshots.
