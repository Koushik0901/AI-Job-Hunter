from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PROMPTS_DIR = Path(__file__).resolve().parents[4] / "prompts"


@lru_cache(maxsize=8)
def load_prompt_yaml(file_name: str) -> dict[str, Any]:
    path = PROMPTS_DIR / file_name
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Prompt YAML must be a mapping: {path}")
    return data


def get_prompt_text(file_name: str, key: str) -> str:
    payload = load_prompt_yaml(file_name)
    value = payload.get(key)
    if not isinstance(value, str):
        raise KeyError(f"Missing string prompt key '{key}' in {file_name}")
    return value


def load_resume_scoring_prompt() -> str:
    return get_prompt_text("resume_scoring_prompt.yaml", "resume_scoring_prompt")


def load_resume_rewriter_prompt() -> str:
    return get_prompt_text("resume_rewriter_prompt.yaml", "resume_rewriter_prompt")


def load_resume_jd_decomposer_prompt() -> str:
    return get_prompt_text("resume_jd_decomposer_prompt.yaml", "resume_jd_decomposer_prompt")


def load_resume_evidence_miner_prompt() -> str:
    return get_prompt_text("resume_evidence_miner_prompt.yaml", "resume_evidence_miner_prompt")


def load_resume_planner_prompt() -> str:
    return get_prompt_text("resume_planner_prompt.yaml", "resume_planner_prompt")


def load_json_repair_prompt() -> str:
    return get_prompt_text("swarm_runtime_prompts.yaml", "json_repair_prompt")
