# CLAUDE.md

## Project Overview
This project is a small AI app that takes meeting notes as input and returns:
- a short summary
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
- Use one LLM call per request unless explicitly needed.
- Where multiple independent LLM/embedding calls are needed, run them in parallel using `asyncio.gather` + `loop.run_in_executor`. Both `/analyze` and `/meetings/{id}/similar` follow this pattern.

## LLM Provider
- Use **Azure OpenAI** via the `openai` Python SDK (`AzureOpenAI` client)
- Required environment variables:
  - `AZURE_OPENAI_API_KEY`
  - `AZURE_OPENAI_ENDPOINT` (e.g. `https://<your-resource>.openai.azure.com/`)
  - `AZURE_OPENAI_DEPLOYMENT` (your deployed model name, e.g. `gpt-4o`)
  - `AZURE_OPENAI_MODEL_VERSION` (e.g. `2024-02-01`)
  - `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` (your embeddings deployment, e.g. `text-embedding-ada-002`)
- Do not use the Anthropic SDK
- API key and all other properties must be read from environment variables
- See `.env.example` for a full list of required environment variables with placeholder values

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
uvicorn app:app --ssl-keyfile key.pem --ssl-certfile cert.pem --port 8000 --reload
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
- `database.py` contains SQLAlchemy models (`Meeting`, `Chunk`, `Tag`, `MeetingTag`) and `init_db()` (also runs ALTER TABLE migrations for new columns)
- `.env.example` documents all required environment variables with placeholder values
- `chunking.py` contains `chunk_text(notes) -> list[str]` — topic-based chunking for Teams AI format
- `pages/index.html` contains the UI — inline CSS and JS, no build step required. Layout: fixed sidebar (260px) listing saved meetings + main area showing either the new-meeting form or a meeting detail view. Style: purple gradient header (`#667eea` → `#764ba2`), white cards with `border-radius: 8px` and `box-shadow`, Inter font via Google Fonts, dark mode via `prefers-color-scheme`. The new-meeting form has fields: title (required), notes (required), date, language, recording URL, plus Save and Cancel buttons.
- `auth.py` handles Okta authentication — PKCE flow, JWT validation, signed session cookies
- `pages/login.html` contains the login page with a single "Sign in with Adobe (Okta)" button
- `tests/` contains basic tests

## Persistence
- SQLite via SQLAlchemy, stored in `meetings.db`
- `meetings` table: `id`, `title`, `notes_raw`, `summary`, `action_items` (JSON string — always `"[]"` for new records; column kept for backward compat), `created_at` (UTC datetime), `meeting_date` (VARCHAR(20), nullable), `language` (VARCHAR(100), nullable), `recording_url` (VARCHAR(500), nullable)
- `chunks` table: `id`, `meeting_id` (FK → meetings, cascade delete), `chunk_index`, `text`, `description` (TEXT, nullable), `embedding` (BLOB, nullable — numpy float32 array serialized via `.tobytes()`)
- `tags` table: `id`, `name` (unique across the whole table)
- `meeting_tags` table: `id`, `meeting_id` (FK → meetings, cascade delete), `tag_id` (FK → tags, cascade delete), unique on `(meeting_id, tag_id)`
- DB is initialized at app startup via `init_db()`
- After each successful `/analyze` call, the meeting and its chunks are saved
- After chunks are saved, all descriptions are generated in parallel (`asyncio.gather`), then all embeddings in parallel, then all tags in parallel — three sequential parallel batches
- Tag generation passes a snapshot of existing tags to all chunks simultaneously (parallel calls don't see each other's newly created tags, but do see all pre-existing ones)
- Description, embedding, and tag failures are isolated per chunk — logged but never fail the request
- New columns are added to existing tables via `ALTER TABLE` in `init_db()` if absent — do not drop or recreate tables
- DB save failures are logged but never surface to the caller — `/analyze` always returns the LLM result

## Meeting History & Detail View
- `GET /meetings` — returns all meetings ordered by `created_at` desc (`id`, `title`, `created_at`)
- `GET /meetings/{id}` — returns full meeting detail (`id`, `title`, `created_at`, `summary`, `tags`, `date`, `language`, `recording_url`, `notes_raw`)
- `POST /meetings/{id}/tags` — adds a tag to a meeting (body: `{name}`); max 10 tags per meeting; validates format; reuses existing global tag if name matches
- `DELETE /meetings/{id}/tags/{tag_name}` — unlinks a tag from a meeting; does NOT delete the tag globally
- `DELETE /meetings/{id}` — deletes the meeting and all its chunks/tags (cascade); returns 204
- Sidebar lists all meetings most recent first; updates after a new meeting is saved
- Clicking a sidebar item opens the detail view without a page reload
- Detail view layout (top to bottom): Back + Delete buttons → title → meta row (saved date, meeting date, language badge, recording link) → Tags section → Summary → "Show related meetings" button → Full Notes collapsible
- Meta row: saved timestamp, optional meeting date (📅), optional language badge, optional recording URL shown as "🎥 Recording" link
- Tags display as color-coded badges; same tag name always gets the same color (deterministic hash over 10-color palette defined in `index.html` as `TAG_COLORS`)
- User can remove a tag from a meeting (unlink only) or add a new one (up to 10 total)
- A "Back" button returns to the new-meeting form; a "Delete" button deletes the meeting after confirmation
- A "Show related meetings" button appears below the summary — triggers `POST /meetings/{id}/similar`; do NOT rename or change the backend logic
- Similar meeting results render as cards; clicking the title opens the meeting
- Each card uses a single table with columns "This meeting" | "{matched meeting title}" | "Match %" | "Why?"
- Collapsed state: header (title, date, green similarity badge, +/− toggle) + table showing only the best-match row; "+ N more matching topics" row below if multiple matches
- Expanded state (toggle via +/− button or the "+ N more" link): all matching rows shown, extra row hidden
- AI-generated descriptions are shown in table cells (readable, wrapping text); falls back to raw topic header when description is absent
- Best match row has a green border; column widths: 42% / 42% / 7% / 9%
- "Why?" button calls `POST /matches/explain`, shows explanation in a yellow/amber row below; clicking again hides it
- Results panel resets when switching to a different meeting

## Similarity Search
- `POST /meetings/{id}/similar` — finds meetings similar to the given one using chunk embeddings
- Two-stage pipeline:
  1. **Embedding filter**: cosine similarity ≥ 0.45 between chunk description embeddings; keeps cheapest possible candidate set
  2. **LLM re-ranking**: each candidate pair is verified with `verify_match()` in `llm_client.py` — asks the model whether the two topics discuss the same subject matter (not just the same product/domain); pairs that get a "no" are dropped
- Deduplication: for each (other meeting, source chunk) pair, only the highest-scoring other-meeting chunk is kept — prevents the same source topic appearing multiple times in one result
- Response: `id`, `title`, `created_at`, `tags`, `score` (best verified score, rounded to 3dp), `all_matches` (list of `ChunkMatch` sorted by score desc, max 3)
- `ChunkMatch`: `source_chunk`, `matched_chunk`, `source_description`, `matched_description` (both optional — null for old chunks), `score`, `is_best`
- If the meeting has no chunks with embeddings, returns an empty list
- Cosine similarity: `dot(a,b) / (norm(a) * norm(b))` in numpy
- `verify_match` failures are logged and the match is kept (fail open — prefer showing a false positive over hiding a true one)

## Match Explanation
- `POST /matches/explain` — generates a 1-2 sentence explanation of why two chunks are semantically related
- Request body: `source_chunk`, `matched_chunk` (frontend sends descriptions when available, falls back to raw chunk text)
- Calls Azure OpenAI via `explain_match()` in `llm_client.py`; starts with "Both meetings discussed…"
- Response: `{"explanation": "..."}`

## Chunk Descriptions & Embeddings
- After each chunk is saved, `generate_description(chunk)` in `llm_client.py` produces a 1-2 sentence summary of the topic
- The description (not the raw chunk text) is then embedded via `generate_embedding(description)` using `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`
- Embeddings are stored as numpy float32 arrays serialized with `.tobytes()` in the `embedding` BLOB column
- Deserialize with `numpy.frombuffer(blob, dtype=numpy.float32)`
- Both operations are isolated: if description fails, embedding is skipped; neither failure affects `/analyze`

## Tag Rules
- Lowercase only
- Single words strongly preferred (e.g. `roadmap`, `budget`, `hiring`)
- Hyphenated compound only when a single word is too vague (e.g. `ai-adoption`)
- No spaces, no special characters
- Each tag must match: `^[a-z0-9][a-z0-9-]*$`
- Up to 3 tags generated per chunk using `generate_tags()` in `llm_client.py`
- Existing tags are passed to the model to encourage reuse over near-synonyms
- If a tag already exists in the `tags` table, reuse it; otherwise insert
- Tags are linked to the meeting via `meeting_tags`, deduplicated across chunks
- If tag generation fails for any chunk, log and continue — do not fail the request

## Chunking (Teams AI format)
- Topic header: a line with NO leading whitespace that ends with `:`
- Lines with leading whitespace ending with `:` are content, not headers
- One chunk = one topic header + all indented lines beneath it
- Lines before the first topic header are skipped
- Everything from `follow-up tasks:` (case-insensitive) onward is stripped before chunking
- `Meeting notes:` (case-insensitive) is NOT a topic header — it is a document-level label and is ignored/skipped
- Fallback: if no topic headers found, return the full text as one chunk

## Output Requirements
The model output should be structured and easy to parse.
Prefer JSON-shaped output with:
- summary
- tags

## Input Fields
- `title` — required meeting title, passed to the prompt to give the model context
- `notes` — required meeting notes (any language; output always in English)
- `date` — optional meeting date (ISO date string, e.g. `2026-03-17`)
- `language` — optional language label (free text, e.g. `Spanish`)
- `recording_url` — optional URL to the meeting recording

`title` and `notes` are required. The frontend validates before submitting and shows a specific error message if either is empty. After a successful save, the frontend navigates to the meeting detail view and shows a "Meeting saved successfully." banner for 5 seconds. The form has a "Cancel" button that clears all fields without navigating away.

## Safe Editing Rules
- Keep changes minimal
- Do not refactor unrelated files
- Prefer updating existing files over creating many new ones