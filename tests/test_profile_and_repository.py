from __future__ import annotations

import os
import tempfile
import unittest

from ai_job_hunter.db import init_db, save_enrichment, save_jobs
from ai_job_hunter.dashboard.backend import repository


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

    def _job_id(self, url: str) -> str:
        job_id = repository.get_job_id_by_url(self.conn, url)
        self.assertIsNotNone(job_id)
        return str(job_id)

    def test_profile_round_trip(self) -> None:
        saved = repository.save_profile(
            self.conn,
            {
                "years_experience": 2,
                "skills": ["Python", "SQL"],
                "desired_job_titles": ["ML Engineer"],
                "target_role_families": ["ml engineer"],
                "requires_visa_sponsorship": False,
            },
        )
        loaded = repository.get_profile(self.conn)
        self.assertEqual(saved["years_experience"], 2)
        self.assertEqual(loaded["skills"], ["Python", "SQL"])
        self.assertEqual(loaded["desired_job_titles"], ["ML Engineer"])
        self.assertEqual(loaded["target_role_families"], ["ml engineer"])
        self.assertFalse(loaded["requires_visa_sponsorship"])
        self.assertEqual(loaded["score_version"], 1)

    def test_match_desc_sort_orders_best_fit_first(self) -> None:
        repository.save_profile(
            self.conn,
            {
                "years_experience": 1,
                "skills": ["python", "pytorch", "sql"],
                "desired_job_titles": ["Junior ML Engineer"],
                "target_role_families": ["ml engineer"],
                "requires_visa_sponsorship": False,
            },
        )
        save_jobs(
            self.conn,
            [
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
            ],
        )
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
        self.assertTrue(bool(items[0]["desired_title_match"]))

        detail = repository.get_job_detail(self.conn, self._job_id("https://example.com/junior"))
        self.assertIsNotNone(detail)
        self.assertEqual(detail["enrichment"]["formatted_description"], "Requirements\n- Python\n- PyTorch")
        self.assertFalse(bool(detail["match_meta"]["stale"]))
        self.assertEqual(detail["match"]["raw_score"], detail["fit_score"])

    def test_recompute_match_scores_refresh_current_profile_version(self) -> None:
        repository.save_profile(
            self.conn,
            {
                "years_experience": 2,
                "skills": ["python", "sql"],
                "target_role_families": ["ml engineer"],
                "requires_visa_sponsorship": False,
            },
        )
        save_jobs(
            self.conn,
            [
                {
                    "url": "https://example.com/scored",
                    "company": "Acme",
                    "title": "Junior ML Engineer",
                    "location": "Remote",
                    "posted": "2026-02-20",
                    "ats": "greenhouse",
                    "description": "x",
                }
            ],
        )
        save_enrichment(
            self.conn,
            "https://example.com/scored",
            {
                "seniority": "junior",
                "role_family": "ml engineer",
                "required_skills": '["python"]',
                "preferred_skills": '["sql"]',
                "visa_sponsorship": "yes",
                "enrichment_status": "ok",
            },
        )
        recomputed = repository.recompute_match_scores(self.conn, urls=["https://example.com/scored"])
        self.assertEqual(recomputed, 1)

        detail = repository.get_job_detail(self.conn, self._job_id("https://example.com/scored"))
        self.assertIsNotNone(detail)
        self.assertIsNotNone(detail["match"])
        self.assertFalse(bool(detail["match_meta"]["stale"]))

        next_version = repository.bump_profile_score_version(self.conn)
        self.assertGreaterEqual(next_version, 2)
        refreshed_detail = repository.get_job_detail(self.conn, self._job_id("https://example.com/scored"))
        self.assertTrue(bool(refreshed_detail["match_meta"]["stale"]))

        refreshed = repository.recompute_match_scores(
            self.conn, urls=["https://example.com/scored"]
        )
        self.assertEqual(refreshed, 1)
        rescored_detail = repository.get_job_detail(
            self.conn, self._job_id("https://example.com/scored")
        )
        self.assertFalse(bool(rescored_detail["match_meta"]["stale"]))
        self.assertEqual(int(refreshed_detail["match_meta"]["profile_version"]), next_version)
        self.assertEqual(refreshed_detail["match"]["raw_score"], refreshed_detail["fit_score"])

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
        self.assertIsNone(created["enrichment"])
        self.assertIsNone(created["match"])
        self.assertIsNone(created["recommendation"])
        self.assertEqual(created["recommendation_reasons"], [])
        self.assertFalse(created["duplicate_detected"])
        self.assertIsNone(created["duplicate_of_job_id"])
        self.assertIsNone(created["duplicate_match_kind"])

        repository.suppress_job(self.conn, job_id=created["id"], reason="Not in target region")
        with self.assertRaises(ValueError):
            repository.create_manual_job(
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

    def test_manual_job_duplicate_detection_reuses_existing_job(self) -> None:
        first = repository.create_manual_job(
            self.conn,
            {
                "url": "https://example.com/manual-duplicate-a",
                "company": "Duplicate Co",
                "title": "Applied ML Engineer",
                "location": "Toronto, Canada",
                "posted": "2026-02-10",
                "ats": "manual",
                "description": "Build ML systems",
            },
        )
        second = repository.create_manual_job(
            self.conn,
            {
                "url": "https://example.com/manual-duplicate-b",
                "company": "Duplicate Co",
                "title": "Applied ML Engineer",
                "location": "Toronto, Canada",
                "posted": "2026-02-28",
                "ats": "manual",
                "description": "Build ML systems",
            },
        )

        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["duplicate_detected"])
        self.assertEqual(second["duplicate_of_job_id"], first["id"])
        self.assertEqual(second["duplicate_match_kind"], "content")

    def test_manual_job_duplicate_detection_requires_location_for_content_match(self) -> None:
        first = repository.create_manual_job(
            self.conn,
            {
                "url": "https://example.com/manual-location-a",
                "company": "Duplicate Co",
                "title": "Applied ML Engineer",
                "location": "",
                "posted": "2026-02-10",
                "ats": "manual",
                "description": "Build ML systems",
            },
        )
        second = repository.create_manual_job(
            self.conn,
            {
                "url": "https://example.com/manual-location-b",
                "company": "Duplicate Co",
                "title": "Applied ML Engineer",
                "location": "",
                "posted": "2026-02-28",
                "ats": "manual",
                "description": "Build ML systems",
            },
        )

        self.assertNotEqual(first["id"], second["id"])
        self.assertFalse(second["duplicate_detected"])
        self.assertIsNone(second["duplicate_of_job_id"])
        self.assertIsNone(second["duplicate_match_kind"])

    def test_manual_job_duplicate_detection_respects_exact_url(self) -> None:
        first = repository.create_manual_job(
            self.conn,
            {
                "url": "https://example.com/manual-exact",
                "company": "Exact Co",
                "title": "Platform Engineer",
                "location": "Remote",
                "posted": "2026-03-02",
                "ats": "manual",
                "description": "Build platform systems",
            },
        )
        second = repository.create_manual_job(
            self.conn,
            {
                "url": "https://example.com/manual-exact",
                "company": "Exact Co",
                "title": "Platform Engineer",
                "location": "Remote",
                "posted": "2026-03-02",
                "ats": "manual",
                "description": "Build platform systems",
            },
        )

        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["duplicate_detected"])
        self.assertEqual(second["duplicate_of_job_id"], first["id"])
        self.assertEqual(second["duplicate_match_kind"], "url")

    def test_tracking_pin_persists_across_status_changes(self) -> None:
        save_jobs(
            self.conn,
            [
                {
                    "url": "https://example.com/pinned-role",
                    "company": "Pinned Co",
                    "title": "ML Engineer",
                    "location": "Remote",
                    "posted": "2026-03-02",
                    "ats": "greenhouse",
                    "description": "x",
                }
            ],
        )
        job_id = self._job_id("https://example.com/pinned-role")

        repository.upsert_tracking(self.conn, job_id, {"status": "staging", "pinned": True})
        staged = repository.get_job_detail(self.conn, job_id)
        self.assertIsNotNone(staged)
        self.assertTrue(bool(staged["pinned"]))
        self.assertEqual(staged["tracking_status"], "staging")

        repository.upsert_tracking(self.conn, job_id, {"status": "applied"})
        applied = repository.get_job_detail(self.conn, job_id)
        self.assertIsNotNone(applied)
        self.assertTrue(bool(applied["pinned"]))
        self.assertEqual(applied["tracking_status"], "applied")

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
        revive_job_id = self._job_id("https://example.com/revive")
        repository.suppress_job(self.conn, job_id=revive_job_id, reason="temp")
        active = repository.list_active_suppressions(self.conn, limit=50)
        self.assertEqual(len(active), 1)

        changed = repository.unsuppress_job(self.conn, job_id=revive_job_id)
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

    def test_manual_decision_override_shapes_recommendation(self) -> None:
        repository.save_profile(
            self.conn,
            {
                "years_experience": 4,
                "skills": ["python", "sql", "pytorch"],
                "desired_job_titles": ["ML Engineer"],
                "target_role_families": ["ml engineer"],
                "requires_visa_sponsorship": False,
            },
        )
        save_jobs(
            self.conn,
            [
                {
                    "url": "https://example.com/override-me",
                    "company": "Acme",
                    "title": "ML Engineer",
                    "location": "Remote",
                    "posted": "2026-03-20",
                    "ats": "greenhouse",
                    "description": "x",
                }
            ],
        )
        save_enrichment(
            self.conn,
            "https://example.com/override-me",
            {
                "role_family": "ml engineer",
                "required_skills": '["python", "sql"]',
                "preferred_skills": '["pytorch"]',
                "visa_sponsorship": "yes",
                "enrichment_status": "ok",
            },
        )
        job_id = self._job_id("https://example.com/override-me")
        before = repository.get_job_detail(self.conn, job_id)
        self.assertIsNotNone(before)
        self.assertIn(before["recommendation"], {"apply_now", "review_manually", "hold", "archive"})

        repository.save_job_decision(self.conn, job_id=job_id, recommendation="archive", note="Too senior")
        after = repository.get_job_detail(self.conn, job_id)
        self.assertEqual(after["recommendation"], "archive")
        self.assertTrue(any("Manual override" in reason for reason in after["recommendation_reasons"]))
        self.assertEqual(after["guidance_mode"], "evaluation")
        self.assertEqual(after["guidance_title"], "Archive candidate")
        self.assertEqual(after["health_label"], "archive")
        self.assertIn("Archive it", after["next_best_action"])

    def test_stage_guidance_moves_later_roles_to_narrative_mode(self) -> None:
        repository.save_profile(
            self.conn,
            {
                "years_experience": 6,
                "skills": ["python", "sql", "pytorch"],
                "desired_job_titles": ["ML Engineer"],
                "target_role_families": ["ml engineer"],
                "requires_visa_sponsorship": False,
            },
        )
        save_jobs(
            self.conn,
            [
                {
                    "url": "https://example.com/stage-guidance",
                    "company": "Acme",
                    "title": "ML Engineer",
                    "location": "Remote",
                    "posted": "2026-03-29",
                    "ats": "greenhouse",
                    "description": "x",
                }
            ],
        )
        save_enrichment(
            self.conn,
            "https://example.com/stage-guidance",
            {
                "role_family": "ml engineer",
                "required_skills": '["python", "sql"]',
                "preferred_skills": '["pytorch"]',
                "visa_sponsorship": "yes",
                "enrichment_status": "ok",
            },
        )
        job_id = self._job_id("https://example.com/stage-guidance")
        repository.upsert_tracking(self.conn, job_id, {"status": "applied", "applied_at": "2026-03-29"})
        applied = repository.get_job_detail(self.conn, job_id)
        self.assertIsNotNone(applied)
        self.assertEqual(applied["guidance_mode"], "stage_narrative")
        self.assertEqual(applied["guidance_title"], "Application in flight")
        self.assertEqual(applied["health_label"], "in_process")
        self.assertTrue(any("application" in reason.lower() for reason in applied["guidance_reasons"]))

        repository.upsert_tracking(self.conn, job_id, {"status": "interviewing"})
        interviewing = repository.get_job_detail(self.conn, job_id)
        self.assertIsNotNone(interviewing)
        self.assertEqual(interviewing["guidance_mode"], "stage_narrative")
        self.assertEqual(interviewing["guidance_title"], "Interview loop active")
        self.assertEqual(interviewing["health_label"], "active")
        self.assertTrue(any("interview" in reason.lower() for reason in interviewing["guidance_reasons"]))

        repository.upsert_tracking(self.conn, job_id, {"status": "offer"})
        offer = repository.get_job_detail(self.conn, job_id)
        self.assertIsNotNone(offer)
        self.assertEqual(offer["guidance_mode"], "stage_narrative")
        self.assertEqual(offer["guidance_title"], "Offer stage")
        self.assertEqual(offer["health_label"], "decision_time")
        self.assertIn("Review the terms", offer["next_best_action"])

    def test_follow_up_action_generation_after_application_event(self) -> None:
        repository.save_profile(
            self.conn,
            {
                "years_experience": 3,
                "skills": ["python", "sql", "mlops"],
                "desired_job_titles": ["ML Engineer"],
                "target_role_families": ["ml engineer"],
                "requires_visa_sponsorship": False,
            },
        )
        save_jobs(
            self.conn,
            [
                {
                    "url": "https://example.com/brief-role",
                    "company": "Brief Co",
                    "title": "ML Engineer",
                    "location": "Remote",
                    "posted": "2026-03-22",
                    "ats": "greenhouse",
                    "description": "x",
                }
            ],
        )
        save_enrichment(
            self.conn,
            "https://example.com/brief-role",
            {
                "role_family": "ml engineer",
                "required_skills": '["python", "sql"]',
                "preferred_skills": '["mlops"]',
                "formatted_description": "Need Python and SQL",
                "visa_sponsorship": "yes",
                "enrichment_status": "ok",
            },
        )
        job_id = self._job_id("https://example.com/brief-role")

        repository.create_event(
            self.conn,
            job_id,
            {
                "event_type": "application_submitted",
                "title": "Applied",
                "body": "Submitted from test",
                "event_at": "2026-03-23",
            },
        )
        queue = repository.refresh_action_queue(self.conn)
        self.assertTrue(any(item["job_id"] == job_id and item["action_type"] == "follow_up" for item in queue))


if __name__ == "__main__":
    unittest.main()
