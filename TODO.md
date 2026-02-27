# TODO

## Application Analytics (v1 - Funnel + Cohorts)

### Goal
- Build a dedicated analytics experience that explains conversion quality, drop-off points, and stage velocity.

### Data + Backend
1. Add `job_status_history` table
- Columns:
  - `id` (PK)
  - `url` (FK -> `jobs.url`)
  - `from_status` (nullable)
  - `to_status` (required)
  - `changed_at` (ISO timestamp)
  - `changed_by` (default `ui`/`system`)
- Indexes:
  - `(url, changed_at DESC)`
  - `(to_status, changed_at DESC)`

2. Write transition history during tracking updates
- On every status change in dashboard tracking patch path, append one history row.
- Keep existing status normalization behavior (`withdrawn` -> `rejected`) consistent.

3. Backfill baseline history for existing rows
- For jobs without history, insert a synthetic baseline transition (`null -> current_status`) using earliest available timestamp (`first_seen` fallback).

4. Add analytics endpoints
- `GET /api/analytics/funnel`
- `GET /api/analytics/cohorts`
- `GET /api/analytics/time-in-stage`
- `GET /api/analytics/breakdowns`
- Support filters:
  - `from`, `to`
  - `ats`
  - `company`
  - status scope

5. Add Redis caching + invalidation for analytics endpoints
- Cache TTL target: short-lived (30-120s).
- Invalidate on:
  - tracking status changes
  - job delete
  - event changes that affect metrics logic

### Frontend
6. Add `/analytics` route
- Add nav link in app shell.

7. Build Analytics page sections
- Funnel summary cards + conversion rates.
- Cohort view (weekly first-seen cohorts).
- Time-in-stage chart/table (median + p75).
- Breakdown table by:
  - ATS
  - company
  - role family
  - match band

8. Add analytics filter bar
- Date range, ATS, company, status scope.
- Keep UI theme consistent with board/profile styles.

9. Add CSV export for visible breakdown table (v1)

### QA
10. Tests
- Unit:
  - conversion math
  - time-in-stage math
  - normalization edge cases
- Integration:
  - status change writes history row
  - backfill behavior for legacy jobs
- API contract:
  - filter combinations
  - empty-state responses

---

## Resume + Cover Letter Generation (v1 - Human-in-the-loop)

### Goal
- Generate editable, job-tailored drafts and track version usage per application.

### Data + Backend
1. Add `application_documents` table
- Columns:
  - `id` (PK)
  - `url` (FK -> `jobs.url`)
  - `doc_type` (`resume` | `cover_letter`)
  - `title`
  - `content_markdown`
  - `content_plain` (nullable)
  - `model` (nullable)
  - `prompt_version` (nullable)
  - `created_at`
  - `updated_at`
  - `is_used` (0/1)
- Indexes:
  - `(url, doc_type, created_at DESC)`
  - `(url, is_used)`

2. Add `application_attempts` table (recommended for attribution)
- Columns:
  - `id` (PK)
  - `url` (FK -> `jobs.url`)
  - `resume_doc_id` (nullable FK)
  - `cover_letter_doc_id` (nullable FK)
  - `applied_at`
  - `notes` (nullable)

3. Add document APIs
- `POST /api/jobs/{job_url}/documents/generate`
- `GET /api/jobs/{job_url}/documents`
- `POST /api/jobs/{job_url}/documents` (save edited version)
- `PATCH /api/documents/{id}` (rename, mark used)
- `POST /api/jobs/{job_url}/application-attempts`

4. Prompting + safety
- Add prompts/templates in `prompts.yaml` for:
  - resume draft
  - cover letter draft
- Constraints:
  - no fabricated experience
  - preserve facts from profile/job only
  - insert placeholders when required info missing

### Frontend
5. Sidebar actions
- Add:
  - `Generate Resume Draft`
  - `Generate Cover Letter Draft`

6. Draft editor workflow
- Open draft modal/page with:
  - editable markdown
  - preview
  - save as new version
  - mark as used for application

7. Version history
- Show existing versions per job by document type.
- Support rename/select/mark-used actions.

8. Timeline integration
- Record events when doc generated/saved/marked-used.

### QA
9. Tests
- Unit:
  - generation payload construction from job/profile data
  - validation of doc type and save flows
- Integration:
  - generate -> edit -> save version -> mark used -> application attempt link
- UI:
  - editor state, version list actions, error states

---

## Cross-cutting
1. Update docs when each milestone ships
- API docs
- dashboard frontend docs
- quickstart/runbook (if commands or flows change)

2. Update changelogs for each release slice
- `CHANGELOG.md`
- `docs/reference/changelog-docs.md`

3. Keep performance guardrails
- Analytics endpoints must remain responsive with cache.
- Frontend routes must preserve current board/profile responsiveness.
