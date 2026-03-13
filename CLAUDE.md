# CLAUDE.md - AI Job Hunter

Project context and conventions.

## What this project does

Daily ML/AI/Data Science job discovery pipeline.

It scrapes ATS boards (Greenhouse, Lever, Ashby, Workable, SmartRecruiters) plus HN "Who is Hiring", filters by role/location, stores jobs in SQLite or Turso (libsql), optionally enriches jobs with structured LLM extraction via OpenRouter, and sends Telegram notifications for new jobs.

## Primary commands

```bash
# Install deps
uv sync

# Main daily run
uv run python src/cli.py scrape

# Variants
uv run python src/cli.py scrape --no-enrich-llm
uv run python src/cli.py scrape --no-notify
uv run python src/cli.py scrape --no-enrich
uv run python src/cli.py scrape --enrich-backfill
uv run python src/cli.py scrape --re-enrich-all

# Source registry management (DB-backed)
uv run python src/cli.py sources list
uv run python src/cli.py sources check openai
uv run python src/cli.py sources import --dry-run
uv run python src/cli.py sources import
uv run python src/cli.py sources enable <slug-or-id>
uv run python src/cli.py sources disable <slug-or-id>

# Company discovery + add
uv run python src/add_company.py "Hugging Face"
uv run python src/add_company.py "Scale AI" --slug scaleai
uv run python src/add_company.py "OpenAI" --slug openai --add

# Job lifecycle
uv run python src/cli.py lifecycle set-status --url <job_url> --status applied
uv run python src/cli.py lifecycle prune --days 28
uv run python src/cli.py lifecycle prune --days 28 --apply

# Eval framework
uv run python eval/eval.py crawl
uv run python eval/eval.py build
uv run python eval/eval.py cost
uv run python eval/eval.py run
uv run python eval/eval.py report
```

## Architecture

```text
src/
|- cli.py                  # top-level CLI router
|- add_company.py          # discover ATS slug + upsert company source rows
|- fetchers.py             # ATS/HN fetch + normalize + description retrieval
|- db.py                   # SQLite/Turso persistence + migrations
|- enrich.py               # LLM enrichment pipeline
|- notify.py               # dotenv helper + Telegram send
|- dashboard/backend/
|  |- main.py              # FastAPI dashboard + artifact AI run endpoints
|  |- evidence_index.py    # lexical/qdrant evidence retrieval + reindex
|  |- claim_validator.py   # grounded claim policy + citation checks
|  |- resume_agents_swarm/          # resume optimization graph + apply engine
|  |- cover_letter_agents_swarm/    # cover-letter draft/score/rewrite graph
|- commands/
|  |- scrape_jobs.py       # scrape subcommand
|  |- company_sources.py   # sources subcommand
|  |- job_lifecycle.py     # lifecycle subcommand
|- services/
   |- scrape_service.py    # filtering/render/scrape orchestration helpers
   |- probe_service.py     # ATS probing helpers
   |- company_source_service.py  # bulk import + source listing helpers

eval/
|- eval.py                 # crawl/build/cost/run/report
|- eval_jobs.db            # local eval DB (git-ignored)
|- dataset.yaml            # eval dataset
|- results/                # eval outputs (git-ignored)
```

## Key conventions

- Use absolute imports from `src/` modules (`from db import ...`, `from services...`).
- Run commands from repo root so `.env` and default `jobs.db` resolve correctly.
- Source registry is DB-only (`company_sources` table).
- `enrich_one_job()` raises `RateLimitSignal` only after provider retries are exhausted.
- DB migrations use additive `ALTER TABLE ... ADD COLUMN` in `init_db()` with safe guards.
- Prefer ASCII in terminal output for Windows compatibility.
- All artifact AI prompts must remain in YAML files under `prompts/`; do not hardcode prompt bodies in Python.
- For artifact AI rewrites, legal-move outputs are preferred over free-form rewrites.

## Artifact AI (Resume + Cover Letter)

- Resume and cover-letter pipelines are LangGraph-driven with stage flow:
  - score -> rewrite -> verify_moves -> apply -> decide_next -> final_score
- Cover letter pipeline also includes deterministic draft injection and tone guard checks.
- Runtime run state is persisted in DB:
  - `artifact_ai_runs`
  - `artifact_ai_run_events`
- Evidence grounding sources:
  - `evidence_context`
  - `brag_document_markdown`
  - `project_cards`
  - `do_not_claim`
- Truth precedence:
  1) evidence context
  2) current LaTeX content
  3) brag/project cards

### Grounding enforcement

- Claim validator blocks:
  - unsupported technical keywords
  - lower-precedence-only technical keywords
  - missing/invalid citation evidence for claim-introducing edits
- Rewrite ops may include `supported_by: [citation_ids]` and should be preferred.

### Controller gates

- Acceptance gates are configured via env:
  - min score delta
  - max ops per cycle
  - max changed-line ratio
  - force continue on non-negotiables
- Cover-letter controller can force another cycle when tone-guard triggers.

## Source registry model

Company sources are stored in `company_sources` table with fields:
- `name`, `ats_type`, `ats_url`, `slug`, `enabled`, `source`, `created_at`, `updated_at`

Runtime behavior:
- `cli.py scrape` loads only `enabled=1` sources.
- `sources import` pulls candidate slugs from curated GitHub lists and upserts deduped rows.
- `add_company.py` probes multiple ATS patterns and upserts selected matches.

## LLM enrichment behavior (`src/enrich.py`)

- Uses LangChain `ChatOpenAI` against OpenRouter.
- Validates output with Pydantic model `JobEnrichment`.
- On rate limit, retries provider selection and can raise `RateLimitSignal`.
- Backfill mode (`--enrich-backfill`) resumes rows with missing/failed enrichment.

## Database notes

Main tables:
- `jobs` (scraped job records, includes `application_status`)
- `job_enrichments` (structured LLM output)
- `company_sources` (enabled source registry)

Lifecycle pruning:
- `lifecycle prune --days N` targets old rows that are not applied/interviewing/final-decision statuses.
- Dry run is default; `--apply` performs deletion.

## Environment variables

- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TURSO_URL` (optional)
- `TURSO_AUTH_TOKEN` (required with Turso)
- `OPENROUTER_API_KEY` (optional; required for enrichment/eval API runs)
- `ENRICHMENT_MODEL` (optional, default `openai/gpt-oss-120b`)
- `RESUME_SWARM_SCORING_MODEL`, `RESUME_SWARM_REWRITE_MODEL`
- `COVER_LETTER_SWARM_DRAFT_MODEL`, `COVER_LETTER_SWARM_SCORING_MODEL`, `COVER_LETTER_SWARM_REWRITE_MODEL`
- `SWARM_MIN_SCORE_DELTA`, `SWARM_MAX_OPS_PER_CYCLE`, `SWARM_MAX_CHANGED_LINE_RATIO`, `SWARM_FORCE_ON_NON_NEGOTIABLES`
- `EVIDENCE_RETRIEVAL_MODE`, `EVIDENCE_MAX_TOP_K`, `EVIDENCE_MIN_LEXICAL_OVERLAP`, `EVIDENCE_MIN_VECTOR_SCORE`
- `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_EVIDENCE_COLLECTION`
- `EVIDENCE_EMBED_MODEL`, `EVIDENCE_EMBED_CACHE_PATH`

## Known gotchas

- SmartRecruiters and Workable can return HTTP 200 with zero jobs for invalid slugs; probing logic suppresses zero-job hits from add flow.
- Telegram has message-length/rate constraints; notifier chunks output.
- If `TURSO_URL` is set, it overrides local `--db` paths.
