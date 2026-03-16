import asyncio
import json
import logging
from dotenv import load_dotenv

load_dotenv()  # must be before auth import — env vars are read at module load

import auth  # noqa: E402 (intentional late import)

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import re
import numpy as np
from models import NotesRequest, NotesResponse, MeetingListItem, MeetingDetail, TagAddRequest, SimilarMeeting, ChunkMatch, ExplainRequest
from llm_client import analyze_notes, generate_tags, generate_description, generate_embedding, explain_match, verify_match
from database import init_db, SessionLocal, Meeting, Chunk, Tag, MeetingTag
from chunking import chunk_text

logger = logging.getLogger(__name__)

app = FastAPI()
templates = Jinja2Templates(directory="pages")

init_db()


# --- Auth routes ---

@app.get("/auth/okta/login")
def okta_login():
    return auth.build_login_redirect()


@app.get("/auth/okta/callback")
def okta_callback(code: str, state: str):
    return auth.handle_callback(code, state)


@app.get("/auth/logout")
def logout():
    return auth.logout_response()


@app.get("/auth/status")
def auth_status(request: Request):
    email = auth.get_session_email(request)
    return {"authenticated": email is not None, "email": email}


# --- Pages ---

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    email = auth.require_auth(request)
    if not email:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("index.html", {"request": request, "email": email})


# --- API ---

@app.post("/analyze", response_model=NotesResponse)
async def analyze(body: NotesRequest, request: Request):
    if not auth.require_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, analyze_notes, body.notes, body.title)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Model returned invalid JSON")

    try:
        db = SessionLocal()
        meeting = Meeting(
            title=body.title,
            notes_raw=body.notes,
            summary=data.get("summary", ""),
            action_items=json.dumps(data.get("action_items", [])),
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

        # All descriptions in parallel
        async def _describe(c):
            try:
                return await loop.run_in_executor(None, generate_description, c.text)
            except Exception as e:
                logger.error("Description generation failed for chunk %s: %s", c.id, e)
                return None

        descriptions = await asyncio.gather(*[_describe(c) for c in chunk_rows])

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

        await asyncio.gather(*[_embed(c) for c in chunk_rows])
        db.commit()

        # All tag generation in parallel
        existing_tags = [row.name for row in db.query(Tag.name).all()]

        async def _tags(c):
            try:
                return await loop.run_in_executor(None, generate_tags, c.text, list(existing_tags))
            except Exception as e:
                logger.error("Tag generation failed for chunk %s: %s", c.id, e)
                return []

        all_tag_names = await asyncio.gather(*[_tags(c) for c in chunk_rows])

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
    except Exception as e:
        logger.error("DB save failed: %s", e)
    finally:
        db.close()

    return NotesResponse(**data)


@app.get("/meetings", response_model=list[MeetingListItem])
def list_meetings(request: Request):
    if not auth.require_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    db = SessionLocal()
    try:
        meetings = db.query(Meeting).order_by(Meeting.created_at.desc()).all()
        return [MeetingListItem(id=m.id, title=m.title, created_at=m.created_at) for m in meetings]
    finally:
        db.close()


def _meeting_tags(db, meeting_id: int) -> list[str]:
    rows = (
        db.query(Tag.name)
        .join(MeetingTag, MeetingTag.tag_id == Tag.id)
        .filter(MeetingTag.meeting_id == meeting_id)
        .all()
    )
    return [r.name for r in rows]


@app.get("/meetings/{meeting_id}", response_model=MeetingDetail)
def get_meeting(meeting_id: int, request: Request):
    if not auth.require_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    db = SessionLocal()
    try:
        m = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not m:
            raise HTTPException(status_code=404, detail="Meeting not found")
        return MeetingDetail(
            id=m.id,
            title=m.title,
            created_at=m.created_at,
            summary=m.summary,
            action_items=json.loads(m.action_items),
            tags=_meeting_tags(db, m.id),
        )
    finally:
        db.close()


TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")

@app.post("/meetings/{meeting_id}/tags", response_model=MeetingDetail)
def add_tag(meeting_id: int, body: TagAddRequest, request: Request):
    if not auth.require_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    name = body.name.strip().lower()
    if not TAG_PATTERN.match(name):
        raise HTTPException(status_code=422, detail="Invalid tag format")
    db = SessionLocal()
    try:
        m = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not m:
            raise HTTPException(status_code=404, detail="Meeting not found")
        current_tags = _meeting_tags(db, meeting_id)
        if len(current_tags) >= 10:
            raise HTTPException(status_code=422, detail="Maximum 10 tags per meeting")
        if name in current_tags:
            raise HTTPException(status_code=422, detail="Tag already linked")
        tag = db.query(Tag).filter(Tag.name == name).first()
        if not tag:
            tag = Tag(name=name)
            db.add(tag)
            db.flush()
        db.add(MeetingTag(meeting_id=meeting_id, tag_id=tag.id))
        db.commit()
        return MeetingDetail(
            id=m.id,
            title=m.title,
            created_at=m.created_at,
            summary=m.summary,
            action_items=json.loads(m.action_items),
            tags=_meeting_tags(db, m.id),
        )
    finally:
        db.close()


@app.delete("/meetings/{meeting_id}/tags/{tag_name}", response_model=MeetingDetail)
def remove_tag(meeting_id: int, tag_name: str, request: Request):
    if not auth.require_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    db = SessionLocal()
    try:
        m = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not m:
            raise HTTPException(status_code=404, detail="Meeting not found")
        tag = db.query(Tag).filter(Tag.name == tag_name).first()
        if tag:
            db.query(MeetingTag).filter(
                MeetingTag.meeting_id == meeting_id,
                MeetingTag.tag_id == tag.id,
            ).delete()
            db.commit()
        return MeetingDetail(
            id=m.id,
            title=m.title,
            created_at=m.created_at,
            summary=m.summary,
            action_items=json.loads(m.action_items),
            tags=_meeting_tags(db, m.id),
        )
    finally:
        db.close()


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom else 0.0


@app.post("/meetings/{meeting_id}/similar", response_model=list[SimilarMeeting])
async def find_similar(meeting_id: int, request: Request):
    if not auth.require_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    db = SessionLocal()
    try:
        source_chunks = (
            db.query(Chunk)
            .filter(Chunk.meeting_id == meeting_id, Chunk.embedding.isnot(None))
            .all()
        )
        if not source_chunks:
            return []

        source_vecs = [np.frombuffer(c.embedding, dtype=np.float32) for c in source_chunks]

        other_chunks = (
            db.query(Chunk)
            .filter(Chunk.meeting_id != meeting_id, Chunk.embedding.isnot(None))
            .all()
        )

        # Best match per (meeting_id, source_chunk_id) — prevents the same source chunk from appearing multiple times
        best_per_source: dict[tuple[int, int], tuple[float, str, str | None, str, str | None]] = {}
        for chunk in other_chunks:
            vec = np.frombuffer(chunk.embedding, dtype=np.float32)
            scores = [(_cosine(sv, vec), i, source_chunks[i].text, source_chunks[i].description) for i, sv in enumerate(source_vecs)]
            top_score, best_src_idx, best_source_text, best_source_desc = max(scores, key=lambda x: x[0])
            if top_score < 0.45:
                continue
            key = (chunk.meeting_id, source_chunks[best_src_idx].id)
            existing = best_per_source.get(key)
            if existing is None or top_score > existing[0]:
                best_per_source[key] = (top_score, chunk.text, chunk.description, best_source_text, best_source_desc)

        # LLM re-ranking: verify all candidates in parallel
        loop = asyncio.get_event_loop()
        candidates = list(best_per_source.items())

        async def _verify(key, entry):
            s, matched_text, matched_desc, src_text, src_desc = entry
            a = src_desc or src_text.split('\n')[0].strip()
            b = matched_desc or matched_text.split('\n')[0].strip()
            try:
                return key, entry, await loop.run_in_executor(None, verify_match, a, b)
            except Exception as e:
                logger.error("verify_match failed: %s", e)
                return key, entry, True  # fail open

        verified = await asyncio.gather(*[_verify(k, v) for k, v in candidates])

        all_matches: dict[int, list[tuple[float, str, str | None, str, str | None]]] = {}
        for (mid, _src_id), entry, passed in verified:
            if passed:
                all_matches.setdefault(mid, []).append(entry)

        if not all_matches:
            return []

        # Sort meetings by best score, take top 5
        meeting_best = {mid: max(m[0] for m in matches) for mid, matches in all_matches.items()}
        top_mids = sorted(meeting_best, key=lambda mid: meeting_best[mid], reverse=True)[:5]

        results = []
        for mid in top_mids:
            m = db.query(Meeting).filter(Meeting.id == mid).first()
            if not m:
                continue
            best_score = meeting_best[mid]
            chunk_matches = sorted(all_matches[mid], key=lambda x: x[0], reverse=True)
            results.append(SimilarMeeting(
                id=m.id,
                title=m.title,
                created_at=m.created_at,
                tags=_meeting_tags(db, m.id),
                score=round(best_score, 3),
                all_matches=[
                    ChunkMatch(
                        source_chunk=src,
                        matched_chunk=matched,
                        source_description=src_desc,
                        matched_description=matched_desc,
                        score=round(s, 3),
                        is_best=(s == best_score),
                    )
                    for s, matched, matched_desc, src, src_desc in chunk_matches
                ],
            ))
        return results
    finally:
        db.close()


@app.post("/matches/explain")
def explain(body: ExplainRequest, request: Request):
    if not auth.require_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    explanation = explain_match(body.source_chunk, body.matched_chunk)
    return {"explanation": explanation}
