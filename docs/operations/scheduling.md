# 🚀 Scheduling

Two scheduling modes are common:

1. CI cron (GitHub Actions)
2. Local/VM scheduler (Task Scheduler, cron)

---

## ✨ Recommended Split

- Scrape job: scrape only (no LLM enrichment)
- Enrichment job: backfill/re-enrich pass

This keeps scrape latency predictable and isolates LLM cost.

---

## ✨ Suggested Cadence

- Scrape: multiple times/day
- Enrichment: 1-2 times/day
- Benchmark: nightly or before release
