# OpenRouter Enrichment Integration

Implemented in `src/enrich.py`.

## Stack

- LangChain `ChatOpenAI`
- Pydantic `JobEnrichment`
- OpenRouter base URL: `https://openrouter.ai/api/v1`
- Two-model setup:
  - `ENRICHMENT_MODEL` for structured extraction
  - `DESCRIPTION_FORMAT_MODEL` for low-cost description formatting

## Structured output contract

`JobEnrichment` model defines all extracted fields and validators.

Validators coerce invalid model outputs into safe defaults for key enum/list fields.

Persisted row includes:

- extracted structured fields
- `formatted_description` (nullable Markdown)

## Output status values

- `ok`: valid extraction persisted
- `failed`: extraction call failed (non-rate-limit)
- `skipped`: no description text

Formatting failures do **not** flip extraction status to `failed`; enrichment remains `ok` with `formatted_description = null`.

Recovery mode for formatting-only gaps:

- `uv run python src/cli.py scrape --jd-reformat-missing`
- Selects rows where `enrichment_status='ok'` but `formatted_description` is null/empty.

Full formatting refresh mode:

- `uv run python src/cli.py scrape --jd-reformat-all`
- Selects all rows where `enrichment_status='ok'` and rewrites `formatted_description`.

## Provider-aware rate-limit handling

`_MAX_PROVIDER_RETRIES = 3`.

On 429/"rate limit" errors:

1. Parse provider name from error text when available.
2. Retry while adding provider to OpenRouter `provider.ignore`.
3. If provider unknown, retry with `provider.sort = throughput`.
4. If retries exhausted, raise `RateLimitSignal`.

## Pipeline stop behavior

`run_enrichment_pipeline` runs with thread pool (`max_workers=5`).

When a `RateLimitSignal` is hit:

- sets stop event
- cancels pending futures
- does not persist cancelled rows
- prints resume command using `--enrich-backfill`

## Description formatting pass

After successful structured extraction, a second LLM call rewrites the raw description into cleaner Markdown for UI rendering.

Rules:

- preserve all factual content
- no hallucinations
- output Markdown only (no markdown fences/HTML/JSON)
- best-effort only (nullable fallback)

## Prompt source of truth

- Runtime prompt source: `prompts.yaml`
- Runtime loader: `src/enrich.py` (`_load_prompts`)

When updating prompts, edit `prompts.yaml` only.
