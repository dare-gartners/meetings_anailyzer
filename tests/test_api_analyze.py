"""Tests for POST /analyze endpoint."""
import json
import numpy as np
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import core.database as database
from core.database import Meeting


VALID_JSON = json.dumps({"summary": "Q2 planning discussed.", "tags": ["roadmap", "budget"]})

def _ebytes(dim: int = 0, size: int = 1536) -> bytes:
    a = np.zeros(size, dtype=np.float32); a[dim] = 1.0
    return a.tobytes()


def _llm_patches(**overrides):
    """Patch all LLM functions used by /analyze."""
    defaults = dict(
        analyze_notes=MagicMock(return_value=VALID_JSON),
        generate_description=MagicMock(return_value="Short description."),
        generate_embedding=MagicMock(return_value=_ebytes()),
        generate_tags=MagicMock(return_value=["roadmap"]),
    )
    defaults.update(overrides)
    return patch.multiple("routers.analyze", **defaults)


NOTES = "Topic one:\n    content here\nTopic two:\n    more content"


class TestAnalyzeHappyPath:
    def test_returns_200_with_summary_and_tags(self, client):
        with _llm_patches():
            res = client.post("/analyze", json={"title": "Q2 Planning", "notes": NOTES})
        assert res.status_code == 200
        data = res.json()
        assert "summary" in data
        assert "tags" in data
        assert isinstance(data["tags"], list)

    def test_response_includes_meeting_id(self, client):
        with _llm_patches():
            res = client.post("/analyze", json={"title": "T", "notes": NOTES})
        assert res.json()["id"] is not None

    def test_meeting_saved_to_db(self, client):
        with _llm_patches():
            client.post("/analyze", json={"title": "Saved Meeting", "notes": NOTES})
        db = database.SessionLocal()
        try:
            assert db.query(Meeting).filter(Meeting.title == "Saved Meeting").first() is not None
        finally:
            db.close()

    def test_with_optional_date(self, client):
        with _llm_patches():
            res = client.post("/analyze", json={"title": "T", "notes": NOTES, "date": "2026-03-17"})
        assert res.status_code == 200
        db = database.SessionLocal()
        try:
            m = db.query(Meeting).filter(Meeting.title == "T").first()
            assert m.meeting_date == "2026-03-17"
        finally:
            db.close()

    def test_with_optional_recording_url(self, client):
        with _llm_patches():
            res = client.post("/analyze", json={
                "title": "T", "notes": NOTES, "recording_url": "https://rec.example.com/1"
            })
        assert res.status_code == 200

    def test_chunks_saved_to_db(self, client):
        with _llm_patches():
            res = client.post("/analyze", json={"title": "Chunked", "notes": NOTES})
        mid = res.json()["id"]
        db = database.SessionLocal()
        try:
            chunks = db.query(database.Chunk).filter(database.Chunk.meeting_id == mid).all()
            assert len(chunks) > 0
        finally:
            db.close()


class TestAnalyzeValidation:
    def test_missing_title_returns_422(self, client):
        res = client.post("/analyze", json={"notes": NOTES})
        assert res.status_code == 422

    def test_missing_notes_returns_422(self, client):
        res = client.post("/analyze", json={"title": "T"})
        assert res.status_code == 422

    def test_requires_auth(self):
        from app import app
        res = TestClient(app).post("/analyze", json={"title": "T", "notes": NOTES})
        assert res.status_code == 401

    def test_duplicate_recording_url_returns_409(self, client):
        url = "https://rec.example.com/unique"
        with _llm_patches():
            client.post("/analyze", json={"title": "First", "notes": NOTES, "recording_url": url})
            res = client.post("/analyze", json={"title": "Second", "notes": NOTES, "recording_url": url})
        assert res.status_code == 409


class TestAnalyzeErrorHandling:
    def test_invalid_json_from_llm_returns_500(self, client):
        with _llm_patches(analyze_notes=MagicMock(return_value="not json {")):
            res = client.post("/analyze", json={"title": "T", "notes": NOTES})
        assert res.status_code == 500

    def test_description_failure_does_not_fail_request(self, client):
        """Description generation failure is isolated — request still succeeds."""
        with _llm_patches(generate_description=MagicMock(side_effect=Exception("LLM down"))):
            res = client.post("/analyze", json={"title": "T", "notes": NOTES})
        assert res.status_code == 200

    def test_embedding_failure_does_not_fail_request(self, client):
        with _llm_patches(generate_embedding=MagicMock(side_effect=Exception("LLM down"))):
            res = client.post("/analyze", json={"title": "T", "notes": NOTES})
        assert res.status_code == 200

    def test_tag_generation_failure_does_not_fail_request(self, client):
        with _llm_patches(generate_tags=MagicMock(side_effect=Exception("LLM down"))):
            res = client.post("/analyze", json={"title": "T", "notes": NOTES})
        assert res.status_code == 200

    def test_llm_missing_summary_field_uses_empty_string(self, client):
        with _llm_patches(analyze_notes=MagicMock(return_value='{"tags": ["roadmap"]}')):
            res = client.post("/analyze", json={"title": "T", "notes": NOTES})
        assert res.status_code == 200
        assert res.json()["summary"] == ""
