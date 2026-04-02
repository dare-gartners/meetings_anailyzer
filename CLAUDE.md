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

### Where to put new code
Every new feature must go into the file that owns that concern. Do not add routes or logic to `app.py`.

| What you're adding | Where it goes |
|--------------------|---------------|
| New API endpoint related to meetings (CRUD, tags, analytics) | `routers/meetings.py` |
| New API endpoint for analysis or ingestion | `routers/analyze.py` |
| New API endpoint for similarity or explanation | `routers/similarity.py` |
| New API endpoint for search | `routers/search.py` |
| Shared helper used by 2+ routers (e.g. a new utility function) | `routers/common.py` |
| New LLM call (chat completion or embedding) | `llm_client.py` |
| New prompt template or prompt-building logic | `ai_templates.py` |
| New Pydantic request/response model | `models.py` |
| New DB table, column, or migration | `database.py` |
| New auth route or Okta logic | `auth.py` |
| New CSS styles | `pages/static/style.css` |
| New JavaScript behaviour | `pages/static/app.js` |
| New HTML page | `pages/<name>.html` |

If a new feature doesn't fit any existing file cleanly, create a new dedicated file rather than cramming it into the nearest one. Add it to the **File Responsibilities** section in this file.

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

### Backend
- `app.py` — FastAPI app setup, auth routes (`/auth/okta/*`, `/auth/logout`, `/auth/status`), page routes (`/`, `/login`), and router registration. No business logic.
- `routers/analyze.py` — `POST /analyze`: LLM call, DB save, parallel description/embedding/tag generation
- `routers/meetings.py` — meeting CRUD (`GET/DELETE /meetings/{id}`), tag management (`POST/DELETE /meetings/{id}/tags`), list (`GET /meetings`), analytics (`GET /tags/trending`)
- `routers/similarity.py` — `POST /meetings/{id}/similar` and `POST /matches/explain`
- `routers/search.py` — `POST /search`: hybrid chunk-embedding + tag-semantic search
- `routers/common.py` — shared utilities: `_cosine`, `_meeting_tags`, `_STOP_WORDS`, `TAG_PATTERN`
- `llm_client.py` — Azure OpenAI API calls: `analyze_notes`, `generate_description`, `generate_embedding`, `generate_tags`, `verify_match`, `explain_match`
- `ai_templates.py` — prompt-building logic
- `models.py` — Pydantic request/response schemas
- `database.py` — SQLAlchemy models (`Meeting`, `Chunk`, `Tag`, `MeetingTag`), `init_db()`, and `PRAGMA foreign_keys=ON` event listener
- `chunking.py` — `chunk_text(notes) -> list[str]`, topic-based chunking for Teams AI format
- `auth.py` — Okta PKCE flow, JWT validation, signed session cookies
- `.env.example` — all required environment variables with placeholder values

### Frontend
- `pages/index.html` — thin Jinja2 template; links to `/static/style.css` and `/static/app.js`; only contains HTML structure and the `{{ email }}` template variable
- `pages/static/style.css` — all CSS: layout, sidebar, cards, tags, similarity table, search, dark mode
- `pages/static/app.js` — all JavaScript: sidebar, views (home/analyze/detail/tags/search), tag management, similarity cards, search
- `pages/login.html` — login page with "Sign in with Adobe (Okta)" button
- Static files are served via `app.mount("/static", StaticFiles(directory="pages/static"))` — requires `aiofiles` package

### Tests
- `tests/conftest.py` — session-scoped in-memory SQLite (StaticPool + `PRAGMA foreign_keys=ON`), per-test `clean_db`, auth-bypassed `client` fixture
- `tests/test_api_analyze.py` — patches via `patch.multiple("routers.analyze", ...)`
- `tests/test_api_similarity.py` — patches via `patch("routers.similarity.verify_match", ...)` etc.
- `tests/test_search_tags.py` — imports `_STOP_WORDS`, `_cosine` from `routers.common`; patches via `patch("routers.search.generate_embedding", ...)`

## Persistence
- SQLite via SQLAlchemy, stored in `meetings.db`
- `meetings` table: `id`, `title`, `notes_raw`, `summary`, `action_items` (JSON string — always `"[]"` for new records; column kept for backward compat), `created_at` (UTC datetime), `meeting_date` (VARCHAR(20), nullable), `recording_url` (VARCHAR(500), nullable — unique at application level; 409 returned if duplicate URL submitted)
- `language` column is dropped via `ALTER TABLE meetings DROP COLUMN language` in `init_db()` if it exists (migration for older DBs)
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
- `GET /meetings` — returns all meetings ordered by `created_at` desc (`id`, `title`, `created_at`); optional `?tag=<name>` query param filters to meetings linked to that tag
- `GET /tags/trending` — returns all tags sorted by meeting count desc; each item: `id`, `name`, `count`
- `GET /meetings/{id}` — returns full meeting detail (`id`, `title`, `created_at`, `summary`, `tags`, `date`, `recording_url`, `notes_raw`)
- `POST /meetings/{id}/tags` — adds a tag to a meeting (body: `{name}`); max 10 tags per meeting; validates format; reuses existing global tag if name matches
- `DELETE /meetings/{id}/tags/{tag_name}` — unlinks a tag from a meeting; does NOT delete the tag globally
- `DELETE /meetings/{id}` — deletes the meeting and all its chunks/tags (cascade); returns 204
- Sidebar lists all meetings most recent first; updates after a new meeting is saved
- Clicking a sidebar item opens the detail view without a page reload
- Detail view layout (top to bottom): Back + Delete buttons → title → meta row → Tags section → Summary → "Show related meetings" button → Full Notes collapsible
- Meta row: optional recording link (🎥, left) + optional meeting date (📅, right, pushed via `margin-left: auto`); `created_at` and language are not shown
- Tags display as color-coded badges; same tag name always gets the same color (deterministic hash over 10-color palette defined in `index.html` as `TAG_COLORS`)
- User can remove a tag from a meeting (unlink only) or add a new one (up to 10 total); the tag input spans full width (`flex: 1`) with placeholder "Add a tag..."
- A "Back" button returns to the new-meeting form; a "Delete" button deletes the meeting after confirmation
- A "Show related meetings" button appears below the summary — triggers `POST /meetings/{id}/similar`; do NOT rename or change the backend logic
- Similar meeting results render as cards; clicking the title in the card header opens the meeting
- The similar meetings table has columns: "This meeting" | matched meeting title (with a ↗ button to open it) | Match % | Why?; the ↗ button calls `openMeeting(id)` inline
- Each card uses a single table with columns "This meeting" | "{matched meeting title}" | "Match %" | "Why?"
- Collapsed state: header (title, date, green similarity badge, +/− toggle) + table showing only the best-match row; "+ N more matching topics" row below if multiple matches
- Expanded state (toggle via +/− button or the "+ N more" link): all matching rows shown, extra row hidden
- AI-generated descriptions are shown in table cells (readable, wrapping text); falls back to raw topic header when description is absent
- Best match row has a green border; column widths: 42% / 42% / 7% / 9%
- "Why?" button calls `POST /matches/explain`, shows explanation in a yellow/amber row below; clicking again hides it
- Results panel resets when switching to a different meeting

## Tag Analytics View
- Sidebar has two sections: "Meetings" (top, with meeting list) and "Analytics" (bottom, section header only); under Analytics is a "Trending Topics" item that opens the tag analytics view
- Shows all tags as color-coded badges (same `tagPalette` logic) with meeting count next to each name
- Clicking a tag sets `activeTagFilter` and re-loads the sidebar to show only meetings with that tag; clicking the same tag again clears the filter
- Active tag has an outline highlight (`.tag-active`)
- `activeTagFilter` persists across view changes until cleared by clicking the tag again or opening the Tags view
- Navigating to New Meeting (`showAnalyzeView`) clears the Tags button active state; the filter itself is cleared

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

## Free-text Search
- `POST /search` — hybrid search combining chunk embeddings and tag matching
- Request body: `SearchRequest(query: str)`
- Logic (two signals merged):
  1. **Tag match**: query is tokenized, stop words filtered out via `_STOP_WORDS` (module-level set in `app.py`), remaining words embedded individually; all tag names are also embedded; both batches run in one `asyncio.gather` call; a tag matches if any query word has cosine similarity ≥ 0.75 against the tag embedding (word-to-word avoids phrase-dilution); meetings with matching tags included regardless of chunk score
  2. **Embedding match**: query is embedded and compared via `_cosine()` against all chunk embeddings; meetings with best chunk score ≥ 0.45 are included
  - For tag-matched meetings that also have embeddings, their actual best embedding score is used (so they rank naturally among other results)
  - For tag-matched meetings with no embeddings at all, `matched_chunk` falls back to the meeting summary and score is 0.0 (sorts last)
  - The 0.45 threshold still applies to non-tag-matched meetings to suppress noise
- Response: list of `SearchResult(id, title, created_at, matched_chunk, matched_description, score)`
- `matched_description` is nullable (null for old chunks without a description)
- Frontend: search bar shown in detail and tags views, hidden in the new-meeting form view; home view has its own centered search bar that feeds into the same `runSearch` flow
- Search bar state: `beforeSearchRestore` captures the previous view as a closure; clearing the input calls it to restore the previous view; navigating to any view directly (openMeeting, showTagsView, showAnalyzeView) resets `beforeSearchRestore = null` and clears the search input
- Results rendered as `.sim-card` style cards (title, date, matched topic snippet); clicking a card opens the meeting
- No results message shown when list is empty; error message on fetch failure

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
- `recording_url` — optional URL to the meeting recording; if provided, must be unique across all meetings (409 if duplicate)

`title` and `notes` are required. The frontend validates before submitting and shows a specific error message if either is empty. After a successful save, the frontend navigates to the meeting detail view and shows a "Meeting saved successfully." banner for 5 seconds. The form has a "Cancel" button that clears all fields without navigating away.

## Safe Editing Rules
- Keep changes minimal
- Do not refactor unrelated files
- Prefer updating existing files over creating many new ones