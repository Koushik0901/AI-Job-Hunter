import time
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def reset_service():
    """Reset all module-level state between tests."""
    import ai_job_hunter.settings_service as ss
    import ai_job_hunter.settings_crypto as sc
    ss._cache.clear()
    ss._conn = None
    sc._fernet = None
    sc._WARNED = False
    yield
    ss._cache.clear()
    ss._conn = None


def _mock_conn(db_value=None):
    """Return a mock DB connection. db_value is the raw stored value or None."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = (db_value,) if db_value is not None else None
    conn.execute.return_value = cursor
    return conn


def test_get_returns_db_value_over_env(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "env-model")
    conn = _mock_conn("db-model")
    with patch("ai_job_hunter.settings_service._get_conn", return_value=conn):
        from ai_job_hunter import settings_service as ss
        assert ss.get("LLM_MODEL") == "db-model"


def test_get_falls_back_to_env_when_no_db_row(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "env-model")
    conn = _mock_conn(None)
    with patch("ai_job_hunter.settings_service._get_conn", return_value=conn):
        from ai_job_hunter import settings_service as ss
        assert ss.get("LLM_MODEL") == "env-model"


def test_get_falls_back_to_default_when_no_env_and_no_db(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    conn = _mock_conn(None)
    with patch("ai_job_hunter.settings_service._get_conn", return_value=conn):
        from ai_job_hunter import settings_service as ss
        assert ss.get("LLM_MODEL") == "z-ai/glm-5.1"


def test_get_returns_explicit_default_for_unknown_key(monkeypatch):
    monkeypatch.delenv("UNKNOWN_KEY", raising=False)
    conn = _mock_conn(None)
    with patch("ai_job_hunter.settings_service._get_conn", return_value=conn):
        from ai_job_hunter import settings_service as ss
        assert ss.get("UNKNOWN_KEY", "my-fallback") == "my-fallback"


def test_get_caches_result_and_avoids_second_db_call():
    conn = _mock_conn("cached-val")
    with patch("ai_job_hunter.settings_service._get_conn", return_value=conn):
        from ai_job_hunter import settings_service as ss
        ss.get("LLM_MODEL")
        ss.get("LLM_MODEL")
    # DB queried only once despite two get() calls
    assert conn.execute.call_count == 1


def test_get_cache_expires_after_ttl(monkeypatch):
    conn = _mock_conn("value")
    with patch("ai_job_hunter.settings_service._get_conn", return_value=conn):
        from ai_job_hunter import settings_service as ss
        ss.get("LLM_MODEL")  # populate cache

        # Manually expire the cache entry
        key = "LLM_MODEL"
        ss._cache[key] = (ss._cache[key][0], time.monotonic() - 1)

        ss.get("LLM_MODEL")  # should re-query DB

    assert conn.execute.call_count == 2


def test_set_stores_plaintext_for_non_secret(monkeypatch):
    monkeypatch.delenv("SETTINGS_ENCRYPTION_KEY", raising=False)
    conn = _mock_conn(None)
    with patch("ai_job_hunter.settings_service._get_conn", return_value=conn), \
         patch("ai_job_hunter.env_utils.now_iso", return_value="2026-04-25T00:00:00"):
        from ai_job_hunter import settings_service as ss
        ss.set("LLM_MODEL", "openai/gpt-4o")

    conn.execute.assert_called_once_with(
        "INSERT OR REPLACE INTO user_settings (key, value, updated_at) VALUES (?, ?, ?)",
        ("LLM_MODEL", "openai/gpt-4o", "2026-04-25T00:00:00"),
    )


def test_set_encrypts_secret_keys(monkeypatch):
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", key)

    conn = _mock_conn(None)
    with patch("ai_job_hunter.settings_service._get_conn", return_value=conn), \
         patch("ai_job_hunter.env_utils.now_iso", return_value="2026-04-25T00:00:00"):
        from ai_job_hunter import settings_service as ss
        ss.set("OPENROUTER_API_KEY", "sk-real-key")

    stored_value = conn.execute.call_args[0][1][1]
    assert stored_value != "sk-real-key"  # encrypted
    # Decrypt and verify round-trip
    from ai_job_hunter import settings_crypto as sc
    assert sc.decrypt(stored_value) == "sk-real-key"


def test_set_invalidates_cache():
    conn = _mock_conn("old-value")
    with patch("ai_job_hunter.settings_service._get_conn", return_value=conn):
        from ai_job_hunter import settings_service as ss
        ss.get("LLM_MODEL")  # populate cache
        assert "LLM_MODEL" in ss._cache

        conn.execute.return_value.fetchone.return_value = ("new-value",)
        ss.set("LLM_MODEL", "new-value")
        assert "LLM_MODEL" not in ss._cache

        result = ss.get("LLM_MODEL")

    assert result == "new-value"


def test_set_rejects_unknown_key():
    from ai_job_hunter import settings_service as ss
    with pytest.raises(ValueError, match="Unknown settings key"):
        ss.set("TOTALLY_UNKNOWN", "value")


def test_get_all_masked_masks_secrets(monkeypatch):
    monkeypatch.delenv("SETTINGS_ENCRYPTION_KEY", raising=False)

    def fake_execute(sql, params=None):
        cursor = MagicMock()
        if params and params[0] == "OPENROUTER_API_KEY":
            cursor.fetchone.return_value = ("sk-or-v1-abcdef1234",)
        else:
            cursor.fetchone.return_value = None
        return cursor

    conn = MagicMock()
    conn.execute.side_effect = fake_execute

    with patch("ai_job_hunter.settings_service._get_conn", return_value=conn):
        from ai_job_hunter import settings_service as ss
        result = ss.get_all_masked()

    assert result["OPENROUTER_API_KEY"] == "sk-o****1234"
    assert result["LLM_MODEL"] == "z-ai/glm-5.1"  # non-secret, plaintext
    assert result["TELEGRAM_TOKEN"] == ""  # not set, empty masked as ""
