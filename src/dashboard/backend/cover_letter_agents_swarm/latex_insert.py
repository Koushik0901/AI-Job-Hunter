from __future__ import annotations

import re

CL_START = "%<CL_START>"
CL_END = "%<CL_END>"
LEGACY_BODY_START_RE = re.compile(r"(?m)^\s*%\s*<section:body>\s*$")
LEGACY_BODY_END_RE = re.compile(r"(?m)^\s*%\s*</section:body>\s*$")


def _escape_latex_text(value: str) -> str:
    out = value
    out = out.replace("\\", r"\textbackslash{}")
    out = out.replace("&", r"\&")
    out = out.replace("%", r"\%")
    out = out.replace("$", r"\$")
    out = out.replace("#", r"\#")
    out = out.replace("_", r"\_")
    out = out.replace("{", r"\{")
    out = out.replace("}", r"\}")
    out = out.replace("~", r"\textasciitilde{}")
    out = out.replace("^", r"\textasciicircum{}")
    return out


def cover_letter_text_to_latex_body(cover_letter_text: str) -> str:
    text = (cover_letter_text or "").replace("\r\n", "\n").strip()
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return "% generated cover letter body is empty\n"
    escaped = [_escape_latex_text(p).replace("\n", " ") for p in paragraphs]
    return "\n\n".join(escaped) + "\n"


def extract_cover_letter_text_from_latex(source_tex: str) -> str:
    start_idx = source_tex.find(CL_START)
    end_idx = source_tex.find(CL_END)
    if start_idx >= 0 and end_idx >= 0 and end_idx > start_idx:
        body = source_tex[start_idx + len(CL_START):end_idx].strip()
    else:
        legacy_start = LEGACY_BODY_START_RE.search(source_tex)
        legacy_end = LEGACY_BODY_END_RE.search(source_tex)
        if not legacy_start or not legacy_end or legacy_end.start() <= legacy_start.end():
            raise ValueError("cover letter template missing %<CL_START>/%<CL_END> or legacy % <section:body> markers")
        body = source_tex[legacy_start.end():legacy_end.start()].strip()
    body = re.sub(r"(?m)^\s*%.*$", "", body)
    lines = [line.strip() for line in body.splitlines()]
    text = "\n".join(line for line in lines if line)
    text = text.replace(r"\%", "%").replace(r"\&", "&").replace(r"\_", "_").replace(r"\#", "#")
    text = text.replace(r"\$", "$").replace(r"\{", "{").replace(r"\}", "}")
    return text.strip()


def inject_cover_letter_body(source_tex: str, cover_letter_text: str) -> str:
    start_idx = source_tex.find(CL_START)
    end_idx = source_tex.find(CL_END)
    if start_idx >= 0 and end_idx >= 0 and end_idx > start_idx:
        insert_from = start_idx + len(CL_START)
        suffix_from = end_idx
    else:
        legacy_start = LEGACY_BODY_START_RE.search(source_tex)
        legacy_end = LEGACY_BODY_END_RE.search(source_tex)
        if not legacy_start or not legacy_end or legacy_end.start() <= legacy_start.end():
            raise ValueError("cover letter template missing %<CL_START>/%<CL_END> or legacy % <section:body> markers")
        insert_from = legacy_start.end()
        suffix_from = legacy_end.start()
    body = cover_letter_text_to_latex_body(cover_letter_text)
    prefix = source_tex[:insert_from]
    suffix = source_tex[suffix_from:]
    if not prefix.endswith("\n"):
        prefix = f"{prefix}\n"
    if not body.endswith("\n"):
        body = f"{body}\n"
    return f"{prefix}{body}{suffix}"
