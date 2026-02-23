# `cli.py sources` CLI Reference

Command group:

```bash
uv run python src/cli.py sources [--db PATH] <subcommand> [options]
```

## Subcommands

### `list`

```bash
uv run python src/cli.py sources list
```

Prints all source rows from `company_sources` including enabled state, ATS type, slug, and provenance.

### `enable`

```bash
uv run python src/cli.py sources enable <slug-or-id>
```

Enables one source by numeric `id` or `slug`.

### `disable`

```bash
uv run python src/cli.py sources disable <slug-or-id>
```

Disables one source by numeric `id` or `slug`.

### `check`

```bash
uv run python src/cli.py sources check <slug>
```

Probes all ATS platforms for a slug and shows availability + best-effort job count.

### `import`

```bash
uv run python src/cli.py sources import [--dry-run]
```

Imports from curated GitHub community lists, dedupes against DB, and upserts new rows.

- `--dry-run`: preview candidates without DB writes.

## DB resolution behavior

- If `TURSO_URL` is set, Turso is used.
- Else if `--db PATH` is provided, local SQLite at that path is used.
- Else default local DB is `<cwd>/jobs.db`.

## Import behavior details

- Sources used by default:
  - `pittcsc/Summer2024-Internships`
  - `j-delaney/easy-application`
  - `SimplifyJobs/New-Grad-Positions`
- Supported ATS extraction in import parsers:
  - Greenhouse
  - Lever
  - SmartRecruiters
- Deduplication keys:
  - existing DB `ats_url`
  - existing DB `slug`
  - duplicate slugs within same import run

## Safety notes

- `check` is read-only and does not write DB.
- `import --dry-run` is read-only.
- `enable`/`disable` and `import` mutate `company_sources` and update timestamps.
