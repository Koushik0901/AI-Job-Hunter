from __future__ import annotations

import sys
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from match_score import compute_match_score


class MatchScoreTests(unittest.TestCase):
    def test_junior_bias_outscores_senior(self) -> None:
        profile = {
            "years_experience": 1,
            "skills": ["python", "pytorch", "sql"],
            "target_role_families": ["ml engineer"],
            "requires_visa_sponsorship": False,
        }
        junior_job = {
            "title": "Junior ML Engineer",
            "enrichment": {
                "seniority": "junior",
                "years_exp_min": 2,
                "required_skills": ["python", "pytorch"],
                "preferred_skills": ["sql"],
                "role_family": "ml engineer",
                "visa_sponsorship": "yes",
            },
        }
        senior_job = {
            "title": "Senior ML Engineer",
            "enrichment": {
                "seniority": "senior",
                "years_exp_min": 7,
                "required_skills": ["python", "pytorch"],
                "preferred_skills": ["sql"],
                "role_family": "ml engineer",
                "visa_sponsorship": "yes",
            },
        }

        junior_score = compute_match_score(junior_job, profile)["score"]
        senior_score = compute_match_score(senior_job, profile)["score"]
        self.assertGreater(junior_score, senior_score)

    def test_required_skill_overlap_improves_score(self) -> None:
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

        high_score = compute_match_score(high_overlap, profile)["score"]
        low_score = compute_match_score(low_overlap, profile)["score"]
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

        fuzzy_score = compute_match_score(fuzzy_overlap, profile)["score"]
        miss_score = compute_match_score(exact_miss, profile)["score"]
        self.assertGreater(fuzzy_score, miss_score)

    def test_acronym_and_expanded_skill_match(self) -> None:
        profile = {
            "years_experience": 2,
            "skills": ["RAG", "python"],
            "target_role_families": [],
            "requires_visa_sponsorship": False,
        }
        expanded_overlap = {
            "title": "Applied AI Engineer",
            "enrichment": {
                "required_skills": ["Retrieval Augmented Generation (RAG)", "python"],
                "preferred_skills": [],
                "years_exp_min": 1,
            },
        }
        no_overlap = {
            "title": "Applied AI Engineer",
            "enrichment": {
                "required_skills": ["go", "rust"],
                "preferred_skills": [],
                "years_exp_min": 1,
            },
        }
        expanded_score = compute_match_score(expanded_overlap, profile)["score"]
        no_overlap_score = compute_match_score(no_overlap, profile)["score"]
        self.assertGreater(expanded_score, no_overlap_score)

    def test_compact_and_acronym_forms_match(self) -> None:
        profile = {
            "years_experience": 3,
            "skills": ["CI/CD", "GenAI"],
            "target_role_families": [],
            "requires_visa_sponsorship": False,
        }
        overlap = {
            "title": "Platform AI Engineer",
            "enrichment": {
                "required_skills": ["cicd", "generative ai"],
                "preferred_skills": [],
                "years_exp_min": 2,
            },
        }
        miss = {
            "title": "Platform AI Engineer",
            "enrichment": {
                "required_skills": ["kafka", "terraform"],
                "preferred_skills": [],
                "years_exp_min": 2,
            },
        }
        overlap_score = compute_match_score(overlap, profile)["score"]
        miss_score = compute_match_score(miss, profile)["score"]
        self.assertGreater(overlap_score, miss_score)

    def test_visa_mismatch_is_strong_penalty(self) -> None:
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
        self.assertEqual(mismatch["breakdown"]["eligibility_penalty"], -40)
        self.assertLess(mismatch["score"], matched["score"])

    def test_missing_enrichment_returns_low_confidence(self) -> None:
        profile = {
            "years_experience": 1,
            "skills": ["python"],
            "target_role_families": [],
            "requires_visa_sponsorship": False,
        }
        job = {"title": "Entry Level ML Engineer"}
        match = compute_match_score(job, profile)
        self.assertIn("score", match)
        self.assertEqual(match["confidence"], "low")

    def test_canada_ineligible_gets_hard_penalty(self) -> None:
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
        yes_score = compute_match_score(canada_yes, profile)["score"]
        no_match = compute_match_score(canada_no, profile)
        self.assertLess(no_match["score"], yes_score)
        self.assertLessEqual(no_match["breakdown"]["eligibility_penalty"], -45)

    def test_intern_and_senior_receive_same_seniority_penalty(self) -> None:
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
                "preferred_skills": [],
                "years_exp_min": 1,
                "role_family": "data scientist",
            },
        }
        coop_job = {
            "title": "Data Science Co-op",
            "enrichment": {
                "required_skills": ["python"],
                "preferred_skills": [],
                "years_exp_min": 1,
                "role_family": "data scientist",
            },
        }
        senior_job = {
            "title": "Senior Data Scientist",
            "enrichment": {
                "required_skills": ["python"],
                "preferred_skills": [],
                "years_exp_min": 5,
                "role_family": "data scientist",
            },
        }

        intern_match = compute_match_score(intern_job, profile)
        coop_match = compute_match_score(coop_job, profile)
        senior_match = compute_match_score(senior_job, profile)
        self.assertEqual(intern_match["breakdown"]["seniority_bias"], -25)
        self.assertEqual(coop_match["breakdown"]["seniority_bias"], -25)
        self.assertEqual(senior_match["breakdown"]["seniority_bias"], -25)


if __name__ == "__main__":
    unittest.main()
