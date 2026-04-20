from __future__ import annotations

import logging
import time

from ai_job_hunter.env_utils import load_dotenv

load_dotenv()

from ai_job_hunter.dashboard.backend.task_handlers import run_operation
from ai_job_hunter.dashboard.backend.task_queue import get_dashboard_task_queue

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    queue = get_dashboard_task_queue()
    queue.startup()
    if not queue.enabled:
        raise RuntimeError("Redis task queue is not available. Set REDIS_URL and ensure Redis is reachable.")
    logger.info("Dashboard worker started.")
    while True:
        task = queue.pop(timeout_seconds=5)
        if not task:
            continue
        operation_id = str(task.get("operation_id") or "").strip()
        kind = str(task.get("kind") or "").strip()
        params = task.get("params") if isinstance(task.get("params"), dict) else {}
        if not operation_id or not kind:
            logger.warning("Ignoring malformed task payload: %s", task)
            continue
        try:
            run_operation(operation_id, kind, params)
        except Exception:
            # Operation status is updated in run_operation; keep worker alive.
            time.sleep(0.2)


if __name__ == "__main__":
    main()
