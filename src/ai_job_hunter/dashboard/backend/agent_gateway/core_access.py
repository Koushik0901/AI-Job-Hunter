from __future__ import annotations

from typing import Any

from ai_job_hunter.db import get_workspace_operation
from ai_job_hunter.dashboard.backend import artifacts as artifact_svc
from ai_job_hunter.dashboard.backend import repository
from ai_job_hunter.dashboard.backend.core_actions import enqueue_artifact_generation


class CoreReadClient:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def search_jobs(self, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        items, _ = repository.list_jobs(
            self._conn,
            status="not_applied",
            q=query.strip() or None,
            ats=None,
            company=None,
            posted_after=None,
            posted_before=None,
            sort="match_desc",
            limit=limit,
            offset=0,
        )
        return items

    def get_job_detail(self, job_id: str) -> dict[str, Any] | None:
        return repository.get_job_detail(self._conn, job_id)

    def list_queue(self) -> list[dict[str, Any]]:
        return artifact_svc.list_queue(self._conn)

    def get_job_artifacts(self, job_id: str) -> list[dict[str, Any]]:
        return artifact_svc.get_artifacts_for_job(job_id, self._conn)

    def get_artifact(self, artifact_id: int) -> dict[str, Any] | None:
        return artifact_svc.get_artifact(artifact_id, self._conn)

    def list_base_documents(self, doc_type: str | None = None) -> list[dict[str, Any]]:
        docs = artifact_svc.list_base_documents(self._conn)
        if doc_type is None:
            return docs
        return [doc for doc in docs if str(doc.get("doc_type") or "") == doc_type]

    def pick_default_base_document(self, doc_type: str) -> dict[str, Any] | None:
        docs = self.list_base_documents(doc_type)
        if not docs:
            return None
        return next((doc for doc in docs if bool(doc.get("is_default"))), docs[0])

    def get_operation(self, operation_id: str) -> dict[str, Any] | None:
        return get_workspace_operation(self._conn, operation_id)


class CoreActionClient:
    def enqueue_resume_generation(self, job_id: str, base_doc_id: int) -> dict[str, Any]:
        return enqueue_artifact_generation(job_id, "resume", base_doc_id)

    def enqueue_cover_letter_generation(self, job_id: str, base_doc_id: int) -> dict[str, Any]:
        return enqueue_artifact_generation(job_id, "cover_letter", base_doc_id)
