# 🚀 System Overview

The repo has one mission: move from job discovery to high-quality application artifacts with measurable safety.

---

## ✨ Main Runtime Layers

1. CLI pipeline (`src/cli.py`)
- Scraping
- Source management
- Lifecycle pruning/status updates

2. Dashboard backend (`src/dashboard/backend`)
- Job/tracking/profile/events APIs
- Artifact CRUD and compile APIs
- Swarm run orchestration and run-event persistence

3. Dashboard frontend (`src/dashboard/frontend`)
- Board, Profile, Artifacts, Analytics
- Editor + swarm timeline UX

4. Evaluation (`eval/`)
- extraction model eval
- swarm acceptance benchmark

---

## ✨ Swarm Subsystems

- `resume_agents_swarm/`
- `cover_letter_agents_swarm/`

Both follow bounded loops with deterministic gates:
- score
- rewrite
- verify
- apply
- gate/decide
- final score

No free-form patching is accepted.

---

## ✨ Persistence Backbone

Core tables:
- jobs/tracking/events
- profile + evidence assets
- artifacts + versions + suggestions
- swarm runs + run events

Optional infra:
- Redis for API caching
- Qdrant for vector retrieval

---

## ✨ Design Principles

- Determinism before cleverness.
- Evidence-grounded edits only.
- Compile-safe outputs only.
- Every decision leaves an inspectable trace.
