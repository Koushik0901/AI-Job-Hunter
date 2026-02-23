# ATS and Source Integrations

Implemented in `src/fetchers.py`.

## ATS support

- Greenhouse
- Lever
- Ashby
- Workable
- SmartRecruiters

All source fetchers use `requests` with retry decorator (`retry_with_backoff`).

## Source-specific notes

### Greenhouse

- Listing: `/v1/boards/{token}/jobs`
- Description requires second request per job (`content` HTML field).

### Lever

- Listing API already includes enough fields to synthesize description.
- No second HTTP call for description.

### Ashby

- Listing extracted from embedded JSON in board HTML (`jobPostings` key).
- Description from job detail page `__NEXT_DATA__` JSON.

### Workable

- Listing endpoint is POST request with empty JSON payload.
- Description fetched by shortcode endpoint.

### SmartRecruiters

- Listing from `/v1/companies/{slug}/postings`.
- Description assembled from `jobAd.sections` fields.
- Discovery probes may return 200 with zero jobs for invalid slugs.

### HN "Who is Hiring"

- Uses Algolia search API.
- Finds latest hiring thread by `author=whoishiring` and title match.
- Filters comments by ML/AI keyword set.
- Normalizes comment first line into company/title/location heuristics.

## Date normalization

`_normalize_datetime` accepts:

- unix seconds or milliseconds
- ISO strings
- `%Y-%m-%d`
- `%Y/%m/%d`
- `%m/%d/%Y`

Returns `YYYY-MM-DD` or empty string.

## Description enrichment stage

`enrich_descriptions()`:

- runs concurrent description fetches (`max_workers=10`)
- mutates each job dict `description` in place
- logs and tolerates per-job failures
