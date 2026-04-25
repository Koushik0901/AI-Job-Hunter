# Scraping Pipeline Solidification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Diagnose and fix broken ATS fetchers (Lever/Ashby/Workable), add fixture-based regression tests for all seven ATS types, and ship a `sources check-all` CLI command.

**Architecture:** Triage first — a script reads your actual `company_sources` DB, samples 10 companies per ATS, probes them concurrently, and surfaces error rates. Fix known-fragile fetchers (Lever missing `User-Agent`, Workable missing `Origin`/`Referer`, Ashby HTML scraping replaced with stable JSON API). Record real API responses as snapshot fixtures, write regression tests against them. Add `sources check-all` as a persistent health check command.

**Tech Stack:** Python 3.11+, pytest (monkeypatch), requests, Rich

> **Note:** `companies.yaml` no longer exists — slugs live entirely in the `company_sources` DB table. Any reference to "auditing companies.yaml" means auditing slugs in the DB (which the triage script does automatically).

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `scripts/triage_fetchers.py` | New | Sample 10 companies/ATS from DB, probe concurrently, report |
| `scripts/record_fixtures.py` | New | Record real API responses to `tests/fixtures/` |
| `tests/conftest.py` | Modify | Add `load_fixture()` helper |
| `tests/fixtures/.gitkeep` | New | Directory marker (fixtures themselves are gitignored) |
| `src/ai_job_hunter/fetchers.py` | Modify | Fix Lever/Workable/Ashby |
| `src/ai_job_hunter/services/probe_service.py` | Modify | Add `probe_company_sources_all()` |
| `src/ai_job_hunter/commands/company_sources.py` | Modify | Add `check-all` subcommand |
| `tests/test_fetchers_greenhouse.py` | New | Greenhouse normalizer + fixture tests |
| `tests/test_fetchers_lever.py` | New | Lever normalizer + header test + fixture test |
| `tests/test_fetchers_ashby.py` | New | Ashby normalizer + API-preference test + fixture test |
| `tests/test_fetchers_workable.py` | Modify | Add header test + normalizer test + fixture test |
| `tests/test_fetchers_smartrecruiters.py` | New | SmartRecruiters normalizer + fixture test |
| `tests/test_fetchers_recruitee.py` | New | Recruitee normalizer + fixture test |
| `tests/test_fetchers_teamtailor.py` | New | Teamtailor normalizer + fixture test |

---

## Task 1: Test infrastructure — conftest helper + fixture directory

**Files:**
- Modify: `tests/conftest.py`
- Create: `tests/fixtures/.gitkeep`
- Create: `scripts/` (directory)
- Create: `.gitignore` entry for fixture snapshots

- [ ] **Step 1: Add `load_fixture` to conftest.py**

Replace the entire contents of `tests/conftest.py` with:

```python
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    """Load a raw fixture file from tests/fixtures/ as text."""
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def load_fixture_json(name: str) -> Any:
    """Load a JSON fixture file from tests/fixtures/ and parse it."""
    return json.loads(load_fixture(name))
```

- [ ] **Step 2: Create fixtures directory and gitkeep**

```bash
mkdir -p tests/fixtures
touch tests/fixtures/.gitkeep
```

- [ ] **Step 3: Add fixture snapshots to .gitignore**

Open `.gitignore` and add at the bottom:
```
# ATS response fixtures (recorded locally, not committed)
tests/fixtures/*.json
tests/fixtures/*.html
```

- [ ] **Step 4: Create scripts directory**

```bash
mkdir -p scripts
```

- [ ] **Step 5: Verify conftest imports cleanly**

```bash
uv run pytest tests/conftest.py --collect-only
```

Expected: no errors, 0 items collected.

- [ ] **Step 6: Commit**

```bash
git add tests/conftest.py tests/fixtures/.gitkeep .gitignore
git commit -m "test: add load_fixture helper and fixtures directory"
```

---

## Task 2: Triage script

**Files:**
- Create: `scripts/triage_fetchers.py`

This script reads your real `company_sources` DB, samples up to 10 companies per ATS, probes them concurrently, and prints a health table. It is a diagnostic tool — run it, read the output, but don't commit its results anywhere.

- [ ] **Step 1: Create `scripts/triage_fetchers.py`**

```python
#!/usr/bin/env python3
"""
Triage fetchers: sample up to 10 companies per ATS from DB, probe concurrently, report.

Usage:
    uv run python scripts/triage_fetchers.py
"""
from __future__ import annotations

import os
import random
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_job_hunter.env_utils import load_dotenv  # noqa: E402

load_dotenv()

from ai_job_hunter.db import init_db, list_company_sources  # noqa: E402
from ai_job_hunter.services.probe_service import (  # noqa: E402
    _ATS_PROBES,
    _send_probe_request,
    probe_job_count,
)
from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

SAMPLE_SIZE = 10
STATUS_STYLE = {"OK": "bold green", "EMPTY": "yellow", "ERROR": "bold red", "SKIP": "dim"}


def _resolve_conn():
    turso_url = os.getenv("TURSO_URL", "")
    turso_token = os.getenv("TURSO_AUTH_TOKEN", "")
    db_path = turso_url if turso_url else str(Path.cwd() / "jobs.db")
    return init_db(db_path, turso_token)


def probe_one(row: dict, probe_map: dict) -> dict:
    ats = row["ats_type"]
    slug = row["slug"]
    name = row["name"]
    params = probe_map.get(ats)
    if not params:
        return {"ats": ats, "name": name, "slug": slug, "status": "SKIP", "jobs": 0, "note": "no probe defined"}
    url_tmpl, method, success_test = params
    url = url_tmpl.format(slug=slug)
    try:
        resp = _send_probe_request(method, url, ats)
        if success_test(resp):
            jobs = probe_job_count(resp, ats)
            status = "OK" if jobs else "EMPTY"
            return {"ats": ats, "name": name, "slug": slug, "status": status, "jobs": jobs, "note": ""}
        return {"ats": ats, "name": name, "slug": slug, "status": "ERROR", "jobs": 0,
                "note": f"HTTP {resp.status_code}"}
    except Exception as exc:
        note = f"{type(exc).__name__}: {str(exc)[:60]}"
        return {"ats": ats, "name": name, "slug": slug, "status": "ERROR", "jobs": 0, "note": note}


def main() -> None:
    console = Console()
    conn = _resolve_conn()
    all_rows = list_company_sources(conn, enabled_only=False)
    conn.close()

    if not all_rows:
        console.print("[yellow]No company sources in DB. Run 'uv run ai-job-hunter sources import' first.[/yellow]")
        return

    by_ats: dict[str, list[dict]] = {}
    for row in all_rows:
        by_ats.setdefault(row["ats_type"], []).append(row)

    sample: list[dict] = []
    for ats in sorted(by_ats):
        picked = random.sample(by_ats[ats], min(SAMPLE_SIZE, len(by_ats[ats])))
        sample.extend(picked)

    probe_map = {
        ats_name: (url_tmpl, method, success_test)
        for ats_name, url_tmpl, method, success_test in _ATS_PROBES
    }

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = {ex.submit(probe_one, row, probe_map): row for row in sample}
        for fut in as_completed(futures):
            results.append(fut.result())

    results.sort(key=lambda r: (r["ats"], r["name"].lower()))

    table = Table(title=f"Fetcher triage — {len(sample)} companies sampled", show_header=True)
    table.add_column("ATS", style="cyan")
    table.add_column("Company")
    table.add_column("Slug", style="dim")
    table.add_column("Status")
    table.add_column("Jobs", justify="right")
    table.add_column("Note", style="dim")

    for r in results:
        style = STATUS_STYLE.get(r["status"], "")
        jobs_str = str(r["jobs"]) if r["status"] in ("OK", "EMPTY") else "-"
        table.add_row(
            r["ats"], r["name"], r["slug"],
            f"[{style}]{r['status']}[/{style}]",
            jobs_str, r["note"],
        )

    console.print(table)
    console.print()

    by_ats_results: dict[str, list[dict]] = {}
    for r in results:
        by_ats_results.setdefault(r["ats"], []).append(r)

    for ats in sorted(by_ats_results):
        counts = Counter(r["status"] for r in by_ats_results[ats])
        total = len(by_ats_results[ats])
        console.print(
            f"  [cyan]{ats:<14}[/cyan] "
            f"[green]{counts.get('OK', 0)} OK[/green]  .  "
            f"[yellow]{counts.get('EMPTY', 0)} empty[/yellow]  .  "
            f"[red]{counts.get('ERROR', 0)} errors[/red]  "
            f"of {total} sampled"
        )

    console.print()
    console.print("[dim]HN ('hn_hiring') is not in company_sources — not included above.[/dim]")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the triage script**

```bash
uv run python scripts/triage_fetchers.py
```

Expected: a Rich table showing each sampled company with OK/EMPTY/ERROR status, followed by a per-ATS summary line. Take note of which ATS providers show the most errors — these are your fix targets.

- [ ] **Step 3: Commit**

```bash
git add scripts/triage_fetchers.py
git commit -m "feat: add fetcher triage script (diagnostic, not a test)"
```

---

## Task 3: Fix Workable headers (TDD)

**Files:**
- Modify: `tests/test_fetchers_workable.py`
- Modify: `src/ai_job_hunter/fetchers.py`

The existing `fetch_workable` sends no `Origin` or `Referer` headers. `probe_service._probe_headers` adds them for probes, which is why probes may succeed while the fetcher fails. Fix: add the same headers to the fetcher.

- [ ] **Step 1: Write the failing test**

Open `tests/test_fetchers_workable.py` and add this test at the bottom (keep existing tests intact):

```python
def test_fetch_workable_sends_required_headers(monkeypatch) -> None:
    """fetch_workable must include Origin, Referer, and User-Agent headers."""
    captured: dict = {}

    def fake_post(url: str, json: Any, headers: dict | None = None,
                  timeout: int = 30) -> _FakeResponse:
        captured["headers"] = dict(headers or {})
        return _FakeResponse(
            {"total": 1, "results": [{"shortcode": "X1", "title": "AI Eng"}], "nextPage": ""}
        )

    monkeypatch.setattr("ai_job_hunter.fetchers.requests.post", fake_post)
    fetch_workable("example-co")

    assert "Origin" in captured["headers"], "Missing Origin header"
    assert captured["headers"]["Origin"] == "https://apply.workable.com"
    assert "Referer" in captured["headers"], "Missing Referer header"
    assert captured["headers"]["Referer"] == "https://apply.workable.com/example-co/"
    assert "User-Agent" in captured["headers"], "Missing User-Agent header"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_fetchers_workable.py::test_fetch_workable_sends_required_headers -v
```

Expected: `FAILED — KeyError: 'Origin'` or `AssertionError: Missing Origin header`

- [ ] **Step 3: Fix `fetch_workable` in `fetchers.py`**

In `src/ai_job_hunter/fetchers.py`, replace the `fetch_workable` function:

```python
@retry_with_backoff(max_attempts=3)
def fetch_workable(account_slug: str) -> list[dict[str, Any]]:
    url = f"https://apply.workable.com/api/v3/accounts/{account_slug}/jobs"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "Origin": "https://apply.workable.com",
        "Referer": f"https://apply.workable.com/{account_slug}/",
        "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    }
    jobs: list[dict[str, Any]] = []
    seen_shortcodes: set[str] = set()
    token: str | None = None

    while True:
        payload: dict[str, str] = {}
        if token:
            payload["token"] = token
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json() if resp.content else {}
        page_jobs = data.get("results", []) if isinstance(data, dict) else []

        for job in page_jobs:
            if not isinstance(job, dict):
                continue
            shortcode = str(job.get("shortcode") or "").strip()
            if shortcode and shortcode in seen_shortcodes:
                continue
            if shortcode:
                seen_shortcodes.add(shortcode)
            if shortcode and not job.get("absolute_url"):
                job["absolute_url"] = f"https://apply.workable.com/{account_slug}/j/{shortcode}"
            location = job.get("location")
            if isinstance(location, dict):
                parts = [
                    str(location.get("city") or "").strip(),
                    str(location.get("region") or "").strip(),
                    str(location.get("country") or "").strip(),
                ]
                job["_location_str"] = ", ".join(p for p in parts if p)
            jobs.append(job)

        next_token = str(data.get("nextPage") or "").strip() if isinstance(data, dict) else ""
        if not next_token or next_token == token:
            break
        token = next_token

    return jobs
```

- [ ] **Step 4: Run all Workable tests to verify they pass**

```bash
uv run pytest tests/test_fetchers_workable.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ai_job_hunter/fetchers.py tests/test_fetchers_workable.py
git commit -m "fix: add Origin/Referer/User-Agent headers to fetch_workable"
```

---

## Task 4: Fix Lever User-Agent (TDD)

**Files:**
- Create: `tests/test_fetchers_lever.py`
- Modify: `src/ai_job_hunter/fetchers.py`

`fetch_lever` sends no `User-Agent`. Lever's bot-detection has tightened and returns 403 for bare requests.

- [ ] **Step 1: Create `tests/test_fetchers_lever.py` with the failing test**

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import requests

from ai_job_hunter.fetchers import fetch_lever, normalize_lever


class _FakeResponse:
    def __init__(self, body: Any, status_code: int = 200) -> None:
        if isinstance(body, (dict, list)):
            self._text = json.dumps(body)
            self._json: Any = body
        else:
            self._text = str(body)
            self._json = None
        self.status_code = status_code
        self.content = self._text.encode("utf-8")
        self.url = ""

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self._json if self._json is not None else json.loads(self._text)

    @property
    def text(self) -> str:
        return self._text


_LEVER_RAW = {
    "text": "Machine Learning Engineer",
    "hostedUrl": "https://jobs.lever.co/acme/abc-123",
    "createdAt": 1700000000000,
    "categories": {"location": "Remote, Canada"},
    "descriptionPlain": "Build ML systems.",
    "lists": [],
    "additionalPlain": "",
}


def test_fetch_lever_sends_user_agent(monkeypatch) -> None:
    captured: dict = {}

    def fake_get(url: str, headers: dict | None = None, timeout: int = 30) -> _FakeResponse:
        captured["headers"] = dict(headers or {})
        return _FakeResponse([_LEVER_RAW])

    monkeypatch.setattr("ai_job_hunter.fetchers.requests.get", fake_get)
    result = fetch_lever("test-co")

    assert "User-Agent" in captured["headers"], "Missing User-Agent header"
    assert len(result) == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_fetchers_lever.py::test_fetch_lever_sends_user_agent -v
```

Expected: `FAILED — AssertionError: Missing User-Agent header`

- [ ] **Step 3: Fix `fetch_lever` in `fetchers.py`**

Replace the `fetch_lever` function:

```python
@retry_with_backoff(max_attempts=3)
def fetch_lever(company_name: str) -> list[dict[str, Any]]:
    url = f"https://api.lever.co/v0/postings/{company_name}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_fetchers_lever.py::test_fetch_lever_sends_user_agent -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ai_job_hunter/fetchers.py tests/test_fetchers_lever.py
git commit -m "fix: add User-Agent header to fetch_lever"
```

---

## Task 5: Fix Ashby — prefer JSON API over HTML scraping (TDD)

**Files:**
- Create: `tests/test_fetchers_ashby.py`
- Modify: `src/ai_job_hunter/fetchers.py`

`fetch_ashby` currently scrapes `jobPostings` out of the HTML bundle. Ashby has a stable public JSON API at `https://api.ashbyhq.com/posting-api/job-board/{slug}` that returns the same data without HTML parsing. The fix makes the API primary and keeps HTML scraping as a silent fallback.

- [ ] **Step 1: Create `tests/test_fetchers_ashby.py` with failing test**

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import requests

from ai_job_hunter.fetchers import fetch_ashby, normalize_ashby


class _FakeResponse:
    def __init__(self, body: Any, status_code: int = 200) -> None:
        if isinstance(body, (dict, list)):
            self._text = json.dumps(body)
            self._json: Any = body
        else:
            self._text = str(body)
            self._json = None
        self.status_code = status_code
        self.content = self._text.encode("utf-8")
        self.url = ""

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self._json if self._json is not None else json.loads(self._text)

    @property
    def text(self) -> str:
        return self._text


_API_RESPONSE = {
    "jobPostings": [
        {
            "id": "abc123",
            "title": "ML Engineer",
            "locationName": "Remote, Canada",
            "publishedDate": "2026-01-15",
        }
    ]
}


def test_fetch_ashby_prefers_json_api(monkeypatch) -> None:
    """fetch_ashby should hit api.ashbyhq.com first, not the HTML page."""
    api_urls: list[str] = []
    html_urls: list[str] = []

    def fake_get(url: str, timeout: int = 30) -> _FakeResponse:
        if "api.ashbyhq.com" in url:
            api_urls.append(url)
            return _FakeResponse(_API_RESPONSE)
        html_urls.append(url)
        raise AssertionError(f"HTML fallback should not be called when API succeeds: {url}")

    monkeypatch.setattr("ai_job_hunter.fetchers.requests.get", fake_get)
    result = fetch_ashby("test-org")

    assert api_urls == ["https://api.ashbyhq.com/posting-api/job-board/test-org"]
    assert not html_urls, "HTML endpoint should not be called when API succeeds"
    assert len(result) == 1
    assert result[0]["jobPostingUrl"] == "https://jobs.ashbyhq.com/test-org/abc123"


def test_fetch_ashby_falls_back_to_html_when_api_fails(monkeypatch) -> None:
    """If the JSON API returns non-200, fetch_ashby falls back to HTML scraping."""
    html_content = (
        'window.__data = {"jobPostings": ['
        '{"id": "xyz", "title": "Data Scientist", "locationName": "Vancouver"}'
        ']}'
    )

    def fake_get(url: str, timeout: int = 30) -> _FakeResponse:
        if "api.ashbyhq.com" in url:
            return _FakeResponse({}, status_code=404)
        return _FakeResponse(html_content)

    monkeypatch.setattr("ai_job_hunter.fetchers.requests.get", fake_get)
    result = fetch_ashby("test-org")

    assert any(r.get("title") == "Data Scientist" for r in result)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_fetchers_ashby.py -v
```

Expected: both tests FAIL (current code never hits `api.ashbyhq.com`).

- [ ] **Step 3: Fix `fetch_ashby` in `fetchers.py`**

Replace the `fetch_ashby` function and add a private helper before it:

```python
def _fetch_ashby_via_api(org_slug: str) -> list[dict[str, Any]] | None:
    """Try Ashby's public JSON posting API. Returns None on any failure."""
    url = f"https://api.ashbyhq.com/posting-api/job-board/{org_slug}"
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return [j for j in data.get("jobPostings", []) if isinstance(j, dict)]
    except Exception:
        return None


@retry_with_backoff(max_attempts=3)
def fetch_ashby(org_slug: str) -> list[dict[str, Any]]:
    jobs = _fetch_ashby_via_api(org_slug)
    if jobs is None:
        url = f"https://jobs.ashbyhq.com/{org_slug}"
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        jobs = _extract_json_array_from_html(resp.text, "jobPostings")

    for job in jobs:
        if not isinstance(job, dict):
            continue
        job_id = str(job.get("id") or "").strip()
        if job_id and not job.get("jobPostingUrl"):
            job["jobPostingUrl"] = f"https://jobs.ashbyhq.com/{org_slug}/{job_id}"
    return [j for j in jobs if isinstance(j, dict)]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_fetchers_ashby.py -v
```

Expected: both tests PASS.

- [ ] **Step 5: Run the full test suite to check for regressions**

```bash
uv run pytest tests/ -v --ignore=tests/test_probe_service_live.py
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ai_job_hunter/fetchers.py tests/test_fetchers_ashby.py
git commit -m "fix: replace Ashby HTML scraping with stable JSON API (html fallback retained)"
```

---

## Task 6: Record fixtures

**Files:**
- Create: `scripts/record_fixtures.py`
- Creates at runtime: `tests/fixtures/<ats>_<slug>.(json|html)`

Run this after the fetcher fixes. It finds the first company per ATS that returns ≥ 1 job and saves the raw response.

- [ ] **Step 1: Create `scripts/record_fixtures.py`**

```python
#!/usr/bin/env python3
"""
Record ATS API response fixtures for regression tests.

For each ATS, finds the first enabled company in DB with >= 1 job and saves
the raw HTTP response body to tests/fixtures/<ats>_<slug>.(json|html).

Run after fixing fetchers. Re-run any time to refresh fixtures.

Usage:
    uv run python scripts/record_fixtures.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_job_hunter.env_utils import load_dotenv  # noqa: E402

load_dotenv()

from ai_job_hunter.db import init_db, list_company_sources  # noqa: E402
from ai_job_hunter.services.probe_service import (  # noqa: E402
    _ATS_PROBES,
    _send_probe_request,
    probe_job_count,
)
from rich.console import Console  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
HTML_ATS = {"ashby", "teamtailor"}


def _resolve_conn():
    turso_url = os.getenv("TURSO_URL", "")
    turso_token = os.getenv("TURSO_AUTH_TOKEN", "")
    db_path = turso_url if turso_url else str(Path.cwd() / "jobs.db")
    return init_db(db_path, turso_token)


def main() -> None:
    console = Console()
    FIXTURES_DIR.mkdir(exist_ok=True)

    conn = _resolve_conn()
    all_rows = list_company_sources(conn, enabled_only=True)
    conn.close()

    by_ats: dict[str, list[dict]] = {}
    for row in all_rows:
        by_ats.setdefault(row["ats_type"], []).append(row)

    probe_url_map = {
        ats_name: (url_tmpl, method)
        for ats_name, url_tmpl, method, _ in _ATS_PROBES
    }
    probe_check_map = {
        ats_name: success_test
        for ats_name, _, _, success_test in _ATS_PROBES
    }

    for ats in sorted(by_ats):
        if ats not in probe_url_map:
            console.print(f"[dim]skip {ats} — no probe defined[/dim]")
            continue

        url_tmpl, method = probe_url_map[ats]
        success_test = probe_check_map[ats]
        found = False

        for row in by_ats[ats]:
            slug = row["slug"]
            url = url_tmpl.format(slug=slug)
            try:
                resp = _send_probe_request(method, url, ats)
                if not success_test(resp):
                    continue
                if probe_job_count(resp, ats) == 0:
                    continue
                ext = "html" if ats in HTML_ATS else "json"
                filename = f"{ats}_{slug}.{ext}"
                FIXTURES_DIR.joinpath(filename).write_text(resp.text, encoding="utf-8")
                console.print(
                    f"[green]Recorded[/green]  {filename}"
                    f"  ({probe_job_count(resp, ats)} jobs)  — {row['name']}"
                )
                found = True
                break
            except Exception as exc:
                console.print(f"  [dim]skip {slug}: {type(exc).__name__}: {exc}[/dim]")

        if not found:
            console.print(
                f"[yellow]No OK slug found for {ats}[/yellow] "
                "— fix the fetcher first, then re-run"
            )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the recorder**

```bash
uv run python scripts/record_fixtures.py
```

Expected: one `Recorded` line per ATS (7 total), listing the company name and job count. Any `No OK slug found` lines indicate a fetcher still needs fixing.

- [ ] **Step 3: Verify fixture files were created**

```bash
ls tests/fixtures/
```

Expected: 7 files, e.g. `greenhouse_stripe.json`, `lever_acme.json`, `ashby_cohere.json`, etc. (exact names depend on which company was first in your DB).

- [ ] **Step 4: Commit the recorder script (not the fixture files)**

```bash
git add scripts/record_fixtures.py
git commit -m "feat: add fixture recorder script for ATS regression tests"
```

---

## Task 7: Normalizer unit tests for all ATS

**Files:**
- Modify: `tests/test_fetchers_lever.py` — add normalizer tests
- Modify: `tests/test_fetchers_ashby.py` — add normalizer tests
- Modify: `tests/test_fetchers_workable.py` — add normalizer test
- Create: `tests/test_fetchers_greenhouse.py`
- Create: `tests/test_fetchers_smartrecruiters.py`
- Create: `tests/test_fetchers_recruitee.py`
- Create: `tests/test_fetchers_teamtailor.py`

These tests use hand-crafted raw dicts — no fixtures needed. They verify the `normalize_<ats>()` functions map fields correctly and produce all required keys.

- [ ] **Step 1: Add normalizer tests to `tests/test_fetchers_lever.py`**

Append to the existing file:

```python
# --- normalizer tests ---

def test_normalize_lever_extracts_required_fields() -> None:
    raw = {
        "text": "Machine Learning Engineer",
        "hostedUrl": "https://jobs.lever.co/acme/abc-123",
        "createdAt": 1700000000000,
        "categories": {"location": "Remote, Canada"},
    }
    result = normalize_lever(raw, "Acme")

    assert result["company"] == "Acme"
    assert result["title"] == "Machine Learning Engineer"
    assert result["location"] == "Remote, Canada"
    assert result["url"] == "https://jobs.lever.co/acme/abc-123"
    assert result["ats"] == "lever"
    assert result["posted"] == "2023-11-14"


def test_normalize_lever_handles_missing_categories() -> None:
    raw = {"text": "Data Scientist", "hostedUrl": "https://jobs.lever.co/acme/xyz", "createdAt": None}
    result = normalize_lever(raw, "Acme")

    assert result["location"] == ""
    assert result["posted"] == ""
    assert result["url"].startswith("https://")
```

- [ ] **Step 2: Add normalizer tests to `tests/test_fetchers_ashby.py`**

Append to the existing file:

```python
# --- normalizer tests ---

def test_normalize_ashby_extracts_required_fields() -> None:
    raw = {
        "id": "abc123",
        "title": "Data Scientist",
        "locationName": "Vancouver, BC",
        "publishedDate": "2026-01-15",
        "jobPostingUrl": "https://jobs.ashbyhq.com/acme/abc123",
    }
    result = normalize_ashby(raw, "Acme")

    assert result["company"] == "Acme"
    assert result["title"] == "Data Scientist"
    assert result["location"] == "Vancouver, BC"
    assert result["url"] == "https://jobs.ashbyhq.com/acme/abc123"
    assert result["ats"] == "ashby"
    assert result["posted"] == "2026-01-15"


def test_normalize_ashby_falls_back_to_location_field() -> None:
    raw = {"title": "ML Eng", "location": "Remote", "publishedDate": "2026-01-15",
           "jobPostingUrl": "https://jobs.ashbyhq.com/acme/1"}
    result = normalize_ashby(raw, "Acme")
    assert result["location"] == "Remote"
```

- [ ] **Step 3: Add normalizer test to `tests/test_fetchers_workable.py`**

Append to the existing file (keep existing tests intact):

```python
def test_normalize_workable_extracts_required_fields() -> None:
    from ai_job_hunter.fetchers import normalize_workable
    raw = {
        "shortcode": "ABC123",
        "title": "AI Engineer",
        "_location_str": "Toronto, Ontario, Canada",
        "absolute_url": "https://apply.workable.com/acme/j/ABC123",
        "published": "2026-01-15T10:00:00Z",
    }
    result = normalize_workable(raw, "Acme")

    assert result["company"] == "Acme"
    assert result["title"] == "AI Engineer"
    assert result["location"] == "Toronto, Ontario, Canada"
    assert result["url"] == "https://apply.workable.com/acme/j/ABC123"
    assert result["ats"] == "workable"
    assert result["posted"] == "2026-01-15"
```

- [ ] **Step 4: Create `tests/test_fetchers_greenhouse.py`**

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import requests

from ai_job_hunter.fetchers import fetch_greenhouse, normalize_greenhouse


class _FakeResponse:
    def __init__(self, body: Any, status_code: int = 200) -> None:
        if isinstance(body, (dict, list)):
            self._text = json.dumps(body)
            self._json: Any = body
        else:
            self._text = str(body)
            self._json = None
        self.status_code = status_code
        self.content = self._text.encode("utf-8")
        self.url = ""

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self._json if self._json is not None else json.loads(self._text)

    @property
    def text(self) -> str:
        return self._text


# --- normalizer tests ---

def test_normalize_greenhouse_extracts_required_fields() -> None:
    raw = {
        "id": 12345,
        "title": "Machine Learning Engineer",
        "location": {"name": "Remote, Canada"},
        "absolute_url": "https://boards.greenhouse.io/acme/jobs/12345",
        "updated_at": "2026-01-15T10:00:00Z",
    }
    result = normalize_greenhouse(raw, "Acme")

    assert result["company"] == "Acme"
    assert result["title"] == "Machine Learning Engineer"
    assert result["location"] == "Remote, Canada"
    assert result["url"] == "https://boards.greenhouse.io/acme/jobs/12345"
    assert result["ats"] == "greenhouse"
    assert result["posted"] == "2026-01-15"


def test_normalize_greenhouse_handles_missing_location() -> None:
    raw = {
        "title": "Data Scientist",
        "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
        "updated_at": None,
    }
    result = normalize_greenhouse(raw, "Acme")

    assert result["location"] == ""
    assert result["posted"] == ""
```

- [ ] **Step 5: Create `tests/test_fetchers_smartrecruiters.py`**

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import requests

from ai_job_hunter.fetchers import fetch_smartrecruiters, normalize_smartrecruiters


class _FakeResponse:
    def __init__(self, body: Any, status_code: int = 200) -> None:
        if isinstance(body, (dict, list)):
            self._text = json.dumps(body)
            self._json: Any = body
        else:
            self._text = str(body)
            self._json = None
        self.status_code = status_code
        self.content = self._text.encode("utf-8")
        self.url = ""

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self._json if self._json is not None else json.loads(self._text)

    @property
    def text(self) -> str:
        return self._text


# --- normalizer tests ---

def test_normalize_smartrecruiters_non_remote() -> None:
    raw = {
        "id": "sr-123",
        "name": "ML Platform Engineer",
        "location": {"city": "Toronto", "region": "Ontario", "country": "Canada", "remote": False},
        "releasedDate": "2026-01-15",
        "ref": "https://careers.smartrecruiters.com/Acme/sr-123",
    }
    result = normalize_smartrecruiters(raw, "Acme")

    assert result["company"] == "Acme"
    assert result["title"] == "ML Platform Engineer"
    assert result["location"] == "Toronto, Ontario, Canada"
    assert result["url"] == "https://careers.smartrecruiters.com/Acme/sr-123"
    assert result["ats"] == "smartrecruiters"
    assert result["posted"] == "2026-01-15"


def test_normalize_smartrecruiters_remote_prepended() -> None:
    raw = {
        "id": "sr-456",
        "name": "Data Scientist",
        "location": {"city": "Toronto", "country": "Canada", "remote": True},
        "releasedDate": "2026-01-15",
        "ref": "https://careers.smartrecruiters.com/Acme/sr-456",
    }
    result = normalize_smartrecruiters(raw, "Acme")

    assert result["location"].startswith("Remote")
    assert "Toronto" in result["location"]
```

- [ ] **Step 6: Create `tests/test_fetchers_recruitee.py`**

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import requests

from ai_job_hunter.fetchers import fetch_recruitee, normalize_recruitee


class _FakeResponse:
    def __init__(self, body: Any, status_code: int = 200) -> None:
        if isinstance(body, (dict, list)):
            self._text = json.dumps(body)
            self._json: Any = body
        else:
            self._text = str(body)
            self._json = None
        self.status_code = status_code
        self.content = self._text.encode("utf-8")
        self.url = ""

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self._json if self._json is not None else json.loads(self._text)

    @property
    def text(self) -> str:
        return self._text


# --- normalizer tests ---

def test_normalize_recruitee_builds_url_from_slug() -> None:
    raw = {
        "id": 123,
        "title": "NLP Engineer",
        "slug": "nlp-engineer-123",
        "company_slug": "acme",
        "location": {"city": "Remote", "country": "Canada"},
        "created_at": "2026-01-15T10:00:00Z",
    }
    result = normalize_recruitee(raw, "Acme")

    assert result["company"] == "Acme"
    assert result["title"] == "NLP Engineer"
    assert "Remote" in result["location"]
    assert result["url"] == "https://acme.recruitee.com/o/nlp-engineer-123"
    assert result["ats"] == "recruitee"
    assert result["posted"] == "2026-01-15"


def test_normalize_recruitee_string_location() -> None:
    raw = {
        "title": "Data Engineer",
        "slug": "data-eng-1",
        "company_slug": "acme",
        "location": "Vancouver, BC, Canada",
        "created_at": "2026-01-15T10:00:00Z",
    }
    result = normalize_recruitee(raw, "Acme")

    assert result["location"] == "Vancouver, BC, Canada"
```

- [ ] **Step 7: Create `tests/test_fetchers_teamtailor.py`**

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import requests

from ai_job_hunter.fetchers import normalize_teamtailor


class _FakeResponse:
    def __init__(self, body: Any, status_code: int = 200) -> None:
        if isinstance(body, (dict, list)):
            self._text = json.dumps(body)
            self._json: Any = body
        else:
            self._text = str(body)
            self._json = None
        self.status_code = status_code
        self.content = self._text.encode("utf-8")
        self.url = ""

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self._json if self._json is not None else json.loads(self._text)

    @property
    def text(self) -> str:
        return self._text


# --- normalizer tests ---

def test_normalize_teamtailor_extracts_required_fields() -> None:
    raw = {
        "@type": "JobPosting",
        "title": "AI Research Scientist",
        "url": "https://careers.acme.com/jobs/123-ai-research-scientist",
        "datePosted": "2026-01-15",
        "location": "Remote, Canada",
    }
    result = normalize_teamtailor(raw, "Acme")

    assert result["company"] == "Acme"
    assert result["title"] == "AI Research Scientist"
    assert result["location"] == "Remote, Canada"
    assert result["url"] == "https://careers.acme.com/jobs/123-ai-research-scientist"
    assert result["ats"] == "teamtailor"
    assert result["posted"] == "2026-01-15"


def test_normalize_teamtailor_handles_empty_location() -> None:
    raw = {
        "title": "ML Eng",
        "url": "https://careers.acme.com/jobs/1",
        "datePosted": "2026-01-15",
    }
    result = normalize_teamtailor(raw, "Acme")
    assert result["location"] == ""
```

- [ ] **Step 8: Run all normalizer tests**

```bash
uv run pytest tests/test_fetchers_greenhouse.py tests/test_fetchers_lever.py \
    tests/test_fetchers_ashby.py tests/test_fetchers_workable.py \
    tests/test_fetchers_smartrecruiters.py tests/test_fetchers_recruitee.py \
    tests/test_fetchers_teamtailor.py -v
```

Expected: all normalizer tests PASS.

- [ ] **Step 9: Commit**

```bash
git add tests/test_fetchers_greenhouse.py tests/test_fetchers_lever.py \
    tests/test_fetchers_ashby.py tests/test_fetchers_workable.py \
    tests/test_fetchers_smartrecruiters.py tests/test_fetchers_recruitee.py \
    tests/test_fetchers_teamtailor.py
git commit -m "test: add normalizer unit tests for all ATS fetchers"
```

---

## Task 8: Fixture-based integration tests for all ATS

**Files:**
- Modify: `tests/test_fetchers_greenhouse.py`
- Modify: `tests/test_fetchers_lever.py`
- Modify: `tests/test_fetchers_ashby.py`
- Modify: `tests/test_fetchers_workable.py`
- Modify: `tests/test_fetchers_smartrecruiters.py`
- Modify: `tests/test_fetchers_recruitee.py`
- Modify: `tests/test_fetchers_teamtailor.py`

These tests load fixture files recorded in Task 6. They skip automatically if no fixture exists (so CI passes before you record). Each test: monkeypatches requests, calls the fetcher, asserts non-empty list + required normalizer keys.

- [ ] **Step 1: Add fixture test to `tests/test_fetchers_greenhouse.py`**

Append to the file:

```python
# --- fixture integration test ---

def test_fetch_greenhouse_fixture(monkeypatch) -> None:
    fixture_files = list((Path(__file__).parent / "fixtures").glob("greenhouse_*.json"))
    if not fixture_files:
        pytest.skip("No greenhouse fixture — run scripts/record_fixtures.py first")
    data = json.loads(fixture_files[0].read_text(encoding="utf-8"))
    slug = fixture_files[0].stem.split("_", 1)[1]

    def fake_get(url: str, timeout: int = 30) -> _FakeResponse:
        return _FakeResponse(data)

    monkeypatch.setattr("ai_job_hunter.fetchers.requests.get", fake_get)
    results = fetch_greenhouse(slug)

    assert len(results) > 0, "Expected at least one job from fixture"
    normalized = [normalize_greenhouse(r, "FixtureTest") for r in results]
    for n in normalized:
        assert all(k in n for k in ("company", "title", "location", "url", "posted", "ats"))
        assert n["url"].startswith("https://")
        assert n["ats"] == "greenhouse"
```

- [ ] **Step 2: Add fixture test to `tests/test_fetchers_lever.py`**

Append to the file:

```python
# --- fixture integration test ---

def test_fetch_lever_fixture(monkeypatch) -> None:
    fixture_files = list((Path(__file__).parent / "fixtures").glob("lever_*.json"))
    if not fixture_files:
        pytest.skip("No lever fixture — run scripts/record_fixtures.py first")
    data = json.loads(fixture_files[0].read_text(encoding="utf-8"))
    slug = fixture_files[0].stem.split("_", 1)[1]

    def fake_get(url: str, headers: dict | None = None, timeout: int = 30) -> _FakeResponse:
        return _FakeResponse(data)

    monkeypatch.setattr("ai_job_hunter.fetchers.requests.get", fake_get)
    results = fetch_lever(slug)

    assert len(results) > 0, "Expected at least one job from fixture"
    normalized = [normalize_lever(r, "FixtureTest") for r in results]
    for n in normalized:
        assert all(k in n for k in ("company", "title", "location", "url", "posted", "ats"))
        assert n["url"].startswith("https://")
        assert n["ats"] == "lever"
```

- [ ] **Step 3: Add fixture test to `tests/test_fetchers_ashby.py`**

Append to the file:

```python
# --- fixture integration test ---

def test_fetch_ashby_fixture(monkeypatch) -> None:
    fixture_files = list((Path(__file__).parent / "fixtures").glob("ashby_*.html"))
    if not fixture_files:
        pytest.skip("No ashby fixture — run scripts/record_fixtures.py first")
    fixture_text = fixture_files[0].read_text(encoding="utf-8")
    slug = fixture_files[0].stem.split("_", 1)[1]

    def fake_get(url: str, timeout: int = 30) -> _FakeResponse:
        if "api.ashbyhq.com" in url:
            # Return non-200 to force HTML fallback (fixture is HTML)
            return _FakeResponse({}, status_code=404)
        return _FakeResponse(fixture_text)

    monkeypatch.setattr("ai_job_hunter.fetchers.requests.get", fake_get)
    results = fetch_ashby(slug)

    assert len(results) > 0, "Expected at least one job from fixture"
    normalized = [normalize_ashby(r, "FixtureTest") for r in results]
    for n in normalized:
        assert all(k in n for k in ("company", "title", "location", "url", "posted", "ats"))
        assert n["url"].startswith("https://")
        assert n["ats"] == "ashby"
```

- [ ] **Step 4: Add fixture test to `tests/test_fetchers_workable.py`**

Append to the file:

```python
def test_fetch_workable_fixture(monkeypatch) -> None:
    from ai_job_hunter.fetchers import normalize_workable
    fixture_files = list((Path(__file__).parent / "fixtures").glob("workable_*.json"))
    if not fixture_files:
        pytest.skip("No workable fixture — run scripts/record_fixtures.py first")
    data = json.loads(fixture_files[0].read_text(encoding="utf-8"))
    slug = fixture_files[0].stem.split("_", 1)[1]

    # Workable uses POST — return the fixture, then empty page to stop pagination
    call_count = [0]

    def fake_post(url: str, json: Any, headers: Any = None, timeout: int = 30) -> _FakeResponse:
        call_count[0] += 1
        if call_count[0] == 1:
            payload = {**data, "nextPage": ""}  # strip pagination to avoid loop
            return _FakeResponse(payload)
        return _FakeResponse({"results": [], "nextPage": ""})

    monkeypatch.setattr("ai_job_hunter.fetchers.requests.post", fake_post)
    results = fetch_workable(slug)

    assert len(results) > 0, "Expected at least one job from fixture"
    normalized = [normalize_workable(r, "FixtureTest") for r in results]
    for n in normalized:
        assert all(k in n for k in ("company", "title", "location", "url", "posted", "ats"))
        assert n["ats"] == "workable"
```

Add these two lines near the top of `tests/test_fetchers_workable.py`, directly after the existing `from typing import Any` import:
```python
import json
from pathlib import Path
```

- [ ] **Step 5: Add fixture test to `tests/test_fetchers_smartrecruiters.py`**

Append to the file:

```python
# --- fixture integration test ---

def test_fetch_smartrecruiters_fixture(monkeypatch) -> None:
    fixture_files = list((Path(__file__).parent / "fixtures").glob("smartrecruiters_*.json"))
    if not fixture_files:
        pytest.skip("No smartrecruiters fixture — run scripts/record_fixtures.py first")
    data = json.loads(fixture_files[0].read_text(encoding="utf-8"))
    slug = fixture_files[0].stem.split("_", 1)[1]

    def fake_get(url: str, params: Any = None, timeout: int = 30) -> _FakeResponse:
        return _FakeResponse(data)

    monkeypatch.setattr("ai_job_hunter.fetchers.requests.get", fake_get)
    results = fetch_smartrecruiters(slug)

    assert len(results) > 0, "Expected at least one job from fixture"
    normalized = [normalize_smartrecruiters(r, "FixtureTest") for r in results]
    for n in normalized:
        assert all(k in n for k in ("company", "title", "location", "url", "posted", "ats"))
        assert n["url"].startswith("https://")
        assert n["ats"] == "smartrecruiters"
```

- [ ] **Step 6: Add fixture test to `tests/test_fetchers_recruitee.py`**

Append to the file:

```python
# --- fixture integration test ---

def test_fetch_recruitee_fixture(monkeypatch) -> None:
    fixture_files = list((Path(__file__).parent / "fixtures").glob("recruitee_*.json"))
    if not fixture_files:
        pytest.skip("No recruitee fixture — run scripts/record_fixtures.py first")
    data = json.loads(fixture_files[0].read_text(encoding="utf-8"))
    slug = fixture_files[0].stem.split("_", 1)[1]

    def fake_get(url: str, timeout: int = 30) -> _FakeResponse:
        return _FakeResponse(data)

    monkeypatch.setattr("ai_job_hunter.fetchers.requests.get", fake_get)
    results = fetch_recruitee(slug)

    assert len(results) > 0, "Expected at least one job from fixture"
    normalized = [normalize_recruitee(r, "FixtureTest") for r in results]
    for n in normalized:
        assert all(k in n for k in ("company", "title", "location", "url", "posted", "ats"))
        assert n["ats"] == "recruitee"
```

- [ ] **Step 7: Add fixture test to `tests/test_fetchers_teamtailor.py`**

Append to the file:

```python
# --- fixture integration test ---

def test_fetch_teamtailor_fixture(monkeypatch) -> None:
    from ai_job_hunter.fetchers import fetch_teamtailor, _extract_teamtailor_job_urls
    fixture_files = list((Path(__file__).parent / "fixtures").glob("teamtailor_*.html"))
    if not fixture_files:
        pytest.skip("No teamtailor fixture — run scripts/record_fixtures.py first")
    list_html = fixture_files[0].read_text(encoding="utf-8")
    slug = fixture_files[0].stem.split("_", 1)[1]
    base_url = f"https://{slug}.teamtailor.com/jobs"
    job_urls = _extract_teamtailor_job_urls(base_url, list_html)
    if not job_urls:
        pytest.skip("No job URLs in teamtailor fixture — re-record with a company that has active listings")

    # Minimal LD+JSON detail page to satisfy _extract_teamtailor_job_posting
    def fake_get(url: str, timeout: int = 30) -> _FakeResponse:
        if url == base_url:
            return _FakeResponse(list_html)
        detail_html = (
            '<script type="application/ld+json">'
            '{"@type":"JobPosting","title":"Software Engineer",'
            f'"url":"{url}","datePosted":"2026-01-15",'
            '"jobLocation":[{"@type":"Place","address":{"addressLocality":"Remote"}}]}'
            "</script>"
        )
        return _FakeResponse(detail_html)

    monkeypatch.setattr("ai_job_hunter.fetchers.requests.get", fake_get)
    results = fetch_teamtailor(slug)

    assert len(results) > 0, "Expected at least one job"
    normalized = [normalize_teamtailor(r, "FixtureTest") for r in results]
    for n in normalized:
        assert all(k in n for k in ("company", "title", "location", "url", "posted", "ats"))
        assert n["ats"] == "teamtailor"
```

- [ ] **Step 8: Run all tests (fixture tests will skip if not yet recorded)**

```bash
uv run pytest tests/test_fetchers_greenhouse.py tests/test_fetchers_lever.py \
    tests/test_fetchers_ashby.py tests/test_fetchers_workable.py \
    tests/test_fetchers_smartrecruiters.py tests/test_fetchers_recruitee.py \
    tests/test_fetchers_teamtailor.py -v
```

Expected: normalizer tests PASS, fixture tests either PASS (if fixtures recorded) or SKIP.

- [ ] **Step 9: If fixtures were recorded in Task 6, run again and verify all fixture tests PASS**

```bash
uv run pytest tests/test_fetchers_greenhouse.py tests/test_fetchers_lever.py \
    tests/test_fetchers_ashby.py tests/test_fetchers_workable.py \
    tests/test_fetchers_smartrecruiters.py tests/test_fetchers_recruitee.py \
    tests/test_fetchers_teamtailor.py -v --no-header
```

Expected: no SKIP, no FAIL.

- [ ] **Step 10: Run the full suite to catch regressions**

```bash
uv run pytest tests/ -v --ignore=tests/test_probe_service_live.py
```

Expected: all PASS.

- [ ] **Step 11: Commit**

```bash
git add tests/test_fetchers_greenhouse.py tests/test_fetchers_lever.py \
    tests/test_fetchers_ashby.py tests/test_fetchers_workable.py \
    tests/test_fetchers_smartrecruiters.py tests/test_fetchers_recruitee.py \
    tests/test_fetchers_teamtailor.py
git commit -m "test: add fixture-based integration tests for all ATS fetchers"
```

---

## Task 9: `probe_company_sources_all()` + `sources check-all` CLI

**Files:**
- Modify: `src/ai_job_hunter/services/probe_service.py`
- Modify: `src/ai_job_hunter/commands/company_sources.py`

`probe_company_sources_all()` takes rows from `company_sources`, probes each concurrently by its specific ATS, and returns status dicts. The CLI command calls it and renders the results as a Rich table.

- [ ] **Step 1: Write the failing test for `probe_company_sources_all`**

Create `tests/test_probe_service_check_all.py`:

```python
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from ai_job_hunter.services.probe_service import probe_company_sources_all

_ROWS = [
    {"id": 1, "name": "Acme", "ats_type": "greenhouse", "slug": "acme",
     "ats_url": "https://boards-api.greenhouse.io/v1/boards/acme/jobs", "enabled": 1},
    {"id": 2, "name": "Beta", "ats_type": "lever", "slug": "beta",
     "ats_url": "https://api.lever.co/v0/postings/beta", "enabled": 1},
    {"id": 3, "name": "Gamma", "ats_type": "greenhouse", "slug": "gamma",
     "ats_url": "https://boards-api.greenhouse.io/v1/boards/gamma/jobs", "enabled": 0},
]


def _make_ok_response(jobs: int = 3) -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {"jobs": [{"id": i} for i in range(jobs)]}
    r.text = '{"jobs": []}'
    r.url = ""
    return r


def test_probe_company_sources_all_returns_one_result_per_enabled_row() -> None:
    with patch("ai_job_hunter.services.probe_service._send_probe_request") as mock_send:
        mock_send.return_value = _make_ok_response(3)
        results = probe_company_sources_all(_ROWS)

    assert len(results) == 2  # disabled row excluded by default
    assert all("probe_status" in r for r in results)
    assert all("probe_jobs" in r for r in results)


def test_probe_company_sources_all_include_disabled() -> None:
    with patch("ai_job_hunter.services.probe_service._send_probe_request") as mock_send:
        mock_send.return_value = _make_ok_response(1)
        results = probe_company_sources_all(_ROWS, include_disabled=True)

    assert len(results) == 3


def test_probe_company_sources_all_ats_filter() -> None:
    with patch("ai_job_hunter.services.probe_service._send_probe_request") as mock_send:
        mock_send.return_value = _make_ok_response(2)
        results = probe_company_sources_all(_ROWS, ats_filter="greenhouse")

    assert len(results) == 1  # only enabled greenhouse row
    assert results[0]["name"] == "Acme"


def test_probe_company_sources_all_marks_errors() -> None:
    import requests

    def raise_error(method: str, url: str, ats_name: str):
        raise requests.ConnectionError("timeout")

    with patch("ai_job_hunter.services.probe_service._send_probe_request", side_effect=raise_error):
        results = probe_company_sources_all(_ROWS)

    assert all(r["probe_status"] == "ERROR" for r in results)
    assert all("ConnectionError" in r["probe_note"] for r in results)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_probe_service_check_all.py -v
```

Expected: `FAILED — ImportError: cannot import name 'probe_company_sources_all'`

- [ ] **Step 3: Add `probe_company_sources_all` to `probe_service.py`**

Append to `src/ai_job_hunter/services/probe_service.py`:

```python
def probe_company_sources_all(
    rows: list[dict],
    *,
    include_disabled: bool = False,
    ats_filter: str | None = None,
) -> list[dict]:
    """Probe company_sources rows concurrently. Returns a status dict per probed row.

    Each result dict is the original row plus three keys:
      probe_status: "OK" | "EMPTY" | "ERROR"
      probe_jobs:   int  (0 on ERROR)
      probe_note:   str  (empty on OK/EMPTY, error message on ERROR)
    """
    probe_map = {
        ats_name: (url_tmpl, method, success_test)
        for ats_name, url_tmpl, method, success_test in _ATS_PROBES
    }

    filtered = [
        r for r in rows
        if (include_disabled or r.get("enabled"))
        and (ats_filter is None or r.get("ats_type") == ats_filter)
        and r.get("ats_type") in probe_map
    ]

    def _probe_one(row: dict) -> dict:
        ats = row["ats_type"]
        slug = row["slug"]
        url_tmpl, method, success_test = probe_map[ats]
        url = url_tmpl.format(slug=slug)
        try:
            resp = _send_probe_request(method, url, ats)
            if success_test(resp):
                jobs = probe_job_count(resp, ats)
                status = "OK" if jobs else "EMPTY"
                return {**row, "probe_status": status, "probe_jobs": jobs, "probe_note": ""}
            return {**row, "probe_status": "ERROR", "probe_jobs": 0,
                    "probe_note": f"HTTP {resp.status_code}"}
        except Exception as exc:
            note = f"{type(exc).__name__}: {str(exc)[:60]}"
            return {**row, "probe_status": "ERROR", "probe_jobs": 0, "probe_note": note}

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = {ex.submit(_probe_one, row): row for row in filtered}
        for fut in as_completed(futures):
            results.append(fut.result())

    results.sort(key=lambda r: (r.get("ats_type", ""), r.get("name", "").lower()))
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_probe_service_check_all.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Add `check-all` to the sources CLI**

In `src/ai_job_hunter/commands/company_sources.py`, update the `register` function to add the new subcommand:

```python
def register(subparsers) -> None:
    parser = subparsers.add_parser("sources", help="Manage company source registry")
    parser.add_argument("--db", default=None, metavar="PATH", help="Local SQLite path (default: jobs.db). Ignored if TURSO_URL is set.")
    sub = parser.add_subparsers(dest="sources_cmd", required=True)

    sub.add_parser("list", help="List company sources")

    p_en = sub.add_parser("enable", help="Enable one source by id or slug")
    p_en.add_argument("target")

    p_dis = sub.add_parser("disable", help="Disable one source by id or slug")
    p_dis.add_argument("target")

    p_chk = sub.add_parser("check", help="Probe ATS boards for a slug")
    p_chk.add_argument("slug")

    p_imp = sub.add_parser("import", help="Import sources from GitHub lists")
    p_imp.add_argument("--dry-run", action="store_true")

    p_all = sub.add_parser("check-all", help="Probe all configured sources and report coverage")
    p_all.add_argument(
        "--include-disabled",
        action="store_true",
        dest="include_disabled",
        help="Also probe disabled sources",
    )
    p_all.add_argument(
        "--ats",
        dest="ats_filter",
        metavar="NAME",
        help="Filter to one ATS provider (e.g. lever)",
    )
```

Then add the `check-all` branch at the top of the `run` function, before the existing `if args.sources_cmd == "check":` block:

```python
def run(args) -> None:
    if args.sources_cmd == "check-all":
        from collections import Counter

        from ai_job_hunter.db import list_company_sources as _list_sources
        from ai_job_hunter.services.probe_service import probe_company_sources_all
        from ai_job_hunter.services.scrape_service import safe_text

        db_url, db_token = _resolve_db(args.db)
        conn = init_db(db_url, db_token)
        all_rows = _list_sources(conn, enabled_only=False)
        conn.close()

        ats_filter = getattr(args, "ats_filter", None)
        include_disabled = getattr(args, "include_disabled", False)
        results = probe_company_sources_all(
            all_rows,
            include_disabled=include_disabled,
            ats_filter=ats_filter,
        )

        console = Console()
        if not results:
            console.print("[yellow]No sources matched the filter.[/yellow]")
            return

        table = Table(
            title=f"Source health check — {len(results)} probed",
            show_header=True,
        )
        table.add_column("Company")
        table.add_column("ATS", style="cyan")
        table.add_column("Status")
        table.add_column("Jobs", justify="right")
        table.add_column("URL", style="dim", no_wrap=False)
        table.add_column("Note", style="dim")

        _STATUS_STYLE = {"OK": "bold green", "EMPTY": "yellow", "ERROR": "bold red"}
        for r in results:
            style = _STATUS_STYLE.get(r["probe_status"], "")
            jobs_str = str(r["probe_jobs"]) if r["probe_status"] in ("OK", "EMPTY") else "-"
            table.add_row(
                safe_text(r["name"]),
                r["ats_type"],
                f"[{style}]{r['probe_status']}[/{style}]",
                jobs_str,
                r.get("ats_url", ""),
                r.get("probe_note", ""),
            )
        console.print(table)
        console.print()

        by_ats: dict[str, list[dict]] = {}
        for r in results:
            by_ats.setdefault(r["ats_type"], []).append(r)

        for ats in sorted(by_ats):
            counts = Counter(r["probe_status"] for r in by_ats[ats])
            total = len(by_ats[ats])
            console.print(
                f"  [cyan]{ats:<14}[/cyan] "
                f"[green]{counts.get('OK', 0)} OK[/green]  .  "
                f"[yellow]{counts.get('EMPTY', 0)} empty[/yellow]  .  "
                f"[red]{counts.get('ERROR', 0)} errors[/red]  "
                f"of {total}"
            )
        return

    if args.sources_cmd == "check":
        # ... (existing check code unchanged)
```

- [ ] **Step 6: Smoke-test the CLI**

```bash
uv run ai-job-hunter sources check-all --ats greenhouse
```

Expected: a Rich table listing greenhouse companies with OK/EMPTY/ERROR status, followed by a summary line.

- [ ] **Step 7: Run the full test suite**

```bash
uv run pytest tests/ -v --ignore=tests/test_probe_service_live.py
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add src/ai_job_hunter/services/probe_service.py \
    src/ai_job_hunter/commands/company_sources.py \
    tests/test_probe_service_check_all.py
git commit -m "feat: add sources check-all CLI and probe_company_sources_all()"
```

---

## Self-Review Checklist

- [ ] Spec §1 (Triage) → Task 2: triage script samples 10/ATS, prints table + summary ✓
- [ ] Spec §2 (Fix strategy) → Tasks 3/4/5: Workable headers, Lever User-Agent, Ashby JSON API ✓
- [ ] Spec §2 Path 2 (wrong slugs) → exposed by triage script output, manual fix in DB via `sources enable/disable` or `sources import` ✓
- [ ] Spec §3 (fixture recording) → Task 6: `record_fixtures.py` picks first OK slug per ATS ✓
- [ ] Spec §3 (regression tests) → Tasks 7+8: normalizer unit tests + fixture integration tests ✓
- [ ] Spec §4 (check-all CLI) → Task 9: `sources check-all` with `--include-disabled` and `--ats` flags ✓
- [ ] No `--save` flag (out of scope per spec) ✓
- [ ] No schema changes ✓
- [ ] `companies.yaml` not referenced (file does not exist; slugs are DB-only) ✓
