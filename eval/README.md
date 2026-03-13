# 🚀 Eval README

This folder is where we prove changes are real, not vibes.

There are two evaluation tracks:

1. Enrichment extraction quality (`eval/eval.py`)
2. Swarm acceptance benchmark (`eval/swarm_benchmark.py`)

---

## ✨ Enrichment Eval (Teacher vs Students)

Primary goal:
- Compare student extraction models against a teacher model on real jobs.

Run sequence:

```bash
uv run python eval/eval.py crawl
uv run python eval/eval.py build
uv run python eval/eval.py cost
uv run python eval/eval.py run
uv run python eval/eval.py report
```

Outputs:
- `eval/results/*.json`
- `eval/results/checkpoint.json`

---

## ✨ Swarm Acceptance Benchmark

Primary goal:
- Validate resume + cover-letter swarm pipelines under production-like constraints.

Acceptance gates:
- apply success > 70%
- zero out-of-region edit violations
- zero compile regressions

### 🔹 Build dataset

```bash
uv run python eval/swarm_benchmark.py build-dataset \
  --out eval/swarm_dataset.yaml \
  --limit 50 \
  --statuses staging applied interviewing not_applied offer rejected archived
```

Notes:
- Uses Turso credentials from `.env`.
- If artifact text is missing, benchmark builder now seeds fallback LaTeX templates so coverage stays high.

### 🔹 Run benchmark

```bash
uv run python eval/swarm_benchmark.py run \
  --dataset eval/swarm_dataset.yaml \
  --cycles 2 \
  --compile-check \
  --out-dir eval/results
```

Optional:
- `--resume-only`
- `--cover-letter-only`
- `--limit N`

---

## ✨ What Swarm Benchmark Measures

Per run:
- applied edits
- failed edits
- out-of-region failures
- compile before/after and regressions
- initial/final score and score delta

Aggregate:
- apply success rate
- out-of-region count
- compile regression count/rate
- score-delta distribution
- pass/fail for acceptance gates

---

## ✨ Read the Results Quickly

- Summary markdown: `eval/results/swarm_benchmark_*.md`
- Full details JSON: `eval/results/swarm_benchmark_*.json`

If gates fail, inspect:
- `failed_move_reasons`
- negative `score_delta` cases
- per-artifact compile regression rows

---

## ✨ Related Docs

- [../docs/evaluation/eval-framework.md](../docs/evaluation/eval-framework.md)
- [../docs/cli/eval.md](../docs/cli/eval.md)
- [../docs/dashboard/overview.md](../docs/dashboard/overview.md)
