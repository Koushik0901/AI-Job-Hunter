# OpenRouter Enrichment Integration

Implemented in `src/enrich.py`.

## Stack

- LangChain `ChatOpenAI`
- Pydantic `JobEnrichment`
- OpenRouter base URL: `https://openrouter.ai/api/v1`

## Structured output contract

`JobEnrichment` model defines all extracted fields and validators.

Validators coerce invalid model outputs into safe defaults for key enum/list fields.

## Output status values

- `ok`: valid extraction persisted
- `failed`: extraction call failed (non-rate-limit)
- `skipped`: no description text

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

## Prompt source of truth

- Runtime prompt strings: `src/enrich.py`
- `prompts.yaml` is a reference copy only

When updating prompts, keep both synchronized.
