"""Tests for Magic Reviewer app."""

import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock vertexai and its submodules before any import of app can trigger them.
_mock_vertexai = MagicMock()
_mock_generative_models = MagicMock()
sys.modules["vertexai"] = _mock_vertexai
sys.modules["vertexai.generative_models"] = _mock_generative_models


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_env(tmp_path, monkeypatch):
    """Set required environment variables and create dummy prompt files."""
    bq_path = str(tmp_path / "bq.cmd")
    with open(bq_path, "w") as f:
        f.write("dummy")

    monkeypatch.setenv("BQ_PROD_PROJECT", "test-project")
    monkeypatch.setenv("BQ_EXECUTABLE_PATH", bq_path)
    monkeypatch.setenv("BQ_DATASET", "test-project.test_dataset")
    monkeypatch.setenv("CUSTOMER_LOOKUP_TABLE", "test-project.test_dataset.lookup")
    monkeypatch.setenv("BQ_MANUAL_REVIEW_TABLE", "test-project.test_dataset.review")
    monkeypatch.setenv("LLM_DEV_PROJECT", "test-llm-project")
    monkeypatch.setenv("LLM_LOCATION", "europe-west4")
    monkeypatch.setenv("LLM_MODEL", "gemini-2.5-pro")
    monkeypatch.setenv("FLASK_DEBUG", "false")


@pytest.fixture
def app_module(mock_env):
    """Import app module with vertexai already mocked at sys.modules level."""
    if "app" in sys.modules:
        del sys.modules["app"]
    import app as app_module
    yield app_module


@pytest.fixture
def client(app_module):
    """Flask test client."""
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# BQ CLI Helper Tests
# ---------------------------------------------------------------------------

class TestRunBqQuery:
    def test_successful_query(self, app_module):
        rows = [{"session_id": "s1", "turn_position": "2"}]
        mock_result = MagicMock(
            returncode=0,
            stdout=json.dumps(rows),
            stderr="",
        )
        with patch("subprocess.run", return_value=mock_result):
            result = app_module.run_bq_query("SELECT 1")
        assert result == rows

    def test_empty_result(self, app_module):
        mock_result = MagicMock(returncode=0, stdout="[]", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            result = app_module.run_bq_query("SELECT 1")
        assert result["error"] == "BQ query returned 0 rows."

    def test_nonzero_exit(self, app_module):
        mock_result = MagicMock(returncode=1, stdout="", stderr="Table not found")
        with patch("subprocess.run", return_value=mock_result):
            result = app_module.run_bq_query("SELECT 1")
        assert "Table not found" in result["error"]

    def test_timeout(self, app_module):
        import subprocess as sp
        with patch("subprocess.run", side_effect=sp.TimeoutExpired("bq", 120)):
            result = app_module.run_bq_query("SELECT 1")
        assert "timed out" in result["error"]

    def test_invalid_json(self, app_module):
        mock_result = MagicMock(returncode=0, stdout="not json", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            result = app_module.run_bq_query("SELECT 1")
        assert "parse" in result["error"].lower()


class TestBqInsertRow:
    def test_successful_insert(self, app_module):
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = app_module.bq_insert_row("project.dataset.table", {"a": 1})
        assert result == {"status": "ok"}
        call_args = mock_run.call_args
        assert call_args.kwargs.get("input") == '{"a": 1}'

    def test_insert_failure(self, app_module):
        mock_result = MagicMock(returncode=1, stdout="", stderr="Permission denied")
        with patch("subprocess.run", return_value=mock_result):
            result = app_module.bq_insert_row("project.dataset.table", {"a": 1})
        assert "Permission denied" in result["error"]


# ---------------------------------------------------------------------------
# Date Validation Tests
# ---------------------------------------------------------------------------

class TestFetchOneRecord:
    def test_invalid_date_rejected(self, app_module):
        result = app_module.fetch_one_record("not-a-date", "2026-01-01")
        assert "Invalid date" in result["error"]

    def test_sql_injection_blocked(self, app_module):
        result = app_module.fetch_one_record("2026-01-01'; DROP TABLE--", "2026-01-01")
        assert "Invalid date" in result["error"]

    def test_valid_dates_run_query(self, app_module):
        rows = [{"session_id": "s1", "turn_position": "2", "req": "hi"}]
        mock_result = MagicMock(returncode=0, stdout=json.dumps(rows), stderr="")
        with patch("subprocess.run", return_value=mock_result):
            result = app_module.fetch_one_record("2026-01-01", "2026-01-31")
        assert result["session_id"] == "s1"


# ---------------------------------------------------------------------------
# LLM JSON Parsing Tests
# ---------------------------------------------------------------------------

class TestAnalyzeGroundedness:
    def test_valid_json_response(self, app_module):
        llm_output = '{"is_correct": true, "reasoning": "all good"}'
        mock_resp = MagicMock()
        mock_resp.text = llm_output
        mock_model = MagicMock()
        mock_model.generate_content.return_value = mock_resp

        with patch("app.GenerativeModel", return_value=mock_model):
            result = app_module.analyze_groundedness("q", "a", "{}")
        assert result["is_correct"] is True
        assert result["reasoning"] == "all good"

    def test_json_with_surrounding_text(self, app_module):
        llm_output = 'Here is my analysis:\n{"is_correct": false, "reasoning": "wrong field"}\nEnd.'
        mock_resp = MagicMock()
        mock_resp.text = llm_output
        mock_model = MagicMock()
        mock_model.generate_content.return_value = mock_resp

        with patch("app.GenerativeModel", return_value=mock_model):
            result = app_module.analyze_groundedness("q", "a", "{}")
        assert result["is_correct"] is False

    def test_no_json_in_response(self, app_module):
        mock_resp = MagicMock()
        mock_resp.text = "I cannot parse this data."
        mock_model = MagicMock()
        mock_model.generate_content.return_value = mock_resp

        with patch("app.GenerativeModel", return_value=mock_model):
            result = app_module.analyze_groundedness("q", "a", "{}")
        assert result["is_correct"] is None

    def test_api_exception(self, app_module):
        mock_model = MagicMock()
        mock_model.generate_content.side_effect = RuntimeError("quota exceeded")

        with patch("app.GenerativeModel", return_value=mock_model):
            result = app_module.analyze_groundedness("q", "a", "{}")
        assert result["is_correct"] is None
        assert "quota exceeded" in result["reasoning"]


# ---------------------------------------------------------------------------
# Route Tests
# ---------------------------------------------------------------------------

class TestGetRecordRoute:
    def test_missing_dates(self, client):
        resp = client.get("/get-record")
        assert resp.status_code == 400

    def test_returns_record(self, client, app_module):
        row = {"session_id": "s1", "turn_position": "2", "req": "q", "response_text": "a"}
        mock_result = MagicMock(returncode=0, stdout=json.dumps([row]), stderr="")
        with patch("subprocess.run", return_value=mock_result):
            resp = client.get("/get-record?start_date=2026-01-01&end_date=2026-01-31")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["record"]["session_id"] == "s1"


class TestLlmReviewRoute:
    def test_missing_data(self, client):
        resp = client.post("/llm-review", json={})
        assert resp.status_code == 400

    def test_caching(self, client, app_module):
        app_module._llm_cache.clear()
        cached = {"is_correct": True, "reasoning": "cached"}
        app_module._llm_cache[("s1", "2")] = cached

        resp = client.post("/llm-review", json={
            "req": "q", "response_text": "a", "customer_json_data": "{}",
            "session_id": "s1", "turn_position": "2",
        })
        assert resp.status_code == 200
        assert resp.get_json()["reasoning"] == "cached"


class TestSaveResponseRoute:
    def test_successful_save(self, client, app_module):
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            resp = client.post("/save-response", json={
                "session_id": "s1", "turn_position": "2",
                "user_response": "YES",
            })
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"

    def test_save_failure(self, client, app_module):
        mock_result = MagicMock(returncode=1, stdout="", stderr="insert error")
        with patch("subprocess.run", return_value=mock_result):
            resp = client.post("/save-response", json={
                "session_id": "s1", "user_response": "NO",
            })
        assert resp.status_code == 500


class TestHealthRoute:
    def test_healthy(self, client, app_module):
        mock_result = MagicMock(returncode=0, stdout='[{"ok": 1}]', stderr="")
        with patch("subprocess.run", return_value=mock_result):
            resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"

    def test_unhealthy(self, client, app_module):
        mock_result = MagicMock(returncode=1, stdout="", stderr="connection refused")
        with patch("subprocess.run", return_value=mock_result):
            resp = client.get("/health")
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Prompt Loading Tests
# ---------------------------------------------------------------------------

class TestPromptLoading:
    def test_prompts_loaded(self, app_module):
        assert len(app_module.SYSTEM_PROMPT) > 100
        assert "{question}" in app_module.USER_PROMPT_TEMPLATE
        assert "{answer}" in app_module.USER_PROMPT_TEMPLATE
        assert "{source_data}" in app_module.USER_PROMPT_TEMPLATE
