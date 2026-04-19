from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

try:
    import redis
except Exception:  # pragma: no cover - dependency remains optional at runtime
    redis = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)

_CACHE_NAMESPACE = "dashboard:v3"
_LOCAL_REDIS_HOSTS = {"localhost", "127.0.0.1", "host.docker.internal"}
_REDIS_CONTAINER_NAME = "ai-job-hunter-redis"
_REDIS_IMAGE = "redis:7-alpine"
_REDIS_PORT = "6379:6379"
_DOCKER_TIMEOUT_SECONDS = 15
_REDIS_READY_TIMEOUT_SECONDS = 15.0
_REDIS_READY_POLL_SECONDS = 0.5

_CACHE_SINGLETON: DashboardCache | None = None
_CACHE_SINGLETON_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def hash_id(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


class DashboardCache:
    def __init__(self, url: str | None) -> None:
        self._url = (url or "").strip()
        self._client: Any | None = None
        self._startup_once = False
        self._startup_lock = threading.Lock()
        self._hot_guard = threading.Lock()
        self._hot_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._health: dict[str, Any] = {
            "configured": bool(self._url),
            "healthy": False,
            "message": "REDIS_URL not configured."
            if not self._url
            else "Redis not initialized.",
        }

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @property
    def configured(self) -> bool:
        return bool(self._url)

    def startup(self) -> None:
        with self._startup_lock:
            if self._startup_once:
                return
            self._startup_once = True
            self._initialize()

    def close(self) -> None:
        client = self._client
        self._client = None
        if client is None:
            return
        try:
            client.close()
        except Exception:
            logger.debug("Ignoring Redis close failure.", exc_info=True)

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
            return dict(self._health)
        try:
            self._client.ping()
            return {
                "configured": True,
                "healthy": True,
                "message": self._health.get("message") or "Redis reachable.",
            }
        except Exception as error:
            return {
                "configured": True,
                "healthy": False,
                "message": f"Redis ping failed after startup: {error}",
            }

    def jobs_list_key(self, params: dict[str, Any]) -> str:
        normalized = {
            "status": _normalize_query_string(params.get("status"), lowercase=False),
            "q": _normalize_query_string(params.get("q")),
            "ats": _normalize_query_string(params.get("ats")),
            "company": _normalize_query_string(params.get("company")),
            "posted_after": _normalize_query_string(
                params.get("posted_after"), lowercase=False
            ),
            "posted_before": _normalize_query_string(
                params.get("posted_before"), lowercase=False
            ),
            "sort": _normalize_query_string(params.get("sort"), lowercase=False),
            "limit": int(params.get("limit") or 0),
            "offset": int(params.get("offset") or 0),
        }
        return f"{_CACHE_NAMESPACE}:jobs:list:{hash_id(_json_dumps(normalized))}"

    def job_detail_key(self, job_id: str) -> str:
        return f"{_CACHE_NAMESPACE}:job:{job_id}"

    def job_events_key(self, job_id: str) -> str:
        return f"{_CACHE_NAMESPACE}:job:{job_id}:events"

    def stats_key(self) -> str:
        return f"{_CACHE_NAMESPACE}:stats"

    def bootstrap_key(self) -> str:
        return f"{_CACHE_NAMESPACE}:bootstrap"

    def profile_key(self) -> str:
        return f"{_CACHE_NAMESPACE}:profile"

    def skill_aliases_key(self) -> str:
        return f"{_CACHE_NAMESPACE}:meta:skill-aliases"

    def daily_briefing_key(self, brief_date: str | None = None) -> str:
        suffix = (brief_date or "latest").strip() or "latest"
        return f"{_CACHE_NAMESPACE}:assistant:daily-briefing:{suffix}"

    def action_queue_key(self) -> str:
        return f"{_CACHE_NAMESPACE}:assistant:action-queue"

    def dashboard_event_key(self) -> str:
        return f"{_CACHE_NAMESPACE}:events:dashboard"

    def actions_today_key(self) -> str:
        return f"{_CACHE_NAMESPACE}:assistant:actions-today"

    def conversion_key(self) -> str:
        return f"{_CACHE_NAMESPACE}:assistant:conversion"

    def source_quality_key(self) -> str:
        return f"{_CACHE_NAMESPACE}:assistant:source-quality"

    def profile_gaps_key(self) -> str:
        return f"{_CACHE_NAMESPACE}:assistant:profile-gaps"

    def profile_insights_key(self) -> str:
        return f"{_CACHE_NAMESPACE}:assistant:profile-insights"

    def get_cached_envelope(self, key: str) -> dict[str, Any] | None:
        hot = self._get_hot_envelope(key)
        if hot is not None:
            hot["_cache_source"] = "HOT"
            return hot
        if self._client is None:
            return None
        raw = self._safe(lambda: self._client.get(key), None)
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        if not isinstance(payload.get("etag"), str):
            return None
        if "body" not in payload:
            return None
        self._set_hot_envelope(key, payload, 5)
        payload["_cache_source"] = "REDIS"
        return payload

    def set_cached_envelope(
        self, key: str, body: Any, ttl_seconds: int
    ) -> dict[str, Any]:
        envelope = {
            "etag": self.build_etag(body),
            "cached_at": _now_iso(),
            "body": body,
        }
        self._set_hot_envelope(key, envelope, min(max(ttl_seconds, 1), 10))
        if self._client is not None:
            encoded = _json_dumps(envelope)
            self._safe(lambda: self._client.setex(key, ttl_seconds, encoded), None)
        return envelope

    def get_dashboard_event(self) -> dict[str, Any] | None:
        key = self.dashboard_event_key()
        with self._hot_guard:
            hot = self._hot_cache.get(key)
            if hot is not None:
                expires_at, payload = hot
                if expires_at > time.time():
                    return dict(payload.get("body") or {})
                self._hot_cache.pop(key, None)
        if self._client is None:
            return None
        raw = self._safe(lambda: self._client.get(key), None)
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        body = payload.get("body")
        if not isinstance(body, dict):
            return None
        self._set_hot_envelope(key, {"body": body}, 30)
        return dict(body)

    def publish_dashboard_event(
        self,
        event: str,
        scope: str,
        **payload: Any,
    ) -> dict[str, Any]:
        body = {
            "id": uuid.uuid4().hex,
            "event": event,
            "scope": scope,
            "at": _now_iso(),
            **payload,
        }
        key = self.dashboard_event_key()
        self._set_hot_envelope(key, {"body": body}, 30)
        if self._client is not None:
            self._safe(
                lambda: self._client.setex(
                    key,
                    60 * 60 * 24,
                    _json_dumps({"body": body}),
                ),
                None,
            )
        return body

    def build_etag(self, body: Any) -> str:
        return f'"{hash_id(_json_dumps(body))}"'

    def delete(self, *keys: str) -> None:
        if keys:
            with self._hot_guard:
                for key in keys:
                    self._hot_cache.pop(key, None)
        if self._client is None or not keys:
            return
        self._safe(lambda: self._client.delete(*keys), None)

    def delete_pattern(
        self, pattern: str, *, exclude_suffix: str | None = None
    ) -> None:
        if self._client is None:
            return
        keys = self._safe(
            lambda: list(self._client.scan_iter(match=pattern, count=200)), []
        )
        if exclude_suffix:
            keys = [
                key
                for key in keys
                if isinstance(key, str) and not key.endswith(exclude_suffix)
            ]
        if not keys:
            return
        with self._hot_guard:
            for key in keys:
                if isinstance(key, str):
                    self._hot_cache.pop(key, None)
        self._safe(lambda: self._client.delete(*keys), None)

    def invalidate_jobs_lists(self) -> None:
        self.delete_pattern(f"{_CACHE_NAMESPACE}:jobs:list:*")

    def invalidate_job_detail(self, job_id: str) -> None:
        self.delete(self.job_detail_key(job_id))

    def invalidate_job_events(self, job_id: str) -> None:
        self.delete(self.job_events_key(job_id))

    def invalidate_stats(self) -> None:
        self.delete(self.stats_key())

    def invalidate_bootstrap(self) -> None:
        self.delete(self.bootstrap_key())

    def invalidate_profile(self) -> None:
        self.delete(self.profile_key())

    def invalidate_all_job_details(self) -> None:
        self.delete_pattern(f"{_CACHE_NAMESPACE}:job:*", exclude_suffix=":events")

    def invalidate_for_profile_change(self) -> None:
        self.invalidate_jobs_lists()
        self.invalidate_all_job_details()
        self.invalidate_stats()
        self.invalidate_profile()
        self.invalidate_bootstrap()
        self.invalidate_for_assistant_change()

    def invalidate_for_score_recompute(self) -> None:
        self.invalidate_jobs_lists()
        self.invalidate_all_job_details()
        self.invalidate_stats()
        self.invalidate_bootstrap()
        self.invalidate_for_assistant_change()

    def invalidate_for_workspace_refresh(self) -> None:
        self.invalidate_jobs_lists()
        self.invalidate_all_job_details()
        self.invalidate_stats()
        self.invalidate_bootstrap()
        self.invalidate_for_assistant_change()

    def invalidate_for_assistant_change(self) -> None:
        self.invalidate_bootstrap()
        self.delete_pattern(f"{_CACHE_NAMESPACE}:assistant:*")

    def _get_hot_envelope(self, key: str) -> dict[str, Any] | None:
        with self._hot_guard:
            cached = self._hot_cache.get(key)
            if cached is None:
                return None
            expires_at, envelope = cached
            if expires_at <= time.time():
                self._hot_cache.pop(key, None)
                return None
            return dict(envelope)

    def _set_hot_envelope(
        self, key: str, envelope: dict[str, Any], ttl_seconds: int
    ) -> None:
        with self._hot_guard:
            self._hot_cache[key] = (
                time.time() + float(max(1, ttl_seconds)),
                dict(envelope),
            )

    def _initialize(self) -> None:
        if not self._url:
            self._health = {
                "configured": False,
                "healthy": False,
                "message": "REDIS_URL not configured.",
            }
            return
        if redis is None:
            self._health = {
                "configured": True,
                "healthy": False,
                "message": "redis dependency unavailable.",
            }
            return

        host = (urlparse(self._url).hostname or "").strip().lower()
        startup_message = "Redis configured."
        if host in _LOCAL_REDIS_HOSTS:
            direct_client = self._try_connect_once()
            if direct_client is not None:
                self._client = direct_client
                self._health = {
                    "configured": True,
                    "healthy": True,
                    "message": "Local Redis already reachable.",
                }
                return
            try:
                startup_message = self._ensure_local_redis_container()
            except Exception as error:
                self._client = None
                self._health = {
                    "configured": True,
                    "healthy": False,
                    "message": f"Local Redis auto-start skipped: {error}. Cache disabled.",
                }
                logger.warning(self._health["message"])
                return
        else:
            startup_message = (
                "Remote Redis configured; container auto-management skipped."
            )

        self._connect(startup_message)

    def _connect(self, startup_message: str) -> None:
        try:
            self._client = self._wait_for_redis()
            self._health = {
                "configured": True,
                "healthy": True,
                "message": startup_message,
            }
        except Exception as error:
            self._client = None
            self._health = {
                "configured": True,
                "healthy": False,
                "message": f"{startup_message} Redis ping failed after startup: {error}",
            }
            logger.warning(self._health["message"])

    def _wait_for_redis(self) -> Any:
        if redis is None:
            raise RuntimeError("redis dependency unavailable")
        deadline = time.monotonic() + _REDIS_READY_TIMEOUT_SECONDS
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                client = redis.from_url(
                    self._url,
                    decode_responses=True,
                    socket_timeout=1,
                    socket_connect_timeout=1,
                    health_check_interval=30,
                )
                client.ping()
                return client
            except (
                Exception
            ) as error:  # pragma: no cover - exercised via startup failure tests
                last_error = error
                time.sleep(_REDIS_READY_POLL_SECONDS)
        if last_error is None:
            raise RuntimeError("Redis did not become reachable in time.")
        raise last_error

    def _try_connect_once(self) -> Any | None:
        if redis is None or not self._url:
            return None
        try:
            client = redis.from_url(
                self._url,
                decode_responses=True,
                socket_timeout=1,
                socket_connect_timeout=1,
                health_check_interval=30,
            )
            client.ping()
            return client
        except Exception:
            return None

    def _ensure_local_redis_container(self) -> str:
        inspect = self._run_docker(
            ["inspect", _REDIS_CONTAINER_NAME], allow_failure=True
        )
        if inspect.returncode == 0:
            try:
                payload = json.loads(inspect.stdout or "[]")
                running = bool(payload and payload[0].get("State", {}).get("Running"))
            except Exception:
                running = False
            if running:
                logger.info(
                    "Redis container %s already running.", _REDIS_CONTAINER_NAME
                )
                return "Local Redis container already running."
            self._run_docker(["start", _REDIS_CONTAINER_NAME])
            logger.info("Redis container %s started.", _REDIS_CONTAINER_NAME)
            return "Local Redis container started."

        self._ensure_image()
        self._run_docker(
            [
                "run",
                "-d",
                "--name",
                _REDIS_CONTAINER_NAME,
                "-p",
                _REDIS_PORT,
                _REDIS_IMAGE,
                "redis-server",
                "--save",
                "",
                "--appendonly",
                "no",
                "--maxmemory",
                "128mb",
                "--maxmemory-policy",
                "allkeys-lru",
            ]
        )
        logger.info("Redis container %s created and started.", _REDIS_CONTAINER_NAME)
        return "Local Redis container created and started."

    def _ensure_image(self) -> None:
        inspect = self._run_docker(
            ["image", "inspect", _REDIS_IMAGE], allow_failure=True
        )
        if inspect.returncode == 0:
            return
        self._run_docker(["pull", _REDIS_IMAGE])

    def _run_docker(
        self, args: list[str], *, allow_failure: bool = False
    ) -> subprocess.CompletedProcess[str]:
        try:
            completed = subprocess.run(
                ["docker", *args],
                capture_output=True,
                text=True,
                timeout=_DOCKER_TIMEOUT_SECONDS,
                check=False,
            )
        except FileNotFoundError as error:
            message = f"Docker unavailable: {error}"
            if allow_failure:
                self._health = {
                    "configured": True,
                    "healthy": False,
                    "message": message,
                }
                logger.warning(message)
                return subprocess.CompletedProcess(
                    ["docker", *args], returncode=1, stdout="", stderr=message
                )
            raise RuntimeError(message) from error
        except subprocess.TimeoutExpired as error:
            message = f"Docker command timed out: {' '.join(args)}"
            if allow_failure:
                self._health = {
                    "configured": True,
                    "healthy": False,
                    "message": message,
                }
                logger.warning(message)
                return subprocess.CompletedProcess(
                    ["docker", *args], returncode=1, stdout="", stderr=str(error)
                )
            raise RuntimeError(message) from error

        if completed.returncode != 0 and not allow_failure:
            stderr = (completed.stderr or "").strip()
            raise RuntimeError(stderr or f"Docker command failed: {' '.join(args)}")
        return completed

    def _safe(self, fn: Any, default: Any) -> Any:
        try:
            return fn()
        except Exception:
            logger.debug("Ignoring Redis operation failure.", exc_info=True)
            return default


def _normalize_query_string(value: Any, *, lowercase: bool = True) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text.lower() if lowercase else text


def get_dashboard_cache() -> DashboardCache:
    global _CACHE_SINGLETON
    with _CACHE_SINGLETON_LOCK:
        if _CACHE_SINGLETON is None:
            _CACHE_SINGLETON = DashboardCache(os.getenv("REDIS_URL"))
        return _CACHE_SINGLETON


def reset_dashboard_cache_for_tests() -> None:
    global _CACHE_SINGLETON
    with _CACHE_SINGLETON_LOCK:
        if _CACHE_SINGLETON is not None:
            _CACHE_SINGLETON.close()
        _CACHE_SINGLETON = None
