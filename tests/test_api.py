"""
Integration tests for FastAPI endpoints.

Tests /generate, /jobs/{id}, /jobs/{id}/retry, /jobs/{id}/pipeline
using FastAPI TestClient with mocked background tasks.

Run:
    pytest tests/test_api.py -v
"""

import json

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch, MagicMock

from app.main import app
from app.models.job import JobStatus


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def mock_enqueue():
    """Prevent tests from pushing real jobs to Redis."""
    with patch("app.main.enqueue_pipeline", new_callable=AsyncMock) as _mock:
        _mock.return_value = "queued"
        yield _mock


@pytest.fixture(autouse=True)
def mock_job_manager():
    """Mock job_manager to avoid SQLite side effects in tests."""
    with patch("app.main.job_manager") as mock_jm:
        # create_job returns a mock record
        mock_job = MagicMock()
        mock_job.id = "test-job-123"
        mock_job.status = JobStatus.PENDING
        mock_job.topic = "Python CI/CD"
        mock_job.primary_keyword = "ci/cd"
        mock_job.target_word_count = 1500
        mock_job.language = "en"
        mock_job.created_at = "2026-01-01T00:00:00"
        mock_job.updated_at = "2026-01-01T00:00:00"
        mock_job.error = None
        mock_job.result = None
        mock_job.pipeline_data = None
        mock_jm.create_job.return_value = mock_job
        mock_jm.get_job.return_value = mock_job
        mock_jm.list_jobs.return_value = [mock_job]
        yield mock_jm


# ---------------------------------------------------------------------------
# POST /generate
# ---------------------------------------------------------------------------

class TestGenerate:
    def test_returns_202(self, client):
        resp = client.post("/generate", json={"topic": "Python Testing Best Practices"})
        assert resp.status_code == 202

    def test_returns_job_id(self, client):
        resp = client.post("/generate", json={"topic": "Python Testing"})
        data = resp.json()
        assert "job_id" in data
        assert data["job_id"] == "test-job-123"

    def test_returns_pending_status(self, client):
        resp = client.post("/generate", json={"topic": "Python Testing"})
        data = resp.json()
        assert data["status"] == "pending"

    def test_rejects_short_topic(self, client):
        resp = client.post("/generate", json={"topic": "ab"})
        assert resp.status_code == 422

    def test_accepts_optional_fields(self, client):
        resp = client.post("/generate", json={
            "topic": "Python Testing",
            "target_word_count": 2000,
            "language": "en",
            "primary_keyword": "python testing",
        })
        assert resp.status_code == 202


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}
# ---------------------------------------------------------------------------

class TestGetJob:
    def test_returns_job_details(self, client):
        resp = client.get("/jobs/test-job-123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "test-job-123"
        assert data["topic"] == "Python CI/CD"

    def test_returns_404_for_missing_job(self, client, mock_job_manager):
        mock_job_manager.get_job.return_value = None
        resp = client.get("/jobs/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /jobs/{job_id}/retry
# ---------------------------------------------------------------------------

class TestRetryJob:
    def test_retries_failed_job(self, client, mock_job_manager):
        mock_job = mock_job_manager.get_job.return_value
        mock_job.status = JobStatus.FAILED
        resp = client.post("/jobs/test-job-123/retry")
        assert resp.status_code == 202

    def test_rejects_non_failed_job(self, client, mock_job_manager):
        mock_job = mock_job_manager.get_job.return_value
        mock_job.status = JobStatus.COMPLETED
        resp = client.post("/jobs/test-job-123/retry")
        assert resp.status_code == 409

    def test_returns_404_for_missing_job(self, client, mock_job_manager):
        mock_job_manager.get_job.return_value = None
        resp = client.post("/jobs/nonexistent/retry")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}/pipeline
# ---------------------------------------------------------------------------

class TestGetPipeline:
    def test_returns_empty_when_no_data(self, client):
        resp = client.get("/jobs/test-job-123/pipeline")
        assert resp.status_code == 200
        assert resp.json() == {}

    def test_returns_pipeline_artifacts(self, client, mock_job_manager):
        mock_job = mock_job_manager.get_job.return_value
        mock_job.pipeline_data = json.dumps({
            "serp": {"query": "test", "results": []},
            "gaps": [{"topic": "gap1", "reason": "missing", "priority": "high"}],
        })
        resp = client.get("/jobs/test-job-123/pipeline")
        assert resp.status_code == 200
        data = resp.json()
        assert "serp" in data
        assert "gaps" in data

    def test_returns_404_for_missing_job(self, client, mock_job_manager):
        mock_job_manager.get_job.return_value = None
        resp = client.get("/jobs/nonexistent/pipeline")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /jobs
# ---------------------------------------------------------------------------

class TestListJobs:
    def test_returns_list(self, client):
        resp = client.get("/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
