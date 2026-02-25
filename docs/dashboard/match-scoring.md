# Job Match Scoring Rubric

This document defines the exact deterministic scoring rules used by:

- Dashboard list/detail match fields
- Dashboard `match_desc` sorting
- CLI scrape `Match` column (`--sort-by match`)

Implementation source of truth: `src/match_score.py`.

## Inputs

- Candidate profile (`candidate_profile`):
  - `years_experience`
  - `skills`
  - `target_role_families`
  - `requires_visa_sponsorship`
- Job data:
  - `title`
  - enrichment fields when available:
    - `seniority`
    - `years_exp_min`, `years_exp_max`
    - `required_skills`, `preferred_skills`
    - `role_family`
    - `visa_sponsorship`

## Score range and bands

- Final score is clamped to `0..100`.
- Bands:
  - `excellent`: `>= 80`
  - `good`: `65..79`
  - `fair`: `45..64`
  - `low`: `< 45`

## Formula

Base score starts at `50`, then adds/subtracts the components below.

### 1) Required skills overlap (`0..+28`)

- Normalize both profile skills and required skills.
- Compute overlap ratio:
  - `len(required ∩ profile) / len(required)`
- Points:
  - `round(28 * ratio)`

### 2) Preferred skills overlap (`0..+12`)

- Overlap ratio:
  - `len(preferred ∩ profile) / len(preferred)`
- Points:
  - `round(12 * ratio)`

### 3) Seniority bias (`-25..+20`)

Priority goal is recent-grad friendly ranking.

- `intern` or `junior`: `+20`
- `mid`: `+8`
- `senior`: `-18`
- `staff` or `principal`: `-25`

When enrichment seniority is missing, title heuristics are used:

- junior signals: `junior`, `entry`, `associate`
- senior signals: `senior`, `sr`, `staff`, `principal`, `lead`

### 4) Experience bias (`-25..+20`)

Strongly favors roles requiring `<= 4` years.

- If `years_exp_min <= 4`: `+20`
- If `years_exp_min >= 5`: `-10`
- If `years_exp_min >= 7`: `-25`
- If candidate years `< years_exp_min`: subtract `min(20, (gap * 5))`
- If `years_exp_max <= 4`: additional `+4`
- Component is clamped to `-25..+20`

### 5) Role family alignment (`-8..+8`)

Applies only when profile target families are set.

- If job `role_family` in profile target families: `+8`
- If job `role_family` not in target families: `-8`

### 6) Eligibility penalty (`0 or -40`)

Hard penalty for sponsorship mismatch:

- If profile `requires_visa_sponsorship = true`
- and job `visa_sponsorship = "no"`
- then apply `-40`

## Confidence level

- `high`: enrichment exists and has skill lists
- `medium`: enrichment exists but skill lists missing/empty
- `low`: enrichment missing (title-only fallback)

## Notes

- Scoring is fully deterministic and local (no LLM inference in the scoring path).
- Missing enrichment does not fail scoring; it lowers confidence.
- Score and breakdown are returned in API detail payload under `match`.

## Skill Normalization and Fuzzy Matching Details

Skill matching is fuzzy and canonicalized before overlap is computed.

Normalization steps:

- lowercase + whitespace normalization
- punctuation cleanup (`/`, `_`, `-`, dots, symbols)
- parenthetical extraction and cleanup (for patterns like `(... )`)
- alias folding for common shorthand (examples: `js` -> `javascript`, `tf` -> `tensorflow`)
- acronym folding for multi-token phrases (example: `retrieval augmented generation` -> `rag`)

Additional fuzzy equivalence checks:

- exact canonical match
- compact-form match (remove non-alphanumeric): `ci/cd` == `cicd`
- acronym-to-phrase match: `rag` == `retrieval augmented generation`
- token overlap + character similarity fallback

Examples that should match:

- `RAG` <-> `rag`
- `RAG` <-> `Retrieval Augmented Generation (RAG)`
- `CI/CD` <-> `cicd`
- `GenAI` <-> `generative ai`
