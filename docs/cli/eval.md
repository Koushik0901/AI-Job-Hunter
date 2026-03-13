# 🚀 CLI: `eval/eval.py`

Command group:

```bash
uv run python eval/eval.py <subcommand>
```

Subcommands:
- `crawl`
- `build`
- `cost`
- `run`
- `report`

---

## ✨ Typical Sequence

```bash
uv run python eval/eval.py crawl
uv run python eval/eval.py build
uv run python eval/eval.py cost
uv run python eval/eval.py run
uv run python eval/eval.py report
```

---

## ✨ What Each Step Does

- `crawl`: collect broad eval jobs into eval DB
- `build`: create `eval/dataset.yaml`
- `cost`: estimate tokens/cost
- `run`: execute teacher/student comparisons
- `report`: summarize results

---

## ✨ Swarm Benchmark (separate tool)

Use `eval/swarm_benchmark.py` for resume/cover-letter acceptance gates.
