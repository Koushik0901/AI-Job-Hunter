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
import threading
import time
import warnings
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Suppress cosmetic LangChain/Pydantic serialization warnings (data is correct)
warnings.filterwarnings("ignore", message=".*PydanticSerializationUnexpectedValue.*", category=UserWarning)

# Allow importing from src/
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from enrich import RateLimitSignal, build_enrichment_prompt, enrich_one_job
from notify import _load_dotenv

_load_dotenv(Path.cwd() / ".env")

EVAL_DIR         = Path(__file__).parent
DATASET_FILE     = EVAL_DIR / "dataset.yaml"
RESULTS_DIR      = EVAL_DIR / "results"
CHECKPOINT_FILE  = RESULTS_DIR / "checkpoint.json"
EVAL_DB_PATH = EVAL_DIR / "eval_jobs.db"

DEFAULT_TEACHER = "openai/gpt-5.2"

DEFAULT_STUDENT_MODELS = [
    "openai/gpt-oss-120b",
    "google/gemma-3-12b-it",
    "google/gemma-3-27b-it",
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
    "google/gemma-3-27b-it":                    {"input": 0.040, "output": 0.15},
    "openai/gpt-oss-120b":                      {"input": 0.039, "output": 0.19},
    "mistralai/mistral-small-3.2-24b-instruct": {"input": 0.060, "output": 0.18},
    "qwen/qwen3-30b-a3b-thinking-2507":         {"input": 0.051, "output": 0.34},
    "meta-llama/llama-4-scout":                 {"input": 0.080, "output": 0.30},
    "openai/gpt-5.2":                           {"input": 1.750, "output": 14.00},
}
PRICING_FALLBACK = {"input": 1.00, "output": 4.00}  # conservative unknown model estimate

CATEGORICAL_FIELDS = ["work_mode", "canada_eligible", "seniority", "role_family", "visa_sponsorship"]
LIST_FIELDS        = ["required_skills", "preferred_skills", "red_flags"]
NUMERIC_FIELDS     = ["years_exp_min", "years_exp_max"]
SALARY_FIELDS      = ["salary_min", "salary_max", "salary_currency"]
SCORED_FIELDS      = CATEGORICAL_FIELDS + LIST_FIELDS + NUMERIC_FIELDS + SALARY_FIELDS

# Ordinal rank for seniority partial-credit scoring
_SENIORITY_RANK = {"intern": 0, "junior": 1, "mid": 2, "senior": 3, "staff": 4, "principal": 5}

# Common skill aliases — normalized before Jaccard / F1 computation
_SKILL_ALIASES: dict[str, str] = {
    "js":       "javascript",
    "ts":       "typescript",
    "k8s":      "kubernetes",
    "postgres": "postgresql",
    "torch":    "pytorch",
    "tf":       "tensorflow",
    "gcp":      "google cloud",
    "aws":      "amazon web services",
    "azure":    "microsoft azure",
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


_SYSTEM_PROMPT_TOKENS = 45   # "You are a structured data extraction engine..." (~180 chars)
_OUTPUT_TOKENS_PER_JOB = 500 # realistic for full JobEnrichment JSON via tool_call format
                              # (schema fields + skill lists + JSON structure overhead)

def estimate_tokens(job: dict) -> tuple[int, int]:
    prompt = build_enrichment_prompt(job)
    input_tokens  = _SYSTEM_PROMPT_TOKENS + len(prompt) // 4
    return input_tokens, _OUTPUT_TOKENS_PER_JOB


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


def _numeric_score(t, s) -> float:
    """Ordinal-tolerance scoring for integer fields (years_exp).
    Exact=1.0, off-by-1=0.75, off-by-2=0.5, off-by-3=0.25, ≥4=0.0.
    Both null→1.0 (both agree: not mentioned). One null→0.0."""
    if t is None and s is None:
        return 1.0
    if t is None or s is None:
        return 0.0
    try:
        diff = abs(int(t) - int(s))
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, 1.0 - diff * 0.25)


def _salary_score(t, s) -> float:
    """Percentage-tolerance scoring for salary integers, with unit normalization.
    Handles the '$150k' ambiguity: one model may output 150, another 150000.
    If one value is <1000 and the other ≥10000 with ratio ≈1000, scale up the smaller.
    Tolerance bands: ≤5%→1.0, ≤15%→0.75, ≤30%→0.5, ≤50%→0.25, >50%→0.0.
    Both null→1.0. One null→0.0."""
    if t is None and s is None:
        return 1.0
    if t is None or s is None:
        return 0.0
    try:
        a, b = int(t), int(s)
    except (TypeError, ValueError):
        return 0.0
    lo, hi = min(a, b), max(a, b)
    # Unit normalization: if one looks like thousands ($150k→150) and other is full dollars
    if lo > 0 and lo < 1_000 and hi >= 10_000 and hi / lo >= 500:
        lo *= 1_000
    if hi == 0:
        return 1.0
    ratio = (hi - lo) / hi
    if ratio <= 0.05:   return 1.0
    if ratio <= 0.15:   return 0.75
    if ratio <= 0.30:   return 0.5
    if ratio <= 0.50:   return 0.25
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

    for field in NUMERIC_FIELDS:
        scores[field] = _numeric_score(teacher.get(field), student.get(field))

    for field in SALARY_FIELDS:
        t = teacher.get(field)
        s = student.get(field)
        if field == "salary_currency":
            # Exact match — CAD vs USD is a definitive error, no partial credit
            if t is None and s is None:
                scores[field] = 1.0
            elif t is None or s is None:
                scores[field] = 0.0
            else:
                scores[field] = 1.0 if str(t).upper() == str(s).upper() else 0.0
        else:
            scores[field] = _salary_score(t, s)

    scores["overall"] = sum(scores[f] for f in SCORED_FIELDS) / len(SCORED_FIELDS)
    return scores


def latest_results_file() -> Path | None:
    if not RESULTS_DIR.exists():
        return None
    # Exclude checkpoint.json — it sorts after timestamped files alphabetically (c > 2)
    files = sorted(
        (f for f in RESULTS_DIR.glob("*.json") if f.name != "checkpoint.json"),
        reverse=True,
    )
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
    # Explicit US work-auth restrictions
    "authorized to work in the united states",
    "must be authorized to work in the us",
    "must be legally authorized",
    "legally authorized to work in the us",
    "eligible to work in the us",
    "eligible to work in the united states",
    "us work authorization",
    "work authorization in the us",
    "us citizenship", "us citizen",
    # Security clearance
    "security clearance", "secret clearance", "top secret",
    # Location restrictions
    "must be located in", "must reside in", "must be based in the us",
    "must be based in the united states",
    # Negative sponsorship statements
    "does not sponsor", "unable to sponsor", "cannot sponsor",
    "not able to sponsor", "sponsorship is not available",
    "no visa sponsorship", "not provide visa sponsorship",
    "not offer visa sponsorship", "does not offer sponsorship",
]
_REMOTE_GEO_US_STATES = [
    "california", "new york", "texas", "washington", "massachusetts",
    "illinois", "colorado", "georgia", "florida",
]
# Regex for "remote" + any punctuation/whitespace + US qualifier (or reversed)
_REMOTE_US_RE = re.compile(
    r"\bremote[\s,\-–]*(us|usa|united\s*states)\b"
    r"|\b(us|usa|united\s*states)[\s,\-–]*remote\b",
    re.IGNORECASE,
)


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

    # 3. remote_geo_edge — "Remote - United States", "Remote, USA", "Remote US", etc.
    if "remote" in loc:
        if _REMOTE_US_RE.search(loc):
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
    "salary_disclosed": 150,  # US jobs routinely disclose salary (pay transparency laws)
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

    avg_input  = total_input  // len(jobs)
    avg_output = total_output // len(jobs)

    all_models = [teacher] + student_models

    print(f"\nDataset : {len(jobs)} jobs")
    print(f"Per job : ~{avg_input:,} input tokens, ~{avg_output:,} output tokens")
    print(f"Total   : {total_input:,} input tokens, {total_output:,} output tokens\n")
    print(f"  (output estimate: {_OUTPUT_TOKENS_PER_JOB} tok/job fixed; "
          f"input from full description, no truncation)\n")

    W = 50
    header = f"  {'Model':<{W}} {'$/M in':>8} {'$/M out':>8} {'Input $':>9} {'Output $':>9} {'Total $':>9}"
    sep = "  " + "-" * (W + 48)
    print(header)
    print(sep)

    grand_total = 0.0
    for model in all_models:
        prices = PRICING.get(model, PRICING_FALLBACK)
        in_cost  = total_input  * prices["input"]  / 1_000_000
        out_cost = total_output * prices["output"] / 1_000_000
        cost = in_cost + out_cost
        grand_total += cost
        label = model + ("  [teacher]" if model == teacher else "")
        flag = " *" if model not in PRICING else "  "
        print(f"  {label:<{W}} {prices['input']:>7.3f}  {prices['output']:>7.2f}  "
              f"${in_cost:>8.4f}  ${out_cost:>8.4f}  ${cost:>8.4f}{flag}")

    print(sep)
    n = len(all_models)
    print(f"  {'TOTAL (' + str(n) + ' models)':<{W}} {'':>8} {'':>8}  {'':>9}  {'':>9}  ${grand_total:>8.4f}")
    unknown = [m for m in all_models if m not in PRICING]
    if unknown:
        print(f"  (* price not in PRICING table — using fallback ${PRICING_FALLBACK['input']:.2f}/${PRICING_FALLBACK['output']:.2f} per M)")
    print()

    if grand_total < 1.00:
        print("  Cost is negligible — recommend running on the full dataset.")
    elif grand_total < 5.00:
        print(f"  Reasonable. Use --subset N for a cheaper smoke test first.")
    else:
        print(f"  Significant cost. Use --subset N to run on a subset first.")


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------

_checkpoint_lock = threading.Lock()


def _load_checkpoint() -> dict | None:
    if CHECKPOINT_FILE.exists():
        try:
            return json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _save_checkpoint(cp: dict) -> None:
    """Write checkpoint to disk, serialized with a lock (Windows-safe)."""
    with _checkpoint_lock:
        RESULTS_DIR.mkdir(exist_ok=True)
        tmp = CHECKPOINT_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(cp, ensure_ascii=False), encoding="utf-8")
        # Retry loop: Windows antivirus/indexer can hold a brief lock on the
        # newly written .tmp file, causing os.replace() to fail with WinError 5.
        for attempt in range(6):
            try:
                tmp.replace(CHECKPOINT_FILE)
                break
            except PermissionError:
                if attempt < 5:
                    time.sleep(0.2 * (attempt + 1))
                else:
                    raise


# ---------------------------------------------------------------------------
# Subcommand: run
# ---------------------------------------------------------------------------

def _run_model(
    jobs: list[dict],
    api_key: str,
    model: str,
    max_workers: int,
    existing_results: dict | None = None,
    on_result=None,   # callback(job_id, result) called after each completed job
    provider_order: list[str] | None = None,
) -> tuple[dict[str, dict], bool]:
    """
    Run enrichment for one model. Skips jobs already in existing_results.
    Returns ({job_id: result}, rate_limited).
    Calls on_result(job_id, result) after each job so the caller can checkpoint immediately.
    """
    results: dict[str, dict] = dict(existing_results or {})
    jobs_to_run = [j for j in jobs if j["id"] not in results]
    total = len(jobs)

    if len(jobs_to_run) < total:
        print(f"  Resuming: {total - len(jobs_to_run)} already done, {len(jobs_to_run)} remaining.")

    stop_event = threading.Event()

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(enrich_one_job, job, api_key, model, stop_event, provider_order): job
            for job in jobs_to_run
        }
        done = total - len(jobs_to_run)  # count already-done jobs in the progress display
        for future in as_completed(futures):
            job = futures[future]
            try:
                result = future.result()
            except (RateLimitSignal, CancelledError):
                if not stop_event.is_set():
                    stop_event.set()
                    for f in futures:
                        f.cancel()
                    print(f"\n  Rate limit hit — {done}/{total} jobs done for this model.")
                continue
            except Exception as e:
                print(f"  [{done+1:3d}/{total}] error    {job['company']} -- {e}")
                continue
            done += 1
            results[job["id"]] = result
            if on_result:
                on_result(job["id"], result)
            status = result.get("enrichment_status", "?")
            print(f"  [{done:3d}/{total}] {status:7s}  {job['company']} -- {job['title'][:50]}")

    return results, stop_event.is_set()


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

    workers = args.workers
    provider_order = args.provider_order or None
    n = len(student_models)
    job_ids = [j["id"] for j in jobs]

    # ── Checkpoint: load or create ──────────────────────────────────────────
    cp: dict = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "teacher": teacher_model,
        "student_models": student_models,
        "job_ids": job_ids,
        "teacher_results": {},
        "student_results": {m: {} for m in student_models},
    }

    if args.resume:
        saved = _load_checkpoint()
        if saved is None:
            print("No checkpoint found — starting fresh.")
        elif saved.get("teacher") != teacher_model:
            print("Checkpoint is for a different teacher — starting fresh.")
        elif saved.get("job_ids") != job_ids:
            print("Dataset changed since checkpoint — starting fresh.")
        else:
            cp = saved
            # Allow a different (e.g. smaller) models list on resume — useful for skipping a
            # rate-limited model without losing all prior checkpoint progress.
            for m in student_models:
                if m not in cp["student_results"]:
                    cp["student_results"][m] = {}
            if saved.get("student_models") != student_models:
                skipped = [m for m in saved.get("student_models", []) if m not in student_models]
                if skipped:
                    print(f"  Note: skipping {skipped} (not in --models list)")
            print(f"Resuming from checkpoint saved at {cp['created_at']}\n")

    print(f"\nRunning eval on {len(jobs)} jobs")
    print(f"  Teacher : {teacher_model}  (workers=2)")
    for m in student_models:
        done = len(cp["student_results"].get(m, {}))
        tag  = f" ({done}/{len(jobs)} done)" if done else ""
        print(f"  Student : {m}{tag}")
    print(f"  Workers : {workers} per student model")
    print()

    # ── Teacher ────────────────────────────────────────────────────────────
    teacher_done = len(cp["teacher_results"])
    if teacher_done == len(jobs):
        print(f"[1/{n+1}] Teacher ({teacher_model}) — already complete, skipping.")
        teacher_results = cp["teacher_results"]
    else:
        print(f"[1/{n+1}] Running teacher ({teacher_model})...")

        def _on_teacher(job_id, result):
            cp["teacher_results"][job_id] = result
            _save_checkpoint(cp)

        teacher_results, teacher_rl = _run_model(
            jobs, api_key, teacher_model,
            max_workers=min(2, workers),
            existing_results=cp["teacher_results"],
            on_result=_on_teacher,
            provider_order=provider_order,
        )
        cp["teacher_results"] = teacher_results
        _save_checkpoint(cp)

        if teacher_rl:
            print(f"\nCheckpoint saved to: {CHECKPOINT_FILE}")
            print("Resume with:  uv run python eval/eval.py run --resume")
            return

    # ── Student models ─────────────────────────────────────────────────────
    all_student_results: dict[str, dict[str, dict]] = {}
    rate_limited = False
    for i, model in enumerate(student_models, 2):
        existing = cp["student_results"].get(model, {})
        if len(existing) == len(jobs):
            print(f"[{i}/{n+1}] {model} — already complete, skipping.")
            all_student_results[model] = existing
            continue

        print(f"\n[{i}/{n+1}] Running {model}...")

        def _on_student(job_id, result, _model=model):
            cp["student_results"][_model][job_id] = result
            _save_checkpoint(cp)

        model_results, model_rl = _run_model(
            jobs, api_key, model,
            max_workers=workers,
            existing_results=existing,
            on_result=_on_student,
            provider_order=provider_order,
        )
        cp["student_results"][model] = model_results
        all_student_results[model] = model_results
        _save_checkpoint(cp)

        if model_rl:
            rate_limited = True
            print(f"  Rate limit exhausted for {model} — skipping it, continuing with remaining models.")
            print(f"  Checkpoint saved. Resume this model later with:")
            print(f"    uv run python eval/eval.py run --resume --models {model}")

    # Score only models that have results (partial run due to rate limit is fine)
    scored_models = list(all_student_results.keys())

    job_records = []
    for job in jobs:
        jid = job["id"]
        t = teacher_results.get(jid, {})
        students = {}
        for model in scored_models:
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
    for model in scored_models:
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

    partial_note = f" (partial — {len(scored_models)}/{n} student models completed)" if rate_limited else ""
    output = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "teacher_model": teacher_model,
        "student_models": scored_models,
        "total_jobs": len(jobs),
        "partial": rate_limited,
        "jobs": job_records,
        "aggregate": aggregate,
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = RESULTS_DIR / f"{ts}_{model_slug(teacher_model)}_{len(scored_models)}models.json"
    out_file.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nResults saved to: {out_file}{partial_note}")
    if rate_limited:
        print(f"Checkpoint at:   {CHECKPOINT_FILE}")
        print("To retry rate-limited models: uv run python eval/eval.py run --resume --models <model>")

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
    from db import init_db, load_enabled_company_sources

    db_path = Path(args.db) if args.db else EVAL_DB_PATH

    turso_url = os.getenv("TURSO_URL", "")
    turso_token = os.getenv("TURSO_AUTH_TOKEN", "")
    if turso_url:
        source_db_url = turso_url
        source_db_token = turso_token
    elif args.source_db:
        source_db_url = args.source_db
        source_db_token = ""
    else:
        source_db_url = str(Path.cwd() / "jobs.db")
        source_db_token = ""

    source_conn = init_db(source_db_url, source_db_token)
    companies = load_enabled_company_sources(source_conn)
    source_conn.close()
    if not companies:
        print("ERROR: no enabled company sources found in DB.")
        print("Run `uv run python src/scrape.py --migrate-companies-from-yaml companies.yaml` first.")
        sys.exit(1)

    print(f"Loaded {len(companies)} enabled companies from DB")
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
    print(f"  Scoring : categoricals=partial-credit  lists=F1  numeric=ordinal-tolerance  salary=pct-tolerance  overall=equal-weight\n")

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
    p_crawl.add_argument("--source-db", default=None, metavar="PATH",
                         help="Source jobs DB path for company_sources (default: jobs.db in cwd, or TURSO_URL)")
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
    p_run.add_argument("--resume", action="store_true",
                       help="Resume from eval/results/checkpoint.json (skip already-done jobs)")
    p_run.add_argument("--workers", type=int, default=3, metavar="N",
                       help="Concurrent requests per student model (default: 3). "
                            "Lower if hitting rate limits.")
    p_run.add_argument("--provider-order", nargs="+", default=[], metavar="PROVIDER",
                       help="OpenRouter provider preference order, e.g. --provider-order DeepInfra. "
                            "Applied to all models. Falls back to other providers if unavailable.")

    p_rep = sub.add_parser("report", help="Print comparison report")
    p_rep.add_argument("results_file", nargs="?", default=None,
                       help="Path to results JSON (default: latest)")

    args = parser.parse_args()
    {"build": cmd_build, "crawl": cmd_crawl, "cost": cmd_cost, "run": cmd_run, "report": cmd_report}[args.command](args)


if __name__ == "__main__":
    main()
