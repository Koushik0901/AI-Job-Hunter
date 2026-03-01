from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any


SECTION_HEADINGS = {"Highlights", "Skills", "Experience", "Education", "Projects", "Publications"}


def _normalize_line(line: str) -> str:
    cleaned = line.replace("\t", " ").replace("\x0c", "").rstrip()
    cleaned = re.sub(r"(\w)-\s+(\w)", r"\1\2", cleaned)
    cleaned = re.sub(r"\s{2,}", "  ", cleaned)
    return cleaned


def _split_sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {key: [] for key in SECTION_HEADINGS}
    current: str | None = None
    for raw in lines:
        line = _normalize_line(raw)
        heading = line.strip()
        if heading in SECTION_HEADINGS:
            current = heading
            continue
        if current is not None:
            sections[current].append(line)
    return sections


def _parse_contact(header_lines: list[str]) -> dict[str, str]:
    joined = " ".join(item.strip() for item in header_lines if item.strip())
    email_match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", joined)
    phone_match = re.search(r"(\+?\d[\d ()-]{7,}\d)", joined)
    email = email_match.group(0).strip() if email_match else ""
    phone = phone_match.group(1).strip() if phone_match else ""

    location = ""
    for candidate in header_lines:
        stripped = candidate.strip()
        if not stripped:
            continue
        if "@" in stripped:
            continue
        if re.search(r"\+\d", stripped):
            continue
        if any(token in stripped.lower() for token in ("linkedin", "github", "portfolio")):
            continue
        if "," in stripped:
            location = stripped
    return {"email": email, "phone": phone, "location": location}


def _parse_profiles(header_lines: list[str]) -> list[dict[str, str]]:
    labels = {"linkedin": "LinkedIn", "github": "Github", "portfolio": "Portfolio"}
    found: list[dict[str, str]] = []
    joined = " ".join(item.strip() for item in header_lines if item.strip()).lower()
    for key, label in labels.items():
        if key in joined:
            found.append({"network": label, "label": label, "url": ""})
    return found


def _parse_highlights(lines: list[str]) -> list[str]:
    bullets: list[str] = []
    current = ""
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        starts_new = not current or current.endswith((".", "!", "?"))
        if starts_new and current:
            bullets.append(current.strip())
            current = line
        elif starts_new and not current:
            current = line
        else:
            current = f"{current} {line}".strip()
    if current.strip():
        bullets.append(current.strip())
    return [item for item in bullets if item]


def _parse_skills(lines: list[str]) -> dict[str, list[str]]:
    categories: dict[str, list[str]] = {}
    current_key: str | None = None
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        match = re.match(r"^\s*([A-Za-z][A-Za-z /&+-]{2,}?)\s{2,}(.+)$", line)
        if match:
            current_key = match.group(1).strip()
            entries = [item.strip() for item in match.group(2).split(",") if item.strip()]
            categories[current_key] = entries
            continue
        if current_key:
            extra = [item.strip() for item in line.strip().split(",") if item.strip()]
            categories[current_key].extend(extra)
    deduped: dict[str, list[str]] = {}
    for key, values in categories.items():
        seen: set[str] = set()
        out: list[str] = []
        for item in values:
            norm = item.lower()
            if norm in seen:
                continue
            seen.add(norm)
            out.append(item)
        deduped[key] = out
    return deduped


def _split_period(period: str) -> tuple[str, str]:
    cleaned = period.strip()
    if "-" not in cleaned:
        return cleaned, ""
    left, right = cleaned.split("-", 1)
    return left.strip(), right.strip()


def _parse_experience(lines: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        role_match = re.match(r"^\s*(.+?)\s{2,}(\d{2}/\d{4}\s*-\s*(?:\d{2}/\d{4}|Present))\s*$", line)
        if not role_match:
            i += 1
            continue
        position = role_match.group(1).strip()
        period = role_match.group(2).strip()
        start_date, end_date = _split_period(period)
        company = ""
        location = ""
        highlights: list[str] = []
        i += 1
        if i < len(lines):
            company_line = lines[i].rstrip()
            company_match = re.match(r"^\s*(.+?)\s{2,}([A-Za-z].+)$", company_line)
            if company_match:
                company = company_match.group(1).strip()
                location = company_match.group(2).strip()
                i += 1
        current_bullet = ""
        while i < len(lines):
            bullet_line = lines[i].rstrip()
            if re.match(r"^\s*(.+?)\s{2,}(\d{2}/\d{4}\s*-\s*(?:\d{2}/\d{4}|Present))\s*$", bullet_line):
                break
            stripped = bullet_line.strip()
            if not stripped:
                if current_bullet:
                    highlights.append(current_bullet.strip())
                    current_bullet = ""
                i += 1
                continue
            starts_new = bullet_line.startswith("  ") and current_bullet.endswith((".", "!", "?"))
            if starts_new and current_bullet:
                highlights.append(current_bullet.strip())
                current_bullet = stripped
            elif not current_bullet:
                current_bullet = stripped
            else:
                current_bullet = f"{current_bullet} {stripped}".strip()
            i += 1
        if current_bullet.strip():
            highlights.append(current_bullet.strip())
        rows.append(
            {
                "name": company,
                "position": position,
                "location": location,
                "startDate": start_date,
                "endDate": end_date,
                "highlights": highlights,
            }
        )
    return rows


def _parse_education(lines: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        match = re.match(r"^\s*(.+?),\s*(.+?)\s{2,}(.+?)\s+(\d{4}\s*-\s*\d{4})\s*$", line)
        if not match:
            i += 1
            continue
        degree_part = match.group(1).strip()
        institution = match.group(2).strip()
        location = match.group(3).strip()
        years = match.group(4).strip()
        start_date, end_date = _split_period(years)
        area = ""
        if " in " in degree_part.lower():
            chunks = re.split(r"\s+in\s+", degree_part, flags=re.IGNORECASE)
            if len(chunks) >= 2:
                degree_part = chunks[0].strip()
                area = chunks[1].strip()
        courses: list[str] = []
        if i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if next_line.lower().startswith("notable coursework:"):
                course_text = next_line.split(":", 1)[1]
                courses = [item.strip() for item in course_text.split(",") if item.strip()]
                i += 1
        rows.append(
            {
                "institution": institution,
                "studyType": degree_part,
                "area": area,
                "location": location,
                "startDate": start_date,
                "endDate": end_date,
                "courses": courses,
            }
        )
        i += 1
    return rows


def _parse_projects(lines: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        header = re.match(r"^\s*(.+?)\s{2,}(\d{2}/\d{4})\s*$", line)
        if not header:
            i += 1
            continue
        name = header.group(1).strip()
        date = header.group(2).strip()
        highlights: list[str] = []
        i += 1
        current = ""
        while i < len(lines):
            row = lines[i].rstrip()
            if re.match(r"^\s*(.+?)\s{2,}(\d{2}/\d{4})\s*$", row):
                break
            stripped = row.strip()
            if not stripped:
                if current:
                    highlights.append(current.strip())
                    current = ""
                i += 1
                continue
            if current and current.endswith((".", "!", "?")) and row.startswith("  "):
                highlights.append(current.strip())
                current = stripped
            elif current:
                current = f"{current} {stripped}".strip()
            else:
                current = stripped
            i += 1
        if current:
            highlights.append(current.strip())
        rows.append({"name": name, "date": date, "highlights": highlights})
    return rows


def _parse_publications(lines: list[str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for line in lines:
        item = line.strip()
        if not item:
            continue
        if "orcid" in item.lower() or "google scholar" in item.lower():
            continue
        if len(item) < 6:
            continue
        out.append({"name": item})
    return out


def _bullets_to_html(items: list[str]) -> str:
    safe = [item.replace("<", "&lt;").replace(">", "&gt;") for item in items if item.strip()]
    if not safe:
        return "<ul><li></li></ul>"
    inner = "".join(f"<li>{item}</li>" for item in safe)
    return f"<ul>{inner}</ul>"


def _extract_pdf_text(path: Path) -> str:
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
    except FileNotFoundError as error:
        raise RuntimeError("pdftotext is not installed on the backend host.") from error
    except subprocess.CalledProcessError as error:
        raise RuntimeError("Failed to extract text from PDF.") from error
    return result.stdout or ""


def _parse_resume_text(text: str) -> dict[str, Any]:
    if not text.strip():
        raise RuntimeError("Extracted PDF text is empty.")

    lines = text.splitlines()
    normalized = [_normalize_line(line) for line in lines]
    top_non_empty = [line.strip() for line in normalized if line.strip()]
    if not top_non_empty:
        raise RuntimeError("Could not parse resume text.")

    name = top_non_empty[0]
    heading_index = next((idx for idx, line in enumerate(normalized) if line.strip() in SECTION_HEADINGS), len(normalized))
    header_lines = normalized[:heading_index]
    sections = _split_sections(normalized)
    contact = _parse_contact(header_lines)
    profiles = _parse_profiles(header_lines)
    highlights = _parse_highlights(sections.get("Highlights", []))
    skills_by_category = _parse_skills(sections.get("Skills", []))
    flattened_skills = [
        {"name": item}
        for values in skills_by_category.values()
        for item in values
        if item.strip()
    ]
    work = _parse_experience(sections.get("Experience", []))
    education = _parse_education(sections.get("Education", []))
    projects = _parse_projects(sections.get("Projects", []))
    publications = _parse_publications(sections.get("Publications", []))

    return {
        "basics": {
            "name": name,
            "label": "",
            "email": contact["email"],
            "phone": contact["phone"],
            "location": contact["location"],
            "website": "",
            "profiles": profiles,
        },
        "highlights_html": _bullets_to_html(highlights),
        "skills_by_category": skills_by_category,
        "skills": flattened_skills,
        "work": work,
        "education": education,
        "projects": projects,
        "publications": publications,
    }


def import_resume_pdf_to_baseline(source_path: str) -> dict[str, Any]:
    path = Path(source_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Resume source not found: {path}")
    text = _extract_pdf_text(path)
    return _parse_resume_text(text)


def import_resume_pdf_bytes_to_baseline(file_bytes: bytes, filename: str | None = None) -> dict[str, Any]:
    if not file_bytes:
        raise RuntimeError("Uploaded PDF is empty.")
    suffix = ".pdf"
    if filename and filename.lower().endswith(".pdf"):
        suffix = Path(filename).suffix or ".pdf"
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
            handle.write(file_bytes)
            temp_path = Path(handle.name)
        text = _extract_pdf_text(temp_path)
        return _parse_resume_text(text)
    finally:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
