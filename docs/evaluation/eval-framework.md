# Eval Framework Details

Primary implementation: `eval/eval.py`.

## Purpose

Compare multiple student extraction models against a teacher model across structured enrichment fields.

## Default model set

- Teacher: `openai/gpt-5.2`
- Students:
  - `openai/gpt-oss-120b`
  - `google/gemma-3-12b-it`
  - `google/gemma-3-27b-it`
  - `nvidia/nemotron-3-nano-30b-a3b`
  - `mistralai/mistral-small-3.2-24b-instruct`
  - `qwen/qwen3-30b-a3b-thinking-2507`
  - `meta-llama/llama-4-scout`

## Workflow

```bash
uv run python eval/eval.py crawl
uv run python eval/eval.py build
uv run python eval/eval.py cost
uv run python eval/eval.py run
uv run python eval/eval.py report
```

## Scoring dimensions

Field groups:

- categorical
- list fields (F1 + precision + recall)
- numeric years exp (tolerance scoring)
- salary values/currency

Overall score:

- equal-weight mean across scored fields.

## Checkpointing

File: `eval/results/checkpoint.json`

- checkpoint updated after each completed job result
- resume validates teacher/model/job set compatibility
- allows narrowing `--models` on resume for targeted retries

## Output artifacts

- `eval/results/<timestamp>_<teacher>_<N>models.json`
- optional partial outputs when rate-limited
- console summary ranking by overall score

## Analysis notebook

`eval/eval_analysis.ipynb` provides deeper inspection and visual analysis for result JSON files.
