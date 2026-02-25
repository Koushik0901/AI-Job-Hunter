# Dashboard Overview

The dashboard is the web app for tracking applications and interview progress on top of the existing jobs DB, including profile-based job match scoring.

## Stack

- Backend API: FastAPI (`src/dashboard/backend/`)
- Frontend UI: React + Vite (`src/dashboard/frontend/`)
- Frontend routing: `react-router-dom` (`/`, `/profile`)
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
- Top app navigation:
  - `Board` tab (`/`)
  - `Profile` tab (`/profile`)
- Board state persistence:
  - returning from `Profile` back to `Board` reuses in-memory board state and detail/event caches
  - avoids full reload when data is still fresh
- Redis acceleration (optional):
  - backend caches jobs list/detail/events/profile/stats when `REDIS_URL` is configured
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
