"""User profile configuration loader.

Reads ``config/profile.yaml`` (falling back to ``config/profile.example.yaml``)
and exposes structured accessors for location filters, role/title keywords,
and notification bucketing.

The cached profile is intentionally simple (plain dict) so the rest of the
codebase can stay decoupled from dataclass details.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


_CACHE: dict[str, Any] | None = None


def _repo_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def _profile_paths() -> list[Path]:
    override = os.getenv("AI_JOB_HUNTER_PROFILE")
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override))
    repo = _repo_dir()
    candidates.extend([
        repo / "config" / "profile.yaml",
        repo / "config" / "profile.example.yaml",
    ])
    return candidates


def _load() -> dict[str, Any]:
    for path in _profile_paths():
        if path.is_file():
            with path.open(encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
            if not isinstance(data, dict):
                raise ValueError(f"{path} must contain a YAML mapping at the top level")
            return data
    return {}


def get_profile(*, refresh: bool = False) -> dict[str, Any]:
    global _CACHE
    if refresh or _CACHE is None:
        _CACHE = _load()
    return _CACHE


def get_locations() -> dict[str, Any]:
    return get_profile().get("locations", {}) or {}


def get_roles() -> dict[str, Any]:
    return get_profile().get("roles", {}) or {}


def get_notifications() -> dict[str, Any]:
    return get_profile().get("notifications", {}) or {}


def notifications_enabled() -> bool:
    return bool(get_notifications().get("enabled", True))
