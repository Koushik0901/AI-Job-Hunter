# Database Storage

Persistence is implemented in `src/db.py`.

## Connection modes

- Local: `sqlite3.connect(path)`
- Turso/libsql: custom `_TursoConnection` wrapper over hrana HTTP `/v2/pipeline`

`_TursoConnection.commit()` is a no-op because statements auto-commit remotely.

## Tables

### `jobs`

- `url` TEXT PRIMARY KEY
- `company` TEXT
- `title` TEXT
- `location` TEXT
- `posted` TEXT
- `ats` TEXT
- `description` TEXT
- `application_status` TEXT
- `first_seen` TEXT NOT NULL
- `last_seen` TEXT NOT NULL

`application_status` allowed values from lifecycle command:

- `not_applied`
- `staging`
- `applied`
- `interviewing`
- `offer`
- `rejected`

### `company_sources`

- `id` INTEGER PRIMARY KEY
- `name` TEXT NOT NULL
- `ats_type` TEXT NOT NULL
- `ats_url` TEXT NOT NULL
- `slug` TEXT NOT NULL
- `enabled` INTEGER NOT NULL DEFAULT 1
- `source` TEXT
- `created_at` TEXT NOT NULL
- `updated_at` TEXT NOT NULL

`ats_type` validation currently allows:

- `greenhouse`
- `lever`
- `ashby`
- `workable`
- `smartrecruiters`
- `recruitee`

Indexes:

- unique `ats_url`
- unique `(ats_type, slug)`
- non-unique `enabled`

### `job_enrichments`

- `url` TEXT PRIMARY KEY references `jobs(url)`
- `work_mode`
- `remote_geo`
- `canada_eligible`
- `seniority`
- `role_family`
- `years_exp_min`
- `years_exp_max`
- `minimum_degree`
- `required_skills` (JSON string)
- `preferred_skills` (JSON string)
- `formatted_description` (Markdown, nullable, UI-ready)
- `salary_min`
- `salary_max`
- `salary_currency`
- `visa_sponsorship`
- `red_flags` (JSON string)
- `enriched_at`
- `enrichment_status`
- `enrichment_model`

### `candidate_profile`

- `id` INTEGER PRIMARY KEY (singleton row `1`)
- `years_experience` INTEGER
- `skills` (JSON string)
- `target_role_families` (JSON string)
- `requires_visa_sponsorship` INTEGER (`0/1`)
- `updated_at`

Used by `src/match_score.py` to compute dashboard/CLI job-fit scoring.

## Upsert logic

`save_jobs()`:

- insert new URL -> increments `new_count`, sets `first_seen` and `last_seen`
- update existing URL -> refreshes fields and `last_seen`

`save_enrichment()`:

- uses `INSERT OR REPLACE`
- writes one full enrichment row per URL

`get_candidate_profile()` / `upsert_candidate_profile()`:

- read/write singleton profile row (`id=1`) used for scoring
- normalize JSON arrays for `skills` and `target_role_families`

`upsert_company_source()`:

- inserts/upserts by `ats_url`
- fallback update path for `(ats_type, slug)` conflict cases
- updates timestamps on mutations

## Enrichment selection logic

`load_unenriched_jobs(force=False)`:

- selects rows with no enrichment row or status not equal to `ok`

`load_unenriched_jobs(force=True)`:

- selects all rows with non-empty description

## Retention pruning logic

`prune_not_applied_older_than_days(days, dry_run)`:

- filters rows where:
  - `application_status` is null/empty/`not_applied`
  - `posted` exists and SQLite `date(posted)` is <= `date('now', -days)`
  - status is not in protected set (`staging`, `applied`, `interviewing`, `offer`, `rejected`, `withdrawn`)
- dry-run returns count only
- apply mode deletes rows and returns deleted count

## Date conventions

- scrape persistence uses `YYYY-MM-DD` strings for `first_seen` and `last_seen`
- posted values come from source metadata normalization and are stored as date-like strings
- enrichment uses full ISO timestamp in `enriched_at`
