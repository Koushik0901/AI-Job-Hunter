# Operational Runbook

## Daily health checks

1. Confirm scraper run completed (CI logs or local console output).
2. Confirm DB write summary (`new` and `updated` counts).
3. Confirm Telegram send summary if new jobs exist.
4. Confirm enrichment summary (`ok/failed/skipped`) if enabled.

## Common operational commands

```bash
# Standard run
uv run python src/scrape.py

# Backfill enrichment (resume after rate limit)
uv run python src/scrape.py --enrich-backfill

# Recompute all enrichments
uv run python src/scrape.py --re-enrich-all

# Validate ATS slug
uv run python src/scrape.py --check openai
```

## Incident playbooks

### Enrichment paused by rate limit

- Symptom: console prints paused message and backfill command.
- Action: rerun with `--enrich-backfill` later.

### Telegram notifications missing

- Verify `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID`.
- Verify `--no-notify` not used.
- Inspect network and Bot API errors in logs.

### Company source quality issues

- Use `src/add_company.py` for targeted add/validation.
- For mass import, always run `--import-companies --dry-run` first.

### Eval interruption

- Resume with:

```bash
uv run python eval/eval.py run --resume
```

- To retry specific model only:

```bash
uv run python eval/eval.py run --resume --models <model>
```

## Change management

When changing filters/prompts/config:

1. Update docs in this folder and relevant references.
2. Run a local scrape dry pass (`--no-notify` recommended).
3. If enrichment semantics changed, run eval subset before full run.
