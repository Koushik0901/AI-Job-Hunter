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
- `first_seen` TEXT NOT NULL
- `last_seen` TEXT NOT NULL

### `job_enrichments`

- `url` TEXT PRIMARY KEY references `jobs(url)`
- `work_mode`
- `remote_geo`
- `canada_eligible`
- `seniority`
- `role_family`
- `years_exp_min`
- `years_exp_max`
- `required_skills` (JSON string)
- `preferred_skills` (JSON string)
- `salary_min`
- `salary_max`
- `salary_currency`
- `visa_sponsorship`
- `red_flags` (JSON string)
- `enriched_at`
- `enrichment_status`
- `enrichment_model`

## Upsert logic

`save_jobs()`:

- insert new URL -> increments `new_count`, sets `first_seen` and `last_seen`
- update existing URL -> refreshes fields and `last_seen`

`save_enrichment()`:

- uses `INSERT OR REPLACE`
- writes one full enrichment row per URL

## Enrichment selection logic

`load_unenriched_jobs(force=False)`:

- default picks URLs with no enrichment row or row where status != `ok`

`load_unenriched_jobs(force=True)`:

- picks all jobs with non-empty description

## Date conventions

- scrape persistence uses `YYYY-MM-DD` strings for first/last seen
- enrichment uses full ISO timestamp in `enriched_at`
