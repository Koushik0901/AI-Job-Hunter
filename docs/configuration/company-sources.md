# 🚀 Company Sources Configuration

`company_sources` is the live registry for scrape targets.

Fresh installs begin with an empty registry. Sources are expected to be added from the Workspace UI or the CLI, depending on the user's preference.

---

## ✨ Stored Fields

- `name`
- `ats_type`
- `ats_url`
- `slug`
- `enabled`
- `source`

---

## ✨ Manage It

```bash
uv run python src/cli.py sources list
uv run python src/cli.py sources enable <slug-or-id>
uv run python src/cli.py sources disable <slug-or-id>
uv run python src/cli.py sources import
uv run python src/add_company.py "Company Name"
```

UI path:
- open `/workspace`
- use `Sources` to probe, add, enable/disable, or import entries

---

## ✨ Runtime Rule

Only `enabled=1` rows are used by `scrape`.
