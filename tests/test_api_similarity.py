"""Tests for POST /meetings/{id}/similar and POST /matches/explain."""
import numpy as np
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import database
from database import Meeting, Chunk, Tag, MeetingTag


def _ebytes(dim: int = 0, size: int = 1536) -> bytes:
    a = np.zeros(size, dtype=np.float32); a[dim] = 1.0
    return a.tobytes()


def _seed_meeting_with_chunk(title: str, embedding: bytes = None, tags=None) -> int:
    db = database.SessionLocal()
    try:
        m = Meeting(title=title, notes_raw="notes", summary="summary", action_items="[]")
        db.add(m); db.flush()
        c = Chunk(
            meeting_id=m.id, chunk_index=0, text=f"chunk for {title}",
            description=f"description for {title}", embedding=embedding,
        )
        db.add(c); db.flush()
        for name in (tags or []):
            t = db.query(Tag).filter(Tag.name == name).first()
            if not t:
                t = Tag(name=name); db.add(t); db.flush()
            db.add(MeetingTag(meeting_id=m.id, tag_id=t.id))
        db.commit()
        return m.id
    finally:
        db.close()


# ── POST /meetings/{id}/similar ───────────────────────────────────────────────

class TestSimilarMeetings:
    def test_no_embeddings_returns_empty(self, client):
        mid = _seed_meeting_with_chunk("Source", embedding=None)
        res = client.post(f"/meetings/{mid}/similar")
        assert res.status_code == 200
        assert res.json() == []

    def test_finds_similar_meeting_above_threshold(self, client):
        # Both meetings use the same embedding dimension → cosine = 1.0
        source_id = _seed_meeting_with_chunk("Source", embedding=_ebytes(0))
        _seed_meeting_with_chunk("Similar", embedding=_ebytes(0))
        with patch("routers.similarity.verify_match", return_value=True):
            res = client.post(f"/meetings/{source_id}/similar")
        assert res.status_code == 200
        titles = [m["title"] for m in res.json()]
        assert "Similar" in titles

    def test_does_not_return_source_meeting_itself(self, client):
        mid = _seed_meeting_with_chunk("Self", embedding=_ebytes(0))
        _seed_meeting_with_chunk("Other", embedding=_ebytes(0))
        with patch("routers.similarity.verify_match", return_value=True):
            res = client.post(f"/meetings/{mid}/similar")
        ids = [m["id"] for m in res.json()]
        assert mid not in ids

    def test_excludes_meetings_below_cosine_threshold(self, client):
        # dim 0 and dim 1 are orthogonal → cosine = 0.0 < 0.45
        source_id = _seed_meeting_with_chunk("Source", embedding=_ebytes(0))
        _seed_meeting_with_chunk("Unrelated", embedding=_ebytes(1))
        res = client.post(f"/meetings/{source_id}/similar")
        assert res.json() == []

    def test_llm_verification_false_excludes_match(self, client):
        source_id = _seed_meeting_with_chunk("Source", embedding=_ebytes(0))
        _seed_meeting_with_chunk("Candidate", embedding=_ebytes(0))
        with patch("routers.similarity.verify_match", return_value=False):
            res = client.post(f"/meetings/{source_id}/similar")
        assert res.json() == []

    def test_verify_match_failure_keeps_match_fail_open(self, client):
        """If verify_match raises, the match is kept (fail open)."""
        source_id = _seed_meeting_with_chunk("Source", embedding=_ebytes(0))
        _seed_meeting_with_chunk("Candidate", embedding=_ebytes(0))
        with patch("routers.similarity.verify_match", side_effect=Exception("LLM error")):
            res = client.post(f"/meetings/{source_id}/similar")
        assert len(res.json()) == 1

    def test_response_includes_score_and_all_matches(self, client):
        source_id = _seed_meeting_with_chunk("Source", embedding=_ebytes(0))
        _seed_meeting_with_chunk("Similar", embedding=_ebytes(0))
        with patch("routers.similarity.verify_match", return_value=True):
            res = client.post(f"/meetings/{source_id}/similar")
        data = res.json()
        assert len(data) == 1
        assert "score" in data[0]
        assert "all_matches" in data[0]
        assert len(data[0]["all_matches"]) >= 1

    def test_all_matches_have_is_best_flag(self, client):
        source_id = _seed_meeting_with_chunk("Source", embedding=_ebytes(0))
        _seed_meeting_with_chunk("Similar", embedding=_ebytes(0))
        with patch("routers.similarity.verify_match", return_value=True):
            res = client.post(f"/meetings/{source_id}/similar")
        match = res.json()[0]["all_matches"][0]
        assert "is_best" in match

    def test_requires_auth(self):
        from app import app
        assert TestClient(app).post("/meetings/1/similar").status_code == 401

    def test_returns_empty_for_meeting_with_no_other_meetings(self, client):
        mid = _seed_meeting_with_chunk("Alone", embedding=_ebytes(0))
        res = client.post(f"/meetings/{mid}/similar")
        assert res.status_code == 200
        assert res.json() == []


# ── POST /matches/explain ──────────────────────────────────────────────────────

class TestExplainMatch:
    def test_returns_explanation(self, client):
        with patch("routers.similarity.explain_match", return_value="Both meetings discussed budget planning."):
            res = client.post("/matches/explain", json={
                "source_chunk": "Q2 budget review",
                "matched_chunk": "Annual budget discussion",
            })
        assert res.status_code == 200
        assert res.json()["explanation"] == "Both meetings discussed budget planning."

    def test_requires_auth(self):
        from app import app
        res = TestClient(app).post("/matches/explain", json={
            "source_chunk": "a", "matched_chunk": "b"
        })
        assert res.status_code == 401

    def test_missing_source_chunk_returns_422(self, client):
        res = client.post("/matches/explain", json={"matched_chunk": "b"})
        assert res.status_code == 422

    def test_missing_matched_chunk_returns_422(self, client):
        res = client.post("/matches/explain", json={"source_chunk": "a"})
        assert res.status_code == 422
