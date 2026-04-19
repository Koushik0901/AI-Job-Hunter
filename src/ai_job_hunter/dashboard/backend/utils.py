from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ai_job_hunter.db import init_db
from ai_job_hunter.env_utils import (
    env_or_default,
    load_dotenv as _shared_load_dotenv,
    local_timezone,
    local_timezone_name,
    local_today,
    now_iso,
)

_REPO_DIR = Path(__file__).resolve().parents[4]

__all__ = [
    "load_dotenv",
    "local_timezone",
    "local_timezone_name",
    "local_today",
    "now_iso",
    "resolve_db_config",
    "get_conn",
    "env_or_default",
]


def load_dotenv() -> None:
    _shared_load_dotenv(_REPO_DIR / ".env")


def resolve_db_config() -> tuple[str, str]:
    turso_url = (os.getenv("TURSO_URL") or "").strip()
    turso_token = (os.getenv("TURSO_AUTH_TOKEN") or "").strip()
    if turso_url:
        if not turso_token:
            raise RuntimeError(
                "TURSO_AUTH_TOKEN is required when TURSO_URL is configured."
            )
        return turso_url, turso_token
    db_path = (os.getenv("DB_PATH") or str(_REPO_DIR / "jobs.db")).strip()
    return db_path, ""


def get_conn() -> Any:
    db_url, db_token = resolve_db_config()
    return init_db(db_url, db_token)


