from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

try:
    import redis
except Exception:  # pragma: no cover
    redis = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)

_TASK_NAMESPACE = "dashboard:v3:tasks"
_QUEUE_SINGLETON: "DashboardTaskQueue | None" = None
_QUEUE_SINGLETON_LOCK = threading.Lock()


class DashboardTaskQueue:
    def __init__(self, url: str | None) -> None:
        self._url = (url or "").strip()
        self._client: Any | None = None
        self._startup_lock = threading.Lock()
        self._startup_once = False

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def startup(self) -> None:
        with self._startup_lock:
            if self._startup_once:
                return
            self._startup_once = True
            if redis is None or not self._url:
                return
            try:
                client = redis.from_url(
                    self._url,
                    decode_responses=True,
                    socket_timeout=1,
                    socket_connect_timeout=1,
                    health_check_interval=30,
                )
                client.ping()
                self._client = client
            except Exception:
                logger.debug("Dashboard task queue unavailable.", exc_info=True)
                self._client = None

    def close(self) -> None:
        client = self._client
        self._client = None
        if client is None:
            return
        try:
            client.close()
        except Exception:
            logger.debug("Ignoring task queue close failure.", exc_info=True)

    def enqueue(self, task: dict[str, Any]) -> bool:
        if self._client is None:
            return False
        try:
            self._client.rpush(_TASK_NAMESPACE, json.dumps(task, ensure_ascii=True))
            return True
        except Exception:
            logger.debug("Task enqueue failed.", exc_info=True)
            return False

    def pop(self, timeout_seconds: int = 5) -> dict[str, Any] | None:
        if self._client is None:
            return None
        try:
            item = self._client.blpop(_TASK_NAMESPACE, timeout=timeout_seconds)
        except Exception:
            logger.debug("Task dequeue failed.", exc_info=True)
            return None
        if not item:
            return None
        _, payload = item
        try:
            parsed = json.loads(payload or "{}")
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None


def get_dashboard_task_queue() -> DashboardTaskQueue:
    global _QUEUE_SINGLETON
    with _QUEUE_SINGLETON_LOCK:
        if _QUEUE_SINGLETON is None:
            _QUEUE_SINGLETON = DashboardTaskQueue(os.getenv("REDIS_URL"))
        return _QUEUE_SINGLETON
