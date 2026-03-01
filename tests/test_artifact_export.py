from __future__ import annotations

import unittest
from unittest.mock import patch

from dashboard.backend import artifact_export


class ArtifactExportTests(unittest.TestCase):
    def test_render_resume_html_contains_skills(self) -> None:
        html = artifact_export.render_artifact_html(
            artifact_type="resume",
            content={
                "basics": {"name": "A", "label": "ML Engineer", "summary": "Summary"},
                "skills": [{"name": "Python"}, {"name": "SQL"}],
            },
            meta={},
        )
        self.assertIn("Python", html)
        self.assertIn("ML Engineer", html)

    def test_missing_browser_binary_raises_runtime_error(self) -> None:
        class FakePlaywrightCtx:
            def __enter__(self):  # noqa: D401
                class FakeChromium:
                    @staticmethod
                    def launch():
                        raise RuntimeError("Executable doesn't exist at /tmp/chromium")

                class FakePlaywright:
                    chromium = FakeChromium()

                return FakePlaywright()

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch("playwright.sync_api.sync_playwright", return_value=FakePlaywrightCtx()):
            with self.assertRaises(RuntimeError) as raised:
                artifact_export.export_artifact_pdf(artifact_type="resume", content={}, meta={})
        self.assertIn("playwright chromium binaries are missing", str(raised.exception).lower())


if __name__ == "__main__":
    unittest.main()

