from __future__ import annotations

from html import escape
import re
import time
from typing import Any
from dashboard.backend.artifact_typography import resolve_document_typography


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip()


def _highlights_array_from_html(html: str) -> list[str]:
    matches = re.findall(r"<li[^>]*>([\s\S]*?)</li>", html or "", flags=re.IGNORECASE)
    items = [_strip_html(match) for match in matches]
    items = [item for item in items if item]
    if items:
        return items
    text = _strip_html(html or "")
    return [text] if text else []


def _skill_labels(content: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for item in _as_list(content.get("skills")):
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            name = str(item.get("name") or "").strip()
        else:
            name = ""
        if name:
            labels.append(name)
    return labels


def _grouped_skills(content: dict[str, Any], labels: list[str]) -> list[tuple[str, list[str]]]:
    by_category = content.get("skills_by_category")
    if isinstance(by_category, dict) and by_category:
        rows: list[tuple[str, list[str]]] = []
        for category, values in by_category.items():
            items = [str(v).strip() for v in _as_list(values) if str(v).strip()]
            if items:
                rows.append((str(category), items))
        if rows:
            return rows

    buckets: dict[str, list[str]] = {
        "Programming Languages": [],
        "Machine Learning": [],
        "Natural Language Processing": [],
        "API Development": [],
        "Cloud Computing": [],
    }
    for skill in labels:
        key = skill.lower()
        if re.search(r"(python|java|c\+\+|sql|bash|cuda|javascript|typescript|go|rust)", key):
            buckets["Programming Languages"].append(skill)
        elif re.search(r"(pytorch|tensorflow|scikit|xgboost|opencv|mlflow|weights|bias|model|dvc)", key):
            buckets["Machine Learning"].append(skill)
        elif re.search(r"(langchain|rag|nlp|openai|crewai|prompt|agent|mcp|embedding|retrieval|llm)", key):
            buckets["Natural Language Processing"].append(skill)
        elif re.search(r"(flask|fastapi|rest|graphql|postgres|api)", key):
            buckets["API Development"].append(skill)
        else:
            buckets["Cloud Computing"].append(skill)
    return [(category, items) for category, items in buckets.items() if items]


def _safe_href(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    has_scheme = bool(re.match(r"^[a-z][a-z0-9+.-]*:", text, flags=re.IGNORECASE))
    candidate = text if has_scheme else f"https://{text}"
    if re.match(r"^(https?|mailto|tel):", candidate, flags=re.IGNORECASE):
        return candidate
    return None


def _link_label(name: Any, url: Any) -> str:
    named = str(name or "").strip()
    if named:
        return named
    href = _safe_href(url)
    if not href:
        return "Link"
    host_match = re.match(r"^[a-z][a-z0-9+.-]*://([^/]+)", href, flags=re.IGNORECASE)
    if host_match:
        return re.sub(r"^www\.", "", host_match.group(1), flags=re.IGNORECASE) or "Link"
    return "Link"


def _bullet_list(items: list[str]) -> str:
    if not items:
        return ""
    joined = "".join(f"<li>{escape(item)}</li>" for item in items)
    return f"<ul>{joined}</ul>"


def _ordered_resume_sections(theme_key: str) -> list[str]:
    if theme_key == "azurill":
        return ["skills", "highlights", "experience", "projects", "education", "publications"]
    if theme_key == "onyx":
        return ["highlights", "experience", "education", "projects", "skills", "publications"]
    if theme_key == "pikachu":
        return ["highlights", "skills", "projects", "experience", "education", "publications"]
    return ["highlights", "skills", "experience", "education", "projects", "publications"]


def _header_variant(theme_key: str) -> str:
    if theme_key == "azurill":
        return "left"
    if theme_key == "pikachu":
        return "split"
    return "center"


def _render_resume_html(content: dict[str, Any], meta: dict[str, Any], theme_class: str, theme_key: str) -> str:
    basics = _as_dict(content.get("basics"))
    work = [entry for entry in _as_list(content.get("work")) if isinstance(entry, dict)]
    education = [entry for entry in _as_list(content.get("education")) if isinstance(entry, dict)]
    projects = [entry for entry in _as_list(content.get("projects")) if isinstance(entry, dict)]
    publications = [entry for entry in _as_list(content.get("publications")) if isinstance(entry, dict)]
    profiles = [entry for entry in _as_list(basics.get("profiles")) if isinstance(entry, dict)]
    highlights = _highlights_array_from_html(str(content.get("highlights_html") or ""))
    summary = str(basics.get("summary") or "").strip()
    if not highlights and summary:
        highlights = [line.strip() for line in re.split(r"\n+", summary) if line.strip()]

    skill_names = _skill_labels(content)
    grouped_skills = _grouped_skills(content, skill_names)

    name = str(basics.get("name") or "")
    phone = str(basics.get("phone") or "").strip()
    email = str(basics.get("email") or "").strip()
    location = str(basics.get("location") or "").strip()
    website = str(basics.get("website") or "").strip()
    contact_chunks: list[str] = []
    for value in (phone, email, location):
        text = str(value or "").strip()
        if text:
            contact_chunks.append(f"<span>{escape(text)}</span>")
    website_href = _safe_href(website)
    if website_href:
        contact_chunks.append(f"<span><a href='{escape(website_href, quote=True)}'>{escape(_link_label('', website))}</a></span>")
    elif website:
        contact_chunks.append(f"<span>{escape(website)}</span>")
    contact_html = "".join(contact_chunks)

    profile_html = ""
    if profiles:
        profile_items: list[str] = []
        for item in profiles:
            network = str(item.get("network") or item.get("label") or "").strip()
            url = str(item.get("url") or "").strip()
            label = _link_label(network, url)
            href = _safe_href(url)
            if label:
                if href:
                    profile_items.append(f"<span><a href='{escape(href, quote=True)}'>{escape(label)}</a></span>")
                else:
                    profile_items.append(f"<span>{escape(label)}</span>")
        if profile_items:
            profile_html = f"<div class='artifact-template-links'>{''.join(profile_items)}</div>"

    skills_html = ""
    if grouped_skills:
        rows: list[str] = []
        for category, items in grouped_skills:
            rows.append(
                "<div class='artifact-template-skill-row'>"
                f"<strong>{escape(category)}</strong>"
                f"<span>{escape(', '.join(items))}</span>"
                "</div>"
            )
        skills_html = "<section class='artifact-template-section section-skills'><h2>Skills</h2><div class='artifact-template-skills-grid'>" + "".join(rows) + "</div></section>"
    elif skill_names:
        skills_html = (
            "<section class='artifact-template-section section-skills'><h2>Skills</h2>"
            f"<p class='artifact-template-inline-list'>{escape(' • '.join(skill_names))}</p></section>"
        )

    experience_html = ""
    if work:
        blocks: list[str] = []
        for item in work:
            position = str(item.get("position") or "Role").strip()
            company = str(item.get("name") or "Company").strip()
            start = str(item.get("startDate") or "").strip()
            end = str(item.get("endDate") or "").strip()
            location_value = str(item.get("location") or "").strip()
            period = f"{start}{f' - {end}' if end else ''}".strip()
            bullets = [str(v).strip() for v in _as_list(item.get("highlights")) if str(v).strip()]
            if not bullets:
                bullets = _highlights_array_from_html(str(item.get("highlights_html") or ""))
            blocks.append(
                "<div class='artifact-template-experience-item'>"
                "<div class='artifact-template-experience-top'>"
                f"<strong>{escape(position)}</strong><span>{escape(period)}</span>"
                "</div>"
                "<div class='artifact-template-experience-sub'>"
                f"<span>{escape(company)}</span><em>{escape(location_value)}</em>"
                "</div>"
                + (_bullet_list(bullets) if bullets else "<p class='artifact-paper-muted'>No bullet points yet.</p>")
                + "</div>"
            )
        experience_html = "<section class='artifact-template-section section-experience'><h2>Experience</h2>" + "".join(blocks) + "</section>"

    education_html = ""
    if education:
        blocks = []
        for item in education:
            degree = str(item.get("studyType") or "").strip()
            field = str(item.get("area") or "").strip()
            institution = str(item.get("institution") or "").strip()
            start = str(item.get("startDate") or "").strip()
            end = str(item.get("endDate") or "").strip()
            period = f"{start}{f' - {end}' if end else ''}".strip()
            location_value = str(item.get("location") or "").strip()
            title = " in ".join([part for part in (degree, field) if part]).strip() or "Education"
            courses = [str(v).strip() for v in _as_list(item.get("courses")) if str(v).strip()]
            course_html = f"<p class='artifact-template-inline-list'>Coursework: {escape(', '.join(courses))}</p>" if courses else ""
            blocks.append(
                "<div class='artifact-template-experience-item'>"
                "<div class='artifact-template-experience-top'>"
                f"<strong>{escape(title)}</strong><span>{escape(period)}</span>"
                "</div>"
                "<div class='artifact-template-experience-sub'>"
                f"<span>{escape(institution)}</span><em>{escape(location_value)}</em>"
                "</div>"
                f"{course_html}"
                "</div>"
            )
        education_html = "<section class='artifact-template-section section-education'><h2>Education</h2>" + "".join(blocks) + "</section>"

    projects_html = ""
    if projects:
        blocks = []
        for item in projects:
            title = str(item.get("name") or "Project").strip()
            date = str(item.get("date") or item.get("endDate") or "").strip()
            bullets = [str(v).strip() for v in _as_list(item.get("highlights")) if str(v).strip()]
            blocks.append(
                "<div class='artifact-template-experience-item'>"
                "<div class='artifact-template-experience-top'>"
                f"<strong>{escape(title)}</strong><span>{escape(date)}</span>"
                "</div>"
                f"{_bullet_list(bullets)}"
                "</div>"
            )
        projects_html = "<section class='artifact-template-section section-projects'><h2>Projects</h2>" + "".join(blocks) + "</section>"

    publications_html = ""
    if publications:
        items = []
        for item in publications:
            title = str(item.get("name") or "").strip()
            publisher = str(item.get("publisher") or "").strip()
            date = str(item.get("releaseDate") or "").strip()
            line = " - ".join([part for part in (title, publisher, date) if part])
            if line:
                items.append(line)
        if items:
            publications_html = (
                "<section class='artifact-template-section section-publications'><h2>Publications</h2>"
                + _bullet_list(items)
                + "</section>"
            )

    section_html_map: dict[str, str] = {
        "highlights": (
            "<section class='artifact-template-section section-highlights'>"
            "<h2>Highlights</h2>"
            + _bullet_list(highlights)
            + "</section>"
        ),
        "skills": skills_html,
        "experience": experience_html,
        "education": education_html,
        "projects": projects_html,
        "publications": publications_html,
    }
    ordered_sections = [section_html_map.get(section_id, "") for section_id in _ordered_resume_sections(theme_key)]
    ordered_sections = [chunk for chunk in ordered_sections if chunk]
    variant = _header_variant(theme_key)

    header_links = profile_html.replace("artifact-template-links", f"artifact-template-links template-links-{variant}") if profile_html else ""
    return "".join(
        [
            f"<article class='artifact-paper-sheet {theme_class}'>",
            f"<header class='artifact-template-header template-header-{variant}'>",
            f"<h1>{escape(name or 'Candidate Name')}</h1>",
            f"<div class='artifact-template-contact template-contact-{variant}'>{contact_html}</div>",
            header_links,
            "</header>",
            "".join(ordered_sections),
            "</article>",
        ]
    )


def _render_cover_letter_html(content: dict[str, Any], meta: dict[str, Any], theme_class: str) -> str:
    frontmatter = content.get("frontmatter") if isinstance(content.get("frontmatter"), dict) else {}
    blocks = content.get("blocks") if isinstance(content.get("blocks"), list) else []
    title = str(frontmatter.get("subject") or "Cover Letter")
    body_chunks: list[str] = [f"<article class='artifact-paper-sheet {theme_class}'>", f"<h1>{escape(title)}</h1>"]
    for block in blocks:
        if not isinstance(block, dict):
            continue
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        body_chunks.append(f"<p>{escape(text).replace(chr(10), '<br/>')}</p>")
    body_chunks.append("</article>")
    return "\n".join(body_chunks)


def render_artifact_html(*, artifact_type: str, content: dict[str, Any], meta: dict[str, Any]) -> str:
    meta_obj = _as_dict(meta)
    template_id = str(meta_obj.get("templateId") or "classic")
    theme_key = re.sub(r"[^a-z0-9_-]+", "", template_id.strip().lower()) or "classic"
    theme_class = f"theme-{theme_key}"
    inner = _render_resume_html(content, meta, theme_class, theme_key) if artifact_type == "resume" else _render_cover_letter_html(content, meta, theme_class)
    explicit_typography = _as_dict(meta_obj.get("typography"))
    resolved_typography, _ = resolve_document_typography(
        template_id=template_id,
        use_template_typography=True,
        document_typography_override={},
    )
    typography = {**resolved_typography, **explicit_typography}
    font_family = str(typography.get("fontFamily") or resolved_typography.get("fontFamily") or "Georgia, 'Times New Roman', serif")
    font_size = float(typography.get("fontSize") or resolved_typography.get("fontSize") or 11)
    line_height = float(typography.get("lineHeight") or resolved_typography.get("lineHeight") or 1.35)
    document_layout = _as_dict(meta_obj.get("documentLayout"))
    page_layout = _as_dict(document_layout.get("page"))
    global_layout = _as_dict(document_layout.get("global"))
    margin_top_mm = float(page_layout.get("marginTopMm") or 18)
    margin_right_mm = float(page_layout.get("marginRightMm") or 14)
    margin_bottom_mm = float(page_layout.get("marginBottomMm") or 18)
    margin_left_mm = float(page_layout.get("marginLeftMm") or 14)
    global_text_align = str(global_layout.get("textAlign") or "left").strip().lower()
    if global_text_align not in {"left", "justify", "center"}:
        global_text_align = "left"
    section_layout = _as_dict(meta_obj.get("sectionLayout"))
    typography_details = _as_dict(meta_obj.get("typographyDetails"))
    def _num(value: Any, default: float, lo: float, hi: float) -> float:
        try:
            parsed = float(value)
        except Exception:
            parsed = default
        return max(lo, min(hi, parsed))
    fs_header_name = _num(typography_details.get("headerNamePx"), 21.0, 14.0, 36.0)
    fs_contact = _num(typography_details.get("contactPx"), 9.7, 8.0, 16.0)
    fs_links = _num(typography_details.get("linksPx"), 9.5, 8.0, 16.0)
    fs_section_heading = _num(typography_details.get("sectionHeadingPx"), 11.4, 9.0, 20.0)
    fs_item_title = _num(typography_details.get("itemTitlePx"), 11.0, 9.0, 20.0)
    fs_item_meta = _num(typography_details.get("itemMetaPx"), 10.1, 8.0, 18.0)
    fs_item_sub = _num(typography_details.get("itemSubPx"), 10.45, 8.0, 18.0)
    fs_body = _num(typography_details.get("bodyPx"), 11.0, 9.0, 18.0)
    section_css_rules: list[str] = []
    for section_key in ("highlights", "skills", "experience", "education", "projects", "publications"):
        row = _as_dict(section_layout.get(section_key))
        if not row:
            continue
        parts: list[str] = []
        if isinstance(row.get("fontSizePx"), (int, float)):
            parts.append(f"font-size: {float(row['fontSizePx']):.2f}px;")
        if isinstance(row.get("lineHeight"), (int, float)):
            parts.append(f"line-height: {float(row['lineHeight']):.3f};")
        align = str(row.get("textAlign") or "").strip().lower()
        if align in {"left", "justify", "center"}:
            parts.append(f"text-align: {align};")
        if parts:
            section_css_rules.append(f".artifact-template-section.section-{section_key} {{ {' '.join(parts)} }}")
    section_css = "\n".join(section_css_rules)
    return f"""
    <!doctype html>
    <html>
      <head>
        <meta charset=\"utf-8\" />
        <style>
          @page {{ size: A4; margin: {margin_top_mm}mm {margin_right_mm}mm {margin_bottom_mm}mm {margin_left_mm}mm; }}
          body {{ font-family: {font_family}; font-size: {font_size}px; line-height: {line_height}; text-align: {global_text_align}; background: #ffffff; margin: 0; padding: 0; }}
          .artifact-paper-sheet {{
            width: auto;
            margin: 0;
            background: #fff;
            color: #20252d;
            border: 1px solid #d8dde8;
            border-radius: 4px;
            padding: 0;
            --fs-header-name: {fs_header_name}px;
            --fs-contact: {fs_contact}px;
            --fs-links: {fs_links}px;
            --fs-section-heading: {fs_section_heading}px;
            --fs-item-title: {fs_item_title}px;
            --fs-item-meta: {fs_item_meta}px;
            --fs-item-sub: {fs_item_sub}px;
            --fs-body: {fs_body}px;
          }}
          .artifact-template-header {{
            text-align: center;
            border-bottom: 1px solid #cfd5df;
            padding-bottom: 8px;
            margin-bottom: 10px;
          }}
          .artifact-template-header.template-header-left {{ text-align: left; }}
          .artifact-template-header.template-header-split {{ text-align: left; display: grid; gap: 4px; }}
          .artifact-template-header h1 {{
            margin: 0;
            font-size: var(--fs-header-name, 1.9em);
            letter-spacing: 0.02em;
            color: #121722;
            line-height: 1.12;
          }}
          .artifact-template-contact {{
            margin-top: 4px;
            display: inline-flex;
            flex-wrap: wrap;
            gap: 8px;
            font-size: var(--fs-contact, 0.88em);
            color: #2f3b4f;
          }}
          .artifact-template-contact.template-contact-left,
          .artifact-template-contact.template-contact-split {{ display: flex; }}
          .artifact-template-contact span + span::before {{
            content: "|";
            margin-right: 8px;
            color: #72809a;
          }}
          .artifact-template-links {{
            margin-top: 4px;
            display: inline-flex;
            flex-wrap: wrap;
            gap: 10px;
            font-size: var(--fs-links, 0.86em);
            color: #2f3b4f;
          }}
          .artifact-template-links.template-links-left,
          .artifact-template-links.template-links-split {{ display: flex; }}
          .artifact-template-links span + span::before {{
            content: "|";
            margin-right: 10px;
            color: #72809a;
          }}
          .artifact-template-links a,
          .artifact-template-contact a {{
            color: inherit;
            text-decoration: underline;
            text-underline-offset: 2px;
          }}
          .artifact-template-section {{ margin-top: 10px; }}
          .artifact-template-section h2 {{
            margin: 0 0 4px;
            font-size: var(--fs-section-heading, 1.04em);
            letter-spacing: 0.03em;
            text-transform: uppercase;
            border-bottom: 1px solid #d3dae7;
            padding-bottom: 2px;
            line-height: 1.2;
            break-after: avoid-page;
            page-break-after: avoid;
          }}
          .artifact-template-section ul {{ margin: 6px 0 0; padding-left: 18px; }}
          .artifact-template-section li {{ margin: 0 0 3px; line-height: 1.34; font-size: var(--fs-body, 1em); }}
          .artifact-template-skills-grid {{ display: grid; gap: 6px; }}
          .artifact-template-skill-row {{
            display: grid;
            grid-template-columns: 220px minmax(0, 1fr);
            gap: 10px;
            align-items: start;
          }}
          .artifact-template-skill-row strong {{ font-size: var(--fs-item-title, 0.98em); }}
          .artifact-template-skill-row span {{ font-size: var(--fs-body, 0.98em); line-height: 1.35; }}
          .artifact-template-experience-item {{ break-inside: avoid; page-break-inside: avoid; }}
          .artifact-template-experience-item + .artifact-template-experience-item {{ margin-top: 8px; }}
          .artifact-template-experience-top {{
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            gap: 10px;
          }}
          .artifact-template-experience-top strong {{ font-size: var(--fs-item-title, 1em); }}
          .artifact-template-experience-top span {{ font-size: var(--fs-item-meta, 0.92em); color: #4f5d74; }}
          .artifact-template-experience-sub {{
            margin-top: 2px;
            display: flex;
            justify-content: space-between;
            gap: 10px;
            font-size: var(--fs-item-sub, 0.95em);
            color: #39465c;
          }}
          .artifact-template-inline-list {{ margin: 4px 0 0; font-size: var(--fs-body, 0.95em); line-height: 1.36; }}
          .artifact-paper-muted {{ color: #5a6578; font-style: italic; margin: 2px 0 0; }}
          .artifact-paper-sheet.theme-azurill {{ border-color: #cfe3ff; box-shadow: 0 16px 30px rgba(39, 95, 170, 0.16); }}
          .artifact-paper-sheet.theme-azurill .artifact-template-header {{ border-bottom-color: #c8dbfa; }}
          .artifact-paper-sheet.theme-azurill .artifact-template-header h1 {{ letter-spacing: 0.01em; }}
          .artifact-paper-sheet.theme-azurill .artifact-template-section h2 {{ color: #244c86; border-bottom-color: #bfd3f3; }}
          .artifact-paper-sheet.theme-onyx {{ border-color: #d0d0d0; box-shadow: 0 12px 24px rgba(30, 30, 30, 0.14); }}
          .artifact-paper-sheet.theme-onyx .artifact-template-header h1 {{ letter-spacing: 0.04em; text-transform: uppercase; }}
          .artifact-paper-sheet.theme-onyx .artifact-template-section h2 {{ letter-spacing: 0.04em; border-bottom-color: #c8c8c8; }}
          .artifact-paper-sheet.theme-pikachu {{ border-color: #f0d479; box-shadow: 0 16px 30px rgba(170, 128, 20, 0.18); }}
          .artifact-paper-sheet.theme-pikachu .artifact-template-header {{ border-bottom-color: #ebd06f; }}
          .artifact-paper-sheet.theme-pikachu .artifact-template-header.template-header-split {{ grid-template-columns: minmax(0, 1fr); }}
          .artifact-paper-sheet.theme-pikachu .artifact-template-contact.template-contact-split {{ gap: 12px; }}
          .artifact-paper-sheet.theme-pikachu .artifact-template-section h2 {{ color: #6a4d04; border-bottom-color: #e3c561; }}
          {section_css}
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
                    prefer_css_page_size=True,
                    print_background=True,
                    margin={"top": "0mm", "right": "0mm", "bottom": "0mm", "left": "0mm"},
                )
                return bytes(pdf_bytes)
            finally:
                browser.close()
    except RuntimeError:
        raise
    except Exception as error:
        raise RuntimeError(f"PDF export failed: {error}") from error
