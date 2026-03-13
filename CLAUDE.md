# CLAUDE.md

## Project Overview
This project is a small AI app that takes meeting notes as input and returns:
- a short summary
- action items
- tags
meetings can be in different languages. output should always be in english.

## Goal
Build a very small MVP first.
Do not overengineer it.

## Tech Stack
- Python
- FastAPI
- Simple HTML frontend

## Architecture
Use one LLM call per request unless explicitly needed.

## LLM Provider
- Use **Azure OpenAI** via the `openai` Python SDK (`AzureOpenAI` client)
- Required environment variables:
  - `AZURE_OPENAI_API_KEY`
  - `AZURE_OPENAI_ENDPOINT` (e.g. `https://<your-resource>.openai.azure.com/`)
  - `AZURE_OPENAI_DEPLOYMENT` (your deployed model name, e.g. `gpt-4o`)
  - `AZURE_OPENAI_MODEL_VERSION` (e.g. `2024-02-01`)
- Do not use the Anthropic SDK
- API key and all other properties must be read from environment variables

## Coding Guidelines
- Keep code simple and readable
- Prefer small functions
- Add basic error handling
- Do not introduce a database unless requested
- Do not add auth unless requested (Okta auth has been requested — see Authentication section)
- Do not add agents, RAG, queues, or Docker unless requested

## Authentication

Authentication is via **Adobe Okta** using the Authorization Code flow with PKCE. No client secret is needed (SPA/public-client app type).

### App registration
- Register at `https://oss.corp.adobe.com/okta/` — choose type **SPA**
- Add redirect URI: `https://localhost:8000/auth/okta/callback` (must be `https`)
- The client ID shown after registration goes in `.env` as `OKTA_CLIENT_ID`

### Okta issuer
- Adobe production Okta: `https://adobe.okta.com/oauth2/aus1gan31wnmCPyB60h8`
- Set this as `OKTA_ISSUER` in `.env`

### Required environment variables
```
OKTA_ISSUER=https://adobe.okta.com/oauth2/aus1gan31wnmCPyB60h8
OKTA_CLIENT_ID=<your client id from oss>
OKTA_REDIRECT_URI=https://localhost:8000/auth/okta/callback
SECRET_KEY=<random secret for signing cookies>
```

### SSL on localhost
Okta requires `https` redirect URIs. Run the backend with a self-signed certificate:
```bash
# Generate self-signed cert (one-time)
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=localhost"

# Run uvicorn with SSL
uvicorn app:app --ssl-keyfile key.pem --ssl-certfile cert.pem --port 8000
```

### Same-origin advantage
Unlike `meeting-laibrary` (React/Vite on a separate port), this app serves HTML directly from FastAPI on port 8000. Frontend and backend share the same origin — no Vite proxy is needed. Cookies work with `httponly=True, samesite="lax"` and no `secure` flag issues.

### Session cookies
Use `itsdangerous.URLSafeSerializer` for signed session cookies. This avoids in-memory session state (which is lost on restart) and requires no database. The cookie value is a signed payload containing the user's email and expiry. Validate by calling `signer.loads(token)` — if it raises `BadSignature`, the session is invalid.

### PKCE flow (backend-driven)
1. On `/auth/okta/login`: generate `code_verifier` + `code_challenge`, store `state → code_verifier` in a short-lived in-memory dict, redirect user to Okta authorization URL
2. On `/auth/okta/callback`: look up `code_verifier` by `state`, exchange `code` for tokens via Okta token endpoint, validate the `id_token` JWT, set signed `okta_session` cookie, redirect to `/`
3. All other routes: check for valid `okta_session` cookie — if missing or invalid, redirect to `/auth/okta/login`

### JWT validation
Use `python-jose`. Fetch the JWKS from `{OKTA_ISSUER}/v1/keys`. Always set `options={"verify_at_hash": False}` — Okta's authorization code flow does not include `at_hash` in the id_token.

### Required packages
Add to `requirements.txt`:
```
httpx>=0.27.0
python-jose[cryptography]>=3.3.0
itsdangerous>=2.1.0
```

### Auth routes in app.py
- `GET /auth/okta/login` — initiates PKCE flow, redirects to Okta
- `GET /auth/okta/callback` — handles Okta redirect, sets cookie, redirects to `/`
- `GET /auth/logout` — clears `okta_session` cookie, redirects to `/auth/okta/login`
- `GET /auth/status` — returns `{"authenticated": bool}` for the frontend to check

### Auth file
All Okta logic lives in `auth.py` (not `app.py`). Import it in `app.py` and call its functions from routes. `load_dotenv()` must be called **before** importing `auth.py`, because env vars are read at module load time.

### Login UI
Add a login page (e.g. `pages/login.html`) served at `/login`. It should show a single "Sign in with Adobe (Okta)" button that links to `/auth/okta/login`. Style it consistently with `index.html`.

## File Responsibilities
- `app.py` contains the FastAPI app and routes
- `llm_client.py` handles model API calls
- `ai_templates.py` stores prompt-building logic
- `models.py` stores request/response schemas
- `pages/index.html` contains the UI — inline CSS and JS, no build step required. Style uses the same design language as `meeting-laibrary`: purple gradient header (`#667eea` → `#764ba2`), white cards with `border-radius: 8px` and `box-shadow`, Inter font via Google Fonts, dark mode via `prefers-color-scheme`.
- `auth.py` handles Okta authentication — PKCE flow, JWT validation, signed session cookies
- `pages/login.html` contains the login page with a single "Sign in with Adobe (Okta)" button
- `tests/` contains basic tests

## Output Requirements
The model output should be structured and easy to parse.
Prefer JSON-shaped output with:
- summary
- action_items
- tags

## Safe Editing Rules
- Keep changes minimal
- Do not refactor unrelated files
- Prefer updating existing files over creating many new ones