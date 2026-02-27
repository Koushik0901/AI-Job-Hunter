# Company Sources Configuration

Company scrape targets are stored in DB table `company_sources` (not YAML).

## Fields

- `name`: display label used in tables and logs.
- `ats_type`: one of `greenhouse`, `lever`, `ashby`, `workable`, `smartrecruiters`, `recruitee`.
- `ats_url`: canonical board API URL for the source.
- `slug`: extracted ATS slug used for probing and dedupe.
- `enabled`: whether `cli.py scrape` includes the source.
- `source`: provenance marker (for example `add_company` or `import:<list>`).

## Management commands

```bash
# list all sources
uv run python src/cli.py sources list

# enable / disable
uv run python src/cli.py sources enable <slug-or-id>
uv run python src/cli.py sources disable <slug-or-id>

# probe ATS support for slug
uv run python src/cli.py sources check openai

# bulk import community lists
uv run python src/cli.py sources import --dry-run
uv run python src/cli.py sources import

# add a company interactively
uv run python src/add_company.py "Company Name"
```

## Runtime behavior

- `cli.py scrape` loads only rows with `enabled = 1`.
- If no enabled rows exist, scrape exits with a setup hint.
- Imports are deduplicated against existing DB rows by slug and canonical URL.
