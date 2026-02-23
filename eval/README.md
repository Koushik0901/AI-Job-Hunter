# Eval Framework

Compares student enrichment models against a teacher model on real job descriptions and reports field-level extraction quality.

Primary implementation: `eval/eval.py`.

## Core workflow

```bash
uv run python eval/eval.py crawl
uv run python eval/eval.py build
uv run python eval/eval.py cost
uv run python eval/eval.py run
uv run python eval/eval.py report
```

## Command reference

### Crawl

```bash
uv run python eval/eval.py crawl [--source-db PATH] [--db PATH] [--limit N]
```

- Scrapes using broader title filter than production.
- Disables location filtering.
- Loads enabled company sources from source DB.
- Saves crawled jobs to eval DB (`eval/eval_jobs.db` by default).

### Build

```bash
uv run python eval/eval.py build [--db PATH]
```

- Generates `eval/dataset.yaml` from eval DB.
- Adds `segment` labels to `db_jobs`.
- Preserves existing `manual_jobs` in dataset file.

### Cost

```bash
uv run python eval/eval.py cost [--models MODEL ...] [--teacher MODEL]
```

- Estimates token/cost spend only.
- Uses internal static pricing map with fallback values.

### Run

```bash
uv run python eval/eval.py run [--models MODEL ...] [--teacher MODEL] [--subset N] [--resume] [--workers N] [--provider-order PROVIDER ...]
```

- Requires `OPENROUTER_API_KEY`.
- Runs teacher first, then each student model.
- Writes checkpoint after each completed job.
- Supports resume from checkpoint and partial model retries.

### Report

```bash
uv run python eval/eval.py report [results_file]
```

- Reads latest result file by default.
- Prints model comparison tables and diagnostics.

## Scored fields

Categorical:

- `work_mode`
- `canada_eligible`
- `seniority`
- `role_family`
- `visa_sponsorship`

List (F1 + precision + recall diagnostics):

- `required_skills`
- `preferred_skills`
- `red_flags`

Numeric:

- `years_exp_min`
- `years_exp_max`

Salary:

- `salary_min`
- `salary_max`
- `salary_currency`

`remote_geo` is intentionally not scored.

## Artifacts

- Dataset: `eval/dataset.yaml`
- Eval DB: `eval/eval_jobs.db` (git-ignored)
- Results JSON: `eval/results/*.json` (git-ignored)
- Checkpoint: `eval/results/checkpoint.json`

## Additional references

- Main docs index: [`../docs/INDEX.md`](../docs/INDEX.md)
- Eval deep reference: [`../docs/evaluation/eval-framework.md`](../docs/evaluation/eval-framework.md)
- CLI details: [`../docs/cli/eval.md`](../docs/cli/eval.md)
