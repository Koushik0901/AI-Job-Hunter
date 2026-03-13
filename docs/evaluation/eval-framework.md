# 🚀 Eval Framework Details

This is the deeper technical reference for `eval/eval.py` and `eval/swarm_benchmark.py`.

---

## ✨ Track A: Enrichment Model Evaluation

Purpose:
- Measure structured extraction quality across models using a teacher/student setup.

Default shape:
- Teacher model produces reference extraction.
- Student models are scored against teacher output.

Typical workflow:

```bash
uv run python eval/eval.py crawl
uv run python eval/eval.py build
uv run python eval/eval.py cost
uv run python eval/eval.py run
uv run python eval/eval.py report
```

Scored dimensions include:
- categorical fields
- list fields (`F1`, precision, recall)
- numeric years-of-experience tolerances
- salary normalization/tolerance

Checkpointing:
- `eval/results/checkpoint.json` is updated after each completed item.
- Resume mode validates compatibility and allows partial retries.

---

## ✨ Track B: Swarm Acceptance Benchmark

Purpose:
- Validate real pipeline behavior for resume + cover letter swarms under strict safety gates.

Pipeline exercised per case:
- resume swarm run
- cover-letter swarm run
- optional compile checks before/after

Acceptance gates:
- apply success > 70%
- zero out-of-region violations
- zero compile regressions

### 🔹 Dataset build

```bash
uv run python eval/swarm_benchmark.py build-dataset \
  --out eval/swarm_dataset.yaml \
  --limit 50 \
  --statuses staging applied interviewing not_applied offer rejected archived
```

Builder behavior:
- pulls jobs + descriptions from DB
- reads active artifact versions
- seeds fallback LaTeX templates when artifact text is missing
- emits benchmark-ready YAML cases

### 🔹 Benchmark run

```bash
uv run python eval/swarm_benchmark.py run \
  --dataset eval/swarm_dataset.yaml \
  --cycles 2 \
  --compile-check \
  --out-dir eval/results
```

Outputs:
- JSON: full per-case/per-artifact metrics and failure reasons
- Markdown: concise report for gate pass/fail

---

## ✨ Practical Interpretation Guide

If apply success is low:
- inspect `failed_move_reasons`
- inspect parser/target resolution and prompt move quality

If compile regressions appear:
- inspect LaTeX safety guards
- inspect compile guard rollback events

If score delta is noisy/negative:
- inspect scorer/rewriter alignment
- inspect evidence retrieval quality and claim-policy strictness

---

## ✨ Related Docs

- [../../eval/README.md](../../eval/README.md)
- [../dashboard/overview.md](../dashboard/overview.md)
- [../dashboard/backend-api.md](../dashboard/backend-api.md)
