"""
Redirect all DB operations to an isolated in-memory SQLite for the test session.

app.py binds SessionLocal at import time via `from database import SessionLocal`,
so we must patch both the database module and the app module's reference.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture(scope="session", autouse=True)
def _use_test_db():
    import database
    import app as app_module

    # StaticPool makes all connections share one in-memory DB,
    # so tables created by init_db() are visible to all test sessions.
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSession = sessionmaker(bind=test_engine)

    orig_engine   = database.engine
    orig_session  = database.SessionLocal
    orig_app_sess = app_module.SessionLocal

    database.engine       = test_engine
    database.SessionLocal = TestSession
    app_module.SessionLocal = TestSession

    # Create schema + run migrations on the test DB
    database.init_db()

    yield

    database.engine         = orig_engine
    database.SessionLocal   = orig_session
    app_module.SessionLocal = orig_app_sess
    test_engine.dispose()
