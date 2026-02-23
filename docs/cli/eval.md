# `eval.py` CLI Reference

Command group:

```bash
uv run python eval/eval.py <subcommand> [options]
```

Subcommands:

- `build`
- `crawl`
- `cost`
- `run`
- `report`

## `crawl`

```bash
uv run python eval/eval.py crawl [--config PATH] [--db PATH] [--limit N]
```

- Scrapes jobs with broader title filter and no location filter.
- Stores results in `eval_jobs.db` style schema.
- Prints location and segment distribution preview.

## `build`

```bash
uv run python eval/eval.py build [--db PATH]
```

- Builds `eval/dataset.yaml` from DB records with non-empty descriptions.
- Assigns segment tags using `tag_segment`.
- Preserves existing `manual_jobs` entries.

## `cost`

```bash
uv run python eval/eval.py cost [--models MODEL...] [--teacher MODEL]
```

- Estimates token and cost totals without API calls.
- Uses hardcoded `PRICING` table and fallback pricing for unknown models.

## `run`

```bash
uv run python eval/eval.py run [--models MODEL...] [--teacher MODEL] [--subset N] [--resume] [--workers N] [--provider-order PROVIDER...]
```

- Requires `OPENROUTER_API_KEY`.
- Runs teacher first, then each student model.
- Checkpoints after each completed job.
- Supports resume and model subset on resume.

Rate limit semantics:

- Uses `RateLimitSignal` from enrichment module.
- On model-level exhaustion, keeps checkpoint and continues other models.

## `report`

```bash
uv run python eval/eval.py report [results_file]
```

- Default input is latest JSON in `eval/results/` excluding `checkpoint.json`.
- Prints field matrix, diagnostics, confusion matrix, segment breakdown, and verdict.

## Data contracts

Dataset (`eval/dataset.yaml`) includes:

- `db_jobs`: auto-generated records with IDs and `segment`
- `manual_jobs`: optional user-curated rows

Results JSON includes:

- metadata (`run_at`, `teacher_model`, `student_models`, `partial`)
- per-job teacher/student outputs and scores
- aggregate metrics per model

## Segment strategy

Priority order:

1. `seniority_extreme`
2. `red_flag`
3. `remote_geo_edge`
4. `salary_disclosed`
5. `sparse`
6. `core`

Targets are encoded in `_SEGMENT_TARGETS` and displayed during build/crawl summaries.
