# `add_company.py` CLI Reference

Command:

```bash
uv run python src/add_company.py "Company Name" [options]
```

## Arguments

- Positional `company`: user-facing company label used when writing new YAML rows.
- `--slug SLUG` (repeatable): extra slug probes appended after generated candidates.
- `--add`: non-interactive mode; auto-add all new matches.
- `--config PATH`: path to `companies.yaml` (default: `<cwd>/companies.yaml`).

## What it does

1. Generates slug candidates from company name.
2. Probes all ATS backends concurrently.
3. Keeps only hits with `jobs > 0`.
4. Filters out entries already represented in `companies.yaml`:
   - exact `ats_url` match
   - slug found in URL path segments of existing entries
5. Prompts for selection (unless `--add`).
6. Appends selected rows.

## Slug generation strategy

From full and suffix-stripped names, generates:

- joined token slug (`huggingface`)
- hyphenated slug (`hugging-face`)
- first-token slug (`hugging`)

Corporate suffixes removed for alternate candidates include values like `inc`, `llc`, `ltd`, `corp`, `technologies`, `labs`, `software`.

## False-positive handling

SmartRecruiters and Workable can return HTTP 200 for non-existent slugs with zero jobs.

- Table output suppresses zero-job rows.
- Hidden zero-job count is shown in dim note.
- Zero-job rows are never offered for writing.

## Safety and assumptions

- No overwrite/edit of existing YAML entries; appends only.
- Duplicate checks are conservative but slug collisions are still possible for ambiguous short slugs.
- Script imports shared probe logic from `src/scrape.py`.

## Examples

```bash
uv run python src/add_company.py "Hugging Face"
uv run python src/add_company.py "Toyota Research Institute" --slug tri
uv run python src/add_company.py "Scale AI" --slug scaleai --add
```
