from __future__ import annotations

import logging
import threading
import uuid
from typing import Any

from ai_job_hunter.db import create_workspace_operation, init_db
from ai_job_hunter.dashboard.backend.task_handlers import run_operation as run_queued_operation
from ai_job_hunter.dashboard.backend.task_queue import get_dashboard_task_queue
from ai_job_hunter.dashboard.backend.utils import now_iso, resolve_db_config

logger = logging.getLogger(__name__)


def _conn() -> Any:
    db_url, db_token = resolve_db_config()
    return init_db(db_url, db_token)


def create_operation(kind: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    conn = _conn()
    try:
        return create_workspace_operation(
            conn,
            {
                "id": str(uuid.uuid4()),
                "kind": kind,
                "status": "queued",
                "params": params or {},
                "summary": {},
                "started_at": now_iso(),
            },
        )
    finally:
        conn.close()


def enqueue_operation(kind: str, params: dict[str, Any]) -> dict[str, Any]:
    operation = create_operation(kind, params)
    queue = get_dashboard_task_queue()
    queue.startup()
    task = {"operation_id": str(operation["id"]), "kind": kind, "params": params}
    if queue.enabled and queue.enqueue(task):
        return operation

    def runner() -> None:
        try:
            run_queued_operation(str(operation["id"]), kind, params)
        except Exception:
            logger.debug("Fallback background operation failed.", exc_info=True)

    threading.Thread(
        target=runner,
        name=f"workspace-op-{kind}",
        daemon=True,
    ).start()
    return operation


def enqueue_artifact_generation(
    job_id: str,
    artifact_type: str,
    base_doc_id: int,
) -> dict[str, Any]:
    return enqueue_operation(
        "artifact_generate",
        {
            "job_id": job_id,
            "artifact_type": artifact_type,
            "base_doc_id": base_doc_id,
        },
    )
