import pytest


def test_user_settings_table_created(tmp_path):
    """init_db() creates user_settings with the expected schema."""
    from ai_job_hunter.db import init_db

    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)

    rows = conn.execute("PRAGMA table_info(user_settings)").fetchall()
    col_names = [r[1] for r in rows]
    assert "key" in col_names
    assert "value" in col_names
    assert "updated_at" in col_names


def test_user_settings_upsert(tmp_path):
    """user_settings supports INSERT OR REPLACE (upsert) by primary key."""
    from ai_job_hunter.db import init_db

    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)

    conn.execute(
        "INSERT OR REPLACE INTO user_settings (key, value, updated_at) VALUES (?, ?, ?)",
        ("LLM_MODEL", "test-model", "2026-04-25T00:00:00"),
    )
    row = conn.execute(
        "SELECT value FROM user_settings WHERE key = ?", ("LLM_MODEL",)
    ).fetchone()
    assert row[0] == "test-model"

    # Upsert with new value
    conn.execute(
        "INSERT OR REPLACE INTO user_settings (key, value, updated_at) VALUES (?, ?, ?)",
        ("LLM_MODEL", "updated-model", "2026-04-25T01:00:00"),
    )
    row = conn.execute(
        "SELECT value FROM user_settings WHERE key = ?", ("LLM_MODEL",)
    ).fetchone()
    assert row[0] == "updated-model"
