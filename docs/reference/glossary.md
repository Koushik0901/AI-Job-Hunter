# Glossary

- ATS: Applicant Tracking System.
- Backfill enrichment: running enrichment against stored jobs missing successful extraction.
- Company source registry: DB table `company_sources` that defines scrape targets.
- Canada eligibility: extracted label describing if role can be worked from Canada.
- HN: Hacker News.
- Job normalization: mapping source-specific fields to common schema.
- Job match score: deterministic `0-100` fit score from profile + job enrichment/title signals.
- Scoring rubric: weighted rules in `docs/dashboard/match-scoring.md` implemented in `src/match_score.py`.
- Lifecycle status: `jobs.application_status` used to track application progression and retention protection.
- Candidate profile: singleton DB row (`candidate_profile`) containing years/skills/targets/visa preference for scoring.
- Prune: retention cleanup that removes old non-applied jobs (dry-run by default).
- RateLimitSignal: control exception used to pause pipelines cleanly on repeated 429 errors.
- Student model: lower-cost evaluation candidate model.
- Teacher model: higher-quality baseline model used as scoring reference.
- Turso/libsql: hosted SQLite-compatible database service.
