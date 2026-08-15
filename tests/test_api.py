import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from datetime import datetime, timezone

from httpx import ASGITransport, AsyncClient

from src.models import AgentAnswer, RunStatus


@pytest.fixture
def mock_db(no_db):
    """Provide mocked database functions for API tests."""
    run_id = uuid4()
    created = datetime.now(timezone.utc)

    with (
        patch("src.main.db.create_run", new_callable=AsyncMock) as mock_create,
        patch("src.main.db.complete_run", new_callable=AsyncMock),
        patch("src.main.db.fail_run", new_callable=AsyncMock),
        patch("src.main.db.get_run", new_callable=AsyncMock) as mock_get,
    ):
        mock_create.return_value = {"id": run_id, "created_at": created}
        mock_get.return_value = {
            "id": run_id,
            "created_at": created,
            "input_question": "test",
            "final_answer": '{"answer":"a","citations":[],"confidence":0.9}',
            "status": "completed",
            "total_cost_usd": 0,
        }
        yield {"run_id": run_id, "created_at": created}


@pytest.fixture
def mock_orchestrator():
    answer = AgentAnswer(answer="42", citations=[], confidence=0.95)
    with patch("src.main._build_orchestrator") as mock_build:
        orch = AsyncMock()
        orch.run = AsyncMock(return_value=answer)
        mock_build.return_value = orch
        yield orch


@pytest.fixture
async def client(no_db):
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestHealthEndpoint:
    async def test_health_returns_ok(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestRunEndpoint:
    async def test_successful_run(self, mock_db, mock_orchestrator, client):
        response = await client.post("/run", json={"question": "What is 2+2?"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["answer"]["answer"] == "42"
        assert data["answer"]["confidence"] == 0.95

    async def test_run_returns_run_id(self, mock_db, mock_orchestrator, client):
        response = await client.post("/run", json={"question": "test"})
        data = response.json()
        assert "run_id" in data
        assert data["run_id"] == str(mock_db["run_id"])

    async def test_failed_run(self, mock_db, client):
        from src.orchestrator import OrchestratorError

        with patch("src.main._build_orchestrator") as mock_build:
            orch = AsyncMock()
            orch.run = AsyncMock(side_effect=OrchestratorError("LLM failed"))
            mock_build.return_value = orch

            response = await client.post("/run", json={"question": "test"})
            data = response.json()
            assert data["status"] == "failed"
            assert data["error"] == "LLM failed"

    async def test_missing_question_returns_422(self, client):
        response = await client.post("/run", json={})
        assert response.status_code == 422


class TestGetRunEndpoint:
    async def test_get_existing_run(self, mock_db, client):
        run_id = mock_db["run_id"]
        response = await client.get(f"/runs/{run_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == str(run_id)

    async def test_get_nonexistent_run(self, client):
        fake_id = uuid4()
        with patch("src.main.db.get_run", new_callable=AsyncMock, return_value=None):
            response = await client.get(f"/runs/{fake_id}")
            assert response.status_code == 404
