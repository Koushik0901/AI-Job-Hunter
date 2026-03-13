# 🚀 File-by-File Reference

High-value entry points by area.

---

## ✨ Backend API

- `src/dashboard/backend/main.py` - route layer
- `src/dashboard/backend/repository.py` - DB operations
- `src/dashboard/backend/schemas.py` - request/response schemas

## ✨ Swarm Pipelines

Resume:
- `src/dashboard/backend/resume_agents_swarm/graph.py`
- `src/dashboard/backend/resume_agents_swarm/latex_apply.py`
- `src/dashboard/backend/resume_agents_swarm/run.py`

Cover letter:
- `src/dashboard/backend/cover_letter_agents_swarm/graph.py`
- `src/dashboard/backend/cover_letter_agents_swarm/latex_apply.py`
- `src/dashboard/backend/cover_letter_agents_swarm/run.py`

Shared safety:
- `src/dashboard/backend/claim_validator.py`
- `src/dashboard/backend/latex_resume.py`

## ✨ Frontend

- `src/dashboard/frontend/src/pages/BoardPage.tsx`
- `src/dashboard/frontend/src/pages/ProfilePage.tsx`
- `src/dashboard/frontend/src/pages/ArtifactsEditorPage.tsx`
- `src/dashboard/frontend/src/pages/AnalyticsPage.tsx`

## ✨ Evaluation

- `eval/eval.py`
- `eval/swarm_benchmark.py`
