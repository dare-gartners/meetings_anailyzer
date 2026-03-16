import json
import logging
from dotenv import load_dotenv

load_dotenv()  # must be before auth import — env vars are read at module load

import auth  # noqa: E402 (intentional late import)

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from models import NotesRequest, NotesResponse
from llm_client import analyze_notes
from database import init_db, SessionLocal, Meeting, Chunk
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
        for idx, chunk in enumerate(chunk_text(body.notes)):
            db.add(Chunk(meeting_id=meeting.id, chunk_index=idx, text=chunk))
        db.commit()
    except Exception as e:
        logger.error("DB save failed: %s", e)
    finally:
        db.close()

    return NotesResponse(**data)
