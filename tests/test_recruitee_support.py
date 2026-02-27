from __future__ import annotations

import sys
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fetchers import normalize_recruitee
from services.company_source_service import parse_companies_from_markdown, slug_to_ats_url
from services.probe_service import probe_job_count
from services.scrape_service import extract_slug


class RecruiteeSupportTests(unittest.TestCase):
    def test_slug_to_ats_url_supports_recruitee(self) -> None:
        self.assertEqual(
            slug_to_ats_url("acme", "recruitee"),
            "https://acme.recruitee.com/api/offers",
        )

    def test_extract_slug_for_recruitee(self) -> None:
        self.assertEqual(
            extract_slug("https://acme.recruitee.com/api/offers", "recruitee"),
            "acme",
        )

    def test_parse_companies_from_markdown_detects_recruitee(self) -> None:
        sample = """
        - [Acme AI](https://acme.recruitee.com/o/ml-engineer)
        - [Beta Labs](https://jobs.lever.co/betalabs/123)
        """
        parsed = parse_companies_from_markdown(sample)
        self.assertIn(("Acme AI", "recruitee", "acme"), parsed)
        self.assertIn(("Beta Labs", "lever", "betalabs"), parsed)

    def test_normalize_recruitee_maps_core_fields(self) -> None:
        raw = {
            "id": "12345",
            "title": "Machine Learning Engineer",
            "careers_url": "https://acme.recruitee.com/o/ml-engineer",
            "location": {"city": "Toronto", "country": "Canada"},
            "created_at": "2026-02-20T12:00:00Z",
            "description": "<p>Build models.</p>",
        }
        normalized = normalize_recruitee(raw, "Acme")
        self.assertEqual(normalized["company"], "Acme")
        self.assertEqual(normalized["ats"], "recruitee")
        self.assertEqual(normalized["url"], "https://acme.recruitee.com/o/ml-engineer")
        self.assertEqual(normalized["posted"], "2026-02-20")
        self.assertIn("Build models.", normalized["description"])

    def test_probe_job_count_recruitee(self) -> None:
        class FakeResp:
            def json(self) -> dict:
                return {"offers": [{"id": 1}, {"id": 2}, {"id": 3}]}

        self.assertEqual(probe_job_count(FakeResp(), "recruitee"), 3)


if __name__ == "__main__":
    unittest.main()

