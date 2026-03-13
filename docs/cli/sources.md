# 🚀 CLI: `sources`

Command group:

```bash
uv run python src/cli.py sources <subcommand>
```

---

## ✨ Subcommands

List:

```bash
uv run python src/cli.py sources list
```

Enable/disable:

```bash
uv run python src/cli.py sources enable <slug-or-id>
uv run python src/cli.py sources disable <slug-or-id>
```

Probe ATS availability:

```bash
uv run python src/cli.py sources check <slug>
```

Import community lists:

```bash
uv run python src/cli.py sources import --dry-run
uv run python src/cli.py sources import
```

---

## ✨ Behavior

- Works against Turso if `TURSO_URL` is set.
- Otherwise local DB path is used.
- Import dedupes by canonical URL + slug signals.
