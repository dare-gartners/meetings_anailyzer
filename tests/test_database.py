"""Tests for database constraints, cascade deletes, and storage behaviour."""
import pytest
import numpy as np
from sqlalchemy.exc import IntegrityError
import core.database as database
from core.database import Meeting, Chunk, Tag, MeetingTag


def _meeting(**kwargs) -> Meeting:
    defaults = dict(title="T", notes_raw="n", summary="s", action_items="[]")
    defaults.update(kwargs)
    return Meeting(**defaults)


class TestCascadeDelete:
    def test_delete_meeting_removes_chunks(self):
        db = database.SessionLocal()
        try:
            m = _meeting(); db.add(m); db.flush()
            c = Chunk(meeting_id=m.id, chunk_index=0, text="chunk")
            db.add(c); db.commit()
            cid = c.id
            db.delete(db.query(Meeting).get(m.id)); db.commit()
            assert db.query(Chunk).filter(Chunk.id == cid).first() is None
        finally:
            db.close()

    def test_delete_meeting_removes_meeting_tags(self):
        db = database.SessionLocal()
        try:
            m = _meeting(); db.add(m); db.flush()
            t = Tag(name="cascade-tag"); db.add(t); db.flush()
            mt = MeetingTag(meeting_id=m.id, tag_id=t.id)
            db.add(mt); db.commit()
            mtid = mt.id
            db.delete(db.query(Meeting).get(m.id)); db.commit()
            assert db.query(MeetingTag).filter(MeetingTag.id == mtid).first() is None
        finally:
            db.close()

    def test_delete_meeting_does_not_delete_global_tag(self):
        db = database.SessionLocal()
        try:
            m = _meeting(); db.add(m); db.flush()
            t = Tag(name="global-tag"); db.add(t); db.flush()
            db.add(MeetingTag(meeting_id=m.id, tag_id=t.id)); db.commit()
            tid = t.id
            db.delete(db.query(Meeting).get(m.id)); db.commit()
            assert db.query(Tag).filter(Tag.id == tid).first() is not None
        finally:
            db.close()


class TestUniqueConstraints:
    def test_tag_name_must_be_unique(self):
        db = database.SessionLocal()
        try:
            db.add(Tag(name="unique-tag")); db.commit()
            db.add(Tag(name="unique-tag"))
            with pytest.raises(IntegrityError):
                db.commit()
        finally:
            db.rollback(); db.close()

    def test_meeting_tag_pair_must_be_unique(self):
        db = database.SessionLocal()
        try:
            m = _meeting(); db.add(m); db.flush()
            t = Tag(name="pair-tag"); db.add(t); db.flush()
            db.add(MeetingTag(meeting_id=m.id, tag_id=t.id)); db.commit()
            db.add(MeetingTag(meeting_id=m.id, tag_id=t.id))
            with pytest.raises(IntegrityError):
                db.commit()
        finally:
            db.rollback(); db.close()

    def test_same_tag_can_link_to_different_meetings(self):
        db = database.SessionLocal()
        try:
            m1 = _meeting(title="M1"); db.add(m1); db.flush()
            m2 = _meeting(title="M2"); db.add(m2); db.flush()
            t = Tag(name="shared-tag"); db.add(t); db.flush()
            db.add(MeetingTag(meeting_id=m1.id, tag_id=t.id))
            db.add(MeetingTag(meeting_id=m2.id, tag_id=t.id))
            db.commit()  # should not raise
        finally:
            db.close()


class TestEmbeddingStorage:
    def test_float32_array_round_trips_via_blob(self):
        db = database.SessionLocal()
        try:
            m = _meeting(); db.add(m); db.flush()
            vec = np.array([0.1, 0.5, -0.3, 0.9], dtype=np.float32)
            c = Chunk(meeting_id=m.id, chunk_index=0, text="t", embedding=vec.tobytes())
            db.add(c); db.commit()
            c2 = db.query(Chunk).filter(Chunk.id == c.id).first()
            recovered = np.frombuffer(c2.embedding, dtype=np.float32)
            np.testing.assert_array_almost_equal(recovered, vec)
        finally:
            db.close()

    def test_null_embedding_allowed(self):
        db = database.SessionLocal()
        try:
            m = _meeting(); db.add(m); db.flush()
            c = Chunk(meeting_id=m.id, chunk_index=0, text="t", embedding=None)
            db.add(c); db.commit()
            c2 = db.query(Chunk).filter(Chunk.id == c.id).first()
            assert c2.embedding is None
        finally:
            db.close()


class TestOptionalMeetingFields:
    def test_meeting_date_nullable(self):
        db = database.SessionLocal()
        try:
            m = _meeting(); db.add(m); db.commit()
            assert db.query(Meeting).get(m.id).meeting_date is None
        finally:
            db.close()

    def test_recording_url_nullable(self):
        db = database.SessionLocal()
        try:
            m = _meeting(); db.add(m); db.commit()
            assert db.query(Meeting).get(m.id).recording_url is None
        finally:
            db.close()

    def test_meeting_date_stored_correctly(self):
        db = database.SessionLocal()
        try:
            m = _meeting(meeting_date="2026-03-17"); db.add(m); db.commit()
            assert db.query(Meeting).get(m.id).meeting_date == "2026-03-17"
        finally:
            db.close()
