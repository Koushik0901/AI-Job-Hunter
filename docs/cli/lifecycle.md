# `cli.py lifecycle` CLI Reference

Command group:

```bash
uv run python src/cli.py lifecycle [--db PATH] <subcommand> [options]
```

This command group manages job application lifecycle state and retention cleanup.

## Subcommands

### `set-status`

```bash
uv run python src/cli.py lifecycle set-status --url <job_url> --status <status>
```

Allowed status values:

- `applied`
- `interviewing`
- `offer`
- `rejected`
- `withdrawn`
- `not_applied`

Writes `jobs.application_status` for the matching URL.

### `prune`

```bash
# dry-run (default)
uv run python src/cli.py lifecycle prune --days 28

# execute delete
uv run python src/cli.py lifecycle prune --days 28 --apply
```

Pruning criteria in `db.py`:

- `application_status` is unset/empty/`not_applied`
- `posted` is non-empty and parseable by SQLite `date(posted)`
- posted date is older than threshold (`--days`)
- rows with status in protected set are never deleted

Protected statuses:

- `applied`
- `interviewing`
- `offer`
- `rejected`
- `withdrawn`

## DB resolution behavior

- If `TURSO_URL` is set, Turso is used.
- Else if `--db PATH` is provided, local SQLite at that path is used.
- Else default local DB is `<cwd>/jobs.db`.

## Safety notes

- `prune` defaults to dry-run.
- `--apply` is required to delete rows.
- If a URL does not exist, `set-status` reports no match and does not error.
