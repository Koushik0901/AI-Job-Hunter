from __future__ import annotations

from typing import Any


TEMPLATE_TYPOGRAPHY_DEFAULTS: dict[str, dict[str, Any]] = {
    "classic": {
        "fontFamily": "Georgia, 'Times New Roman', serif",
        "fontSize": 11,
        "lineHeight": 1.35,
    },
    "modern": {
        "fontFamily": "'IBM Plex Sans', 'Segoe UI', sans-serif",
        "fontSize": 10.8,
        "lineHeight": 1.38,
    },
    "compact": {
        "fontFamily": "'Plus Jakarta Sans', 'Segoe UI', sans-serif",
        "fontSize": 10.4,
        "lineHeight": 1.28,
    },
    "azurill": {
        "fontFamily": "'IBM Plex Sans', 'Segoe UI', sans-serif",
        "fontSize": 10.8,
        "lineHeight": 1.36,
    },
    "onyx": {
        "fontFamily": "Georgia, 'Times New Roman', serif",
        "fontSize": 11,
        "lineHeight": 1.34,
    },
    "pikachu": {
        "fontFamily": "'Plus Jakarta Sans', 'Segoe UI', sans-serif",
        "fontSize": 10.6,
        "lineHeight": 1.32,
    },
}


def resolve_document_typography(
    *,
    template_id: str,
    use_template_typography: bool,
    document_typography_override: dict[str, Any] | None,
) -> tuple[dict[str, Any], str]:
    normalized_template = (template_id or "classic").strip().lower() or "classic"
    base = dict(TEMPLATE_TYPOGRAPHY_DEFAULTS.get(normalized_template, TEMPLATE_TYPOGRAPHY_DEFAULTS["classic"]))
    if use_template_typography:
        return base, "template"
    override = document_typography_override if isinstance(document_typography_override, dict) else {}
    font_family = str(override.get("fontFamily") or "").strip()
    if font_family:
        base["fontFamily"] = font_family
    if isinstance(override.get("fontSize"), (int, float)):
        base["fontSize"] = round(float(override["fontSize"]), 2)
    if isinstance(override.get("lineHeight"), (int, float)):
        base["lineHeight"] = round(float(override["lineHeight"]), 3)
    return base, "profile_override"
