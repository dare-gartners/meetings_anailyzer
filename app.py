import json
import logging
from dotenv import load_dotenv

load_dotenv()  # must be before auth import — env vars are read at module load

import auth  # noqa: E402 (intentional late import)

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import re
from models import NotesRequest, NotesResponse, MeetingListItem, MeetingDetail, TagAddRequest
from llm_client import analyze_notes, generate_tags
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
def analyze(body: NotesRequest, request: Request):
    if not auth.require_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    raw = analyze_notes(body.notes, body.title)
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
        saved_chunks = []
        for idx, chunk in enumerate(chunks):
            c = Chunk(meeting_id=meeting.id, chunk_index=idx, text=chunk)
            db.add(c)
            saved_chunks.append(chunk)
        db.commit()

        # Tag generation — failures are isolated per chunk
        existing_tags = [row.name for row in db.query(Tag.name).all()]
        linked_tag_ids: set[int] = set()

        for chunk in saved_chunks:
            try:
                tag_names = generate_tags(chunk, existing_tags)
            except Exception as e:
                logger.error("Tag generation failed for chunk: %s", e)
                continue

            for name in tag_names:
                tag = db.query(Tag).filter(Tag.name == name).first()
                if not tag:
                    tag = Tag(name=name)
                    db.add(tag)
                    db.flush()
                    existing_tags.append(name)
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
