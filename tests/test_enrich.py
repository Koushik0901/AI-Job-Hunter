from __future__ import annotations

import unittest
from unittest.mock import patch


from ai_job_hunter.enrich import JobEnrichment, enrich_one_job


class EnrichFormattingTests(unittest.TestCase):
    @patch("ai_job_hunter.enrich.format_description_with_llm")
    @patch("ai_job_hunter.enrich._invoke_once")
    @patch("ai_job_hunter.enrich._make_chain")
    def test_enrich_one_job_includes_formatted_description(
        self,
        mock_make_chain,
        mock_invoke_once,
        mock_format,
    ) -> None:
        mock_make_chain.return_value = object()
        mock_invoke_once.return_value = JobEnrichment(
            canada_eligible="yes",
            role_family="ml engineer",
            required_skills=["Python"],
            preferred_skills=[],
            red_flags=[],
        )
        mock_format.return_value = "Requirements\n- Python"
        job = {
            "url": "https://example.com/job",
            "title": "Junior ML Engineer",
            "company": "Acme",
            "location": "Remote - Canada",
            "description": "Need Python.",
        }

        result = enrich_one_job(job, "key", "extract-model", "format-model")
        self.assertEqual(result["enrichment_status"], "ok")
        self.assertEqual(result["formatted_description"], "Requirements\n- Python")

    @patch("ai_job_hunter.enrich.format_description_with_llm", side_effect=RuntimeError("format failed"))
    @patch("ai_job_hunter.enrich._invoke_once")
    @patch("ai_job_hunter.enrich._make_chain")
    def test_enrich_one_job_format_failure_is_non_fatal(
        self,
        mock_make_chain,
        mock_invoke_once,
        _mock_format,
    ) -> None:
        mock_make_chain.return_value = object()
        mock_invoke_once.return_value = JobEnrichment(
            canada_eligible="unknown",
            role_family="other",
            required_skills=[],
            preferred_skills=[],
            red_flags=[],
        )
        job = {
            "url": "https://example.com/job-2",
            "title": "ML Engineer",
            "company": "Acme",
            "location": "Remote",
            "description": "Some description.",
        }

        result = enrich_one_job(job, "key", "extract-model", "format-model")
        self.assertEqual(result["enrichment_status"], "ok")
        self.assertIsNone(result["formatted_description"])


if __name__ == "__main__":
    unittest.main()
