# `companies.yaml` Configuration

`companies.yaml` contains ATS boards to scrape.

## Current shape

Top-level key:

```yaml
companies:
  - name: Example Company
    ats_type: greenhouse
    ats_url: https://boards-api.greenhouse.io/v1/boards/example/jobs
    enabled: true
```

## Supported `ats_type`

- `greenhouse`
- `lever`
- `ashby`
- `workable`
- `smartrecruiters`

## URL templates

- greenhouse: `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs`
- lever: `https://api.lever.co/v0/postings/{slug}`
- ashby: `https://jobs.ashbyhq.com/{slug}`
- workable: `https://apply.workable.com/api/v3/accounts/{slug}/jobs`
- smartrecruiters: `https://api.smartrecruiters.com/v1/companies/{slug}/postings`

## Runtime behavior

- `load_companies()` returns only entries where `enabled` is true (or missing).
- A legacy mapping format is still accepted and transformed at runtime.

## Project inventory snapshot

Computed from current tracked `companies.yaml`:

- Total entries: `234`
- ATS distribution:
  - greenhouse: `167`
  - lever: `53`
  - ashby: `10`
  - workable: `2`
  - smartrecruiters: `2`
- Enabled false entries: `0`

## Managing entries

### Manual add

Append with required fields (`name`, `ats_type`, `ats_url`, `enabled`).

### Assisted add

Use:

```bash
uv run python src/add_company.py "Company Name"
```

### Bulk import

```bash
uv run python src/scrape.py --import-companies --dry-run
uv run python src/scrape.py --import-companies
```

Bulk import appends entries and includes a source comment marker block.

## De-duplication assumptions

- `add_company.py` detects duplicates by exact URL and slug path segments.
- `--import-companies` dedupes by slug and URL against existing entries.
- Slug collision across unrelated companies can still happen; review imported entries.
