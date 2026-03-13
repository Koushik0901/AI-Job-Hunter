# 🚀 CLI: `lifecycle`

Command group:

```bash
uv run python src/cli.py lifecycle <subcommand>
```

---

## `set-status`

```bash
uv run python src/cli.py lifecycle set-status --url <job_url> --status <status>
```

Allowed statuses:
- `not_applied`
- `staging`
- `applied`
- `interviewing`
- `offer`
- `rejected`

---

## `prune`

Dry run:

```bash
uv run python src/cli.py lifecycle prune --days 28
```

Apply delete:

```bash
uv run python src/cli.py lifecycle prune --days 28 --apply
```

Protected statuses are never deleted.

---

## ✨ Safety

- `prune` defaults to dry-run.
- `--apply` is required for destructive action.
