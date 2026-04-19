from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from html.parser import HTMLParser
from io import BytesIO
import re
from typing import Any, Mapping
from urllib.parse import urlparse


_ALLOWED_HTML_TAGS = {
    "a",
    "blockquote",
    "br",
    "code",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "hr",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}
_VOID_HTML_TAGS = {"br", "hr"}


def _safe_href(value: str) -> str | None:
    parsed = urlparse(value)
    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    return value


class _RenderedHtmlSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        if tag_name not in _ALLOWED_HTML_TAGS:
            return
        rendered_attrs: list[str] = []
        if tag_name == "a":
            href = next((value for key, value in attrs if key.lower() == "href" and value), None)
            safe_href = _safe_href(str(href)) if href else None
            if safe_href:
                rendered_attrs.append(f'href="{escape(safe_href, quote=True)}"')
        attr_text = f" {' '.join(rendered_attrs)}" if rendered_attrs else ""
        if tag_name in _VOID_HTML_TAGS:
            self._parts.append(f"<{tag_name}{attr_text} />")
            return
        self._parts.append(f"<{tag_name}{attr_text}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name in _ALLOWED_HTML_TAGS and tag_name not in _VOID_HTML_TAGS:
            self._parts.append(f"</{tag_name}>")

    def handle_data(self, data: str) -> None:
        self._parts.append(escape(data))

    def handle_entityref(self, name: str) -> None:
        self._parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        del data

    def get_html(self) -> str:
        return "".join(self._parts)


def _slugify_filename_part(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    return normalized.strip("-")


def build_job_description_filename(job: Mapping[str, Any]) -> str:
    parts = [
        _slugify_filename_part(str(job.get("company") or "")),
        _slugify_filename_part(str(job.get("title") or "")),
        "job-description",
    ]
    cleaned = [part for part in parts if part]
    job_id = str(job.get("id") or "").strip()
    if cleaned:
        return f"{'-'.join(cleaned)}.pdf"
    if job_id:
        return f"job-description-{job_id}.pdf"
    return "job-description.pdf"


def _job_label(value: Any, fallback: str = "-") -> str:
    text = str(value or "").strip()
    return text or fallback


def _job_link(value: Any) -> str:
    text = str(value or "").strip()
    return text if re.match(r"^https?://", text, flags=re.IGNORECASE) else ""


def _render_markdown_html(markdown_text: str) -> str:
    try:
        import markdown as markdown_lib
    except Exception as error:
        raise RuntimeError("Python-Markdown is not installed for JD PDF export") from error

    rendered = str(
        markdown_lib.markdown(
            markdown_text,
            extensions=["tables", "sane_lists", "nl2br"],
            output_format="xhtml",
        )
    )
    sanitizer = _RenderedHtmlSanitizer()
    sanitizer.feed(rendered)
    sanitizer.close()
    return sanitizer.get_html()


def render_job_description_html(job: Mapping[str, Any], exported_at: datetime | None = None) -> str:
    enrichment = job.get("enrichment") if isinstance(job.get("enrichment"), Mapping) else {}
    formatted_description = str((enrichment or {}).get("formatted_description") or "").strip()
    if not formatted_description:
        raise ValueError("Formatted markdown is not available for this job")

    timestamp = exported_at or datetime.now(timezone.utc)
    body_html = _render_markdown_html(formatted_description)
    title = escape(_job_label(job.get("title")))
    company = escape(_job_label(job.get("company")))
    location = escape(_job_label(job.get("location")))
    posted = escape(_job_label(job.get("posted")))
    ats = escape(_job_label(job.get("ats")))
    source_url = _job_link(job.get("url"))
    source_html = (
        f"<a href='{escape(source_url, quote=True)}'>{escape(source_url)}</a>"
        if source_url
        else escape(_job_label(job.get("url")))
    )
    exported_label = escape(timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))

    return f"""<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>{title} - Job Description</title>
    <style>
      @page {{
        size: A4;
        margin: 20mm 16mm 18mm 16mm;
      }}
      body {{
        font-family: Helvetica, Arial, sans-serif;
        font-size: 10.5pt;
        line-height: 1.45;
        color: #18202b;
      }}
      h1 {{
        font-size: 18pt;
        line-height: 1.15;
        margin: 0 0 6pt;
      }}
      h2, h3, h4 {{
        font-size: 11.5pt;
        margin: 14pt 0 6pt;
        color: #223752;
      }}
      p {{
        margin: 0 0 8pt;
      }}
      ul, ol {{
        margin: 0 0 10pt 18pt;
        padding: 0;
      }}
      li {{
        margin: 0 0 4pt;
      }}
      a {{
        color: #1f5ea8;
        text-decoration: none;
      }}
      hr {{
        border: 0;
        border-top: 1px solid #cfd7e3;
        margin: 12pt 0;
      }}
      table {{
        width: 100%;
        border-collapse: collapse;
        margin: 10pt 0 12pt;
        table-layout: fixed;
      }}
      th, td {{
        border: 1px solid #cfd7e3;
        padding: 6pt 7pt;
        vertical-align: top;
        word-wrap: break-word;
      }}
      th {{
        background: #edf3fb;
        text-align: left;
      }}
      .jd-sheet {{
        border: 1px solid #d7deea;
        padding: 14pt 16pt 10pt;
      }}
      .jd-header {{
        border-bottom: 1px solid #d7deea;
        padding-bottom: 10pt;
        margin-bottom: 12pt;
      }}
      .jd-meta {{
        width: 100%;
        border-collapse: collapse;
        margin: 8pt 0 0;
      }}
      .jd-meta td {{
        border: 0;
        padding: 2pt 0;
      }}
      .jd-meta td:first-child {{
        width: 92pt;
        color: #526275;
        font-weight: bold;
      }}
      .jd-body {{
        margin-top: 2pt;
      }}
      .jd-body pre, .jd-body code {{
        font-family: "Courier New", monospace;
        white-space: pre-wrap;
      }}
    </style>
  </head>
  <body>
    <div class="jd-sheet">
      <div class="jd-header">
        <h1>{title}</h1>
        <table class="jd-meta">
          <tr><td>Company</td><td>{company}</td></tr>
          <tr><td>Location</td><td>{location}</td></tr>
          <tr><td>Posted</td><td>{posted}</td></tr>
          <tr><td>ATS</td><td>{ats}</td></tr>
          <tr><td>Source</td><td>{source_html}</td></tr>
          <tr><td>Exported</td><td>{exported_label}</td></tr>
        </table>
      </div>
      <div class="jd-body">
        {body_html}
      </div>
    </div>
  </body>
</html>
"""


def export_job_description_pdf(job: Mapping[str, Any], exported_at: datetime | None = None) -> bytes:
    try:
        from xhtml2pdf import pisa
    except Exception as error:
        raise RuntimeError("xhtml2pdf is not installed for JD PDF export") from error

    html = render_job_description_html(job, exported_at=exported_at)
    output = BytesIO()
    result = pisa.CreatePDF(html, dest=output, encoding="utf-8")
    if getattr(result, "err", 0):
        raise RuntimeError("JD PDF export failed")
    return output.getvalue()
