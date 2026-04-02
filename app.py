import logging
from dotenv import load_dotenv

load_dotenv()  # must be before auth import — env vars are read at module load

import auth  # noqa: E402 (intentional late import)

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from database import init_db
from routers import analyze, meetings, similarity, search

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

app = FastAPI()
templates = Jinja2Templates(directory="pages")
app.mount("/static", StaticFiles(directory="pages/static"), name="static")

init_db()

app.include_router(analyze.router)
app.include_router(meetings.router)
app.include_router(similarity.router)
app.include_router(search.router)


# ── Auth routes ───────────────────────────────────────────────────────────────

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


# ── Page routes ───────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    email = auth.require_auth(request)
    if not email:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("index.html", {"request": request, "email": email})
