from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import unquote


def decode_job_url(encoded: str) -> str:
    return unquote(encoded)


def normalize_tracking_patch(payload: dict[str, object]) -> dict[str, object]:
    patch = {k: v for k, v in payload.items() if v is not None}
    if patch.get("status") == "applied" and not patch.get("applied_at"):
        patch["applied_at"] = datetime.now(timezone.utc).date().isoformat()
    return patch
