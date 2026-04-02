from fastapi.testclient import TestClient
from app import app

client = TestClient(app)


def test_index():
    res = client.get("/")
    assert res.status_code == 200


def test_analyze_requires_title():
    res = client.post("/analyze", json={"notes": "Test meeting"})
    assert res.status_code == 422
