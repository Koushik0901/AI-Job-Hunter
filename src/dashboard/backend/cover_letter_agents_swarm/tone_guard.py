from __future__ import annotations

import re
from typing import Any

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'_-]*")
_CLICHE_PHRASES = (
    "passionate",
    "thrilled",
    "fast-paced environment",
    "dynamic team",
    "great fit",
    "perfect fit",
    "mission-driven",
    "i am confident",
    "i'm confident",
)


def evaluate_cover_letter_tone(text: str) -> dict[str, Any]:
    content = (text or "").strip()
    if not content:
        return {
            "triggered": True,
            "issues": ["empty_cover_letter"],
            "metrics": {"sentence_count": 0, "avg_sentence_words": 0.0, "long_sentence_count": 0, "comma_density": 0.0},
        }
    sentences = [part.strip() for part in _SENTENCE_SPLIT.split(content) if part.strip()]
    sentence_word_counts: list[int] = []
    long_sentence_count = 0
    for sentence in sentences:
        words = _WORD_RE.findall(sentence)
        count = len(words)
        sentence_word_counts.append(count)
        if count >= 32:
            long_sentence_count += 1
    avg_sentence_words = (sum(sentence_word_counts) / len(sentence_word_counts)) if sentence_word_counts else 0.0
    comma_count = content.count(",")
    word_count = len(_WORD_RE.findall(content))
    comma_density = (comma_count / max(1, word_count)) * 100.0

    lowered = content.lower()
    cliches_found = [phrase for phrase in _CLICHE_PHRASES if phrase in lowered]
    skills_list_pattern_count = len(re.findall(r"(python|sql|aws|docker|kubernetes|tensorflow|pytorch)(\s*,\s*(python|sql|aws|docker|kubernetes|tensorflow|pytorch)){2,}", lowered))

    issues: list[str] = []
    if avg_sentence_words > 26:
        issues.append("avg_sentence_too_long")
    if long_sentence_count >= 3:
        issues.append("too_many_long_sentences")
    if comma_density > 7.0:
        issues.append("comma_density_high")
    if skills_list_pattern_count > 0:
        issues.append("skills_list_pattern_detected")
    if cliches_found:
        issues.append("cliche_phrases_detected")

    return {
        "triggered": len(issues) > 0,
        "issues": issues,
        "metrics": {
            "sentence_count": len(sentences),
            "avg_sentence_words": round(avg_sentence_words, 2),
            "long_sentence_count": long_sentence_count,
            "comma_density": round(comma_density, 2),
            "skills_list_pattern_count": skills_list_pattern_count,
            "cliches_found": cliches_found,
        },
    }
