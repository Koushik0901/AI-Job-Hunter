from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from db import init_db, save_enrichment, save_jobs
from dashboard.backend import repository


class ProfileAndRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self.db_path = handle.name
        self.conn = init_db(self.db_path)

    def tearDown(self) -> None:
        try:
            self.conn.close()
        finally:
            if os.path.exists(self.db_path):
                os.unlink(self.db_path)

    def test_profile_round_trip(self) -> None:
        saved = repository.save_profile(
            self.conn,
            {
                "years_experience": 2,
                "skills": ["Python", "SQL"],
                "target_role_families": ["ml engineer"],
                "requires_visa_sponsorship": False,
            },
        )
        loaded = repository.get_profile(self.conn)
        self.assertEqual(saved["years_experience"], 2)
        self.assertEqual(loaded["skills"], ["Python", "SQL"])
        self.assertEqual(loaded["target_role_families"], ["ml engineer"])
        self.assertFalse(loaded["requires_visa_sponsorship"])
        self.assertIsNotNone(loaded["updated_at"])

    def test_match_desc_sort_orders_best_fit_first(self) -> None:
        repository.save_profile(
            self.conn,
            {
                "years_experience": 1,
                "skills": ["python", "pytorch", "sql"],
                "target_role_families": ["ml engineer"],
                "requires_visa_sponsorship": False,
            },
        )

        jobs = [
            {
                "url": "https://example.com/junior",
                "company": "Acme",
                "title": "Junior ML Engineer",
                "location": "Remote",
                "posted": "2026-02-20",
                "ats": "greenhouse",
                "description": "x",
            },
            {
                "url": "https://example.com/senior",
                "company": "Acme",
                "title": "Senior ML Engineer",
                "location": "Remote",
                "posted": "2026-02-21",
                "ats": "greenhouse",
                "description": "x",
            },
        ]
        save_jobs(self.conn, jobs)

        save_enrichment(
            self.conn,
            "https://example.com/junior",
            {
                "seniority": "junior",
                "role_family": "ml engineer",
                "years_exp_min": 2,
                "required_skills": '["python", "pytorch"]',
                "preferred_skills": '["sql"]',
                "formatted_description": "Requirements\n- Python\n- PyTorch",
                "visa_sponsorship": "yes",
                "enrichment_status": "ok",
            },
        )
        save_enrichment(
            self.conn,
            "https://example.com/senior",
            {
                "seniority": "senior",
                "role_family": "ml engineer",
                "years_exp_min": 8,
                "required_skills": '["python", "pytorch"]',
                "preferred_skills": '["sql"]',
                "visa_sponsorship": "yes",
                "enrichment_status": "ok",
            },
        )

        items, total = repository.list_jobs(
            self.conn,
            status=None,
            q=None,
            ats=None,
            company=None,
            posted_after=None,
            sort="match_desc",
            limit=50,
            offset=0,
        )
        self.assertEqual(total, 2)
        self.assertEqual(items[0]["url"], "https://example.com/junior")
        self.assertGreaterEqual(int(items[0]["match_score"]), int(items[1]["match_score"]))

        detail = repository.get_job_detail(self.conn, "https://example.com/junior")
        self.assertIsNotNone(detail)
        self.assertEqual(
            detail["enrichment"]["formatted_description"],
            "Requirements\n- Python\n- PyTorch",
        )


if __name__ == "__main__":
    unittest.main()
