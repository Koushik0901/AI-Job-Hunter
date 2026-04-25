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

A script at `scripts/triage_fetchers.py`. Reads `company_sources` from the DB, samples up to 10 companies per ATS, probes them all concurrently via the existing `probe_service` infrastructure, and prints the results. Nothing is saved, nothing is modified.

**Sampling:** For each ATS provider, select up to 10 rows at random from `company_sources` (all rows if fewer than 10 exist for that ATS). The sample is re-randomised on each run so repeated runs give wider coverage over time.

**Output:** One flat Rich table, sorted by ATS then company name:

| ATS | Company | Slug | Status | Jobs | Note |
|---|---|---|---|---|---|
| ashby | Cohere | cohere | OK | 12 | |
| ashby | Notion | notion | OK | 8 | |
| ashby | Properly | properly | EMPTY | 0 | |
| lever | AltaML | altaml | ERROR | — | HTTPError 404 |
| lever | Aisera | aisera | OK | 5 | |
| ... | | | | | |

**Status colour coding:** green `OK` (≥1 job), yellow `EMPTY` (probe succeeded, 0 jobs), red `ERROR` (network/HTTP failure — short exception class + message in Note column).

**Summary block** after the table — one line per ATS:

```
greenhouse   18 OK  ·  2 empty  ·  0 errors  of 10 sampled
lever         6 OK  ·  1 empty  ·  3 errors  of 10 sampled
ashby         9 OK  ·  1 empty  ·  0 errors  of 10 sampled
workable      4 OK  ·  2 empty  ·  4 errors  of 10 sampled
...
```

This gives an error-rate per ATS at a glance — the primary output we need to decide which fetchers to fix first.

**HN** has no slug; the triage checks thread lookup only and reports a single OK/ERROR row.

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

Script at `scripts/record_fixtures.py`. For each ATS, uses one confirmed-OK slug (chosen from the triage output — the first company that returned ≥1 job) to hit the real API and saves the raw response to `tests/fixtures/`. File naming: `<ats>_<slug>.(json|html)`. HTML for scrapers (Ashby, Teamtailor); JSON for API-based fetchers. Re-record at any time by re-running the script — it overwrites in place. The chosen slug is printed to stdout so it's reproducible.

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
    greenhouse_<slug>.json     ← slug determined at record time
    lever_<slug>.json
    ashby_<slug>.html
    workable_<slug>.json
    smartrecruiters_<slug>.json
    recruitee_<slug>.json
    teamtailor_<slug>.html
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
