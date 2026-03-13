# 🚀 OpenRouter Enrichment

OpenRouter powers structured enrichment and swarm LLM calls.

---

## ✨ Used For

1. Job enrichment extraction.
2. JD formatting enhancement.
3. Resume swarm scoring + rewriting.
4. Cover-letter swarm draft/scoring/rewriting.

---

## ✨ Required Env

- `OPENROUTER_API_KEY`

Model selectors:
- enrichment models (`ENRICHMENT_MODEL`, `DESCRIPTION_FORMAT_MODEL`)
- swarm models (`RESUME_SWARM_*`, `COVER_LETTER_SWARM_*`)

---

## ✨ Reliability Pattern

- Prompt templates in `prompts.yaml`
- Pydantic validation on model outputs
- retry + repair on malformed JSON
- deterministic apply/safety stages after LLM output
