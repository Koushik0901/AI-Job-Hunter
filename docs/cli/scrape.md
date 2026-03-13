# 🚀 CLI: `scrape`

Command:

```bash
uv run python src/cli.py scrape [options]
```

---

## ✨ What It Does

- Loads enabled company sources from DB.
- Scrapes ATS + HN jobs.
- Normalizes and filters results.
- Persists jobs.
- Optionally enriches and notifies.

---

## ✨ Common Modes

Daily run:

```bash
uv run python src/cli.py scrape
```

Scrape only (no notify, no LLM):

```bash
uv run python src/cli.py scrape --no-notify --no-enrich-llm
```

Backfill enrichment only:

```bash
uv run python src/cli.py scrape --enrich-backfill
```

Reformat missing formatted JDs:

```bash
uv run python src/cli.py scrape --jd-reformat-missing
```

---

## ✨ Important Options

- `--no-location-filter`
- `--limit N`
- `--no-enrich`
- `--no-notify`
- `--no-enrich-llm`
- `--enrich-backfill`
- `--re-enrich-all`
- `--jd-reformat-missing`
- `--jd-reformat-all`
- `--sort-by {match|posted}`

---

## ✨ Notes

- Source registry is DB-driven (`company_sources`).
- If no enabled sources exist, scrape exits with setup hint.
- Match scoring uses profile + job/enrichment signals.
