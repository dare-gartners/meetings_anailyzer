"""
Shared test fixtures.

- _use_test_db  : redirects all DB ops to an isolated in-memory SQLite for the
                  whole test session — production meetings.db is never touched.
- clean_db      : wipes all rows before each test (autouse).
- client        : FastAPI TestClient with Okta auth bypassed.
"""
import pytest
from unittest.mock import patch
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def _use_test_db():
    import database

    # StaticPool forces all connections to share one in-memory DB so that
    # tables created by init_db() are visible to every subsequent session.
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(test_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    TestSession = sessionmaker(bind=test_engine)

    orig_engine  = database.engine
    orig_session = database.SessionLocal

    database.engine       = test_engine
    database.SessionLocal = TestSession

    database.init_db()

    yield

    database.engine       = orig_engine
    database.SessionLocal = orig_session
    test_engine.dispose()


@pytest.fixture(autouse=True)
def clean_db():
    """Wipe all rows before each test. Deletes in FK order."""
    import database
    db = database.SessionLocal()
    try:
        db.query(database.MeetingTag).delete()
        db.query(database.Chunk).delete()
        db.query(database.Tag).delete()
        db.query(database.Meeting).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture
def client():
    """TestClient with Okta auth bypassed."""
    from app import app
    with patch("auth.require_auth", return_value="test@example.com"):
        yield TestClient(app)
