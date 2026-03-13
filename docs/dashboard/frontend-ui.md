# 🚀 Dashboard Frontend UI

This is the UI layer that turns raw jobs + artifacts into an actual operating workflow.

---

## ✨ Core Routes

- `/` Board
- `/workspace` Workspace setup and operations
- `/profile` Profile + Evidence Vault
- `/artifacts` Artifacts Hub
- `/artifacts/editor/:jobUrl/:artifactType` Artifact editor
- `/analytics` Funnel and velocity analytics

---

## ✨ Board Experience

What users can do fast:
- drag jobs across pipeline stages
- open detail drawer with enrichment + timeline
- update tracking fields inline
- add manual jobs
- refresh board and keep filters/search/sort active

Design behavior:
- board keeps cached state when navigating away and back
- detail/event caches are reused when still fresh
- controls panel is compact and expandable (view/sort/filter/search)

---

## ✨ Profile Experience

Two concerns live together but remain separate:
- scoring profile (match-score inputs)
- evidence vault (grounding assets for swarm)

The scoring and resume areas are intended to start empty on a fresh clone. Users provide their own job titles, skills, resume baseline, and evidence rather than editing hardcoded defaults.

Evidence Vault powers retrieval + claim validation in swarm runs.

## ✨ Workspace Experience

Workspace is the setup surface for blank installs:
- probe and save company sources
- import community source lists
- run scrape, enrichment, JD reformat, and prune actions
- inspect recent operation history and service health

---

## ✨ Artifact Editor Experience

Editor page combines:
- LaTeX source editor
- compile diagnostics + PDF preview
- AI Swarm modal with per-stage timeline

Swarm modal surfaces:
- scoring output
- rewrite proposal
- verify/apply results
- cycle decisions
- evidence citations
- confirm-save/cancel actions

---

## ✨ Interaction Guarantees

- Manual save flow (no silent autosave surprises).
- Dirty-state protection before leaving editor.
- Long-running swarm runs are visible with live status updates.
- Final save can trigger recompile and preview refresh.

---

## ✨ Component Landmarks

Primary files:
- `src/dashboard/frontend/src/App.tsx`
- `src/dashboard/frontend/src/components/layout/AppShell.tsx`
- `src/dashboard/frontend/src/pages/BoardPage.tsx`
- `src/dashboard/frontend/src/pages/ProfilePage.tsx`
- `src/dashboard/frontend/src/pages/ArtifactsHubPage.tsx`
- `src/dashboard/frontend/src/pages/ArtifactsEditorPage.tsx`
- `src/dashboard/frontend/src/pages/AnalyticsPage.tsx`

---

## ✨ Local Run

```bash
cd src/dashboard/frontend
npm install
npm run dev
```

If backend base URL must be overridden:

```bash
set VITE_API_BASE=http://127.0.0.1:8000
npm run dev
```

---

## ✨ Related Docs

- [overview.md](overview.md)
- [backend-api.md](backend-api.md)
- [match-scoring.md](match-scoring.md)
