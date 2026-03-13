import os
import base64
import hashlib
import secrets
import time

import httpx
from jose import jwt, JWTError
from itsdangerous import URLSafeSerializer, BadSignature
from fastapi import Request
from fastapi.responses import RedirectResponse

OKTA_ISSUER = os.environ.get("OKTA_ISSUER", "")
OKTA_CLIENT_ID = os.environ.get("OKTA_CLIENT_ID", "")
OKTA_REDIRECT_URI = os.environ.get("OKTA_REDIRECT_URI", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "change-me")

COOKIE_NAME = "okta_session"
SESSION_TTL = 8 * 60 * 60  # 8 hours

signer = URLSafeSerializer(SECRET_KEY, salt="okta-session")

# Short-lived in-memory store: state -> code_verifier
_pkce_store: dict[str, str] = {}


# --- PKCE helpers ---

def _generate_code_verifier() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode()


def _code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


# --- Login redirect ---

def build_login_redirect() -> RedirectResponse:
    verifier = _generate_code_verifier()
    challenge = _code_challenge(verifier)
    state = secrets.token_urlsafe(16)
    _pkce_store[state] = verifier

    params = (
        f"?response_type=code"
        f"&client_id={OKTA_CLIENT_ID}"
        f"&redirect_uri={OKTA_REDIRECT_URI}"
        f"&scope=openid+email+profile"
        f"&state={state}"
        f"&code_challenge={challenge}"
        f"&code_challenge_method=S256"
    )
    return RedirectResponse(url=f"{OKTA_ISSUER}/v1/authorize{params}")


# --- Callback handling ---

def handle_callback(code: str, state: str) -> RedirectResponse:
    verifier = _pkce_store.pop(state, None)
    if not verifier:
        return RedirectResponse(url="/login?error=invalid_state")

    token_url = f"{OKTA_ISSUER}/v1/token"
    with httpx.Client() as client:
        resp = client.post(token_url, data={
            "grant_type": "authorization_code",
            "client_id": OKTA_CLIENT_ID,
            "redirect_uri": OKTA_REDIRECT_URI,
            "code": code,
            "code_verifier": verifier,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})

    if resp.status_code != 200:
        return RedirectResponse(url="/login?error=token_exchange_failed")

    tokens = resp.json()
    id_token = tokens.get("id_token")
    if not id_token:
        return RedirectResponse(url="/login?error=no_id_token")

    email = _validate_id_token(id_token)
    if not email:
        return RedirectResponse(url="/login?error=invalid_token")

    session_value = signer.dumps({"email": email, "exp": int(time.time()) + SESSION_TTL})
    response = RedirectResponse(url="/")
    response.set_cookie(COOKIE_NAME, session_value, httponly=True, samesite="lax", max_age=SESSION_TTL)
    return response


# --- JWT validation ---

def _validate_id_token(id_token: str) -> str | None:
    jwks_url = f"{OKTA_ISSUER}/v1/keys"
    with httpx.Client() as client:
        jwks = client.get(jwks_url).json()

    try:
        claims = jwt.decode(
            id_token,
            jwks,
            algorithms=["RS256"],
            audience=OKTA_CLIENT_ID,
            options={"verify_at_hash": False},
        )
        return claims.get("email") or claims.get("sub")
    except JWTError:
        return None


# --- Session helpers ---

def get_session_email(request: Request) -> str | None:
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        return None
    try:
        data = signer.loads(cookie)
        if time.time() > data.get("exp", 0):
            return None
        return data.get("email")
    except BadSignature:
        return None


def require_auth(request: Request) -> str | None:
    """Return email if authenticated, else None (caller should redirect)."""
    return get_session_email(request)


def logout_response() -> RedirectResponse:
    response = RedirectResponse(url="/login")
    response.delete_cookie(COOKIE_NAME)
    return response
