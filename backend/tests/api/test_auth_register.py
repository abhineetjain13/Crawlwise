# Registration endpoint behavior (settings-driven).
from __future__ import annotations

import pytest
from app.main import app
from fastapi.testclient import TestClient


def test_register_forbidden_when_registration_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config

    monkeypatch.setattr(config.settings, "registration_enabled", False)
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/register",
            json={"email": "new@example.com", "password": "TestPass#12345"},
        )
    assert response.status_code == 403
    assert "disabled" in response.json()["detail"].lower()
