# Eval Framework

Compares cheap student LLMs against a high-quality teacher (GPT-5.2) on real job descriptions,
measuring how accurately each model extracts structured enrichment fields for AI/ML roles.

The goal is to find the cheapest model that matches teacher quality closely enough for production use.

---

## File layout

```
eval/
├── README.md          # this file
├── eval.py            # CLI: crawl / build / cost / run / report
├── eval_jobs.db       # local crawl DB — git-ignored (*.db)
├── dataset.yaml       # evaluation dataset — auto-generated + manual jobs
└── results/           # JSON results files — git-ignored
```

---

## Workflow

```
crawl → build → cost → run → report
```

### 1. Crawl — populate `eval_jobs.db`

```bash
uv run python eval/eval.py crawl
uv run python eval/eval.py crawl --limit 200        # cap total jobs
uv run python eval/eval.py crawl --config PATH      # custom companies.yaml
uv run python eval/eval.py crawl --db PATH          # custom output DB
```

Scrapes all companies with **no location filter** and a **broader title filter** than production
(adds deep learning, reinforcement learning, interns, researchers — see `EVAL_TITLE_INCLUDE`).
Stores raw job data in `eval/eval_jobs.db`. Re-running is safe: existing URLs are updated in
place, new URLs are inserted.

After crawling it prints:
- Location breakdown (Canada / Remote / US non-remote / Other)
- Segment preview vs targets (see [Segments](#segments) below)

### 2. Build — generate `dataset.yaml`

```bash
uv run python eval/eval.py build
uv run python eval/eval.py build --db PATH          # custom source DB
```

Reads `eval_jobs.db`, tags each job with a segment label, and writes `eval/dataset.yaml`.
Preserves any `manual_jobs` already in the file. Prints the segment distribution table with
coverage targets and `<-- LOW` markers.

Errors if `eval_jobs.db` does not exist — run `crawl` first.

### 3. Cost — estimate API spend before running

```bash
uv run python eval/eval.py cost
uv run python eval/eval.py cost --models google/gemma-3-12b-it openai/gpt-4o
uv run python eval/eval.py cost --teacher openai/gpt-4o
```

Counts tokens across the dataset and prints per-model cost using hardcoded pricing in `PRICING`.
Makes no API calls. Run this before `run` to avoid surprises.

### 4. Run — execute the eval

```bash
uv run python eval/eval.py run                    # all 7 student models, full dataset
uv run python eval/eval.py run --subset 5         # quick sanity check (5 jobs)
uv run python eval/eval.py run --models google/gemma-3-12b-it mistralai/mistral-small-3.2-24b-instruct
uv run python eval/eval.py run --teacher openai/gpt-4o
uv run python eval/eval.py run --workers 1        # serial requests — use if hitting rate limits
```

Runs teacher first (max 2 concurrent requests), then each student model sequentially (jobs within
each model run concurrently at `--workers`, default 3). Saves results to
`eval/results/<timestamp>_<teacher>_<N>models.json`.

**Rate limit handling:** HTTP 429 responses trigger exponential backoff (5s, 10s, 20s, 40s) before
retrying — up to 4 attempts per job per attempt. If all retries fail, the job is marked `failed`
and skipped in scoring. Lower `--workers` to reduce how often rate limits are hit.

Requires `OPENROUTER_API_KEY` in `.env`.

### 5. Report — view results

```bash
uv run python eval/eval.py report                        # latest results file
uv run python eval/eval.py report eval/results/foo.json  # specific file
```

Prints:
1. **Field × model accuracy table** — all 14 scored fields, models ranked by overall score, `*` = best in column
2. **List field diagnostics** — F1, Precision, Recall per list field for the best model, with `hallucinates` / `under-extracts` notes
3. **`canada_eligible` confusion matrix** — 3×3 (yes/no/unknown) for the best model
4. **Per-segment breakdown** — overall score by segment for the best model
5. **Low-scoring jobs** — jobs where best model scored below 50%

---

## Scoring

The eval re-runs enrichment from scratch on raw descriptions — it does not read from `job_enrichments`.
Teacher output is ground truth; student output is compared against it.

### Categorical fields — partial credit

| Field | Scoring |
|-------|---------|
| `work_mode` | Exact=1.0 · hybrid↔remote or hybrid↔onsite=0.5 · remote↔onsite=0.0 |
| `canada_eligible` | Exact=1.0 · either side "unknown"=0.25 · yes↔no=0.0 |
| `seniority` | Ordinal distance — off-by-1=0.75, off-by-2=0.50, off-by-3=0.25, 4+=0.0 |
| `role_family` | Exact=1.0 or 0.0 |
| `visa_sponsorship` | Exact=1.0 · either side "unknown"=0.25 · yes↔no=0.0 |

Rationale: `"unknown"` is a soft miss (model lacked confidence), not a hard wrong answer like `yes→no`.
Seniority is ordinal — confusing `senior` and `staff` is a minor error; `intern` vs `principal` is major.

### List fields — F1 score

**F1** = `2 * precision * recall / (precision + recall)` over normalized skill sets.

Both empty → 1.0 (both agree there's nothing). One empty → 0.0.

**Normalization applied before scoring:**
- Lowercase and strip leading/trailing whitespace
- Strip parentheticals: `"python (3.x)"` → `"python"`
- Expand common aliases: `js→javascript`, `ts→typescript`, `k8s→kubernetes`, `postgres→postgresql`, `torch→pytorch`

**Precision and Recall** are stored separately per list field in the results JSON and reported in
the diagnostics section:
- Low precision → model **hallucinates** items the teacher didn't list
- Low recall → model **under-extracts**, missing items the teacher found

### Numeric fields — ordinal tolerance

| Field | Scoring |
|-------|---------|
| `years_exp_min` | Exact=1.0 · off-by-1=0.75 · off-by-2=0.5 · off-by-3=0.25 · ≥4=0.0 |
| `years_exp_max` | Same as above |

Both null → 1.0 (both agree: not mentioned). One null → 0.0.

### Salary fields — percentage tolerance + unit normalization

`salary_min` and `salary_max` are scored with a tolerance band after normalizing for the common
`$150k → 150` vs `150000` ambiguity: if one value is <1000 and the other ≥10000 with a ~1000×
ratio, the smaller is scaled up before comparison.

| Relative difference | Score |
|--------------------|-------|
| ≤5% | 1.0 |
| ≤15% | 0.75 |
| ≤30% | 0.5 |
| ≤50% | 0.25 |
| >50% | 0.0 |

`salary_currency` is an exact match categorical (CAD / USD / null) — no partial credit.

Both null → 1.0. One null → 0.0.

### Overall

Simple mean across all **14 scored fields** — each field contributes equally.
Reflects general extraction quality rather than any field's specific business impact.

### Not scored

`remote_geo` — genuinely free-form string. Teacher might output `"North America"`, student might
output `"US and Canada"` — semantically identical, but no reliable automatic comparison.

---

## Segments

`tag_segment()` assigns each job a coverage label so the dataset stress-tests a range of extraction
challenges. Priority order — first match wins:

| Priority | Segment | Detection signal |
|----------|---------|-----------------|
| 1 | `seniority_extreme` | Title contains intern/junior/entry OR staff/principal |
| 2 | `red_flag` | Description mentions US work auth, citizenship, clearance, negative sponsorship, or "must reside in" |
| 3 | `remote_geo_edge` | Location contains "remote" + US qualifier (us/usa/united states/state names) via any separator, or "north america/americas" |
| 4 | `salary_disclosed` | Description matches `$\d{2,3}[,k\d]` |
| 5 | `sparse` | Description under 800 characters |
| 6 | `core` | Everything else |

### Coverage targets

| Segment | Target | What it tests |
|---------|--------|---------------|
| `core` | 100 | Typical mid-level AI/ML/DS roles — baseline extraction quality |
| `remote_geo_edge` | 30 | Ambiguous "Remote US" postings — challenges `canada_eligible` and `work_mode` |
| `red_flag` | 20 | US-restricted roles — tests `canada_eligible = "no"` and `red_flags` extraction |
| `seniority_extreme` | 20 | Interns, staff, and principals — levels rare in Canada-filtered prod set |
| `salary_disclosed` | 150 | Roles with explicit compensation — US pay transparency laws make this very common |
| `sparse` | 10 | Thin descriptions — tests graceful degradation with limited signal |

`crawl` and `build` print `<-- LOW` next to any segment below 50% of its target.

---

## Dataset format (`dataset.yaml`)

```yaml
db_jobs:
  - id: db-001
    url: https://...
    company: Acme
    title: Senior ML Engineer
    location: Remote - Canada
    posted: "2026-02-10"
    description: |
      Full job description text...
    segment: core          # auto-assigned by tag_segment()

manual_jobs:
  - id: manual-001
    company: ""            # fill in to activate
    title: ""
    location: ""
    url: ""
    description: ""
```

`db_jobs` is auto-generated — do not edit manually. Re-run `crawl && build` to refresh.

`manual_jobs` is yours to curate. Add hand-picked edge cases the crawler misses. A placeholder
block with an empty `company` and `description` is ignored by `load_dataset()`.

---

## Default models

| Role | Model |
|------|-------|
| Teacher (ground truth) | `openai/gpt-5.2` |
| Student | `google/gemma-3-12b-it` |
| Student | `google/gemma-3-27b-it` |
| Student | `openai/gpt-oss-120b` |
| Student | `nvidia/nemotron-3-nano-30b-a3b` |
| Student | `mistralai/mistral-small-3.2-24b-instruct` |
| Student | `qwen/qwen3-30b-a3b-thinking-2507` |
| Student | `meta-llama/llama-4-scout` |

The production enrichment model is `openai/gpt-oss-120b` by default (set via `ENRICHMENT_MODEL`).
The eval tells you if a different model would be worth upgrading to.

---

## Results file format

Saved to `eval/results/<timestamp>_<teacher>_<N>models.json`:

```json
{
  "run_at": "2026-02-18T...",
  "teacher_model": "openai/gpt-5.2",
  "student_models": ["google/gemma-3-12b-it", ...],
  "total_jobs": 200,
  "jobs": [
    {
      "id": "db-001",
      "company": "Acme",
      "title": "Senior ML Engineer",
      "segment": "core",
      "teacher": { "work_mode": "remote", "canada_eligible": "yes", ... },
      "students": {
        "google/gemma-3-12b-it": {
          "output": { "work_mode": "remote", ... },
          "scores": {
            "work_mode": 1.0,
            "canada_eligible": 1.0,
            "seniority": 0.75,
            "role_family": 1.0,
            "visa_sponsorship": 0.25,
            "must_have_skills": 0.74,
            "must_have_skills__p": 0.80,
            "must_have_skills__r": 0.69,
            "nice_to_have_skills": 0.50,
            "tech_stack": 0.82,
            "red_flags": 1.0,
            "years_exp_min": 0.75,
            "years_exp_max": 1.0,
            "salary_min": 1.0,
            "salary_max": 1.0,
            "salary_currency": 1.0,
            "overall": 0.83
          }
        }
      }
    }
  ],
  "aggregate": {
    "google/gemma-3-12b-it": {
      "work_mode": 0.94,
      "canada_eligible": 0.81,
      "seniority": 0.88,
      "role_family": 0.91,
      "visa_sponsorship": 0.72,
      "must_have_skills": 0.62,
      "must_have_skills__p": 0.71,
      "must_have_skills__r": 0.55,
      "nice_to_have_skills": 0.48,
      "tech_stack": 0.70,
      "red_flags": 0.85,
      "years_exp_min": 0.79,
      "years_exp_max": 0.81,
      "salary_min": 0.88,
      "salary_max": 0.87,
      "salary_currency": 0.95,
      "overall": 0.80
    }
  }
}
```

---

## Common operations

```bash
# Full dataset refresh from scratch
uv run python eval/eval.py crawl
uv run python eval/eval.py build
uv run python eval/eval.py cost
uv run python eval/eval.py run

# Cheap sanity check before committing to a full run
uv run python eval/eval.py run --subset 5

# Compare just two models
uv run python eval/eval.py run --models google/gemma-3-12b-it openai/gpt-4o

# Re-report on an older results file
uv run python eval/eval.py report eval/results/20260101_120000_openai-gpt-5_2_7models.json
```
