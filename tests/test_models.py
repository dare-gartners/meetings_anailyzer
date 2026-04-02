"""Tests for Pydantic models in models.py — no DB or LLM needed."""
import pytest
from pydantic import ValidationError
from models import (
    NotesRequest, NotesResponse, TagAddRequest,
    SearchRequest, SearchResult, ChunkMatch, SimilarMeeting,
)
from datetime import datetime, timezone


class TestNotesRequest:
    def test_requires_title(self):
        with pytest.raises(ValidationError):
            NotesRequest(notes="some notes")

    def test_requires_notes(self):
        with pytest.raises(ValidationError):
            NotesRequest(title="Title")

    def test_requires_both(self):
        with pytest.raises(ValidationError):
            NotesRequest()

    def test_valid_minimal(self):
        r = NotesRequest(title="T", notes="N")
        assert r.title == "T"
        assert r.notes == "N"
        assert r.date is None
        assert r.recording_url is None

    def test_with_all_optional_fields(self):
        r = NotesRequest(title="T", notes="N", date="2026-01-01", recording_url="https://x.com")
        assert r.date == "2026-01-01"
        assert r.recording_url == "https://x.com"


class TestTagAddRequest:
    def test_requires_name(self):
        with pytest.raises(ValidationError):
            TagAddRequest()

    def test_valid(self):
        r = TagAddRequest(name="hiring")
        assert r.name == "hiring"


class TestSearchRequest:
    def test_requires_query(self):
        with pytest.raises(ValidationError):
            SearchRequest()

    def test_valid(self):
        r = SearchRequest(query="customer meetings")
        assert r.query == "customer meetings"


class TestChunkMatch:
    def test_required_fields(self):
        cm = ChunkMatch(source_chunk="src", matched_chunk="match", score=0.85, is_best=True)
        assert cm.source_description is None
        assert cm.matched_description is None

    def test_with_descriptions(self):
        cm = ChunkMatch(
            source_chunk="src", matched_chunk="match",
            source_description="desc a", matched_description="desc b",
            score=0.72, is_best=False,
        )
        assert cm.source_description == "desc a"
        assert cm.is_best is False


class TestSimilarMeeting:
    def test_serializes_correctly(self):
        now = datetime.now(timezone.utc)
        sm = SimilarMeeting(
            id=1, title="Meeting", created_at=now, tags=["roadmap"],
            score=0.88,
            all_matches=[
                ChunkMatch(source_chunk="a", matched_chunk="b", score=0.88, is_best=True)
            ],
        )
        assert sm.score == 0.88
        assert len(sm.all_matches) == 1
        assert sm.all_matches[0].is_best is True


class TestSearchResult:
    def test_matched_description_nullable(self):
        from datetime import datetime, timezone
        sr = SearchResult(
            id=1, title="T", created_at=datetime.now(timezone.utc),
            matched_chunk="chunk text", score=0.5,
        )
        assert sr.matched_description is None
