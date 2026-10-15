"""The application shell: nothing unexpected reaches the client."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from law_agent.api.app import create_app


@pytest.fixture
def failing_client() -> TestClient:
    app: FastAPI = create_app()

    @app.get("/boom")
    def boom() -> None:
        msg = "connection to secret-host:5432 refused"
        raise RuntimeError(msg)

    return TestClient(app, raise_server_exceptions=False)


def test_an_unexpected_error_is_a_generic_500(failing_client: TestClient) -> None:
    response = failing_client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
    assert "secret-host" not in response.text
