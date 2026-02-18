"""
eval.py -- Enrichment model evaluation framework.

Runs N student models against a high-quality teacher model on a curated dataset of job
postings, then reports per-field extraction accuracy for each model side-by-side.

Usage:
    uv run python eval/eval.py build                        # pull DB jobs -> eval/dataset.yaml
    uv run python eval/eval.py cost                         # estimate API cost, no calls made
    uv run python eval/eval.py run                          # run full eval (all models, all jobs)
    uv run python eval/eval.py run --subset 5               # run on 5 jobs only
    uv run python eval/eval.py run --models google/gemma-3-12b-it meta-llama/llama-4-scout
    uv run python eval/eval.py report                       # print report from latest results file
    uv run python eval/eval.py report eval/results/foo.json # report from specific file
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3 as _sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Allow importing from src/
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from enrich import build_enrichment_prompt, enrich_one_job
from notify import _load_dotenv

_load_dotenv(Path.cwd() / ".env")

EVAL_DIR     = Path(__file__).parent
DATASET_FILE = EVAL_DIR / "dataset.yaml"
RESULTS_DIR  = EVAL_DIR / "results"
EVAL_DB_PATH = EVAL_DIR / "eval_jobs.db"

DEFAULT_TEACHER = "openai/gpt-5.2"

DEFAULT_STUDENT_MODELS = [
    "google/gemma-3-12b-it",
    "google/gemma-3-27b-it",
    "openai/gpt-oss-120b",
    "nvidia/nemotron-3-nano-30b-a3b",
    "mistralai/mistral-small-3.2-24b-instruct",
    "qwen/qwen3-30b-a3b-thinking-2507",
    "meta-llama/llama-4-scout",
]

EVAL_TITLE_INCLUDE = [          # superset of production — adds deep learning, interns, researchers
    "machine learning", "ml engineer", "mlops", "ml ops", "applied ml",
    "ai engineer", "applied scientist", "data scientist", "data science",
    "research scientist", "nlp", "llm", "computer vision", "generative ai",
    "deep learning", "reinforcement learning", "ml researcher", "ai researcher",
    "ml intern", "ai intern", "data science intern",
]
EVAL_TITLE_EXCLUDE = [          # same as prod but WITHOUT "principal staff"
    "sales", "recruiter", "marketing", "legal", "hr ",
    "designer", "customer success", "director", "vp ",
]

# Pricing ($/M tokens) -- update if OpenRouter prices change
PRICING = {
    "google/gemma-3-12b-it":                    {"input": 0.040, "output": 0.13},
    "google/gemma-3-27b-it":                    {"input": 0.040, "output": 0.15},
    "openai/gpt-oss-120b":                      {"input": 0.039, "output": 0.19},
    "nvidia/nemotron-3-nano-30b-a3b":           {"input": 0.050, "output": 0.20},
    "mistralai/mistral-small-3.2-24b-instruct": {"input": 0.060, "output": 0.18},
    "qwen/qwen3-30b-a3b-thinking-2507":         {"input": 0.051, "output": 0.34},
    "meta-llama/llama-4-scout":                 {"input": 0.080, "output": 0.30},
    "openai/gpt-5.2":                           {"input": 1.750, "output": 14.00},
    "openai/gpt-4o":                            {"input": 2.500, "output": 10.00},
}
PRICING_FALLBACK = {"input": 1.00, "output": 4.00}  # conservative unknown model estimate

CATEGORICAL_FIELDS = ["work_mode", "canada_eligible", "seniority", "role_family", "visa_sponsorship"]
LIST_FIELDS        = ["must_have_skills", "nice_to_have_skills", "tech_stack", "red_flags"]
SCORED_FIELDS      = CATEGORICAL_FIELDS + LIST_FIELDS

# Ordinal rank for seniority partial-credit scoring
_SENIORITY_RANK = {"intern": 0, "junior": 1, "mid": 2, "senior": 3, "staff": 4, "principal": 5}

# Common skill aliases — normalized before Jaccard / F1 computation
_SKILL_ALIASES: dict[str, str] = {
    "js":       "javascript",
    "ts":       "typescript",
    "k8s":      "kubernetes",
    "postgres": "postgresql",
    "torch":    "pytorch",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_dataset() -> list[dict]:
    if not DATASET_FILE.exists():
        print(f"ERROR: {DATASET_FILE} not found. Run `eval.py build` first.")
        sys.exit(1)
    data = yaml.safe_load(DATASET_FILE.read_text(encoding="utf-8")) or {}
    db_jobs     = data.get("db_jobs", []) or []
    manual_jobs = data.get("manual_jobs", []) or []
    # Filter out empty manual job placeholders
    manual_jobs = [j for j in manual_jobs if j.get("description", "").strip()
                   and j.get("company", "").strip()]
    return db_jobs + manual_jobs


def estimate_tokens(job: dict) -> tuple[int, int]:
    prompt = build_enrichment_prompt(job)
    input_tokens  = len(prompt) // 4
    output_tokens = 300  # conservative fixed estimate for JSON response
    return input_tokens, output_tokens


def model_cost(model: str, input_tok: int, output_tok: int) -> float:
    prices = PRICING.get(model, PRICING_FALLBACK)
    return (input_tok * prices["input"] + output_tok * prices["output"]) / 1_000_000


def parse_list_field(value) -> set[str]:
    """Parse a list field that may be a JSON string, a list, or None."""
    if value is None:
        return set()
    if isinstance(value, list):
        return {str(v).strip().lower() for v in value if v}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return {str(v).strip().lower() for v in parsed if v}
        except (json.JSONDecodeError, ValueError):
            pass
    return set()


def _normalize_skill(s: str) -> str:
    """Lowercase, strip parentheticals, apply common aliases."""
    s = s.lower().strip()
    s = re.sub(r"\s*\(.*?\)\s*$", "", s).strip()   # "python (3.x)" → "python"
    return _SKILL_ALIASES.get(s, s)


def _normalize_skills(skills: set) -> set:
    return {_normalize_skill(s) for s in skills if s}


def _categorical_score(field: str, t: str, s: str) -> float:
    """Partial-credit scoring for a single categorical field."""
    t, s = str(t).strip().lower(), str(s).strip().lower()
    if t == s:
        return 1.0
    if field == "seniority" and t in _SENIORITY_RANK and s in _SENIORITY_RANK:
        # Ordinal distance: off-by-1 → 0.75, off-by-2 → 0.5, off-by-3 → 0.25, 4+ → 0.0
        diff = abs(_SENIORITY_RANK[t] - _SENIORITY_RANK[s])
        return max(0.0, 1.0 - diff * 0.25)
    if field == "work_mode":
        # hybrid is adjacent to both remote and onsite
        if {t, s} in ({"remote", "hybrid"}, {"hybrid", "onsite"}):
            return 0.5
    if field in ("canada_eligible", "visa_sponsorship"):
        # "unknown" is a soft miss — neither confidently right nor fully wrong
        if "unknown" in (t, s):
            return 0.25
    return 0.0


def f1_score(t_set: set, s_set: set) -> float:
    """F1 between two sets. Both empty → 1.0 (both agree: nothing here)."""
    if not t_set and not s_set:
        return 1.0
    if not t_set or not s_set:
        return 0.0
    intersection = len(t_set & s_set)
    p = intersection / len(s_set)
    r = intersection / len(t_set)
    return 2 * p * r / (p + r) if (p + r) else 0.0


def precision_recall(t_set: set, s_set: set) -> tuple[float, float]:
    """(precision, recall) — student precision = what fraction of student output matches teacher."""
    if not t_set and not s_set:
        return 1.0, 1.0
    intersection = len(t_set & s_set)
    p = intersection / len(s_set) if s_set else 0.0
    r = intersection / len(t_set) if t_set else 0.0
    return p, r


def score_job(teacher: dict, student: dict) -> dict[str, float]:
    scores: dict[str, float] = {}

    for field in CATEGORICAL_FIELDS:
        t = teacher.get(field)
        s = student.get(field)
        if t is None and s is None:
            scores[field] = 1.0
        elif t is None and s is not None:
            scores[field] = 0.0  # student invented data
        elif t is not None and s is None:
            scores[field] = 0.0  # student missed it
        else:
            scores[field] = _categorical_score(field, t, s)

    for field in LIST_FIELDS:
        t_set = _normalize_skills(parse_list_field(teacher.get(field)))
        s_set = _normalize_skills(parse_list_field(student.get(field)))
        scores[field] = f1_score(t_set, s_set)
        # Store precision/recall separately for diagnostics
        p, r = precision_recall(t_set, s_set)
        scores[f"{field}__p"] = p
        scores[f"{field}__r"] = r

    scores["overall"] = sum(scores[f] for f in SCORED_FIELDS) / len(SCORED_FIELDS)
    return scores


def latest_results_file() -> Path | None:
    if not RESULTS_DIR.exists():
        return None
    files = sorted(RESULTS_DIR.glob("*.json"), reverse=True)
    return files[0] if files else None


def model_slug(model: str) -> str:
    return model.replace("/", "-").replace(".", "_")


def model_short(model: str) -> str:
    """Short display name: strip provider prefix and common suffixes."""
    name = model.split("/")[-1]
    for suf in ["-instruct", "-it", "-thinking-2507"]:
        name = name.replace(suf, "")
    return name[:18]


# ---------------------------------------------------------------------------
# Crawl helpers
# ---------------------------------------------------------------------------

def _eval_title_filter(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in EVAL_TITLE_INCLUDE) and not any(kw in t for kw in EVAL_TITLE_EXCLUDE)


def _init_eval_db(path: Path):
    conn = _sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eval_jobs (
            url         TEXT PRIMARY KEY,
            company     TEXT,
            title       TEXT,
            location    TEXT,
            description TEXT,
            posted      TEXT,
            ats         TEXT,
            crawled_at  TEXT
        )
    """)
    conn.commit()
    return conn


def _save_eval_jobs(conn, jobs: list[dict]) -> tuple[int, int]:
    now = datetime.now(timezone.utc).isoformat()
    new_count = updated_count = 0
    for job in jobs:
        url = job.get("url", "")
        if not url:
            continue
        existing = conn.execute("SELECT url FROM eval_jobs WHERE url = ?", (url,)).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO eval_jobs (url, company, title, location, description, posted, ats, crawled_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (url, job.get("company", ""), job.get("title", ""), job.get("location", ""),
                 job.get("description", ""), job.get("posted", ""), job.get("ats", ""), now),
            )
            new_count += 1
        else:
            conn.execute(
                "UPDATE eval_jobs SET description=?, crawled_at=? WHERE url=?",
                (job.get("description", ""), now, url),
            )
            updated_count += 1
    conn.commit()
    return new_count, updated_count


_RED_FLAG_PHRASES = [
    "authorized to work in the united states", "us work authorization",
    "us citizenship", "us citizen", "security clearance", "secret clearance",
    "top secret", "must be located in", "must reside in",
]
_REMOTE_GEO_US_STATES = [
    "california", "new york", "texas", "washington", "massachusetts",
    "illinois", "colorado", "georgia", "florida",
]


def tag_segment(job: dict) -> str:
    """Assign a segment label to a job for eval coverage tracking. First match wins."""
    title = (job.get("title") or "").lower()
    desc  = (job.get("description") or "").lower()
    loc   = (job.get("location") or "").lower()

    # 1. seniority_extreme
    if re.search(r"\b(intern|junior|entry)\b", title) or re.search(r"\b(staff|principal)\b", title):
        return "seniority_extreme"

    # 2. red_flag
    if any(phrase in desc for phrase in _RED_FLAG_PHRASES):
        return "red_flag"

    # 3. remote_geo_edge
    if "remote" in loc:
        if re.search(r"\bremote\s*(us|usa)\b|\bremote\s*united\s*states\b|\b(us|usa)\s*remote\b", loc):
            return "remote_geo_edge"
        if any(state in loc for state in _REMOTE_GEO_US_STATES):
            return "remote_geo_edge"
        if "north america" in loc or "americas" in loc:
            return "remote_geo_edge"

    # 4. salary_disclosed
    if re.search(r'\$\s*\d{2,3}[,k\d]', desc):
        return "salary_disclosed"

    # 5. sparse
    if len(desc.strip()) < 800:
        return "sparse"

    # 6. core
    return "core"


_SEGMENT_TARGETS = {
    "core": 100,
    "remote_geo_edge": 30,
    "red_flag": 20,
    "seniority_extreme": 20,
    "salary_disclosed": 20,
    "sparse": 10,
}


# ---------------------------------------------------------------------------
# Subcommand: build
# ---------------------------------------------------------------------------

def cmd_build(args) -> None:
    db_path = Path(args.db) if args.db else EVAL_DB_PATH
    if not db_path.exists():
        print(f"ERROR: {db_path} not found. Run `eval.py crawl` first.")
        sys.exit(1)

    conn = _sqlite3.connect(db_path)
    rows = conn.execute("""
        SELECT url, company, title, location, description, posted
        FROM eval_jobs
        WHERE description IS NOT NULL AND TRIM(description) != ''
        ORDER BY crawled_at DESC
    """).fetchall()
    conn.close()

    db_jobs = []
    for i, r in enumerate(rows):
        job = {
            "id": f"db-{i+1:03d}",
            "url": r[0],
            "company": r[1],
            "title": r[2],
            "location": r[3],
            "description": r[4],
            "posted": r[5],
            "segment": tag_segment({"title": r[2], "description": r[4], "location": r[3]}),
        }
        db_jobs.append(job)

    # Preserve existing manual_jobs if dataset already exists
    manual_jobs = []
    if DATASET_FILE.exists():
        existing = yaml.safe_load(DATASET_FILE.read_text(encoding="utf-8")) or {}
        manual_jobs = existing.get("manual_jobs") or []

    if not manual_jobs:
        manual_jobs = [{
            "id": "manual-001",
            "company": "",
            "title": "",
            "location": "",
            "url": "",
            "description": "",
        }]

    EVAL_DIR.mkdir(exist_ok=True)

    header = (
        "# eval/dataset.yaml -- Enrichment evaluation dataset\n"
        "#\n"
        "# db_jobs: auto-generated from eval/eval_jobs.db. DO NOT edit manually.\n"
        "#          Re-run `eval.py crawl && eval.py build` to refresh.\n"
        "#\n"
        "# manual_jobs: add your own job postings here.\n"
        "#   Copy the placeholder block and fill in company, title, location, description.\n"
        "#   Leave id as manual-NNN (increment for each new job).\n"
        "#   url is optional.\n"
    )

    data = {"db_jobs": db_jobs, "manual_jobs": manual_jobs}
    DATASET_FILE.write_text(
        header + "\n" + yaml.dump(data, allow_unicode=True, default_flow_style=False,
                                  sort_keys=False, width=120),
        encoding="utf-8",
    )

    existing_manual = [j for j in manual_jobs
                       if j.get("description", "").strip() and j.get("company", "").strip()]
    print(f"Built dataset: {len(db_jobs)} DB jobs, {len(existing_manual)} manual jobs")
    print(f"Saved to: {DATASET_FILE}")

    # Segment distribution
    seg_counts: dict[str, int] = {}
    for job in db_jobs:
        seg = job["segment"]
        seg_counts[seg] = seg_counts.get(seg, 0) + 1

    print(f"\nSegment distribution (target in parentheses):")
    for seg, target in _SEGMENT_TARGETS.items():
        count = seg_counts.get(seg, 0)
        low = "  <-- LOW" if count < target * 0.5 else ""
        print(f"  {seg:<20} {count:>4}  (target {target}){low}")


# ---------------------------------------------------------------------------
# Subcommand: cost
# ---------------------------------------------------------------------------

def cmd_cost(args) -> None:
    jobs = load_dataset()
    student_models = args.models
    teacher = args.teacher

    total_input = total_output = 0
    for job in jobs:
        inp, out = estimate_tokens(job)
        total_input  += inp
        total_output += out

    all_models = [teacher] + student_models

    print(f"\nDataset: {len(jobs)} jobs  ({total_input:,} input tokens, {total_output:,} output tokens estimated)\n")

    W = 50
    header = f"  {'Model':<{W}} {'Input $/M':>10} {'Output $/M':>11} {'Est. Cost':>10}"
    sep = "  " + "-" * (W + 35)
    print(header)
    print(sep)

    grand_total = 0.0
    for model in all_models:
        prices = PRICING.get(model, PRICING_FALLBACK)
        cost = model_cost(model, total_input, total_output)
        grand_total += cost
        label = model + ("  [teacher]" if model == teacher else "")
        flag = "  (*unknown price)" if model not in PRICING else ""
        print(f"  {label:<{W}} ${prices['input']:>8.3f}   ${prices['output']:>8.2f}   ${cost:>8.4f}{flag}")

    print(sep)
    n = len(all_models)
    print(f"  {'TOTAL (' + str(n) + ' models)':<{W}} {'':>10} {'':>11} ${grand_total:>8.4f}\n")

    if grand_total < 1.00:
        print("  Cost is negligible -- recommend running on the full dataset.")
    elif grand_total < 5.00:
        print(f"  Reasonable cost. Consider --subset N if you want a cheaper smoke test first.")
    else:
        print(f"  Cost is significant. Use --subset N to run on a subset first.")


# ---------------------------------------------------------------------------
# Subcommand: run
# ---------------------------------------------------------------------------

def _run_model(jobs: list[dict], api_key: str, model: str, max_workers: int) -> dict[str, dict]:
    """Run enrichment for a single model across all jobs. Returns {job_id: result}."""
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(enrich_one_job, job, api_key, model): job for job in jobs}
        for i, future in enumerate(as_completed(futures), 1):
            job = futures[future]
            result = future.result()
            results[job["id"]] = result
            status = result.get("enrichment_status", "?")
            print(f"  [{i:3d}/{len(jobs)}] {status:7s}  {job['company']} -- {job['title'][:50]}")
    return results


def cmd_run(args) -> None:
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set.")
        sys.exit(1)

    student_models = args.models
    teacher_model  = args.teacher
    jobs = load_dataset()

    if args.subset:
        total = len(jobs)
        jobs = jobs[:args.subset]
        print(f"Subset mode: using {len(jobs)} of {total} jobs")

    n = len(student_models)
    print(f"\nRunning eval on {len(jobs)} jobs")
    print(f"  Teacher : {teacher_model}")
    for m in student_models:
        print(f"  Student : {m}")
    print()

    # Run teacher first (conservative concurrency -- gpt-5.2 has rate limits)
    print(f"[1/{n+1}] Running teacher ({teacher_model})...")
    teacher_results = _run_model(jobs, api_key, teacher_model, max_workers=3)

    # Run each student model sequentially (jobs within each model run concurrently)
    all_student_results: dict[str, dict[str, dict]] = {}
    for i, model in enumerate(student_models, 2):
        print(f"\n[{i}/{n+1}] Running {model}...")
        all_student_results[model] = _run_model(jobs, api_key, model, max_workers=5)

    # Score each model against teacher
    job_records = []
    for job in jobs:
        jid = job["id"]
        t = teacher_results.get(jid, {})
        students = {}
        for model in student_models:
            s = all_student_results[model].get(jid, {})
            scores = {}
            if t.get("enrichment_status") == "ok" and s.get("enrichment_status") == "ok":
                scores = score_job(t, s)
            students[model] = {"output": s, "scores": scores}

        job_records.append({
            "id": jid,
            "company": job.get("company", ""),
            "title": job.get("title", ""),
            "segment": job.get("segment", "core"),
            "teacher": t,
            "students": students,
        })

    # Aggregate per model
    aggregate: dict[str, dict[str, float]] = {}
    for model in student_models:
        scoreable = [r for r in job_records if r["students"][model].get("scores")]
        if scoreable:
            model_agg: dict[str, float] = {}
            # Main scored fields + overall
            for field in SCORED_FIELDS + ["overall"]:
                vals = [r["students"][model]["scores"][field]
                        for r in scoreable if field in r["students"][model]["scores"]]
                model_agg[field] = sum(vals) / len(vals) if vals else 0.0
            # Precision / recall for list fields
            for field in LIST_FIELDS:
                for suffix in ("__p", "__r"):
                    key = f"{field}{suffix}"
                    vals = [r["students"][model]["scores"][key]
                            for r in scoreable if key in r["students"][model]["scores"]]
                    model_agg[key] = sum(vals) / len(vals) if vals else 0.0
            aggregate[model] = model_agg

    output = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "teacher_model": teacher_model,
        "student_models": student_models,
        "total_jobs": len(jobs),
        "jobs": job_records,
        "aggregate": aggregate,
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = RESULTS_DIR / f"{ts}_{model_slug(teacher_model)}_{n}models.json"
    out_file.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nResults saved to: {out_file}")

    # Quick summary: overall score per model, sorted best first
    if aggregate:
        print()
        ranked = sorted(aggregate.items(), key=lambda kv: kv[1].get("overall", 0.0), reverse=True)
        print(f"  {'Model':<50} {'Overall':>8}  {'Teacher ok':>10}  {'Student ok':>10}")
        print("  " + "-" * 82)
        for model, agg in ranked:
            t_ok = sum(1 for r in job_records if r["teacher"].get("enrichment_status") == "ok")
            s_ok = sum(1 for r in job_records
                       if r["students"][model]["output"].get("enrichment_status") == "ok")
            print(f"  {model:<50} {agg['overall']:>7.0%}  {t_ok:>10d}  {s_ok:>10d}")

    print(f"\nRun `eval.py report` to see the full field-by-field comparison.")


# ---------------------------------------------------------------------------
# Subcommand: crawl
# ---------------------------------------------------------------------------

def cmd_crawl(args) -> None:
    import scrape  # src/scrape.py via sys.path

    config_path = Path(args.config) if args.config else Path.cwd() / "companies.yaml"
    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}")
        sys.exit(1)

    db_path = Path(args.db) if args.db else EVAL_DB_PATH

    companies = scrape.load_companies(config_path)
    print(f"Loaded {len(companies)} companies from {config_path}")
    print(f"Crawling with no location filter, broader title filter...")
    print(f"Output: {db_path}\n")

    jobs = scrape.scrape_all(
        companies,
        apply_location_filter=False,
        enrich=True,
        title_filter_fn=_eval_title_filter,
    )

    if args.limit and len(jobs) > args.limit:
        print(f"\nCapping at {args.limit} jobs (--limit {args.limit})")
        jobs = jobs[:args.limit]

    print(f"\nCrawled {len(jobs)} jobs total")

    conn = _init_eval_db(db_path)
    new_count, updated_count = _save_eval_jobs(conn, jobs)
    conn.close()

    # Location breakdown
    ca     = sum(1 for j in jobs if "canada" in (j.get("location") or "").lower())
    remote = sum(1 for j in jobs if "remote" in (j.get("location") or "").lower()
                 and "canada" not in (j.get("location") or "").lower())
    us_nr  = sum(1 for j in jobs if "remote" not in (j.get("location") or "").lower()
                 and "canada" not in (j.get("location") or "").lower()
                 and ("united states" in (j.get("location") or "").lower()
                      or ", " in (j.get("location") or "")))
    other  = len(jobs) - ca - remote - us_nr

    print(f"\nLocation breakdown:")
    print(f"  Canada:          {ca}")
    print(f"  Remote:          {remote}")
    print(f"  US (non-remote): {us_nr}")
    print(f"  Other:           {other}")

    # Segment preview
    seg_counts: dict[str, int] = {}
    for job in jobs:
        seg = tag_segment(job)
        seg_counts[seg] = seg_counts.get(seg, 0) + 1

    print(f"\nSegment preview (target in parentheses):")
    for seg, target in _SEGMENT_TARGETS.items():
        count = seg_counts.get(seg, 0)
        low = "  <-- LOW" if count < target * 0.5 else ""
        print(f"  {seg:<20} {count:>4}  (target {target}){low}")

    print(f"\nSaved: {new_count} new, {updated_count} updated  →  {db_path}")
    print(f"Run `eval.py build` to build dataset.yaml from crawled jobs.")


# ---------------------------------------------------------------------------
# Subcommand: report
# ---------------------------------------------------------------------------

def cmd_report(args) -> None:
    if args.results_file:
        results_path = Path(args.results_file)
    else:
        results_path = latest_results_file()
        if not results_path:
            print("No results files found. Run `eval.py run` first.")
            sys.exit(1)

    data = json.loads(results_path.read_text(encoding="utf-8"))

    # Detect format: new multi-model vs legacy binary
    if "student_models" in data:
        _report_multi(data, results_path)
    else:
        _report_legacy(data, results_path)


def _report_multi(data: dict, results_path: Path) -> None:
    teacher        = data["teacher_model"]
    student_models = data["student_models"]
    agg            = data.get("aggregate", {})
    jobs           = data.get("jobs", [])

    # Sort models by overall score descending (best first)
    sorted_models = sorted(
        [m for m in student_models if m in agg],
        key=lambda m: agg[m].get("overall", 0.0),
        reverse=True,
    )

    print(f"\nEval report: {results_path.name}")
    print(f"  Teacher : {teacher}  (ground truth)")
    print(f"  Jobs    : {data['total_jobs']} total")
    print(f"  Models  : {len(sorted_models)} students evaluated")
    print(f"  Run at  : {data['run_at']}")
    print(f"  Scoring : categoricals=partial-credit  lists=F1  overall=equal-weight\n")

    # ── Main field × model table ─────────────────────────────────────────────
    FIELD_W = 26
    COL_W   = 10
    short_names = [model_short(m) for m in sorted_models]

    hdr = f"  {'Field':<{FIELD_W}}" + "".join(f"{s:>{COL_W}}" for s in short_names)
    sep = "  " + "-" * (FIELD_W + COL_W * len(sorted_models) + 2)
    print(hdr)
    print(sep)

    for field in SCORED_FIELDS:
        row = f"  {field:<{FIELD_W}}"
        field_scores = [agg.get(m, {}).get(field, 0.0) for m in sorted_models]
        best = max(field_scores) if field_scores else 0.0
        for score in field_scores:
            marker = "*" if score == best and len(sorted_models) > 1 else " "
            row += f"{score:>{COL_W-2}.0%}{marker} "
        print(row)

    print(sep)
    row = f"  {'OVERALL':<{FIELD_W}}"
    overall_scores = [agg.get(m, {}).get("overall", 0.0) for m in sorted_models]
    best_overall = max(overall_scores) if overall_scores else 0.0
    for score in overall_scores:
        marker = "*" if score == best_overall and len(sorted_models) > 1 else " "
        row += f"{score:>{COL_W-2}.0%}{marker} "
    print(row)

    # Model ranking footer
    print(f"\n  Models ranked by overall  (* = best in column):")
    for rank, model in enumerate(sorted_models, 1):
        score = agg.get(model, {}).get("overall", 0.0)
        n_scored = sum(1 for r in jobs if r.get("students", {}).get(model, {}).get("scores"))
        print(f"  {rank}. {score:.0%}  {model}  ({n_scored} jobs scored)")

    # ── List field diagnostics: F1 / Precision / Recall ─────────────────────
    best_model = sorted_models[0] if sorted_models else None
    if best_model and any(f"{f}__p" in agg.get(best_model, {}) for f in LIST_FIELDS):
        print(f"\n  List field diagnostics — {model_short(best_model)} (best model):")
        print(f"  {'Field':<24} {'F1':>6}  {'Precision':>10}  {'Recall':>8}  {'Note'}")
        print("  " + "-" * 60)
        for field in LIST_FIELDS:
            f1  = agg[best_model].get(field, 0.0)
            p   = agg[best_model].get(f"{field}__p", 0.0)
            r   = agg[best_model].get(f"{field}__r", 0.0)
            if p < r - 0.10:
                note = "hallucinates"
            elif r < p - 0.10:
                note = "under-extracts"
            else:
                note = ""
            print(f"  {field:<24} {f1:>5.0%}  {p:>10.0%}  {r:>8.0%}  {note}")

    # ── canada_eligible confusion matrix ─────────────────────────────────────
    if best_model:
        labels = ["yes", "no", "unknown"]
        matrix: dict[tuple[str, str], int] = {}
        for r in jobs:
            t_val = str(r["teacher"].get("canada_eligible") or "unknown").lower()
            s_val = str(r["students"].get(best_model, {}).get("output", {}).get("canada_eligible") or "unknown").lower()
            if t_val not in labels: t_val = "unknown"
            if s_val not in labels: s_val = "unknown"
            matrix[(t_val, s_val)] = matrix.get((t_val, s_val), 0) + 1

        print(f"\n  canada_eligible confusion matrix (teacher↓ / {model_short(best_model)}→):")
        print(f"  {'':16}" + "".join(f"{l:>10}" for l in labels))
        for t_val in labels:
            row = f"  {t_val:<16}"
            for s_val in labels:
                count = matrix.get((t_val, s_val), 0)
                row += f"  {count:>8}"
            print(row)

    # ── Per-segment breakdown ────────────────────────────────────────────────
    if best_model and any(r.get("segment") for r in jobs):
        print(f"\n  Per-segment overall — {model_short(best_model)} (best model):")
        print(f"  {'Segment':<20} {'Score':>7}  {'Jobs':>5}")
        print("  " + "-" * 38)
        for seg in _SEGMENT_TARGETS:
            seg_jobs = [
                r for r in jobs
                if r.get("segment") == seg
                and r.get("students", {}).get(best_model, {}).get("scores")
            ]
            if not seg_jobs:
                continue
            seg_score = sum(r["students"][best_model]["scores"]["overall"] for r in seg_jobs) / len(seg_jobs)
            print(f"  {seg:<20} {seg_score:>6.0%}  {len(seg_jobs):>5}")

    # ── Low-scoring jobs ─────────────────────────────────────────────────────
    if best_model and jobs:
        poor = [
            r for r in jobs
            if r.get("students", {}).get(best_model, {}).get("scores", {}).get("overall", 1.0) < 0.5
        ]
        if poor:
            print(f"\n  Jobs where best model score < 50% ({len(poor)} jobs):")
            for r in poor:
                s = r["students"][best_model]["scores"].get("overall", 0.0)
                seg = r.get("segment", "")
                print(f"    {s:.0%}  [{seg}]  {r['company']} — {r['title'][:50]}")

    # ── Verdict ──────────────────────────────────────────────────────────────
    print()
    if best_overall >= 0.80:
        print(f"  Verdict: {model_short(sorted_models[0])} matches teacher well. Suitable for production.")
    elif best_overall >= 0.60:
        print(f"  Verdict: Best model adequate for categoricals but underextracts list fields.")
        print(f"           Consider prompt improvements before upgrading the model.")
    else:
        print(f"  Verdict: All models significantly underperform. Upgrade model or improve prompt.")


def _report_legacy(data: dict, results_path: Path) -> None:
    """Handle old binary student/teacher results format."""
    agg     = data.get("aggregate", {})
    jobs    = data.get("jobs", [])
    student = data["student_model"]
    teacher = data["teacher_model"]

    print(f"\nEval report (legacy format): {results_path.name}")
    print(f"  Student : {student}")
    print(f"  Teacher : {teacher}  (ground truth)")
    print(f"  Jobs    : {data['total_jobs']} total, {data.get('scoreable_jobs', '?')} scored")
    print(f"  Run at  : {data['run_at']}\n")

    col = 24
    print(f"  {'Field':<{col}} {'Score':>7}  {'Bar'}")
    print("  " + "-" * 52)
    for field in SCORED_FIELDS:
        score = agg.get(field, 0.0)
        bar_len = int(score * 20)
        bar = "#" * bar_len + "." * (20 - bar_len)
        flag = "  <-- weakest" if score == min(agg.get(f, 1.0) for f in SCORED_FIELDS) else ""
        print(f"  {field:<{col}} {score:>6.0%}  [{bar}]{flag}")
    print("  " + "-" * 52)
    overall = agg.get("overall", 0.0)
    bar_len = int(overall * 20)
    bar = "#" * bar_len + "." * (20 - bar_len)
    print(f"  {'OVERALL':<{col}} {overall:>6.0%}  [{bar}]")

    poor = [r for r in jobs if r.get("scores", {}).get("overall", 1.0) < 0.5]
    if poor:
        print(f"\n  Jobs where student score < 50% ({len(poor)} jobs):")
        for r in poor:
            s = r["scores"].get("overall", 0.0)
            print(f"    {s:.0%}  {r['company']} -- {r['title'][:55]}")

    print()
    if overall >= 0.80:
        print("  Verdict: student matches teacher well. Cheap model is sufficient.")
    elif overall >= 0.60:
        print("  Verdict: student adequate for categoricals but misses list extraction.")
        print("           Consider prompt improvements before upgrading the model.")
    else:
        print("  Verdict: student significantly underperforms. Upgrade to a larger model.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Enrichment model evaluation framework.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="Build dataset.yaml from eval/eval_jobs.db")
    p_build.add_argument("--db", default=None, metavar="PATH",
                         help="Path to eval_jobs.db (default: eval/eval_jobs.db)")

    p_crawl = sub.add_parser("crawl", help="Crawl jobs into eval/eval_jobs.db (no location filter)")
    p_crawl.add_argument("--config", default=None, metavar="PATH",
                         help="Path to companies.yaml (default: companies.yaml in cwd)")
    p_crawl.add_argument("--db", default=None, metavar="PATH",
                         help="Output DB path (default: eval/eval_jobs.db)")
    p_crawl.add_argument("--limit", type=int, default=None, metavar="N",
                         help="Cap total jobs saved (safety valve)")

    p_cost = sub.add_parser("cost", help="Estimate API cost for all models")
    p_cost.add_argument("--models", nargs="+", default=DEFAULT_STUDENT_MODELS, metavar="MODEL",
                        help="Student models to evaluate (default: all 7)")
    p_cost.add_argument("--teacher", default=DEFAULT_TEACHER, metavar="MODEL")

    p_run = sub.add_parser("run", help="Run eval: all models vs teacher on dataset")
    p_run.add_argument("--models", nargs="+", default=DEFAULT_STUDENT_MODELS, metavar="MODEL",
                       help="Student models to evaluate (default: all 7)")
    p_run.add_argument("--teacher", default=DEFAULT_TEACHER, metavar="MODEL")
    p_run.add_argument("--subset", type=int, default=None, metavar="N",
                       help="Run on first N jobs only")

    p_rep = sub.add_parser("report", help="Print comparison report")
    p_rep.add_argument("results_file", nargs="?", default=None,
                       help="Path to results JSON (default: latest)")

    args = parser.parse_args()
    {"build": cmd_build, "crawl": cmd_crawl, "cost": cmd_cost, "run": cmd_run, "report": cmd_report}[args.command](args)


if __name__ == "__main__":
    main()
