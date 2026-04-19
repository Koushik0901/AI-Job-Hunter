"""Shared helpers for .env loading and timezone resolution.

Kept as a flat top-level module so both CLI-layer code (notify, cli) and
dashboard-layer code can import without inverting the dependency direction.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_DEFAULT_TZ = "UTC"


def _repo_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def load_dotenv(path: Path | None = None) -> None:
    """Load KEY=VALUE pairs from .env into os.environ. Does not overwrite existing vars."""
    target = path if path is not None else _repo_dir() / ".env"
    if not target.exists():
        return
    with target.open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def local_timezone_name() -> str:
    raw = (
        os.getenv("JOB_HUNTER_TIMEZONE")
        or os.getenv("TIMEZONE")
        or os.getenv("TZ")
        or _DEFAULT_TZ
    )
    return str(raw).strip() or _DEFAULT_TZ


def local_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(local_timezone_name())
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def local_today() -> str:
    return datetime.now(local_timezone()).date().isoformat()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def env_or_default(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    cleaned = value.strip()
    return cleaned or default
