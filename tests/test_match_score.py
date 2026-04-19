from __future__ import annotations

import unittest


from ai_job_hunter.match_score import calibrate_match_scores, compute_match_score


class MatchScoreTests(unittest.TestCase):
    def test_required_skill_overlap_improves_raw_fit(self) -> None:
        profile = {
            "years_experience": 2,
            "skills": ["python", "sql", "pytorch"],
            "target_role_families": [],
            "requires_visa_sponsorship": False,
        }
        high_overlap = {
            "title": "ML Engineer",
            "enrichment": {
                "required_skills": ["python", "sql", "pytorch"],
                "preferred_skills": [],
                "years_exp_min": 3,
            },
        }
        low_overlap = {
            "title": "ML Engineer",
            "enrichment": {
                "required_skills": ["rust", "go", "haskell"],
                "preferred_skills": [],
                "years_exp_min": 3,
            },
        }

        high_score = compute_match_score(high_overlap, profile)["raw_score"]
        low_score = compute_match_score(low_overlap, profile)["raw_score"]
        self.assertGreater(high_score, low_score)

    def test_fuzzy_skill_overlap_counts_near_matches(self) -> None:
        profile = {
            "years_experience": 2,
            "skills": ["nodejs", "reactjs", "tensorflow"],
            "target_role_families": [],
            "requires_visa_sponsorship": False,
        }
        fuzzy_overlap = {
            "title": "Frontend ML Engineer",
            "enrichment": {
                "required_skills": ["node.js", "react js", "tf"],
                "preferred_skills": [],
                "years_exp_min": 2,
            },
        }
        exact_miss = {
            "title": "Frontend ML Engineer",
            "enrichment": {
                "required_skills": ["golang", "vue", "pytorch"],
                "preferred_skills": [],
                "years_exp_min": 2,
            },
        }

        fuzzy_score = compute_match_score(fuzzy_overlap, profile)["raw_score"]
        miss_score = compute_match_score(exact_miss, profile)["raw_score"]
        self.assertGreater(fuzzy_score, miss_score)

    def test_visa_mismatch_triggers_eligibility_suppressor(self) -> None:
        profile = {
            "years_experience": 2,
            "skills": ["python"],
            "target_role_families": [],
            "requires_visa_sponsorship": True,
        }
        mismatched_job = {
            "title": "Junior Data Scientist",
            "enrichment": {
                "seniority": "junior",
                "years_exp_min": 2,
                "required_skills": ["python"],
                "visa_sponsorship": "no",
            },
        }
        matched_job = {
            "title": "Junior Data Scientist",
            "enrichment": {
                "seniority": "junior",
                "years_exp_min": 2,
                "required_skills": ["python"],
                "visa_sponsorship": "yes",
            },
        }

        mismatch = compute_match_score(mismatched_job, profile)
        matched = compute_match_score(matched_job, profile)
        self.assertEqual(mismatch["breakdown"]["suppressor_eligibility"], 1)
        self.assertLess(mismatch["raw_score"], matched["raw_score"])
        self.assertLessEqual(mismatch["breakdown"]["suppressed_score_cap"], 26)

    def test_canada_ineligible_triggers_eligibility_suppressor(self) -> None:
        profile = {
            "years_experience": 1,
            "skills": ["python", "sql"],
            "target_role_families": ["data scientist"],
            "requires_visa_sponsorship": False,
        }
        canada_yes = {
            "title": "Junior Data Scientist",
            "enrichment": {
                "seniority": "junior",
                "years_exp_min": 2,
                "required_skills": ["python", "sql"],
                "canada_eligible": "yes",
            },
        }
        canada_no = {
            "title": "Junior Data Scientist",
            "enrichment": {
                "seniority": "junior",
                "years_exp_min": 2,
                "required_skills": ["python", "sql"],
                "canada_eligible": "no",
            },
        }
        yes_score = compute_match_score(canada_yes, profile)["raw_score"]
        no_match = compute_match_score(canada_no, profile)
        self.assertLess(no_match["raw_score"], yes_score)
        self.assertEqual(no_match["breakdown"]["suppressor_eligibility"], 1)

    def test_intern_and_too_senior_roles_trigger_seniority_suppressor(self) -> None:
        profile = {
            "years_experience": 3,
            "skills": ["python", "sql"],
            "target_role_families": ["data scientist"],
            "requires_visa_sponsorship": False,
        }
        intern_job = {
            "title": "Machine Learning Intern",
            "enrichment": {
                "required_skills": ["python"],
                "years_exp_min": 1,
                "role_family": "data scientist",
            },
        }
        senior_job = {
            "title": "Senior Data Scientist",
            "enrichment": {
                "required_skills": ["python"],
                "years_exp_min": 5,
                "role_family": "data scientist",
            },
        }

        intern_match = compute_match_score(intern_job, profile)
        senior_match = compute_match_score(senior_job, profile)
        self.assertEqual(intern_match["breakdown"]["suppressor_seniority"], 1)
        self.assertEqual(senior_match["breakdown"]["suppressor_seniority"], 0)
        self.assertLess(intern_match["raw_score"], senior_match["raw_score"])

    def test_title_alignment_is_continuous_not_boost_only(self) -> None:
        profile = {
            "years_experience": 3,
            "skills": ["python", "sql"],
            "desired_job_titles": ["Machine Learning Engineer", "Applied Scientist"],
            "target_role_families": [],
            "requires_visa_sponsorship": False,
        }
        matching_job = {
            "title": "Machine Learning Engineer",
            "enrichment": {
                "required_skills": ["python"],
                "preferred_skills": [],
            },
        }
        non_matching_job = {
            "title": "Backend Platform Engineer",
            "enrichment": {
                "required_skills": ["python"],
                "preferred_skills": [],
            },
        }

        matched = compute_match_score(matching_job, profile)
        non_matched = compute_match_score(non_matching_job, profile)
        self.assertGreater(matched["breakdown"]["desired_title_alignment"], non_matched["breakdown"]["desired_title_alignment"])
        self.assertGreater(matched["raw_score"], non_matched["raw_score"])

    def test_missing_enrichment_returns_low_confidence_and_conservative_fit(self) -> None:
        profile = {
            "years_experience": 1,
            "skills": ["python"],
            "target_role_families": [],
            "requires_visa_sponsorship": False,
        }
        job = {"title": "Entry Level ML Engineer"}
        match = compute_match_score(job, profile)
        self.assertEqual(match["confidence"], "low")
        self.assertLess(match["raw_score"], 60)

    def test_calibration_spreads_scores_without_saturating(self) -> None:
        raw_items = [
            {"raw_score": raw, "score": raw, "suppressed": False, "status": "not_applied"}
            for raw in [28, 34, 39, 44, 49, 55, 59, 64, 70, 74, 79, 84, 89, 93]
        ]
        calibrated = calibrate_match_scores(raw_items)
        scores = [item["score"] for item in calibrated]
        self.assertGreater(max(scores), min(scores))
        self.assertLess(sum(1 for score in scores if score >= 85), len(scores))
        self.assertGreaterEqual(sum(1 for score in scores if score >= 85), 1)

    def test_calibration_keeps_suppressed_jobs_low_ranked(self) -> None:
        raw_items = [
            {"raw_score": 82, "score": 82, "suppressed": False, "status": "not_applied"},
            {"raw_score": 78, "score": 78, "suppressed": False, "status": "not_applied"},
            {"raw_score": 90, "score": 90, "suppressed": True, "status": "not_applied", "breakdown": {"suppressed_score_cap": 22}},
        ]
        calibrated = calibrate_match_scores(raw_items)
        suppressed = calibrated[2]
        self.assertLessEqual(suppressed["score"], 30)


if __name__ == "__main__":
    unittest.main()
