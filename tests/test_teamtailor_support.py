from __future__ import annotations

import sys
from pathlib import Path
import unittest

import pytest
import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fetchers import fetch_teamtailor, normalize_teamtailor
from services.company_registry_service import extract_slug_from_careers_url
from services.company_source_service import parse_companies_from_markdown, slug_to_ats_url
from services.probe_service import probe_job_count
from services.scrape_service import extract_slug


class _FakeResponse:
    def __init__(self, *, text: str = "", status_code: int = 200, url: str = "") -> None:
        self.text = text
        self.status_code = status_code
        self.url = url

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class TeamtailorSupportTests(unittest.TestCase):
    def test_slug_to_ats_url_supports_teamtailor(self) -> None:
        self.assertEqual(
            slug_to_ats_url("acme", "teamtailor"),
            "https://acme.teamtailor.com/jobs",
        )

    def test_extract_slug_for_teamtailor(self) -> None:
        self.assertEqual(
            extract_slug("https://acme.teamtailor.com/jobs", "teamtailor"),
            "acme",
        )

    def test_extract_slug_from_careers_url_detects_teamtailor(self) -> None:
        self.assertEqual(
            extract_slug_from_careers_url("https://acme.teamtailor.com/jobs/123-machine-learning-engineer"),
            ("teamtailor", "acme"),
        )

    def test_parse_companies_from_markdown_detects_teamtailor(self) -> None:
        sample = """
        - [Acme AI](https://acme.teamtailor.com/jobs/123-machine-learning-engineer)
        - [Beta Labs](https://jobs.lever.co/betalabs/123)
        """
        parsed = parse_companies_from_markdown(sample)
        self.assertIn(("Acme AI", "teamtailor", "acme"), parsed)
        self.assertIn(("Beta Labs", "lever", "betalabs"), parsed)

    def test_normalize_teamtailor_maps_core_fields(self) -> None:
        raw = {
            "title": "Machine Learning Engineer",
            "location": "Toronto (Remote)",
            "url": "https://acme.teamtailor.com/jobs/123-machine-learning-engineer",
            "datePosted": "2026-03-01",
            "description": "<p>Build models.</p>",
        }
        normalized = normalize_teamtailor(raw, "Acme")
        self.assertEqual(normalized["company"], "Acme")
        self.assertEqual(normalized["ats"], "teamtailor")
        self.assertEqual(normalized["posted"], "2026-03-01")
        self.assertEqual(normalized["url"], "https://acme.teamtailor.com/jobs/123-machine-learning-engineer")
        self.assertIn("Build models.", normalized["description"])

    def test_probe_job_count_teamtailor(self) -> None:
        resp = _FakeResponse(
            url="https://acme.teamtailor.com/jobs",
            text="""
            <a href="https://acme.teamtailor.com/jobs/123-machine-learning-engineer">ML Engineer</a>
            <a href="/jobs/456-data-scientist">Data Scientist</a>
            <a href="/jobs/456-data-scientist">Duplicate</a>
            """,
        )
        self.assertEqual(probe_job_count(resp, "teamtailor"), 2)


def test_fetch_teamtailor_collects_job_details(monkeypatch) -> None:
    list_html = """
    <html><body>
      <a href="https://acme.teamtailor.com/jobs/123-machine-learning-engineer">Machine Learning Engineer</a>
      <a href="/jobs/456-data-scientist">Data Scientist</a>
    </body></html>
    """
    detail_pages = {
        "https://acme.teamtailor.com/jobs/123-machine-learning-engineer": """
        <script type="application/ld+json">
        {
          "@context": "http://schema.org/",
          "@type": "JobPosting",
          "title": "Machine Learning Engineer",
          "description": "<p>Build models.</p>",
          "datePosted": "2026-03-01",
          "url": "https://acme.teamtailor.com/jobs/123-machine-learning-engineer",
          "jobLocation": [{"@type": "Place", "address": {"addressLocality": "Toronto", "addressCountry": "Canada"}}]
        }
        </script>
        <dt>Remote status</dt><dd>Remote</dd>
        """,
        "https://acme.teamtailor.com/jobs/456-data-scientist": """
        <script type="application/ld+json">
        {
          "@context": "http://schema.org/",
          "@type": "JobPosting",
          "title": "Data Scientist",
          "description": "<p>Analyze data.</p>",
          "datePosted": "2026-03-02",
          "url": "https://acme.teamtailor.com/jobs/456-data-scientist"
        }
        </script>
        <dt>Location</dt><dd>Montreal</dd>
        <dt>Remote status</dt><dd>Hybrid</dd>
        """,
    }

    def fake_get(url: str, timeout: int) -> _FakeResponse:
        assert timeout == 30
        if url == "https://acme.teamtailor.com/jobs":
            return _FakeResponse(text=list_html, url=url)
        if url in detail_pages:
            return _FakeResponse(text=detail_pages[url], url=url)
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("fetchers.requests.get", fake_get)

    jobs = fetch_teamtailor("acme")

    assert [job["title"] for job in jobs] == ["Machine Learning Engineer", "Data Scientist"]
    assert jobs[0]["location"] == "Toronto, Canada (Remote)"
    assert jobs[1]["location"] == "Montreal (Hybrid)"
    assert jobs[0]["description"].startswith("<p>Build models.")
    assert jobs[1]["datePosted"] == "2026-03-02"


def test_fetch_teamtailor_supports_job_posting_nested_in_graph(monkeypatch) -> None:
    list_html = """
    <html><body>
      <a href="https://acme.teamtailor.com/jobs/789-platform-ml-engineer">Platform ML Engineer</a>
    </body></html>
    """
    detail_html = """
    <script type="application/ld+json">
    {
      "@context": "http://schema.org/",
      "@graph": [
        {
          "@type": "WebPage",
          "name": "Careers"
        },
        {
          "@type": "JobPosting",
          "title": "Platform ML Engineer",
          "description": "<p>Build platform tooling.</p>",
          "datePosted": "2026-03-03",
          "url": "https://acme.teamtailor.com/jobs/789-platform-ml-engineer"
        }
      ]
    }
    </script>
    <dt>Location</dt><dd>Calgary</dd>
    """

    def fake_get(url: str, timeout: int) -> _FakeResponse:
        assert timeout == 30
        if url == "https://acme.teamtailor.com/jobs":
            return _FakeResponse(text=list_html, url=url)
        if url == "https://acme.teamtailor.com/jobs/789-platform-ml-engineer":
            return _FakeResponse(text=detail_html, url=url)
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("fetchers.requests.get", fake_get)

    jobs = fetch_teamtailor("acme")

    assert [job["title"] for job in jobs] == ["Platform ML Engineer"]
    assert jobs[0]["datePosted"] == "2026-03-03"
    assert jobs[0]["location"] == "Calgary"


if __name__ == "__main__":
    unittest.main()
