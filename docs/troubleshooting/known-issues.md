# Known Issues and Quirks

## 1) `uv` cache permission issues in restricted environments

Symptom:

- `Failed to initialize cache ... Access is denied`.

Impact:

- `uv run ...` may fail in sandboxed contexts.

Workaround:

- run outside restricted sandbox or with approved escalation.

## 2) SmartRecruiters and Workable zero-job false positives

Symptom:

- slug probe returns HTTP 200 but no real jobs.

Handling:

- `add_company.py` suppresses `jobs == 0` results from add table.

## 3) Prompt loading failures

- Runtime prompts are loaded from `prompts.yaml`.
- Missing keys or invalid YAML can fail enrichment prompt construction.

Risk:

- Enrichment calls fail fast until `prompts.yaml` is corrected.

## 4) Location filter is intentionally permissive for some remote roles

- "Remote US" can pass location filter.
- Final Canada eligibility is delegated to LLM field `canada_eligible`.

## 5) Turso vs local DB selection

- `TURSO_URL` in environment always overrides `--db`.
- This can surprise local debugging if env is still set.

## 6) Zero description jobs

- Enrichment marks them as `skipped`.
- They will not produce extracted metadata.

## 7) Eval pricing table drift risk

- `eval/eval.py` pricing constants are static.
- If OpenRouter prices change, cost estimates become stale.
