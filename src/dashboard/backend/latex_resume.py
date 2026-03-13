from __future__ import annotations

import shutil
import subprocess
import os
import re
from pathlib import Path
from typing import Any, Literal


_TEMPLATE_CLASSIC = r"""
\documentclass[11pt,a4paper]{article}
\usepackage[a4paper,margin=1.7cm]{geometry}
\usepackage{enumitem}
\usepackage[hidelinks]{hyperref}
\usepackage{titlesec}
\usepackage{parskip}
\setlength{\parindent}{0pt}
\pagenumbering{gobble}
\titleformat{\section}{\large\bfseries}{}{0em}{}[\vspace{-0.4em}\hrule\vspace{0.4em}]
\begin{document}
\begin{center}
    {\LARGE \textbf{<<NAME>>}}\\
    \vspace{0.2em}
    <<HEADLINE>>\\
    \vspace{0.2em}
    <<CONTACT_LINE>>
\end{center}

<<SUMMARY_SECTION>>
<<EXPERIENCE_SECTION>>
<<EDUCATION_SECTION>>
<<PROJECTS_SECTION>>
<<SKILLS_SECTION>>
\end{document}
""".strip()


def _escape_latex(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    out = []
    for ch in text:
        out.append(replacements.get(ch, ch))
    return "".join(out)


TemplateKind = Literal["resume", "cover_letter"]


def _template_dir(kind: TemplateKind) -> Path:
    base = Path(__file__).resolve().parent
    if kind == "cover_letter":
        configured = os.environ.get("COVER_LETTER_TEMPLATE_DIR", "").strip()
        primary = "cover_letter_templates"
        nested = base / "latex_templates" / "cover_letter_templates"
        legacy = base / "latex_templates_cover_letter"
    else:
        configured = os.environ.get("RESUME_TEMPLATE_DIR", "").strip()
        primary = "resume_templates"
        nested = base / "latex_templates" / "resume_templates"
        legacy = base / "latex_templates"

    if configured:
        root = Path(configured).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    # Prefer nested latex_templates/{resume_templates|cover_letter_templates} when present.
    if nested.exists():
        nested_resolved = nested.resolve()
        nested_resolved.mkdir(parents=True, exist_ok=True)
        return nested_resolved

    # Preferred flat structure.
    preferred = (base / primary).resolve()
    if preferred.exists():
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred

    # Backward-compatible fallback.
    legacy_path = legacy.resolve()
    if legacy_path.exists():
        legacy_path.mkdir(parents=True, exist_ok=True)
        return legacy_path

    preferred.mkdir(parents=True, exist_ok=True)
    return preferred


def _normalize_template_id(template_id: str) -> str:
    normalized = (template_id or "").strip().lower()
    if not normalized:
        return "classic"
    if not re.fullmatch(r"[a-z0-9_-]+", normalized):
        return "classic"
    return normalized


def _id_from_filename(stem: str, kind: TemplateKind) -> str:
    normalized = stem.strip().lower()
    suffix = "_resume" if kind == "resume" else "_cover_letter"
    if normalized.endswith(suffix):
        trimmed = normalized[: -len(suffix)].strip("_-")
        return trimmed or "classic"
    return normalized


def _candidate_filenames(template_id: str, kind: TemplateKind) -> list[str]:
    normalized = _normalize_template_id(template_id)
    if kind == "resume":
        return [f"{normalized}_resume.tex", f"{normalized}.tex"]
    return [f"{normalized}_cover_letter.tex", f"{normalized}.tex"]


def _list_templates(kind: TemplateKind) -> list[dict[str, str]]:
    seen: set[str] = set()
    items: list[dict[str, str]] = []
    for file in sorted(_template_dir(kind).glob("*.tex")):
        stem = file.stem.strip()
        if not stem:
            continue
        template_id = _id_from_filename(stem, kind)
        if not re.fullmatch(r"[a-z0-9_-]+", template_id):
            continue
        if template_id in seen:
            continue
        seen.add(template_id)
        items.append({"id": template_id, "name": template_id})
    if not items:
        items.append({"id": "classic", "name": "classic"})
    return items


def list_resume_templates() -> list[dict[str, str]]:
    return _list_templates("resume")


def list_cover_letter_templates() -> list[dict[str, str]]:
    return _list_templates("cover_letter")


def _get_template_source(template_id: str, *, kind: TemplateKind) -> str:
    root = _template_dir(kind)
    for filename in _candidate_filenames(template_id, kind):
        target = (root / filename).resolve()
        if target.is_file():
            return target.read_text(encoding="utf-8")

    for fallback_name in _candidate_filenames("classic", kind):
        fallback = (root / fallback_name).resolve()
        if fallback.is_file():
            return fallback.read_text(encoding="utf-8")

    # Final safety fallback so startup does not break if folder is empty.
    return _TEMPLATE_CLASSIC


def get_resume_template_source(template_id: str) -> str:
    return _get_template_source(template_id, kind="resume")


def get_cover_letter_template_source(template_id: str) -> str:
    return _get_template_source(template_id, kind="cover_letter")


# Backward compatibility for existing imports.
def list_builtin_templates() -> list[dict[str, str]]:
    return list_resume_templates()


def get_template_source(template_id: str) -> str:
    return get_resume_template_source(template_id)


def _section(title: str, body: str) -> str:
    body_clean = body.strip()
    if not body_clean:
        return ""
    return f"\\section*{{{_escape_latex(title)}}}\n{body_clean}\n"


def bootstrap_resume_tex(
    *,
    profile: dict[str, Any] | None,
    resume_profile: dict[str, Any] | None,
    job: dict[str, Any] | None,
    template_id: str = "classic",
) -> str:
    baseline = (
        (resume_profile or {}).get("baseline_resume_json")
        if isinstance((resume_profile or {}).get("baseline_resume_json"), dict)
        else {}
    )
    basics = baseline.get("basics") if isinstance(baseline.get("basics"), dict) else {}
    work = baseline.get("work") if isinstance(baseline.get("work"), list) else []
    education = baseline.get("education") if isinstance(baseline.get("education"), list) else []
    projects = baseline.get("projects") if isinstance(baseline.get("projects"), list) else []
    skills = baseline.get("skills") if isinstance(baseline.get("skills"), list) else []

    name = str(basics.get("name") or "Your Name").strip()
    headline = str(basics.get("label") or (job or {}).get("title") or "").strip()
    summary = str(basics.get("summary") or "").strip()
    email = str(basics.get("email") or "").strip()
    phone = str(basics.get("phone") or "").strip()
    location = str(basics.get("location") or "").strip()

    contact_parts = [p for p in [email, phone, location] if p]
    contact_line = r" \textbar{} ".join(_escape_latex(p) for p in contact_parts) if contact_parts else ""

    exp_chunks: list[str] = []
    for item in work:
        if not isinstance(item, dict):
            continue
        company = _escape_latex(str(item.get("name") or ""))
        position = _escape_latex(str(item.get("position") or ""))
        start = _escape_latex(str(item.get("startDate") or ""))
        end = _escape_latex(str(item.get("endDate") or "Present"))
        header = f"\\textbf{{{position}}} -- {company} \\hfill {start} -- {end}\n"
        highlights = item.get("highlights") if isinstance(item.get("highlights"), list) else []
        lines: list[str] = [header]
        if highlights:
            lines.append("\\begin{itemize}[leftmargin=1.2em,itemsep=0.15em,topsep=0.2em]")
            for h in highlights:
                txt = _escape_latex(str(h).strip())
                if txt:
                    lines.append(f"\\item {txt}")
            lines.append("\\end{itemize}")
        exp_chunks.append("\n".join(lines))

    edu_chunks: list[str] = []
    for item in education:
        if not isinstance(item, dict):
            continue
        inst = _escape_latex(str(item.get("institution") or ""))
        area = _escape_latex(str(item.get("area") or ""))
        study = _escape_latex(str(item.get("studyType") or ""))
        start = _escape_latex(str(item.get("startDate") or ""))
        end = _escape_latex(str(item.get("endDate") or ""))
        label = " ".join(part for part in [study, area] if part).strip()
        edu_chunks.append(f"\\textbf{{{label}}} -- {inst} \\hfill {start} -- {end}")

    project_chunks: list[str] = []
    for item in projects:
        if not isinstance(item, dict):
            continue
        name_txt = _escape_latex(str(item.get("name") or ""))
        desc = _escape_latex(str(item.get("description") or ""))
        if not name_txt and not desc:
            continue
        project_chunks.append(f"\\textbf{{{name_txt}}}: {desc}".strip(": "))

    skill_names: list[str] = []
    for skill in skills:
        if isinstance(skill, dict):
            name_val = str(skill.get("name") or "").strip()
            if name_val:
                skill_names.append(name_val)
        elif isinstance(skill, str) and skill.strip():
            skill_names.append(skill.strip())
    if not skill_names and isinstance(profile, dict):
        prof_skills = profile.get("skills") if isinstance(profile.get("skills"), list) else []
        skill_names.extend(str(s).strip() for s in prof_skills if str(s).strip())
    skills_text = ", ".join(_escape_latex(s) for s in skill_names)

    source = get_resume_template_source(template_id)
    return (
        source.replace("<<NAME>>", _escape_latex(name))
        .replace("<<HEADLINE>>", _escape_latex(headline))
        .replace("<<CONTACT_LINE>>", contact_line)
        .replace("<<SUMMARY_SECTION>>", _section("Summary", _escape_latex(summary)))
        .replace("<<EXPERIENCE_SECTION>>", _section("Experience", "\n\n".join(exp_chunks)))
        .replace("<<EDUCATION_SECTION>>", _section("Education", "\n".join(edu_chunks)))
        .replace("<<PROJECTS_SECTION>>", _section("Projects", "\n".join(project_chunks)))
        .replace("<<SKILLS_SECTION>>", _section("Skills", _escape_latex(skills_text)))
    )


def bootstrap_cover_letter_tex(*, job: dict[str, Any] | None, template_id: str = "classic") -> str:
    source = get_cover_letter_template_source(template_id)
    company = _escape_latex(str((job or {}).get("company") or "Hiring Team"))
    role = _escape_latex(str((job or {}).get("title") or "the role"))
    replacements = {
        "<<SENDER_NAME>>": "Your Name",
        "<<SENDER_CONTACT>>": "email@example.com | +1 000 000 0000",
        "<<DATE>>": r"\today",
        "<<RECIPIENT_NAME>>": "Hiring Manager",
        "<<COMPANY>>": company,
        "<<COMPANY_NAME>>": company,
        "<<COMPANY_ADDRESS>>": "",
        "<<COMPANY_LOCATION>>": "",
        "<<SUBJECT_LINE>>": f"Application for {role}",
        "<<BODY_PARAGRAPHS>>": (
            f"I am writing to apply for {role} at {company}.\\\\\n\n"
            "My background aligns with the role requirements, and I can contribute immediately."
        ),
    }
    out = source
    for key, value in replacements.items():
        out = out.replace(key, value)
    return out


def get_workspace_root() -> Path:
    root = Path((os.environ.get("RESUME_WORKSPACE_ROOT") or "artifacts_workspace")).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def version_workspace(artifact_id: str, version: int) -> Path:
    root = get_workspace_root()
    path = root / "resumes" / artifact_id / f"v{version}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def compiled_pdf_path(artifact_id: str, version: int) -> Path:
    # Resolve deterministic path from trusted identifiers only.
    return get_workspace_root() / "resumes" / artifact_id / f"v{version}" / "output.pdf"


def _parse_diagnostics(log_text: str) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    pattern = re.compile(r"^(.+?):(\d+):\s*(.+)$")
    for raw in (log_text or "").splitlines():
        line = raw.strip()
        match = pattern.match(line)
        if not match:
            continue
        file_name = match.group(1).strip()
        line_no = int(match.group(2))
        message = match.group(3).strip()
        severity = "error" if message.startswith(("!", "LaTeX Error", "Undefined control sequence")) else "warning"
        diagnostics.append(
            {
                "severity": severity,
                "file": file_name,
                "line": line_no,
                "message": message,
                "raw": raw,
            }
        )
    return diagnostics


def compile_resume_tex(*, artifact_id: str, version: int, source_text: str, timeout_seconds: int = 45) -> dict[str, Any]:
    workdir = version_workspace(artifact_id, version)
    source_path = workdir / "source.tex"
    log_path = workdir / "compile.log"
    pdf_path = workdir / "output.pdf"
    source_path.write_text(source_text, encoding="utf-8")

    if shutil.which("latexmk") is None:
        raise RuntimeError("latexmk is not installed or not on PATH")

    cmd = [
        "latexmk",
        "-xelatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        "source.tex",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workdir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("LaTeX compile timed out") from error

    combined = f"{proc.stdout}\n{proc.stderr}".strip()
    log_path.write_text(combined, encoding="utf-8")
    built_pdf = workdir / "source.pdf"
    if proc.returncode != 0 or not built_pdf.exists():
        tail = "\n".join(combined.splitlines()[-40:])
        return {"ok": False, "pdf_path": None, "log_tail": tail, "diagnostics": _parse_diagnostics(combined)}

    if pdf_path.exists():
        pdf_path.unlink()
    built_pdf.replace(pdf_path)
    tail = "\n".join(combined.splitlines()[-40:])
    return {"ok": True, "pdf_path": str(pdf_path), "log_tail": tail, "diagnostics": _parse_diagnostics(combined)}


def validate_template(*, artifact_type: TemplateKind, template_id: str) -> dict[str, Any]:
    source = _get_template_source(template_id, kind=artifact_type)
    section_ids = sorted(
        set(match.group(1).lower() for match in re.finditer(r"%\s*<section:([a-z0-9_-]+)>", source, re.IGNORECASE))
    )
    item_ids = sorted(
        set(match.group(1).lower() for match in re.finditer(r"%\s*<item:([a-z0-9_-]+)>", source, re.IGNORECASE))
    )
    warnings: list[str] = []
    missing_sections: list[str] = []
    missing_placeholders: list[str] = []
    if artifact_type == "resume":
        required_sections = ["header", "highlights", "skills", "experience", "education"]
        required_placeholders = ["<<NAME>>"]
    else:
        required_sections = ["recipient", "opening", "body", "closing"]
        required_placeholders = ["<<RECIPIENT_NAME>>", "<<BODY_PARAGRAPHS>>"]
    for section in required_sections:
        if section not in section_ids:
            missing_sections.append(section)
            warnings.append(f"Missing recommended section tag: {section}")
    for ph in required_placeholders:
        if ph not in source:
            missing_placeholders.append(ph)
            warnings.append(f"Missing recommended placeholder: {ph}")
    return {
        "ok": True,
        "warnings": warnings,
        "missing_required_sections": missing_sections,
        "missing_required_placeholders": missing_placeholders,
        "detected_sections": section_ids,
        "detected_items": item_ids,
    }
