# Operational Runbook

## Daily health checks

1. Confirm scraper run completed (CI logs or local console output).
2. Confirm DB write summary (`new` and `updated` counts).
3. Confirm Telegram send summary if new jobs exist.
4. Confirm enrichment summary (`ok/failed/skipped`) if enabled.

## Common operational commands

```bash
# Standard run
uv run python src/cli.py scrape

# Backfill enrichment (resume after rate limit)
uv run python src/cli.py scrape --enrich-backfill

# Recompute all enrichments
uv run python src/cli.py scrape --re-enrich-all

# Fill only missing formatted descriptions on already-enriched rows
uv run python src/cli.py scrape --jd-reformat-missing

# Reformat descriptions for all already-enriched rows
uv run python src/cli.py scrape --jd-reformat-all

# Validate ATS slug
uv run python src/cli.py sources check openai

# Review source registry
uv run python src/cli.py sources list

# Preview old-row retention impact
uv run python src/cli.py lifecycle prune --days 28
```

## Incident playbooks

### Enrichment paused by rate limit

- Symptom: console prints paused message and backfill command.
- Action: rerun with `--enrich-backfill` later.

### Telegram notifications missing

- Verify `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID`.
- Verify `--no-notify` was not used.
- Inspect network and Bot API errors in logs.

### Source registry empty or stale

- Check current rows: `uv run python src/cli.py sources list`
- Add one company: `uv run python src/add_company.py "Company Name"`
- Bulk refresh candidates:
  - `uv run python src/cli.py sources import --dry-run`
  - `uv run python src/cli.py sources import`

### Over-pruning risk review

- Always run dry-run first:
  - `uv run python src/cli.py lifecycle prune --days 28`
- Protect desired rows by setting lifecycle statuses before apply.
- Execute deletion only after review:
  - `uv run python src/cli.py lifecycle prune --days 28 --apply`

### Eval interruption

Resume with:

```bash
uv run python eval/eval.py run --resume
```

To retry specific models only:

```bash
uv run python eval/eval.py run --resume --models <model>
```

## Change management

When changing filters, prompts, source import logic, or lifecycle rules:

1. Update relevant docs under `docs/`.
2. Append entries to `CHANGELOG.md` and `docs/reference/changelog-docs.md`.
3. Run local compile + smoke checks.
4. Run a local scrape pass (`--no-notify` recommended).
5. If enrichment semantics changed, run eval subset before full eval.
