from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, UniqueConstraint, DateTime, LargeBinary
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timezone

DATABASE_URL = "sqlite:///./meetings.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Meeting(Base):
    __tablename__ = "meetings"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    notes_raw = Column(Text, nullable=False)
    summary = Column(Text, nullable=False)
    action_items = Column(Text, nullable=False)  # JSON string
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    embedding = Column(LargeBinary, nullable=True)


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)


class MeetingTag(Base):
    __tablename__ = "meeting_tags"

    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (UniqueConstraint("meeting_id", "tag_id"),)


def init_db():
    Base.metadata.create_all(bind=engine)
    import sqlalchemy as sa
    with engine.connect() as conn:
        # meetings table migrations
        meetings_cols = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(meetings)"))}
        if "created_at" not in meetings_cols:
            conn.execute(sa.text("ALTER TABLE meetings ADD COLUMN created_at DATETIME"))
            conn.execute(sa.text("UPDATE meetings SET created_at = '1970-01-01 00:00:00' WHERE created_at IS NULL"))
        # chunks table migrations
        chunks_cols = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(chunks)"))}
        if "description" not in chunks_cols:
            conn.execute(sa.text("ALTER TABLE chunks ADD COLUMN description TEXT"))
        if "embedding" not in chunks_cols:
            conn.execute(sa.text("ALTER TABLE chunks ADD COLUMN embedding BLOB"))
        conn.commit()
