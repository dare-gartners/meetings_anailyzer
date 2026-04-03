"""Tests for meetings CRUD, tag management, deletion, and analytics endpoints."""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
import core.database as database
from core.database import Meeting, Tag, MeetingTag


def _seed(title="Test Meeting", tags=None, recording_url=None, meeting_date=None):
    db = database.SessionLocal()
    try:
        m = Meeting(
            title=title, notes_raw="notes", summary="summary",
            action_items="[]", recording_url=recording_url,
            meeting_date=meeting_date,
        )
        db.add(m); db.flush()
        for name in (tags or []):
            t = db.query(Tag).filter(Tag.name == name).first()
            if not t:
                t = Tag(name=name); db.add(t); db.flush()
            db.add(MeetingTag(meeting_id=m.id, tag_id=t.id))
        db.commit()
        return m.id
    finally:
        db.close()


# ── GET /meetings ─────────────────────────────────────────────────────────────

class TestListMeetings:
    def test_returns_all_meetings(self, client):
        _seed("First"); _seed("Second")
        res = client.get("/meetings")
        assert res.status_code == 200
        assert len(res.json()) == 2

    def test_ordered_by_created_at_desc(self, client):
        _seed("Older"); _seed("Newer")
        titles = [m["title"] for m in client.get("/meetings").json()]
        assert titles[0] == "Newer"

    def test_empty_db_returns_empty_list(self, client):
        assert client.get("/meetings").json() == []

    def test_filter_by_tag(self, client):
        _seed("Tagged", tags=["customer"])
        _seed("Untagged")
        res = client.get("/meetings?tag=customer")
        assert res.status_code == 200
        titles = [m["title"] for m in res.json()]
        assert titles == ["Tagged"]

    def test_filter_by_nonexistent_tag_returns_empty(self, client):
        _seed("Meeting")
        assert client.get("/meetings?tag=nosuchtagxyz").json() == []

    def test_requires_auth(self):
        from app import app
        res = TestClient(app).get("/meetings")
        assert res.status_code == 401


# ── GET /meetings/{id} ────────────────────────────────────────────────────────

class TestGetMeeting:
    def test_returns_full_detail(self, client):
        mid = _seed("Detail Test", tags=["roadmap"])
        res = client.get(f"/meetings/{mid}")
        assert res.status_code == 200
        data = res.json()
        assert data["title"] == "Detail Test"
        assert data["summary"] == "summary"
        assert "roadmap" in data["tags"]
        assert "notes_raw" in data

    def test_returns_404_for_missing_meeting(self, client):
        assert client.get("/meetings/99999").status_code == 404

    def test_requires_auth(self):
        from app import app
        assert TestClient(app).get("/meetings/1").status_code == 401

    def test_includes_recording_url(self, client):
        mid = _seed("Recorded", recording_url="https://example.com/rec")
        data = client.get(f"/meetings/{mid}").json()
        assert data["recording_url"] == "https://example.com/rec"

    def test_includes_meeting_date(self, client):
        mid = _seed("Dated", meeting_date="2026-03-17")
        data = client.get(f"/meetings/{mid}").json()
        assert data["date"] == "2026-03-17"


# ── POST /meetings/{id}/tags ──────────────────────────────────────────────────

class TestAddTag:
    def test_adds_new_tag(self, client):
        mid = _seed("Meeting")
        res = client.post(f"/meetings/{mid}/tags", json={"name": "hiring"})
        assert res.status_code == 200
        assert "hiring" in res.json()["tags"]

    def test_reuses_existing_global_tag(self, client):
        db = database.SessionLocal()
        try:
            db.add(Tag(name="existing-tag")); db.commit()
        finally:
            db.close()
        mid = _seed("Meeting")
        res = client.post(f"/meetings/{mid}/tags", json={"name": "existing-tag"})
        assert res.status_code == 200
        # Tag count in DB should not have duplicates
        db2 = database.SessionLocal()
        try:
            count = db2.query(Tag).filter(Tag.name == "existing-tag").count()
            assert count == 1
        finally:
            db2.close()

    def test_normalizes_case(self, client):
        mid = _seed("Meeting")
        res = client.post(f"/meetings/{mid}/tags", json={"name": "  Hiring  "})
        assert res.status_code == 200
        assert "hiring" in res.json()["tags"]

    def test_rejects_tag_with_spaces(self, client):
        mid = _seed("Meeting")
        assert client.post(f"/meetings/{mid}/tags", json={"name": "bad tag"}).status_code == 422

    def test_rejects_tag_with_underscore(self, client):
        mid = _seed("Meeting")
        assert client.post(f"/meetings/{mid}/tags", json={"name": "bad_tag"}).status_code == 422

    def test_rejects_tag_starting_with_hyphen(self, client):
        mid = _seed("Meeting")
        assert client.post(f"/meetings/{mid}/tags", json={"name": "-bad"}).status_code == 422

    def test_rejects_duplicate_tag_on_same_meeting(self, client):
        mid = _seed("Meeting", tags=["roadmap"])
        assert client.post(f"/meetings/{mid}/tags", json={"name": "roadmap"}).status_code == 422

    def test_enforces_max_10_tags(self, client):
        tags = [f"tag{i}" for i in range(10)]
        mid = _seed("Meeting", tags=tags)
        assert client.post(f"/meetings/{mid}/tags", json={"name": "eleventh"}).status_code == 422

    def test_returns_404_for_missing_meeting(self, client):
        assert client.post("/meetings/99999/tags", json={"name": "x"}).status_code == 404

    def test_requires_auth(self):
        from app import app
        assert TestClient(app).post("/meetings/1/tags", json={"name": "x"}).status_code == 401


# ── DELETE /meetings/{id}/tags/{name} ────────────────────────────────────────

class TestRemoveTag:
    def test_unlinks_tag_from_meeting(self, client):
        mid = _seed("Meeting", tags=["roadmap"])
        res = client.delete(f"/meetings/{mid}/tags/roadmap")
        assert res.status_code == 200
        assert "roadmap" not in res.json()["tags"]

    def test_does_not_delete_global_tag(self, client):
        mid = _seed("Meeting", tags=["roadmap"])
        client.delete(f"/meetings/{mid}/tags/roadmap")
        db = database.SessionLocal()
        try:
            assert db.query(Tag).filter(Tag.name == "roadmap").first() is not None
        finally:
            db.close()

    def test_nonexistent_tag_returns_200_gracefully(self, client):
        mid = _seed("Meeting")
        res = client.delete(f"/meetings/{mid}/tags/nothere")
        assert res.status_code == 200

    def test_requires_auth(self):
        from app import app
        assert TestClient(app).delete("/meetings/1/tags/x").status_code == 401


# ── DELETE /meetings/{id} ─────────────────────────────────────────────────────

class TestDeleteMeeting:
    def test_returns_204(self, client):
        mid = _seed("To Delete")
        assert client.delete(f"/meetings/{mid}").status_code == 204

    def test_meeting_no_longer_retrievable(self, client):
        mid = _seed("To Delete")
        client.delete(f"/meetings/{mid}")
        assert client.get(f"/meetings/{mid}").status_code == 404

    def test_returns_404_for_missing_meeting(self, client):
        assert client.delete("/meetings/99999").status_code == 404

    def test_requires_auth(self):
        from app import app
        assert TestClient(app).delete("/meetings/1").status_code == 401


# ── GET /tags/trending ────────────────────────────────────────────────────────

class TestTagsTrending:
    def test_returns_tags_sorted_by_count_desc(self, client):
        _seed("M1", tags=["roadmap", "budget"])
        _seed("M2", tags=["roadmap"])
        res = client.get("/tags/trending")
        assert res.status_code == 200
        tags = res.json()
        assert tags[0]["name"] == "roadmap"
        assert tags[0]["count"] == 2
        assert tags[1]["count"] == 1

    def test_empty_db_returns_empty_list(self, client):
        assert client.get("/tags/trending").json() == []

    def test_each_item_has_id_name_count(self, client):
        _seed("M", tags=["hiring"])
        item = client.get("/tags/trending").json()[0]
        assert "id" in item and "name" in item and "count" in item

    def test_requires_auth(self):
        from app import app
        assert TestClient(app).get("/tags/trending").status_code == 401
