# Scraping Pipeline Solidification — Design

**Date:** 2026-04-25
**Status:** Approved
**Scope:** Task (1) from TODO.md — partial. Covers diagnosis, fixes, regression tests, and `sources check-all` CLI. Excludes Career-Ops repo review and Wellfound feasibility evaluation (deferred to backlog).

---

## Problem

Only Greenhouse fetches reliably. Lever, Ashby, and Workable are suspected broken — AltaML is registered in `company_sources` with a valid Lever URL but no jobs land in `jobs`. The failure mode is unknown: it could be an HTTP error, a response shape change, missing request headers, a wrong slug in `companies.yaml`, or a silent drop in the title/location filter. Every other feature (scoring, dashboard, agent) degrades when the data supply is broken.

---

## Approach

**Diagnose live → fix → record fixtures → write regression tests → add check-all CLI.**

The failure mode is unknown, so we treat diagnosis as its own step (a throwaway triage script) before touching any fetcher code. Once we have ground truth, fixes are scoped to `fetchers.py` and `companies.yaml`. Tests are written against real API response snapshots recorded after the fix.

---

## Section 1 — Triage

A script at `scripts/triage_fetchers.py`. Calls each fetcher against a known-good slug, prints HTTP outcome + field names in the first record + job count. Nothing is saved, nothing is modified.

**Known-good slugs:**

| ATS | Slug | Basis |
|---|---|---|
| greenhouse | `stripe` | large board, always hiring |
| lever | `lever` | Lever's own jobs board — self-referential, always live |
| ashby | `ashby` | same |
| workable | `valsoft-corp` | in existing `test_probe_service_live.py` |
| smartrecruiters | `Visa` | in existing live test |
| recruitee | `recruitee` | self-referential — substitute with first company in `company_sources` if slug is invalid |
| teamtailor | `teamtailor` | self-referential — substitute with first company in `company_sources` if slug is invalid |
| hn | — | no slug; checks thread lookup only |

Output: plain table — ATS, slug, status (`OK` / `ERROR` / `EMPTY`), job count, and for errors: exception class + message.

---

## Section 2 — Fix Strategy

After triage, each broken fetcher is resolved via one of three paths:

### Path 1 — HTTP error (4xx/5xx): endpoint or request changed

Known fragile spots to check before triage even runs:

- **Lever** (`api.lever.co/v0/postings/{slug}`): public, auth-free API, but Lever's bot-detection has tightened. The fetcher sends no `User-Agent`. Fix: add the browser `User-Agent` already present in `probe_service.py`'s `_DEFAULT_HEADERS`.
- **Ashby** (HTML scrape for `jobPostings` key): if Ashby's Next.js hydration structure changed, the key may have moved or the JSON is split across script tags. Known stable fallback: `api.ashbyhq.com/posting-api/job-board/{slug}` — Ashby's public posting API, more reliable than scraping.
- **Workable** (v3 POST): requires `Origin` and `Referer` headers. These are present in `probe_service.py` but **absent from `fetch_workable()` in `fetchers.py`**. Fix: add the same headers to the fetcher.

### Path 2 — Empty results, no HTTP error

Two sub-cases:
- Wrong slug in `companies.yaml` — e.g. AltaML's Lever slug should be `altaml`, not the full URL.
- Company genuinely has no open roles — confirm by checking their careers page.

### Path 3 — Jobs fetched but none land in DB

The pipeline drops them after fetch. Trace order:
`fetch_<ats>` → `normalize_<ats>` → `passes_title_filter` → `passes_location_filter` → `db.save_jobs`

The title/location filter is the most common silent drop. Fix is in `companies.yaml` (add correct location tags) or the filter config — not in the fetcher itself.

**Constraint:** All fixes are confined to `fetchers.py` and `companies.yaml`. No schema changes, no new DB columns.

---

## Section 3 — Regression Tests

### Fixture recording

Script at `scripts/record_fixtures.py`. Calls each fetcher's underlying HTTP layer against the known-good slugs and saves raw responses to `tests/fixtures/`. File naming: `<ats>_<slug>.(json|html)`. HTML for scrapers (Ashby, Teamtailor); JSON for API-based fetchers. Re-record at any time by re-running the script — it overwrites in place.

### Test structure

One file per ATS, matching the existing `test_fetchers_workable.py` pattern:

```
tests/
  test_fetchers_greenhouse.py
  test_fetchers_lever.py
  test_fetchers_ashby.py
  test_fetchers_workable.py   ← already exists (keep)
  test_fetchers_smartrecruiters.py
  test_fetchers_recruitee.py
  test_fetchers_teamtailor.py
  fixtures/
    greenhouse_stripe.json
    lever_lever.json
    ashby_ashby.html
    workable_valsoft-corp.json
    smartrecruiters_Visa.json
    recruitee_recruitee.json
    teamtailor_teamtailor.html
```

Each test monkeypatches `requests.get` / `requests.post` to return a `_FakeResponse` loaded from the fixture file — same pattern as the existing Workable test. No network required at test time.

### Assertions per fetcher test (three things only)

1. Fetcher returns a non-empty list (at least 1 job).
2. Every returned job has the required normalizer keys: `company`, `title`, `location`, `url`, `posted`, `ats`.
3. `url` is a non-empty string starting with `https://`.

### Normalizer unit tests

A separate parametrized section (or file) tests `normalize_<ats>()` in isolation with a single hand-crafted dict. Catches field-name drift silently. Covers: field mapping, `_normalize_datetime()` on each ATS's date format, location extraction.

### Infrastructure

A `load_fixture(name)` helper in `tests/conftest.py`:
```python
def load_fixture(name: str) -> str:
    return (Path(__file__).parent / "fixtures" / name).read_text(encoding="utf-8")
```

No new dependencies.

---

## Section 4 — `sources check-all` CLI

### Command

```bash
uv run ai-job-hunter sources check-all
```

Registered in `company_sources.py` alongside existing `check`, `list`, `enable`, `disable`.

### Behaviour

Reads every enabled row from `company_sources`. Probes each concurrently via the existing `probe_service` infrastructure. Prints a Rich table.

**Output columns:** Company · ATS · Status · Jobs · URL

**Status colour coding:**
- `OK` — green (≥1 job returned)
- `EMPTY` — yellow (probe succeeded but 0 jobs)
- `ERROR` — red (network or HTTP failure; short exception message in the row)

**Summary line** after the table: `14 OK · 2 empty · 1 error of 17 sources checked`

### Options

- `--include-disabled` — also probe disabled rows (useful during triage)
- `--ats <name>` — scope to one provider, e.g. `--ats lever`

### Implementation

**No `--save` flag.** Writing health state back to DB belongs in task (2) (Sources Management UI), which will design those columns properly. YAGNI.

**Files touched:**
- `src/ai_job_hunter/commands/company_sources.py` — new `check-all` branch (~40 lines)
- `src/ai_job_hunter/services/probe_service.py` — add `probe_company_sources_all(rows)` wrapper that builds the slug list and template dict from DB rows and delegates to the existing `probe_all()`

No schema changes. No new dependencies.

---

## Files Changed / Created

| File | Action |
|---|---|
| `scripts/triage_fetchers.py` | New — throwaway diagnostic |
| `scripts/record_fixtures.py` | New — fixture recorder |
| `src/ai_job_hunter/fetchers.py` | Modified — fix broken fetchers |
| `companies.yaml` | Modified — correct wrong slugs |
| `src/ai_job_hunter/commands/company_sources.py` | Modified — add `check-all` subcommand |
| `src/ai_job_hunter/services/probe_service.py` | Modified — add `probe_company_sources_all()` |
| `tests/conftest.py` | Modified — add `load_fixture()` helper |
| `tests/fixtures/<ats>_<slug>.(json\|html)` | New — recorded response snapshots |
| `tests/test_fetchers_<ats>.py` | New — one file per ATS |

---

## Out of Scope

- Career-Ops GitHub repo review — deferred to backlog
- Wellfound / AngelList Talent feasibility — deferred to backlog
- Writing health state back to `company_sources` — belongs in task (2)
- Any UI changes
