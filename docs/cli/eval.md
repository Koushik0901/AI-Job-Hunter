# `eval.py` CLI Reference

Command group:

```bash
uv run python eval/eval.py <subcommand> [options]
```

Subcommands:

- `crawl`
- `build`
- `cost`
- `run`
- `report`

## `crawl`

```bash
uv run python eval/eval.py crawl [--source-db PATH] [--db PATH] [--limit N]
```

- Loads enabled company sources from production source DB (`jobs.db` by default).
- Uses broader eval title filter and disables location filtering.
- Saves crawled jobs into eval DB (`eval/eval_jobs.db` by default).

Options:

- `--source-db PATH`: source DB for company registry and scrape input.
- `--db PATH`: output eval DB path.
- `--limit N`: cap number of crawled rows after filtering.

## `build`

```bash
uv run python eval/eval.py build [--db PATH]
```

- Builds `eval/dataset.yaml` from eval DB records with non-empty descriptions.
- Assigns segment tags using `tag_segment`.
- Preserves existing `manual_jobs` entries in dataset file.

## `cost`

```bash
uv run python eval/eval.py cost [--models MODEL...] [--teacher MODEL]
```

- Estimates token and cost totals without API calls.
- Uses static `PRICING` map and `PRICING_FALLBACK` for unknown models.

## `run`

```bash
uv run python eval/eval.py run [--models MODEL...] [--teacher MODEL] [--subset N] [--resume] [--workers N] [--provider-order PROVIDER...]
```

- Requires `OPENROUTER_API_KEY`.
- Runs teacher first, then each student model.
- Checkpoints after each completed job.
- Supports resume and model subset on resume.

Rate-limit semantics:

- Uses `RateLimitSignal` from enrichment module.
- On model-level exhaustion, persists partial progress + checkpoint.

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

Targets are encoded in `_SEGMENT_TARGETS` and shown during crawl/build summaries.
