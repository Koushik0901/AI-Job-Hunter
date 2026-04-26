# Source Discovery Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expand `company_sources` coverage automatically via two mechanisms: a one-off career-ops company import and a recurring Brave-powered discovery pipeline driven by the user's candidate profile.

**Architecture:** `sources import career-ops` seeds the DB from the career-ops `portals.example.yml`. `sources discover` generates Brave Search queries from the candidate profile (`desired_job_titles` + `country` + `preferred_work_mode`), normalizes result URLs to `(ats_type, slug)` pairs, probes new sources, and auto-adds confirmed hits. Both live as subcommands of the existing `sources` CLI. A weekly GitHub Actions workflow runs `sources discover` on a schedule.

**Tech Stack:** Python, Brave Search API (`BRAVE_SEARCH_API_KEY`), existing `probe_service._ATS_PROBES` + `probe_all()`, existing `db.upsert_company_source()`, Rich for output, pytest for tests.

---

## Architecture & New Files

### New files

- **`src/ai_job_hunter/services/discovery_service.py`**
  - `build_discovery_queries(profile: dict) -> list[str]` — generates Brave query strings from `desired_job_titles`, `country`, `preferred_work_mode`
  - `brave_search(query: str, api_key: str, count: int = 10) -> list[str]` — calls Brave Web Search API, returns list of result URLs
  - `normalize_url(url: str) -> tuple[str, str] | None` — maps a job board URL to `(ats_type, slug)` or `None` if unrecognized

- **`.github/workflows/discovery.yml`**
  - Weekly cron: `0 18 * * 0` (Sundays 18:00 UTC)
  - `workflow_dispatch` for manual trigger
  - Runs `uv run ai-job-hunter sources discover`
  - Requires `BRAVE_SEARCH_API_KEY` secret; exits cleanly with a warning if absent

### Modified files

- **`src/ai_job_hunter/commands/company_sources.py`**
  - `import career-ops` subcommand
  - `discover` subcommand with `--dry-run` flag

- **`src/ai_job_hunter/services/company_source_service.py`**
  - `parse_career_ops_portals(yaml_text: str) -> list[tuple[str, str, str]]` — parses career-ops `portals.example.yml`, returns `(name, ats_type, slug)` triples

- **`.env.example`**
  - Add `BRAVE_SEARCH_API_KEY=` entry with comment

---

## Feature 1 — `sources import career-ops`

Fetches `portals.example.yml` from the career-ops repo via raw GitHub URL:
```
https://raw.githubusercontent.com/santifer/career-ops/main/templates/portals.example.yml
```

**Parser rules (`parse_career_ops_portals`):**
- Entry has `api:` field containing `greenhouse.io` → extract greenhouse slug from path
- Entry `careers_url` matches `jobs.ashbyhq.com/{slug}` → ashby
- Entry `careers_url` matches `jobs.lever.co/{slug}` → lever
- Entry has only `scan_method: websearch` with no parseable ATS URL → skip
- Entry `careers_url` is a branded page (e.g. `retool.com/careers`) with no ATS pattern → skip

**Import flow:**
1. Fetch and parse YAML → list of `(name, ats_type, slug)`
2. Load existing `company_sources` rows
3. Dedup by `(ats_type, slug.lower())` — skip anything already present
4. Probe new candidates via existing `probe_all()` in `probe_service`
5. Upsert confirmed hits via `upsert_company_source()` with `source='career-ops-import'`
6. Print Rich summary: added N / already present N / probe-failed N

No flags. This is a seed operation — safe to re-run (dedup prevents duplicates).

---

## Feature 2 — `sources discover`

### Query generation (`build_discovery_queries`)

Takes the candidate profile dict and generates one Brave query per `(title_group × ATS)`:

- **Role terms:** `desired_job_titles` list. If empty, `sources discover` prints a friendly message ("Complete your profile's desired job titles to enable discovery") and exits cleanly.
- **Location terms:** `country` field (if set) + `"remote"` (if `preferred_work_mode` is `"remote"` or `"hybrid"`). If neither is set, no location filter is appended.
- **ATS site filters:** `site:jobs.ashbyhq.com`, `site:job-boards.greenhouse.io`, `site:jobs.lever.co`

Example output for a user with `desired_job_titles=["Machine Learning Engineer", "Data Scientist"]`, `country="Canada"`, `preferred_work_mode="remote"`:
```
site:jobs.ashbyhq.com "Machine Learning Engineer" OR "Data Scientist" Canada OR remote
site:job-boards.greenhouse.io "Machine Learning Engineer" OR "Data Scientist" Canada OR remote
site:jobs.lever.co "Machine Learning Engineer" OR "Data Scientist" Canada OR remote
```

Generates 3 queries (one per ATS). Titles are joined with `OR` within each query — no combinatorial explosion.

### Brave Search API (`brave_search`)

```
GET https://api.search.brave.com/res/v1/web/search
Headers: X-Subscription-Token: {BRAVE_SEARCH_API_KEY}
Params:  q={query}, count=10
```

Returns `response.json()["web"]["results"][].url`. On HTTP error or missing `web` key, logs a warning and returns `[]` — never raises.

Free tier: 2,000 queries/month. 3 queries/run × weekly = ~13/month. Well within limit.

### URL normalizer (`normalize_url`)

Maps raw search result URLs to `(ats_type, slug)` pairs using regex:

| URL pattern | ats_type | slug extraction |
|---|---|---|
| `boards-api.greenhouse.io/v1/boards/{slug}/jobs` | greenhouse | regex `boards/([^/]+)/jobs` |
| `job-boards.greenhouse.io/{slug}` | greenhouse | first path segment |
| `boards.greenhouse.io/{slug}` | greenhouse | first path segment |
| `jobs.ashbyhq.com/{slug}` | ashby | path segment 1 |
| `jobs.lever.co/{slug}` | lever | path segment 1 |
| `apply.workable.com/{slug}` | workable | path segment 1 |
| `{slug}.recruitee.com` | recruitee | subdomain |
| `{slug}.teamtailor.com` | teamtailor | subdomain |

Anything not matching a known pattern returns `None` and is silently skipped.

### Discovery flow

1. Load candidate profile from DB
2. Call `build_discovery_queries(profile)` — if empty, exit with message
3. For each query: call `brave_search(query, api_key)` → list of URLs
4. For each URL: call `normalize_url(url)` → `(ats_type, slug)` or skip
5. Dedup across all queries and against existing `company_sources` rows (by `(ats_type, slug.lower())`)
6. Probe new candidates via `probe_all(slugs, url_templates)` where `url_templates` is built from `_ATS_PROBES` — returns only rows where the probe succeeded (status OK, non-empty jobs list)
7. Upsert confirmed hits via `upsert_company_source()` with `source='discovery'`
8. `--dry-run`: print what would be added, skip steps 7

### Output (Rich table)

```
sources discover -- 3 new sources found

  Name              ATS      Status  Jobs  Action
  Cohere            ashby    OK       212  added
  Mistral AI        lever    OK        18  added
  LangChain         ashby    EMPTY      0  skipped
```

Per-run summary line: `N new sources probed, N added, N skipped (empty), N failed`.

---

## Scheduling

`.github/workflows/discovery.yml`:

```yaml
name: Source Discovery

on:
  schedule:
    - cron: '0 18 * * 0'   # Sundays 18:00 UTC
  workflow_dispatch:

jobs:
  discover:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync
      - name: Run discovery
        run: uv run ai-job-hunter sources discover
        env:
          TURSO_URL: ${{ secrets.TURSO_URL }}
          TURSO_AUTH_TOKEN: ${{ secrets.TURSO_AUTH_TOKEN }}
          BRAVE_SEARCH_API_KEY: ${{ secrets.BRAVE_SEARCH_API_KEY }}
        continue-on-error: false
    # If BRAVE_SEARCH_API_KEY is absent, sources discover exits cleanly with a warning
```

---

## CLI Interface

Registered in `company_sources.py` alongside existing `check`, `check-all`, `list`, `enable`, `disable`:

```
uv run ai-job-hunter sources import career-ops
uv run ai-job-hunter sources discover [--dry-run]
```

`--dry-run` prints the discovery table without writing to DB. Useful for new users verifying their profile generates sensible queries.

---

## Testing

### `tests/test_discovery_service.py`

- `test_build_discovery_queries_basic` — 2 titles + country + remote → 3 queries (one per ATS), each containing all titles joined with OR and location terms
- `test_build_discovery_queries_remote_only` — `preferred_work_mode="remote"`, no country → queries include "remote" but no country term
- `test_build_discovery_queries_no_country_no_remote` — neither set → queries have no location filter, still valid
- `test_build_discovery_queries_empty_titles` — `desired_job_titles=[]` → returns `[]`
- `test_normalize_url_greenhouse_boards_api` — `boards-api.greenhouse.io/v1/boards/anthropic/jobs` → `("greenhouse", "anthropic")`
- `test_normalize_url_greenhouse_job_boards` — `job-boards.greenhouse.io/openai` → `("greenhouse", "openai")`
- `test_normalize_url_ashby` — `jobs.ashbyhq.com/cohere` → `("ashby", "cohere")`
- `test_normalize_url_lever` — `jobs.lever.co/mistral` → `("lever", "mistral")`
- `test_normalize_url_workable` — `apply.workable.com/mila-institute/` → `("workable", "mila-institute")`
- `test_normalize_url_recruitee` — `acme.recruitee.com/api/offers` → `("recruitee", "acme")`
- `test_normalize_url_teamtailor` — `rvezy.teamtailor.com/jobs` → `("teamtailor", "rvezy")`
- `test_normalize_url_unrecognized` — `linkedin.com/jobs/123` → `None`
- `test_brave_search_returns_urls` — mock `requests.get` returning sample JSON → list of URLs, verifies `X-Subscription-Token` header and `q` param
- `test_brave_search_handles_http_error` — mock returning 401 → returns `[]`, no exception

### `tests/test_company_source_service_career_ops.py`

- `test_parse_career_ops_portals_greenhouse_api_field` — YAML with `api: https://boards-api.greenhouse.io/v1/boards/anthropic/jobs` → `("Anthropic", "greenhouse", "anthropic")`
- `test_parse_career_ops_portals_ashby_careers_url` — `careers_url: https://jobs.ashbyhq.com/cohere` → `("Cohere", "ashby", "cohere")`
- `test_parse_career_ops_portals_lever_careers_url` — `careers_url: https://jobs.lever.co/mistral` → `("Mistral AI", "lever", "mistral")`
- `test_parse_career_ops_portals_skips_websearch_only` — entry with only `scan_method: websearch` → not in results
- `test_parse_career_ops_portals_skips_branded_url` — `careers_url: https://retool.com/careers` → not in results
- `test_parse_career_ops_portals_deduplicates` — two entries with same slug → appears once

---

## Key Constraints

- **No YAML config files for end users.** All discovery parameters come from the candidate profile. Users configure through the Profile/Settings UI.
- **Probe before add.** No source is added to `company_sources` without a successful probe (status OK or EMPTY — but only OK rows are added; EMPTY rows are skipped since they have no jobs to scrape).
- **Dedup by `(ats_type, slug.lower())`**, not by name. Two companies could share a similar name with different slugs.
- **Source attribution.** Rows added via import get `source='career-ops-import'`; rows added via discovery get `source='discovery'`.
- **Graceful degradation.** If `BRAVE_SEARCH_API_KEY` is absent, `sources discover` exits with a clear message rather than crashing. The GitHub Actions workflow does not fail the CI run.
- **Windows CP1252.** All `console.print()` output must use ASCII only — no em dashes, no arrows, no emoji.
