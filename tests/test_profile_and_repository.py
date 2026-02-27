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
            posted_before=None,
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

    def test_funnel_analytics_counts_and_conversions(self) -> None:
        jobs = [
            {
                "url": "https://example.com/backlog",
                "company": "A",
                "title": "Role 1",
                "location": "Remote",
                "posted": "2026-02-01",
                "ats": "greenhouse",
                "description": "x",
            },
            {
                "url": "https://example.com/staging",
                "company": "B",
                "title": "Role 2",
                "location": "Remote",
                "posted": "2026-02-02",
                "ats": "greenhouse",
                "description": "x",
            },
            {
                "url": "https://example.com/applied",
                "company": "C",
                "title": "Role 3",
                "location": "Remote",
                "posted": "2026-02-03",
                "ats": "lever",
                "description": "x",
            },
            {
                "url": "https://example.com/interview",
                "company": "D",
                "title": "Role 4",
                "location": "Remote",
                "posted": "2026-02-04",
                "ats": "lever",
                "description": "x",
            },
            {
                "url": "https://example.com/offer",
                "company": "E",
                "title": "Role 5",
                "location": "Remote",
                "posted": "2026-02-05",
                "ats": "ashby",
                "description": "x",
            },
        ]
        save_jobs(self.conn, jobs)

        repository.upsert_tracking(self.conn, "https://example.com/staging", {"status": "staging"})
        repository.upsert_tracking(self.conn, "https://example.com/applied", {"status": "applied"})
        repository.upsert_tracking(self.conn, "https://example.com/interview", {"status": "interviewing"})
        repository.upsert_tracking(self.conn, "https://example.com/offer", {"status": "offer"})

        result = repository.get_funnel_analytics(
            self.conn,
            from_date="2026-02-01",
            to_date="2026-02-28",
            status_scope="pipeline",
            applications_goal_target=5,
            interviews_goal_target=2,
        )

        counts = {item["status"]: item["count"] for item in result["stages"]}
        self.assertEqual(counts["not_applied"], 1)
        self.assertEqual(counts["staging"], 1)
        self.assertEqual(counts["applied"], 1)
        self.assertEqual(counts["interviewing"], 1)
        self.assertEqual(counts["offer"], 1)

        self.assertEqual(result["conversions"]["backlog_to_staging"], 1.0)
        self.assertEqual(result["conversions"]["staging_to_applied"], 1.0)
        self.assertEqual(result["conversions"]["applied_to_interviewing"], 1.0)
        self.assertEqual(result["conversions"]["interviewing_to_offer"], 1.0)
        self.assertEqual(result["conversions"]["backlog_to_offer"], 1.0)
        self.assertIn("deltas", result)
        self.assertIn("weekly_goals", result)
        self.assertIn("alerts", result)
        self.assertIn("cohorts", result)
        self.assertIn("source_quality", result)
        self.assertIn("forecast", result)
        self.assertEqual(result["weekly_goals"]["applications"]["target"], 5)
        self.assertEqual(result["weekly_goals"]["interviews"]["target"], 2)
        self.assertGreaterEqual(len(result["cohorts"]), 1)
        self.assertIn("ats", result["source_quality"])
        self.assertIn("companies", result["source_quality"])
        self.assertEqual(len(result["forecast"]["windows"]), 2)

    def test_manual_job_creation_and_suppression_hides_job(self) -> None:
        created = repository.create_manual_job(
            self.conn,
            {
                "url": "https://example.com/manual-role",
                "company": "Manual Co",
                "title": "Applied ML Engineer",
                "location": "Toronto, Canada",
                "posted": "2026-02-10",
                "ats": "manual",
                "description": "Build ML systems",
            },
        )
        self.assertEqual(created["url"], "https://example.com/manual-role")
        self.assertEqual(created["title"], "Applied ML Engineer")

        repository.suppress_job(self.conn, url="https://example.com/manual-role", reason="Not in target region")
        items, total = repository.list_jobs(
            self.conn,
            status=None,
            q=None,
            ats=None,
            company=None,
            posted_after=None,
            posted_before=None,
            sort="match_desc",
            limit=50,
            offset=0,
        )
        self.assertEqual(total, 0)
        self.assertEqual(items, [])

    def test_save_jobs_skips_suppressed_urls(self) -> None:
        repository.suppress_job(self.conn, url="https://example.com/suppressed", reason="Not relevant")
        new_count, updated_count, new_jobs = save_jobs(
            self.conn,
            [
                {
                    "url": "https://example.com/suppressed",
                    "company": "Suppressed Co",
                    "title": "Role",
                    "location": "Remote",
                    "posted": "2026-02-12",
                    "ats": "greenhouse",
                    "description": "x",
                }
            ],
        )
        self.assertEqual(new_count, 0)
        self.assertEqual(updated_count, 0)
        self.assertEqual(new_jobs, [])

    def test_unsuppress_restores_visibility(self) -> None:
        save_jobs(
            self.conn,
            [
                {
                    "url": "https://example.com/revive",
                    "company": "Revive Co",
                    "title": "ML Engineer",
                    "location": "Remote",
                    "posted": "2026-02-12",
                    "ats": "greenhouse",
                    "description": "x",
                }
            ],
        )
        repository.suppress_job(self.conn, url="https://example.com/revive", reason="temp")
        active = repository.list_active_suppressions(self.conn, limit=50)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["url"], "https://example.com/revive")

        changed = repository.unsuppress_job(self.conn, url="https://example.com/revive")
        self.assertEqual(changed, 1)
        active_after = repository.list_active_suppressions(self.conn, limit=50)
        self.assertEqual(active_after, [])

        items, total = repository.list_jobs(
            self.conn,
            status=None,
            q=None,
            ats=None,
            company=None,
            posted_after=None,
            posted_before=None,
            sort="match_desc",
            limit=50,
            offset=0,
        )
        self.assertEqual(total, 1)
        self.assertEqual(items[0]["url"], "https://example.com/revive")


if __name__ == "__main__":
    unittest.main()
