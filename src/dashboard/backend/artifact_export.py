from __future__ import annotations

from html import escape
import time
from typing import Any


def _render_resume_html(content: dict[str, Any], meta: dict[str, Any]) -> str:
    basics = content.get("basics") if isinstance(content.get("basics"), dict) else {}
    skills = content.get("skills") if isinstance(content.get("skills"), list) else []
    skill_names = []
    for item in skills:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            if name:
                skill_names.append(name)
    summary = str(basics.get("summary") or "")
    name = str(basics.get("name") or "")
    label = str(basics.get("label") or "")
    return f"""
    <article>
      <h1>{escape(name)}</h1>
      <p><strong>{escape(label)}</strong></p>
      <p>{escape(summary)}</p>
      <h2>Skills</h2>
      <p>{escape(', '.join(skill_names))}</p>
    </article>
    """


def _render_cover_letter_html(content: dict[str, Any], meta: dict[str, Any]) -> str:
    frontmatter = content.get("frontmatter") if isinstance(content.get("frontmatter"), dict) else {}
    blocks = content.get("blocks") if isinstance(content.get("blocks"), list) else []
    title = str(frontmatter.get("subject") or "Cover Letter")
    body_chunks: list[str] = [f"<h1>{escape(title)}</h1>"]
    for block in blocks:
        if not isinstance(block, dict):
            continue
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        body_chunks.append(f"<p>{escape(text).replace(chr(10), '<br/>')}</p>")
    return "\n".join(body_chunks)


def render_artifact_html(*, artifact_type: str, content: dict[str, Any], meta: dict[str, Any]) -> str:
    inner = _render_resume_html(content, meta) if artifact_type == "resume" else _render_cover_letter_html(content, meta)
    return f"""
    <!doctype html>
    <html>
      <head>
        <meta charset=\"utf-8\" />
        <style>
          body {{ font-family: 'Georgia', 'Times New Roman', serif; background: #f4f5f7; margin: 0; padding: 32px; }}
          article {{ max-width: 800px; margin: 0 auto; background: #fff; border: 1px solid #d6d9df; border-radius: 8px; padding: 36px; }}
          h1 {{ margin: 0 0 8px; font-size: 28px; }}
          h2 {{ margin: 24px 0 8px; font-size: 18px; }}
          p {{ margin: 0 0 12px; line-height: 1.45; font-size: 13pt; color: #1e2530; }}
        </style>
      </head>
      <body>
        {inner}
      </body>
    </html>
    """


def export_artifact_pdf(*, artifact_type: str, content: dict[str, Any], meta: dict[str, Any], timeout_ms: int = 15000) -> bytes:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as error:
        raise RuntimeError("Playwright is not installed for PDF export") from error

    html = render_artifact_html(artifact_type=artifact_type, content=content, meta=meta)
    try:
        with sync_playwright() as p:
            browser = None
            launch_error: Exception | None = None
            for attempt in range(2):
                try:
                    browser = p.chromium.launch()
                    break
                except Exception as error:
                    launch_error = error
                    if attempt == 0:
                        time.sleep(0.2)
                        continue
            if browser is None:
                message = str(launch_error or "unknown launch error")
                if "executable doesn't exist" in message.lower() or "browser" in message.lower():
                    raise RuntimeError(
                        "Playwright Chromium binaries are missing. Run `uv run playwright install chromium` on the server."
                    ) from launch_error
                raise RuntimeError(f"Failed to launch Playwright browser: {message}") from launch_error
            try:
                page = browser.new_page()
                page.set_content(html, wait_until="networkidle", timeout=timeout_ms)
                pdf_bytes = page.pdf(
                    format="A4",
                    print_background=True,
                    margin={"top": "18mm", "right": "14mm", "bottom": "18mm", "left": "14mm"},
                )
                return bytes(pdf_bytes)
            finally:
                browser.close()
    except RuntimeError:
        raise
    except Exception as error:
        raise RuntimeError(f"PDF export failed: {error}") from error
