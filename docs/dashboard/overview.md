# Dashboard Overview

The dashboard is the web app for tracking applications and interview progress on top of the existing jobs DB, including profile-based job match scoring.

## Stack

- Backend API: FastAPI (`src/dashboard/backend/`)
- Frontend UI: React + Vite (`src/dashboard/frontend/`)
- Frontend routing: `react-router-dom` (`/`, `/profile`, `/analytics`)
- UI transitions: `framer-motion`
- UI component polish: ReactBits-style spotlight/tag components
- Data store: existing DB (`jobs`) + tracking tables (`job_tracking`, `job_events`) + profile table (`candidate_profile`)

## Key workflows

- Kanban pipeline across statuses:
  - `not_applied`
  - `staging`
  - `applied`
  - `interviewing`
  - `offer`
  - `rejected`
- Job detail panel with:
  - source URL
  - description
  - priority
  - applied date
  - next step
  - target compensation
- enrichment fields from `job_enrichments`
- dedicated profile page (`/profile`) for scoring inputs (`candidate_profile`)
- match score panel (`score`, `band`, `breakdown`, `reasons`, `confidence`)
- Timeline events rendered in read-only mode.
- Drag/drop micro-interactions:
  - active drop-target column styling
  - optimistic status movement + DB persistence
- Spotlight-hover metric cards for top-level stats.
- Theme system:
  - dark/light mode toggle
  - animated theme switch
  - local preference persistence (`dashboard-theme`)
- Side rail navigation:
  - `Board` (`/`)
  - `Profile` (`/profile`)
  - `Analytics` (`/analytics`)
- Funnel analytics workflow:
  - date-window presets (`30d`, `90d`, `all`)
  - stage counts for pipeline states
  - conversion rates across major transitions (`backlog -> staging -> applied -> interviewing -> offer`)
  - delta comparisons vs previous equal-length window
  - weekly goals tracking (applications + interview activities)
  - stale-state alert cards
  - cohort funnel by posted week
  - source quality ranking by ATS and company
  - forecast simulator with confidence bands for 7-day and 30-day projections
- Board state persistence:
  - returning from `Profile` back to `Board` reuses in-memory board state and detail/event caches
  - avoids full reload when data is still fresh
- Redis acceleration (optional):
  - backend caches jobs list/detail/events/profile/stats when `REDIS_URL` is configured
  - backend also caches funnel analytics (`GET /api/analytics/funnel`)
  - job-detail cache is LRU-bounded by `DASHBOARD_CACHE_MAX_JOB_DETAILS`

## Local run

### Backend

```bash
uv run python src/dashboard/backend/main.py
```

API is served at `http://127.0.0.1:8000`.

### Frontend

```bash
cd src/dashboard/frontend
npm install
npm run dev
```

UI is served at `http://localhost:5173`.

If needed, override API base:

```bash
# in frontend shell
set VITE_API_BASE=http://127.0.0.1:8000
npm run dev
```

## Compatibility notes

- Existing scrape/eval CLI commands remain unchanged.
- Dashboard writes tracking state and mirrors status into `jobs.application_status` for consistency with lifecycle CLI.
- Dashboard backend requires Turso credentials (`TURSO_URL`, `TURSO_AUTH_TOKEN`) and does not fallback to local SQLite.
- Match scoring rubric and weights: [`match-scoring.md`](match-scoring.md).

## Board interaction primer

- Controls are grouped under a single capsule that expands inline to reveal the current `View`, `Sort`, Filter popover (status/ATS/company/posted range), and search bar without increasing toolbar height; active filters light up a count badge on that capsule.
- The `Suppressed`, `Add Job`, and `Refresh` buttons sit to the right with consistent spacing and fixed width so their affordances remain legible; adding a job opens the drawer immediately and quietly triggers background enrichment + forced board refresh once the LLM formatting completes.
- The kanban grid spans roughly two viewport heights, so scrolling moves the entire board (columns and backlog note) together; each column keeps its cards aligned, and the side rail collapses to icons with hover tooltips until the user reopens it with the burger toggle.
- Each column’s card list scrolls independently when it overflows, so “Applied” and the other stages surface their own scrollbar only if they contain more cards than fit in the viewport height.
