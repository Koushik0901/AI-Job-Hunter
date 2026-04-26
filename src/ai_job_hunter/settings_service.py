from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

SECRET_KEYS: frozenset[str] = frozenset({
    "OPENROUTER_API_KEY",
    "TELEGRAM_TOKEN",
    "TELEGRAM_CHAT_ID",
})

MODEL_DEFAULTS: dict[str, str] = {
    "LLM_MODEL": "z-ai/glm-5.1",
    "SLM_MODEL": "google/gemma-4-31b-it",
    "ENRICHMENT_MODEL": "openai/gpt-oss-120b",
    "DESCRIPTION_FORMAT_MODEL": "openai/gpt-oss-120b",
    "EMBEDDING_MODEL": "qwen/qwen3-embedding-8b",
    "JOB_HUNTER_TIMEZONE": "America/Edmonton",
}

KNOWN_KEYS: frozenset[str] = SECRET_KEYS | frozenset(MODEL_DEFAULTS)

_CACHE_TTL: float = 60.0
_cache: dict[str, tuple[str, float]] = {}
_conn: Any = None


def _get_conn() -> Any:
    global _conn
    if _conn is not None:
        return _conn
    from ai_job_hunter.env_utils import load_dotenv
    from ai_job_hunter.db import init_db
    load_dotenv()
    db_url = os.getenv("DB_PATH", "jobs.db")
    auth_token = os.getenv("TURSO_AUTH_TOKEN", "")
    _conn = init_db(db_url, auth_token)
    return _conn


def _db_read(key: str) -> str | None:
    try:
        row = _get_conn().execute(
            "SELECT value FROM user_settings WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        from ai_job_hunter import settings_crypto
        return settings_crypto.decrypt(row[0]) if key in SECRET_KEYS else row[0]
    except Exception as exc:
        logger.debug("settings_service._db_read(%r) failed: %s", key, exc)
        return None


def get(key: str, default: str = "") -> str:
    now = time.monotonic()
    entry = _cache.get(key)
    if entry is not None and entry[1] > now:
        return entry[0]
    value = _db_read(key)
    if value is None:
        value = os.getenv(key) or MODEL_DEFAULTS.get(key) or default
    _cache[key] = (value, now + _CACHE_TTL)
    return value


def set(key: str, value: str) -> None:
    if key not in KNOWN_KEYS:
        raise ValueError(f"Unknown settings key: {key!r}")
    from ai_job_hunter import settings_crypto
    from ai_job_hunter.env_utils import now_iso
    stored = settings_crypto.encrypt(value) if key in SECRET_KEYS else value
    _get_conn().execute(
        "INSERT OR REPLACE INTO user_settings (key, value, updated_at) VALUES (?, ?, ?)",
        (key, stored, now_iso()),
    )
    _cache.pop(key, None)


def get_all_masked() -> dict[str, str]:
    from ai_job_hunter import settings_crypto
    result: dict[str, str] = {}
    for key in KNOWN_KEYS:
        raw = get(key)
        result[key] = settings_crypto.mask(raw) if key in SECRET_KEYS else raw
    return result
