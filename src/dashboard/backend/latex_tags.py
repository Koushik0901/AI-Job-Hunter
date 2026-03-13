from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


_SECTION_OPEN = re.compile(r"^\s*%\s*<section:([a-z0-9_-]+)>\s*$", re.IGNORECASE)
_SECTION_CLOSE = re.compile(r"^\s*%\s*</section:([a-z0-9_-]+)>\s*$", re.IGNORECASE)
_ITEM_OPEN = re.compile(r"^\s*%\s*<item:([a-z0-9_-]+)>\s*$", re.IGNORECASE)
_ITEM_CLOSE = re.compile(r"^\s*%\s*</item:([a-z0-9_-]+)>\s*$", re.IGNORECASE)


@dataclass
class _Span:
    tag: str
    start: int
    end: int
    inner_start: int
    inner_end: int


def parse_tag_spans(source_text: str) -> dict[str, Any]:
    lines = source_text.splitlines(keepends=True)
    offsets: list[int] = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line)

    sections: dict[str, _Span] = {}
    items_by_section: dict[str, list[_Span]] = {}
    active_section: tuple[str, int, int] | None = None
    # Allow nested item tags; only top-level items are indexed for operations.
    item_stack: list[tuple[str, int, int]] = []

    for idx, line in enumerate(lines):
        s_open = _SECTION_OPEN.match(line)
        if s_open:
            if active_section is not None:
                raise ValueError("nested section tags are not supported")
            section_id = s_open.group(1).lower()
            active_section = (section_id, offsets[idx], idx)
            items_by_section.setdefault(section_id, [])
            continue
        s_close = _SECTION_CLOSE.match(line)
        if s_close:
            section_id = s_close.group(1).lower()
            if active_section is None or active_section[0] != section_id:
                raise ValueError(f"unbalanced section close tag: {section_id}")
            start_offset, start_line = active_section[1], active_section[2]
            if section_id in sections:
                raise ValueError(f"duplicate section id: {section_id}")
            close_end = offsets[idx] + len(line)
            inner_start = offsets[start_line] + len(lines[start_line])
            inner_end = offsets[idx]
            sections[section_id] = _Span(section_id, start_offset, close_end, inner_start, inner_end)
            active_section = None
            continue

        i_open = _ITEM_OPEN.match(line)
        if i_open:
            if active_section is None:
                raise ValueError("item tag must be inside section")
            item_id = i_open.group(1).lower()
            item_stack.append((item_id, offsets[idx], idx))
            continue
        i_close = _ITEM_CLOSE.match(line)
        if i_close:
            item_id = i_close.group(1).lower()
            if active_section is None:
                raise ValueError("item close found outside section")
            if not item_stack:
                raise ValueError(f"unbalanced item close tag: {item_id}")
            current_item = item_stack[-1]
            if current_item[0] != item_id:
                raise ValueError(f"unbalanced item close tag: {item_id}")
            start_offset, start_line = current_item[1], current_item[2]
            close_end = offsets[idx] + len(line)
            inner_start = offsets[start_line] + len(lines[start_line])
            inner_end = offsets[idx]
            if len(item_stack) == 1:
                items_by_section[active_section[0]].append(_Span(item_id, start_offset, close_end, inner_start, inner_end))
            item_stack.pop()
            continue

    if active_section is not None:
        raise ValueError(f"unclosed section tag: {active_section[0]}")
    if item_stack:
        raise ValueError(f"unclosed item tag: {item_stack[-1][0]}")

    return {
        "sections": sections,
        "items_by_section": items_by_section,
    }


def _apply_replace(source: str, start: int, end: int, value: str) -> str:
    return source[:start] + value + source[end:]


def _replace_placeholder(source: str, name: str, value: str) -> str:
    token = f"<<{name}>>"
    return source.replace(token, value)


def apply_tag_ops(source_text: str, ops: list[dict[str, Any]]) -> str:
    text = source_text
    for op in ops:
        op_name = str(op.get("op") or "").strip().lower()
        spans = parse_tag_spans(text)
        sections: dict[str, _Span] = spans["sections"]
        items_by_section: dict[str, list[_Span]] = spans["items_by_section"]

        if op_name == "replace_placeholder":
            placeholder_name = str(op.get("name") or "").strip()
            if not placeholder_name:
                raise ValueError("replace_placeholder requires name")
            text = _replace_placeholder(text, placeholder_name, str(op.get("value") or ""))
            continue

        section_id = str(op.get("section_id") or "").strip().lower()
        if section_id not in sections:
            raise ValueError(f"section not found: {section_id}")
        section = sections[section_id]

        if op_name == "replace_section":
            text = _apply_replace(text, section.inner_start, section.inner_end, str(op.get("content") or ""))
            continue

        section_items = items_by_section.get(section_id, [])
        if op_name == "append_item":
            content = str(op.get("content") or "")
            insert_at = section.inner_end
            if insert_at > 0 and not text[insert_at - 1:insert_at].endswith("\n"):
                content = "\n" + content
            text = text[:insert_at] + content + text[insert_at:]
            continue

        index = int(op.get("index") or 0)
        if index < 0 or index >= len(section_items):
            raise IndexError(f"item index out of range: {index}")
        item = section_items[index]

        if op_name == "replace_item":
            text = _apply_replace(text, item.inner_start, item.inner_end, str(op.get("content") or ""))
            continue
        if op_name == "remove_item":
            text = _apply_replace(text, item.start, item.end, "")
            continue
        if op_name == "insert_item":
            content = str(op.get("content") or "")
            text = text[:item.start] + content + ("\n" if not content.endswith("\n") else "") + text[item.start:]
            continue
        raise ValueError(f"unsupported tag op: {op_name}")
    return text
