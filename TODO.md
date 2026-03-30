# TODO

Last updated: 2026-03-30

## Current status

- No active implementation batch is currently open in this file.
- Core dashboard, assistant workflow, caching, manual-add, duplicate prevention, and retry-processing work are shipped.
- Historical implementation detail has been moved into `CHANGELOG.md` so this file can stay actionable.

## Recently completed

- [x] Normalize job descriptions before persistence and enrichment
- [x] Close the job drawer on outside click
- [x] Prevent duplicate manual jobs by URL and normalized content matching
- [x] Reopen the existing record when manual add hits a duplicate
- [x] Make manual add save instantly and run processing asynchronously
- [x] Add durable processing state and retry-processing flow
- [x] Bring `Today` and `Insights` assistant reads to Redis + `ETag` cache parity
- [x] Rework `Today` into an operational landing page
- [x] Replace misleading later-stage interview-likelihood framing with stage-aware guidance
- [x] Split the dashboard into `Today`, `Board`, and `Insights`
- [x] Simplify the manual-add modal so it uses required markers and concise validation instead of explanatory UI copy
- [x] Verify retry-processing and stale-cache hardening paths after integration

## Deferred / future backlog

### [ ] Smart manual-add parsing with browser/computer-use assistance

Goal:
- reduce manual typing when adding jobs from pasted job-board URLs or raw job text

Why this is deferred:
- multi-board extraction is too brittle for rule-only parsing
- this likely needs browser/computer-use style automation rather than site-specific heuristics

Planned direction:
- use a browser/computer-use flow to extract and prefill:
  - title
  - company
  - location
  - posted date
  - source / ATS hints
- keep this as prefill assistance, not a silent auto-ingestion path
- do not add a parse-from-URL control to the current modal until that extraction path is designed properly

## Verification commands

Backend regression:

```bash
pytest -q tests/test_advisor_recommendation.py tests/test_job_id_routes.py tests/test_dashboard_cache_runtime.py tests/test_daily_briefing.py tests/test_profile_and_repository.py tests/test_db_description_normalization.py tests/test_teamtailor_support.py tests/test_job_description_pdf_export.py
```

Frontend build:

```bash
cd src/dashboard/frontend
npm.cmd run build
```

## Notes

- Resume tailoring and cover-letter generation are intentionally not tracked in this file yet.
- When a new implementation batch starts, add only open work here; keep shipped detail in `CHANGELOG.md`.
