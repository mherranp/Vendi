"""Test de humo del esqueleto de la API (tarea 2.1)."""

from fastapi.testclient import TestClient

from app.main import app


def test_health():
    assert TestClient(app).get("/health").json() == {"status": "ok"}
