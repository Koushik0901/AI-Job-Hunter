# 🚀 Operations Runbook

Use this when things break or when you are doing a routine check.

---

## ✨ Daily Health Check

1. Backend up and healthy (`/api/health`).
2. Board loads jobs and stats.
3. Profile endpoint loads.
4. Artifact editor compile works.
5. One swarm run executes and returns timeline events.

---

## ✨ If Swarm Quality Drops

1. Run benchmark:

```bash
uv run python eval/swarm_benchmark.py run --dataset eval/swarm_dataset.yaml --cycles 2 --compile-check --out-dir eval/results
```

2. Inspect in JSON:
- `failed_move_reasons`
- negative `score_delta` cases
- compile regression rows

3. Patch in this order:
- target validation and apply engine
- LaTeX safety rules
- claim policy strictness
- prompt structure

---

## ✨ Recovery Shortcuts

- Cancel stuck run via swarm cancel endpoint.
- Recompile artifact manually via recompile endpoint.
- Use confirm-save only after run status is `awaiting_confirmation`.
