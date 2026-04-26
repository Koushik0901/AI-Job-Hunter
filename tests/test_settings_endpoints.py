import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from ai_job_hunter.dashboard.backend.main import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_service():
    import ai_job_hunter.settings_service as ss
    ss._cache.clear()
    yield
    ss._cache.clear()


# --- GET /api/settings ---

def test_get_settings_returns_all_known_keys(client):
    masked = {
        "OPENROUTER_API_KEY": "sk-o****1234",
        "TELEGRAM_TOKEN": "****",
        "TELEGRAM_CHAT_ID": "****",
        "LLM_MODEL": "z-ai/glm-5.1",
        "SLM_MODEL": "google/gemma-4-31b-it",
        "ENRICHMENT_MODEL": "openai/gpt-oss-120b",
        "DESCRIPTION_FORMAT_MODEL": "openai/gpt-oss-120b",
        "EMBEDDING_MODEL": "qwen/qwen3-embedding-8b",
        "JOB_HUNTER_TIMEZONE": "America/Edmonton",
    }
    with patch("ai_job_hunter.settings_service.get_all_masked", return_value=masked):
        resp = client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["LLM_MODEL"] == "z-ai/glm-5.1"
    assert "****" in data["OPENROUTER_API_KEY"]


# --- PUT /api/settings ---

def test_put_settings_calls_set_for_each_key(client):
    with patch("ai_job_hunter.settings_service.set") as mock_set, \
         patch("ai_job_hunter.settings_service.get_all_masked", return_value={"LLM_MODEL": "openai/gpt-4o"}):
        resp = client.put("/api/settings", json={"LLM_MODEL": "openai/gpt-4o"})
    assert resp.status_code == 200
    mock_set.assert_called_once_with("LLM_MODEL", "openai/gpt-4o")


def test_put_settings_rejects_unknown_keys(client):
    resp = client.put("/api/settings", json={"TOTALLY_UNKNOWN": "value"})
    assert resp.status_code == 422


def test_put_settings_returns_masked_response(client):
    with patch("ai_job_hunter.settings_service.set"), \
         patch("ai_job_hunter.settings_service.get_all_masked", return_value={"LLM_MODEL": "openai/gpt-4o"}):
        resp = client.put("/api/settings", json={"LLM_MODEL": "openai/gpt-4o"})
    assert resp.status_code == 200
    assert resp.json()["LLM_MODEL"] == "openai/gpt-4o"


# --- POST /api/settings/telegram/test ---

def test_telegram_test_missing_credentials_returns_400(client):
    with patch("ai_job_hunter.settings_service.get", return_value=""):
        resp = client.post("/api/settings/telegram/test")
    assert resp.status_code == 400


def test_telegram_test_success(client):
    def mock_get(key, default=""):
        return {"TELEGRAM_TOKEN": "123:ABC", "TELEGRAM_CHAT_ID": "456789"}.get(key, default)

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    with patch("ai_job_hunter.settings_service.get", side_effect=mock_get), \
         patch("requests.post", return_value=mock_resp) as mock_post:
        resp = client.post("/api/settings/telegram/test")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    call_args = mock_post.call_args
    assert call_args[0][0].endswith("/sendMessage")
    assert call_args[1]["json"]["text"] == "Kenji settings test -- connection is working."


def test_telegram_test_send_failure_returns_ok_false(client):
    def mock_get(key, default=""):
        return {"TELEGRAM_TOKEN": "bad-token", "TELEGRAM_CHAT_ID": "456"}.get(key, default)

    import requests as req_lib
    mock_err_resp = MagicMock()
    mock_err_resp.status_code = 401
    http_error = req_lib.HTTPError(response=mock_err_resp)

    with patch("ai_job_hunter.settings_service.get", side_effect=mock_get), \
         patch("requests.post", side_effect=http_error):
        resp = client.post("/api/settings/telegram/test")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "401" in body["error"]


# --- GET /api/settings/openrouter/validate ---

def test_openrouter_validate_missing_key_returns_400(client):
    with patch("ai_job_hunter.settings_service.get", return_value=""):
        resp = client.get("/api/settings/openrouter/validate")
    assert resp.status_code == 400


def test_openrouter_validate_success(client):
    def mock_get(key, default=""):
        return "sk-or-v1-testkey" if key == "OPENROUTER_API_KEY" else default

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": [{"id": "model-a"}, {"id": "model-b"}, {"id": "model-c"}]}

    with patch("ai_job_hunter.settings_service.get", side_effect=mock_get), \
         patch("requests.get", return_value=mock_resp):
        resp = client.get("/api/settings/openrouter/validate")

    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True
    assert data["model_count"] == 3


def test_openrouter_validate_bad_key_returns_valid_false(client):
    def mock_get(key, default=""):
        return "bad-key" if key == "OPENROUTER_API_KEY" else default

    import requests as req_lib
    with patch("ai_job_hunter.settings_service.get", side_effect=mock_get), \
         patch("requests.get", side_effect=req_lib.HTTPError("401 Unauthorized")):
        resp = client.get("/api/settings/openrouter/validate")

    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert body["error"]
