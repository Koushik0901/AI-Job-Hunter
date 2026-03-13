from __future__ import annotations

import hashlib
import json
from typing import Any

try:
    import redis
except Exception:  # pragma: no cover - import optional by design
    redis = None  # type: ignore[assignment]


class DashboardCache:
    def __init__(self, url: str | None) -> None:
        self._url = (url or "").strip()
        self._client: Any | None = None
        if not self._url or redis is None:
            return
        try:
            self._client = redis.from_url(self._url, decode_responses=True)
            self._client.ping()
        except Exception:
            self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def health(self) -> dict[str, Any]:
        if not self._url:
            return {
                "configured": False,
                "healthy": False,
                "message": "REDIS_URL not configured.",
            }
        if redis is None:
            return {
                "configured": True,
                "healthy": False,
                "message": "redis dependency unavailable.",
            }
        if self._client is None:
            return {
                "configured": True,
                "healthy": False,
                "message": "Redis client unavailable.",
            }
        try:
            self._client.ping()
            return {
                "configured": True,
                "healthy": True,
                "message": "Redis reachable.",
            }
        except Exception as error:
            return {
                "configured": True,
                "healthy": False,
                "message": str(error),
            }

    def _safe(self, fn: Any, default: Any) -> Any:
        try:
            return fn()
        except Exception:
            return default

    def get_json(self, key: str) -> dict[str, Any] | list[Any] | None:
        if not self._client:
            return None

        raw = self._safe(lambda: self._client.get(key), None)
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if isinstance(value, (dict, list)):
            return value
        return None

    def set_json(self, key: str, value: dict[str, Any] | list[Any], ttl_seconds: int) -> None:
        if not self._client:
            return
        encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        self._safe(lambda: self._client.setex(key, ttl_seconds, encoded), None)

    def delete(self, *keys: str) -> None:
        if not self._client or not keys:
            return
        self._safe(lambda: self._client.delete(*keys), None)

    def expire(self, key: str, ttl_seconds: int) -> None:
        if not self._client:
            return
        self._safe(lambda: self._client.expire(key, ttl_seconds), None)

    def delete_pattern(self, pattern: str) -> None:
        if not self._client:
            return
        keys = self._safe(lambda: list(self._client.scan_iter(match=pattern, count=200)), [])
        if not keys:
            return
        self._safe(lambda: self._client.delete(*keys), None)

    def zadd(self, key: str, members: dict[str, float]) -> None:
        if not self._client or not members:
            return
        self._safe(lambda: self._client.zadd(key, members), None)

    def zcard(self, key: str) -> int:
        if not self._client:
            return 0
        value = self._safe(lambda: self._client.zcard(key), 0)
        if isinstance(value, int):
            return value
        return 0

    def zrange(self, key: str, start: int, end: int) -> list[str]:
        if not self._client:
            return []
        value = self._safe(lambda: self._client.zrange(key, start, end), [])
        if isinstance(value, list):
            return [item for item in value if isinstance(item, str)]
        return []

    def zrem(self, key: str, *members: str) -> None:
        if not self._client or not members:
            return
        self._safe(lambda: self._client.zrem(key, *members), None)


def hash_id(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()
