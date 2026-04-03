"""Meeting analysis endpoint — calls LLM, saves meeting + chunks + tags."""

import asyncio
import json
import logging
import time

from fastapi import APIRouter, HTTPException, Request

import auth
import core.database as database
from core.database import Meeting, Chunk, Tag, MeetingTag
from llm.client import analyze_notes, generate_tags, generate_description, generate_embedding
from core.models import NotesRequest, NotesResponse
from core.chunking import chunk_text

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/analyze", response_model=NotesResponse)
async def analyze(body: NotesRequest, request: Request):
    if not auth.require_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    t_req = time.perf_counter()
    logger.info("analyze:start title=%r", body.title)

    if body.recording_url:
        db = database.SessionLocal()
        try:
            if db.query(Meeting).filter(Meeting.recording_url == body.recording_url).first():
                raise HTTPException(status_code=409, detail="A meeting with this recording URL already exists.")
        finally:
            db.close()

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, analyze_notes, body.notes, body.title)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Model returned invalid JSON")
    data.setdefault("summary", "")

    db = database.SessionLocal()
    try:
        meeting = Meeting(
            title=body.title,
            notes_raw=body.notes,
            summary=data.get("summary", ""),
            action_items=json.dumps([]),
            meeting_date=body.date,
            recording_url=body.recording_url,
        )
        db.add(meeting)
        db.flush()

        chunks = chunk_text(body.notes)
        chunk_rows = []
        for idx, chunk in enumerate(chunks):
            c = Chunk(meeting_id=meeting.id, chunk_index=idx, text=chunk)
            db.add(c)
            chunk_rows.append(c)
        db.commit()
        logger.info("analyze:meeting_saved id=%s chunks=%d", meeting.id, len(chunk_rows))

        # All descriptions in parallel
        async def _describe(c):
            try:
                return await loop.run_in_executor(None, generate_description, c.text)
            except Exception as e:
                logger.error("Description generation failed for chunk %s: %s", c.id, e)
                return None

        t0 = time.perf_counter()
        descriptions = await asyncio.gather(*[_describe(c) for c in chunk_rows])
        logger.info("analyze:descriptions_batch done %.0fms chunks=%d", (time.perf_counter() - t0) * 1000, len(chunk_rows))

        for c, desc in zip(chunk_rows, descriptions):
            c.description = desc

        # All embeddings in parallel (only for chunks that got a description)
        async def _embed(c):
            if not c.description:
                return
            try:
                c.embedding = await loop.run_in_executor(None, generate_embedding, c.description)
            except Exception as e:
                logger.error("Embedding generation failed for chunk %s: %s", c.id, e)

        t0 = time.perf_counter()
        await asyncio.gather(*[_embed(c) for c in chunk_rows])
        logger.info("analyze:embeddings_batch done %.0fms chunks=%d", (time.perf_counter() - t0) * 1000, len(chunk_rows))
        db.commit()

        # All tag generation in parallel
        existing_tags = [row.name for row in db.query(Tag.name).all()]

        async def _tags(c):
            try:
                return await loop.run_in_executor(None, generate_tags, c.text, list(existing_tags))
            except Exception as e:
                logger.error("Tag generation failed for chunk %s: %s", c.id, e)
                return []

        t0 = time.perf_counter()
        all_tag_names = await asyncio.gather(*[_tags(c) for c in chunk_rows])
        logger.info("analyze:tags_batch done %.0fms chunks=%d", (time.perf_counter() - t0) * 1000, len(chunk_rows))

        linked_tag_ids: set[int] = set()
        for tag_names in all_tag_names:
            for name in tag_names:
                tag = db.query(Tag).filter(Tag.name == name).first()
                if not tag:
                    tag = Tag(name=name)
                    db.add(tag)
                    db.flush()
                if tag.id not in linked_tag_ids:
                    db.add(MeetingTag(meeting_id=meeting.id, tag_id=tag.id))
                    linked_tag_ids.add(tag.id)

        db.commit()
        data["tags"] = [db.query(Tag).filter(Tag.id == tid).first().name for tid in linked_tag_ids]
        data["id"] = meeting.id
    except Exception as e:
        logger.error("DB save failed: %s", e)
    finally:
        db.close()

    logger.info("analyze:done total=%.0fms", (time.perf_counter() - t_req) * 1000)
    return NotesResponse(**data)
