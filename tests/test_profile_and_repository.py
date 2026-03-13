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
from dashboard.backend.main import _validate_resume_baseline_json


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
        self.assertIsNotNone(loaded["updated_at"])

    def test_resume_profile_isolated_from_scoring_profile_updates(self) -> None:
        baseline = {
            "basics": {"name": "Candidate", "summary": "Summary text"},
            "skills": [{"name": "Rust"}],
        }
        saved_resume = repository.save_resume_profile_data(
            self.conn,
            {
                "baseline_resume_json": baseline,
                "template_id": "classic",
            },
        )
        self.assertEqual(saved_resume["baseline_resume_json"], baseline)
        repository.save_profile(
            self.conn,
            {
                "years_experience": 4,
                "skills": ["Python", "SQL", "Rust"],
                "target_role_families": ["ml engineer"],
                "requires_visa_sponsorship": False,
            },
        )
        loaded_resume = repository.get_resume_profile_data(self.conn)
        self.assertEqual(loaded_resume["baseline_resume_json"], baseline)
        self.assertEqual(loaded_resume["template_id"], "classic")

    def test_starter_artifacts_create_if_missing_and_emit_progress(self) -> None:
        save_jobs(
            self.conn,
            [
                {
                    "url": "https://example.com/starter-job",
                    "company": "Acme",
                    "title": "ML Engineer",
                    "location": "Remote",
                    "posted": "2026-02-20",
                    "ats": "greenhouse",
                    "description": "x",
                }
            ],
        )
        job_id = self._job_id("https://example.com/starter-job")
        repository.upsert_tracking(self.conn, job_id, {"status": "staging"})
        progress: list[tuple[str, int]] = []

        repository.ensure_starter_artifacts_for_job_with_progress(
            self.conn,
            job_id,
            lambda stage, percent: progress.append((stage, percent)),
        )
        repository.ensure_starter_artifacts_for_job_with_progress(
            self.conn,
            job_id,
            lambda stage, percent: progress.append((stage, percent)),
        )

        artifacts = repository.list_job_artifacts(self.conn, job_id)
        self.assertEqual(len(artifacts), 2)
        self.assertIn(("done", 100), progress)
        self.assertTrue(any(stage == "creating_resume" for stage, _ in progress))
        self.assertTrue(any(stage == "creating_cover_letter" for stage, _ in progress))

    def test_starter_artifacts_bootstrap_clean_blank_templates(self) -> None:
        save_jobs(
            self.conn,
            [
                {
                    "url": "https://example.com/blank-start",
                    "company": "Example Company",
                    "title": "Platform Engineer",
                    "location": "Remote",
                    "posted": "2026-03-01",
                    "ats": "greenhouse",
                    "description": "x",
                }
            ],
        )
        job_id = self._job_id("https://example.com/blank-start")
        repository.upsert_tracking(self.conn, job_id, {"status": "staging"})

        repository.ensure_starter_artifacts_for_job(self.conn, job_id)
        artifacts = repository.list_job_artifacts(self.conn, job_id)
        by_type = {str(item["artifact_type"]): item for item in artifacts}

        resume_text = str(((by_type["resume"].get("active_version") or {}).get("content_text")) or "")
        cover_letter_text = str(((by_type["cover_letter"].get("active_version") or {}).get("content_text")) or "")

        self.assertIn("Your Name", resume_text)
        self.assertIn("Hiring Manager", cover_letter_text)
        self.assertNotIn("Koushik", resume_text)
        self.assertNotIn("koushik", cover_letter_text.lower())

    def test_resume_baseline_schema_validation(self) -> None:
        _validate_resume_baseline_json(
            {
                "basics": {"name": "Candidate", "label": "Engineer"},
                "skills": [{"name": "Python"}, "SQL"],
                "work": [],
                "education": [],
            }
        )
        with self.assertRaises(ValueError):
            _validate_resume_baseline_json({"skills": [{"foo": "bar"}]})

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
        self.assertTrue(bool(items[0]["desired_title_match"]))
        self.assertFalse(bool(items[1]["desired_title_match"]))

        detail = repository.get_job_detail(self.conn, self._job_id("https://example.com/junior"))
        self.assertIsNotNone(detail)
        self.assertEqual(
            detail["enrichment"]["formatted_description"],
            "Requirements\n- Python\n- PyTorch",
        )
        self.assertIsNotNone(detail.get("match_meta"))
        self.assertFalse(bool(detail["match_meta"]["stale"]))
        self.assertTrue(bool(detail["desired_title_match"]))

    def test_match_desc_with_pagination_still_ranks_after_missing_score_compute(self) -> None:
        repository.save_profile(
            self.conn,
            {
                "years_experience": 2,
                "skills": ["python", "pytorch", "sql"],
                "target_role_families": ["ml engineer"],
                "requires_visa_sponsorship": False,
            },
        )
        save_jobs(
            self.conn,
            [
                {
                    "url": "https://example.com/high-fit-older",
                    "company": "Acme",
                    "title": "ML Engineer",
                    "location": "Remote",
                    "posted": "2026-02-01",
                    "ats": "greenhouse",
                    "description": "x",
                },
                {
                    "url": "https://example.com/low-fit-newer",
                    "company": "Acme",
                    "title": "Senior Backend Engineer",
                    "location": "Remote",
                    "posted": "2026-02-20",
                    "ats": "greenhouse",
                    "description": "x",
                },
            ],
        )
        save_enrichment(
            self.conn,
            "https://example.com/high-fit-older",
            {
                "seniority": "mid",
                "role_family": "ml engineer",
                "required_skills": '["python", "pytorch"]',
                "preferred_skills": '["sql"]',
                "visa_sponsorship": "yes",
                "enrichment_status": "ok",
            },
        )
        save_enrichment(
            self.conn,
            "https://example.com/low-fit-newer",
            {
                "seniority": "senior",
                "role_family": "data engineer",
                "required_skills": '["java", "kafka"]',
                "preferred_skills": '["go"]',
                "visa_sponsorship": "yes",
                "enrichment_status": "ok",
            },
        )

        top_page, total = repository.list_jobs(
            self.conn,
            status=None,
            q=None,
            ats=None,
            company=None,
            posted_after=None,
            posted_before=None,
            sort="match_desc",
            limit=1,
            offset=0,
        )
        self.assertEqual(total, 2)
        self.assertEqual(len(top_page), 1)
        self.assertEqual(top_page[0]["url"], "https://example.com/high-fit-older")

    def test_recompute_match_scores_and_profile_version_staleness(self) -> None:
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
        scored_job_id = self._job_id("https://example.com/scored")
        detail = repository.get_job_detail(self.conn, scored_job_id)
        self.assertIsNotNone(detail)
        self.assertIsNotNone(detail["match"])
        self.assertFalse(bool(detail["match_meta"]["stale"]))

        next_version = repository.bump_profile_score_version(self.conn)
        self.assertGreaterEqual(next_version, 2)
        stale_detail = repository.get_job_detail(self.conn, scored_job_id)
        self.assertTrue(bool(stale_detail["match_meta"]["stale"]))

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

        repository.upsert_tracking(self.conn, self._job_id("https://example.com/staging"), {"status": "staging"})
        repository.upsert_tracking(self.conn, self._job_id("https://example.com/applied"), {"status": "applied"})
        repository.upsert_tracking(self.conn, self._job_id("https://example.com/interview"), {"status": "interviewing"})
        repository.upsert_tracking(self.conn, self._job_id("https://example.com/offer"), {"status": "offer"})

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

        repository.suppress_job(self.conn, job_id=created["id"], reason="Not in target region")
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
        created = repository.create_manual_job(
            self.conn,
            {
                "url": "https://example.com/suppressed",
                "company": "Suppressed Co",
                "title": "Role",
                "location": "Remote",
                "posted": "2026-02-12",
                "ats": "manual",
                "description": "x",
            },
        )
        repository.suppress_job(self.conn, job_id=created["id"], reason="Not relevant")
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

    def test_artifact_starter_creation_is_idempotent(self) -> None:
        save_jobs(
            self.conn,
            [
                {
                    "url": "https://example.com/artifact-role",
                    "company": "Artifact Co",
                    "title": "ML Engineer",
                    "location": "Remote",
                    "posted": "2026-02-12",
                    "ats": "greenhouse",
                    "description": "Build and ship ML models",
                }
            ],
        )
        artifact_role_id = self._job_id("https://example.com/artifact-role")
        created = repository.ensure_starter_artifacts_for_job(self.conn, artifact_role_id)
        self.assertEqual(len(created), 2)

        rows = repository.list_job_artifacts(self.conn, artifact_role_id)
        self.assertEqual(len(rows), 2)
        self.assertSetEqual({row["artifact_type"] for row in rows}, {"resume", "cover_letter"})
        for row in rows:
            self.assertIsNotNone(row["active_version"])
            self.assertEqual(row["active_version"]["label"], "draft")
            self.assertEqual(row["active_version"]["version"], 1)

        created_again = repository.ensure_starter_artifacts_for_job(self.conn, artifact_role_id)
        self.assertEqual(created_again, [])
        rows_again = repository.list_job_artifacts(self.conn, artifact_role_id)
        self.assertEqual(len(rows_again), 2)

    def test_artifact_versioning_and_suggestion_outdated_guard(self) -> None:
        save_jobs(
            self.conn,
            [
                {
                    "url": "https://example.com/artifact-ops",
                    "company": "Artifact Ops",
                    "title": "Applied Scientist",
                    "location": "Remote",
                    "posted": "2026-02-12",
                    "ats": "greenhouse",
                    "description": "Own experiments and productionization",
                }
            ],
        )
        artifact_ops_id = self._job_id("https://example.com/artifact-ops")
        repository.ensure_starter_artifacts_for_job(self.conn, artifact_ops_id)
        resume = next(
            row for row in repository.list_job_artifacts(self.conn, artifact_ops_id)
            if row["artifact_type"] == "resume"
        )
        self.assertIsNotNone(resume["active_version"])
        active = resume["active_version"]

        suggestion = repository.create_artifact_suggestions(
            self.conn,
            artifact_id=resume["id"],
            base_version_id=active["id"],
            suggestions=[
                {
                    "target_path": "/basics/summary",
                    "summary": "Tailor summary to role",
                    "group_key": "summary",
                    "patch_json": [{"op": "replace", "path": "/basics/summary", "value": "Tailored summary"}],
                }
            ],
        )[0]
        accepted = repository.accept_artifact_suggestion(
            self.conn,
            suggestion_id=suggestion["id"],
            edited_patch_json=None,
            allow_outdated=False,
            created_by="test",
        )
        self.assertEqual(accepted["state"], "accepted")
        self.assertEqual(accepted["new_version"]["version"], 2)

        suggestion2 = repository.create_artifact_suggestions(
            self.conn,
            artifact_id=resume["id"],
            base_version_id=accepted["new_version"]["id"],
            suggestions=[
                {
                    "target_path": "/basics/summary",
                    "summary": "Another tweak",
                    "group_key": "summary",
                    "patch_json": [{"op": "replace", "path": "/basics/summary", "value": "Second summary"}],
                }
            ],
        )[0]
        repository.create_artifact_version(
            self.conn,
            artifact_id=resume["id"],
            label="draft",
            content_json={"basics": {"summary": "Concurrent edit"}},
            meta_json={},
            created_by="test",
            base_version_id=accepted["new_version"]["id"],
        )
        with self.assertRaises(ValueError):
            repository.accept_artifact_suggestion(
                self.conn,
                suggestion_id=suggestion2["id"],
                edited_patch_json=None,
                allow_outdated=False,
                created_by="test",
            )

    def test_artifact_suggestion_supports_json_patch_array_append(self) -> None:
        save_jobs(
            self.conn,
            [
                {
                    "url": "https://example.com/artifact-append",
                    "company": "Artifact Append",
                    "title": "ML Engineer",
                    "location": "Remote",
                    "posted": "2026-02-15",
                    "ats": "greenhouse",
                    "description": "Build production systems",
                }
            ],
        )
        artifact_append_id = self._job_id("https://example.com/artifact-append")
        repository.ensure_starter_artifacts_for_job(self.conn, artifact_append_id)
        resume = next(
            row for row in repository.list_job_artifacts(self.conn, artifact_append_id)
            if row["artifact_type"] == "resume"
        )
        base = resume["active_version"]
        suggestion = repository.create_artifact_suggestions(
            self.conn,
            artifact_id=resume["id"],
            base_version_id=base["id"],
            suggestions=[
                {
                    "target_path": "/skills/-",
                    "summary": "Append one skill",
                    "group_key": "skills",
                    "patch_json": [{"op": "add", "path": "/skills/-", "value": {"name": "PyTorch"}}],
                }
            ],
        )[0]
        accepted = repository.accept_artifact_suggestion(
            self.conn,
            suggestion_id=suggestion["id"],
            edited_patch_json=None,
            allow_outdated=False,
            created_by="test",
        )
        next_content = accepted["new_version"]["content_json"]
        self.assertIn("skills", next_content)
        self.assertTrue(isinstance(next_content["skills"], list))
        self.assertTrue(any(isinstance(item, dict) and item.get("name") == "PyTorch" for item in next_content["skills"]))

    def test_delete_job_cleans_artifact_tables(self) -> None:
        save_jobs(
            self.conn,
            [
                {
                    "url": "https://example.com/delete-artifacts",
                    "company": "Cleanup Co",
                    "title": "ML Engineer",
                    "location": "Remote",
                    "posted": "2026-02-16",
                    "ats": "greenhouse",
                    "description": "cleanup test",
                }
            ],
        )
        delete_job_id = self._job_id("https://example.com/delete-artifacts")
        repository.ensure_starter_artifacts_for_job(self.conn, delete_job_id)
        artifacts = repository.list_job_artifacts(self.conn, delete_job_id)
        resume = next(row for row in artifacts if row["artifact_type"] == "resume")
        active = resume["active_version"]
        repository.create_artifact_suggestions(
            self.conn,
            artifact_id=resume["id"],
            base_version_id=active["id"],
            suggestions=[
                {
                    "target_path": "/basics/summary",
                    "summary": "cleanup suggestion",
                    "group_key": "summary",
                    "patch_json": [{"op": "replace", "path": "/basics/summary", "value": "cleanup"}],
                }
            ],
        )

        deleted = repository.delete_job(self.conn, delete_job_id)
        self.assertEqual(deleted, 1)
        self.assertEqual(repository.list_job_artifacts(self.conn, delete_job_id), [])
        remaining_versions = self.conn.execute("SELECT COUNT(*) FROM artifact_versions").fetchone()
        remaining_suggestions = self.conn.execute("SELECT COUNT(*) FROM artifact_suggestions").fetchone()
        self.assertEqual(int(remaining_versions[0] if remaining_versions else 0), 0)
        self.assertEqual(int(remaining_suggestions[0] if remaining_suggestions else 0), 0)

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
        self.assertEqual(active[0]["job_id"], revive_job_id)

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


if __name__ == "__main__":
    unittest.main()
