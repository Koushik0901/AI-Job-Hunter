from __future__ import annotations

import logging
import os
from typing import Final

logger = logging.getLogger(__name__)

_KEY_ENV: Final[str] = "SETTINGS_ENCRYPTION_KEY"
_WARNED: bool = False
_fernet: object | None = None


def _get_fernet() -> object | None:
    global _fernet, _WARNED
    if _fernet is not None:
        return _fernet
    raw = os.getenv(_KEY_ENV, "").strip()
    if not raw:
        if not _WARNED:
            logger.warning(
                "SETTINGS_ENCRYPTION_KEY is not set -- secrets are stored "
                "as plaintext. Set this variable for hosted instances."
            )
            _WARNED = True
        return None
    try:
        from cryptography.fernet import Fernet

        _fernet = Fernet(raw.encode())
        return _fernet
    except Exception as exc:
        logger.error("SETTINGS_ENCRYPTION_KEY is invalid: %s", exc)
        return None


def encrypt(plaintext: str) -> str:
    f = _get_fernet()
    if f is None:
        return plaintext
    return f.encrypt(plaintext.encode()).decode()  # type: ignore[attr-defined]


def decrypt(ciphertext: str) -> str:
    f = _get_fernet()
    if f is None:
        return ciphertext
    try:
        return f.decrypt(ciphertext.encode()).decode()  # type: ignore[attr-defined]
    except Exception:
        # Value was stored as plaintext before encryption was enabled
        return ciphertext


def mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return value[:4] + "****" + value[-4:]
