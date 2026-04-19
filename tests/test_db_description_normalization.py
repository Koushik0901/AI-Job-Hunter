from __future__ import annotations

import tempfile
from pathlib import Path
import unittest


from ai_job_hunter.db import init_db, normalize_description_text, save_jobs


class DbDescriptionNormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self.db_path = Path(handle.name)
        self.conn = init_db(str(self.db_path))

    def tearDown(self) -> None:
        self.conn.close()
        if self.db_path.exists():
            self.db_path.unlink()

    def _description_for(self, url: str) -> str:
        row = self.conn.execute("SELECT description FROM jobs WHERE url = ?", (url,)).fetchone()
        self.assertIsNotNone(row)
        return str(row[0] or "")

    def test_normalize_description_text_decodes_entities_and_preserves_blocks(self) -> None:
        raw = (
            "Senior Engineer&nbsp;&nbsp;\u200b\n"
            "\n"
            "Build ML systems &amp; teams.\n"
            "\n"
            "- Own pipelines &nsbp; and infra\n"
            "- Collaborate with product &lt;and&gt; design\n"
            "\n"
            "1. Ship &quot;quality&quot; features\n"
            "2. Improve reliability"
        )

        self.assertEqual(
            normalize_description_text(raw),
            (
                "Senior Engineer\n\n"
                "Build ML systems & teams.\n\n"
                "- Own pipelines and infra\n"
                "- Collaborate with product <and> design\n\n"
                "1. Ship \"quality\" features\n"
                "2. Improve reliability"
            ),
        )

    def test_save_jobs_normalizes_description_on_insert_and_returns_clean_payload(self) -> None:
        url = "https://example.com/manual-cleaning"
        raw_description = (
            "Senior Engineer&nbsp;&nbsp;\u200b\n"
            "\n"
            "Build ML systems &amp; teams.\n"
            "\n"
            "- Own pipelines &nsbp; and infra\n"
            "- Collaborate with product &lt;and&gt; design"
        )

        new_count, updated_count, new_jobs = save_jobs(
            self.conn,
            [
                {
                    "url": url,
                    "company": "Acme AI",
                    "title": "Senior ML Engineer",
                    "location": "Remote",
                    "posted": "2026-03-12",
                    "ats": "manual",
                    "description": raw_description,
                }
            ],
        )

        self.assertEqual(new_count, 1)
        self.assertEqual(updated_count, 0)
        self.assertEqual(new_jobs[0]["description"], normalize_description_text(raw_description))
        self.assertEqual(self._description_for(url), normalize_description_text(raw_description))

    def test_save_jobs_normalizes_description_on_update(self) -> None:
        url = "https://example.com/manual-update"
        initial_description = "Raw text"
        updated_description = "Updated&nbsp;text &amp; more\n\n- Keep &nsbp; this"

        save_jobs(
            self.conn,
            [
                {
                    "url": url,
                    "company": "Acme AI",
                    "title": "ML Engineer",
                    "location": "Toronto",
                    "posted": "2026-03-01",
                    "ats": "manual",
                    "description": initial_description,
                }
            ],
        )

        new_count, updated_count, new_jobs = save_jobs(
            self.conn,
            [
                {
                    "url": url,
                    "company": "Acme AI",
                    "title": "ML Engineer",
                    "location": "Toronto",
                    "posted": "2026-03-02",
                    "ats": "manual",
                    "description": updated_description,
                }
            ],
        )

        self.assertEqual(new_count, 0)
        self.assertEqual(updated_count, 1)
        self.assertEqual(new_jobs, [])
        self.assertEqual(self._description_for(url), normalize_description_text(updated_description))


if __name__ == "__main__":
    unittest.main()
