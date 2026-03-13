from __future__ import annotations

import sys
from pathlib import Path
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

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
        self.assertIn(">A</h1>", html)
        self.assertIn("Summary", html)

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

    def test_render_resume_html_renders_clickable_named_links(self) -> None:
        html = artifact_export.render_artifact_html(
            artifact_type="resume",
            content={
                "basics": {
                    "name": "A",
                    "email": "a@example.com",
                    "website": "example.com",
                    "profiles": [
                        {"network": "LinkedIn", "url": "https://linkedin.com/in/example"},
                        {"network": "GitHub", "url": "github.com/example"},
                    ],
                },
                "skills": [{"name": "Python"}],
            },
            meta={},
        )
        self.assertIn(">LinkedIn</a>", html)
        self.assertIn(">GitHub</a>", html)
        self.assertIn("href='https://linkedin.com/in/example'", html)
        self.assertIn("href='https://github.com/example'", html)
        self.assertIn("href='https://example.com'", html)

    def test_render_resume_html_uses_item_level_page_break_policy(self) -> None:
        html = artifact_export.render_artifact_html(
            artifact_type="resume",
            content={"basics": {"name": "A"}, "work": [{"name": "C", "position": "R"}]},
            meta={},
        )
        self.assertIn(".artifact-template-section { margin-top: 10px; }", html)
        self.assertIn(".artifact-template-experience-item { break-inside: avoid; page-break-inside: avoid; }", html)
        self.assertNotIn(".artifact-template-section { margin-top: 10px; break-inside: avoid;", html)

    def test_export_pdf_uses_css_page_size_and_zero_runtime_margin(self) -> None:
        captured_kwargs: dict[str, object] = {}

        class FakePage:
            @staticmethod
            def set_content(*args, **kwargs):
                return None

            @staticmethod
            def pdf(**kwargs):
                captured_kwargs.update(kwargs)
                return b"%PDF-1.4"

        class FakeBrowser:
            @staticmethod
            def new_page():
                return FakePage()

            @staticmethod
            def close():
                return None

        class FakePlaywrightCtx:
            def __enter__(self):
                class FakeChromium:
                    @staticmethod
                    def launch():
                        return FakeBrowser()

                class FakePlaywright:
                    chromium = FakeChromium()

                return FakePlaywright()

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch("playwright.sync_api.sync_playwright", return_value=FakePlaywrightCtx()):
            pdf = artifact_export.export_artifact_pdf(artifact_type="resume", content={"basics": {"name": "A"}}, meta={})
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertEqual(captured_kwargs.get("format"), "A4")
        self.assertEqual(captured_kwargs.get("prefer_css_page_size"), True)
        self.assertEqual(
            captured_kwargs.get("margin"),
            {"top": "0mm", "right": "0mm", "bottom": "0mm", "left": "0mm"},
        )


if __name__ == "__main__":
    unittest.main()
