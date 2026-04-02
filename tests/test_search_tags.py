"""
Tests for the hybrid search tag-matching logic.

The stop word filtering and cosine helper are pure functions — tested directly.
The full tag-matching pipeline is tested via the /search endpoint with mocked
embeddings, covering the regressions that motivated the feature:
  - "customers" (single word) matches "customer" tag
  - "meetings about customers" matches "customer" tag despite stop words
  - "meetings about customer" matches "customer" tag
  - unrelated query does not match "customer" tag
"""

import re
import struct
import numpy as np
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

import database
from routers.common import _STOP_WORDS, _cosine
from app import app
from database import Meeting, Tag, MeetingTag


# ── Helper: replicate the stop-word filtering from /search ───────────────────

def _query_words(query: str) -> list[str]:
    raw = re.findall(r'[a-z0-9]+', query.lower())
    filtered = [w for w in raw if w not in _STOP_WORDS]
    return filtered or [query.lower()]


def _vec(*values: float) -> bytes:
    """Return a normalised float32 numpy array serialised to bytes."""
    a = np.array(values, dtype=np.float32)
    norm = np.linalg.norm(a)
    if norm:
        a = a / norm
    return a.tobytes()


# ── Stop word filtering ───────────────────────────────────────────────────────

class TestStopWordFiltering:
    def test_strips_about_and_meetings(self):
        assert _query_words("meetings about customers") == ["customers"]

    def test_single_word_unchanged(self):
        assert _query_words("customers") == ["customers"]

    def test_strips_meetings_about_customer(self):
        assert _query_words("meetings about customer") == ["customer"]

    def test_multi_meaningful_words_preserved(self):
        assert _query_words("Q3 budget planning") == ["q3", "budget", "planning"]

    def test_all_stop_words_falls_back_to_full_query(self):
        result = _query_words("about the")
        assert result == ["about the"]

    def test_show_find_list_are_stop_words(self):
        assert _query_words("show me hiring meetings") == ["hiring"]
        assert _query_words("find meetings related to budget") == ["budget"]

    def test_mixed_case_normalised(self):
        assert _query_words("Meetings About Customers") == ["customers"]

    def test_regarding_stripped(self):
        assert _query_words("meetings regarding onboarding") == ["onboarding"]


# ── Stop word set membership ──────────────────────────────────────────────────

class TestStopWordSet:
    def test_filler_words_present(self):
        for word in ["meetings", "meeting", "about", "the", "and", "for",
                     "with", "regarding", "find", "show", "get", "list",
                     "search", "tell"]:
            assert word in _STOP_WORDS, f"'{word}' should be a stop word"

    def test_topic_words_absent(self):
        for word in ["customer", "budget", "hiring", "roadmap", "onboarding",
                     "ai", "design", "launch", "q3", "okr"]:
            assert word not in _STOP_WORDS, f"'{word}' should not be a stop word"


# ── Cosine helper ─────────────────────────────────────────────────────────────

class TestCosine:
    def test_identical_vectors(self):
        a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        assert _cosine(a, a) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        a = np.array([1.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0], dtype=np.float32)
        assert _cosine(a, b) == pytest.approx(0.0)

    def test_zero_vector_returns_zero(self):
        a = np.array([0.0, 0.0], dtype=np.float32)
        b = np.array([1.0, 0.0], dtype=np.float32)
        assert _cosine(a, b) == 0.0


# ── /search tag matching (mocked embeddings) ─────────────────────────────────
#
# Embedding space (4-dim unit vectors):
#   "customer"  / "customers" / "costumer" → dim 0  (high similarity to each other)
#   "budget"                               → dim 1
#   (stop words / noise like "meetings", "about" → dim 2, far from all tags)
#
# TAG_MATCH_THRESHOLD = 0.75
# word-to-word cosine for same-dim vectors ≈ 1.0, cross-dim ≈ 0.0

# Use 1536-dim vectors (matches ada-002 output) so shape checks pass.
# We set meaningful values only in a few dims; the rest are zero.
def _basis(dim: int, size: int = 1536) -> bytes:
    """Unit vector along `dim` in a `size`-dimensional space."""
    a = np.zeros(size, dtype=np.float32)
    a[dim] = 1.0
    return a.tobytes()


def _near_basis(dim: int, size: int = 1536, noise_dim: int = 1, noise: float = 0.1) -> bytes:
    """Vector close to basis `dim` — cos ≈ 0.995 vs the exact basis vector."""
    a = np.zeros(size, dtype=np.float32)
    a[dim] = 1.0
    a[noise_dim] = noise
    norm = np.linalg.norm(a)
    return (a / norm).tobytes()


_CUSTOMER_VEC  = _basis(0)                      # tag "customer"
_CUSTOMERS_VEC = _near_basis(0, noise_dim=1)    # cos ≈ 0.995 vs customer → matches
_BUDGET_VEC    = _basis(1)                      # tag "budget", orthogonal to customer
_NOISE_VEC     = _basis(2)                      # "meetings", "about" — far from all tags


def _make_embedding_map(**kwargs) -> dict[str, bytes]:
    """Map text → embedding bytes for use in mock."""
    return kwargs



def _seed_meeting(title: str, tag_name: str, chunk_emb: bytes) -> int:
    """Insert a meeting + tag + chunk with embedding. Returns meeting id."""
    db = database.SessionLocal()
    try:
        m = Meeting(title=title, notes_raw="notes", summary="summary",
                    action_items="[]")
        db.add(m)
        db.flush()
        c = database.Chunk(meeting_id=m.id, chunk_index=0, text="chunk text",
                  description="desc", embedding=chunk_emb)
        db.add(c)
        db.flush()
        tag = db.query(Tag).filter(Tag.name == tag_name).first()
        if not tag:
            tag = Tag(name=tag_name)
            db.add(tag)
            db.flush()
        db.add(MeetingTag(meeting_id=m.id, tag_id=tag.id))
        db.commit()
        return m.id
    finally:
        db.close()


class TestSearchTagMatching:
    """
    Verify that tag matching fires correctly for different query forms.
    Embeddings are mocked so the test is deterministic and free.
    """

    def _run_search(self, query: str, embedding_map: dict) -> list[dict]:
        def fake_embedding(text: str) -> bytes:
            if text in embedding_map:
                return embedding_map[text]
            # default: noise vector (won't match any tag)
            return _NOISE_VEC

        with patch("routers.search.generate_embedding", side_effect=fake_embedding), \
             patch("auth.require_auth", return_value="test@example.com"):
            client = TestClient(app)
            res = client.post("/search", json={"query": query})
        assert res.status_code == 200
        return res.json()

    def test_single_word_customer_matches_tag(self):
        mid = _seed_meeting("Customer sync", "customer", _NOISE_VEC)
        emb_map = {"customers": _CUSTOMERS_VEC, "customer": _CUSTOMER_VEC}
        results = self._run_search("customers", emb_map)
        assert any(r["id"] == mid for r in results)

    def test_meetings_about_customers_matches_tag(self):
        """Regression: phrase query should match via stop-word-filtered word 'customers'."""
        mid = _seed_meeting("Customer review", "customer", _NOISE_VEC)
        emb_map = {
            "customers": _CUSTOMERS_VEC,
            "customer": _CUSTOMER_VEC,
        }
        results = self._run_search("meetings about customers", emb_map)
        assert any(r["id"] == mid for r in results)

    def test_meetings_about_customer_matches_tag(self):
        """Regression: singular form should also match."""
        mid = _seed_meeting("Customer review", "customer", _NOISE_VEC)
        emb_map = {"customer": _CUSTOMER_VEC}
        results = self._run_search("meetings about customer", emb_map)
        assert any(r["id"] == mid for r in results)

    def test_unrelated_query_does_not_match_customer_tag(self):
        _seed_meeting("Customer sync", "customer", _NOISE_VEC)
        # "budget" is orthogonal to "customer" in our mock space
        emb_map = {"budget": _BUDGET_VEC, "customer": _CUSTOMER_VEC}
        results = self._run_search("budget", emb_map)
        assert all(r.get("title") != "Customer sync" for r in results)

    def test_tag_matched_meeting_included_even_below_chunk_threshold(self):
        """
        A meeting whose chunk embedding scores below 0.45 vs the query
        should still appear if its tag matches.
        """
        mid = _seed_meeting("Customer strategy", "customer", _NOISE_VEC)
        # chunk embedding is NOISE_VEC → cosine vs query word ≈ 0 → below 0.45
        # but tag "customer" matches query word "customer" → should still surface
        emb_map = {"customer": _CUSTOMER_VEC}
        results = self._run_search("customer", emb_map)
        assert any(r["id"] == mid for r in results)
