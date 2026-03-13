# 🚀 CLI: `add_company.py`

Command:

```bash
uv run python src/add_company.py "Company Name" [options]
```

---

## ✨ What It Does

- Generates ATS slug candidates.
- Probes supported ATS backends.
- Filters zero-job/duplicate candidates.
- Lets you select and upsert source rows.

---

## ✨ Useful Options

- `--slug <slug>` (repeatable)
- `--add` (non-interactive add-all)
- `--db <path>` (local DB when not using Turso)

You can also pass a direct careers URL; ATS/slug is inferred first.

---

## ✨ Example

```bash
uv run python src/add_company.py "Example Company"
uv run python src/add_company.py "Acme Robotics" --slug acme-robotics --add
```
