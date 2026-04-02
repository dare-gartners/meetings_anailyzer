# Meeting L-AI-brary

AI-powered meeting library. Paste meeting notes in, get back a structured summary and auto-generated tags. Browse and search past meetings semantically — find related topics across all your history.

---

## What it does

- **Analyze** — paste raw meeting notes (any language); the app produces an English summary and tags
- **Smart search** — hybrid search combining semantic chunk similarity and tag matching; phrase queries like "meetings about customers" work correctly by filtering stop words and comparing word embeddings against tag embeddings
- **Related meetings** — two-stage similarity: embedding cosine filter (≥ 0.45) then LLM verification; each match shows which topics connected the two meetings and why
- **Tag management** — auto-generated tags per meeting; add or remove manually; browse all tags by frequency; filter the sidebar by tag
- **Meeting detail** — summary, full notes, recording link, date, tags, and a "Show related meetings" button

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12+, FastAPI |
| LLM / Embeddings | Azure OpenAI (`gpt-4o`, `text-embedding-ada-002`) |
| Database | SQLite via SQLAlchemy |
| Auth | Adobe Okta — Authorization Code + PKCE |
| Frontend | Vanilla HTML/CSS/JS, no build step |

---

## Project structure

```
app.py                  # FastAPI app, auth routes, page routes
routers/
  analyze.py            # POST /analyze
  meetings.py           # meetings CRUD, tag management, /tags/trending
  similarity.py         # POST /meetings/{id}/similar, POST /matches/explain
  search.py             # POST /search (hybrid)
  common.py             # shared utilities (_cosine, _meeting_tags, _STOP_WORDS)
llm_client.py           # all Azure OpenAI calls
ai_templates.py         # prompt templates
models.py               # Pydantic schemas
database.py             # SQLAlchemy models, init_db()
chunking.py             # topic-based chunker for Teams AI format
auth.py                 # Okta PKCE flow, JWT validation, session cookies
pages/
  index.html            # main app (Jinja2 template)
  login.html            # login page
  static/
    style.css           # all styles including dark mode
    app.js              # all frontend logic
tests/                  # pytest suite (150 tests, in-memory SQLite)
```

---

## Installation

**Prerequisites:** Python 3.12+, an Azure OpenAI resource, an Adobe Okta app registration (SPA type).

### 1. Clone and create a virtual environment

```bash
git clone <repo-url>
cd meeting-notes-ai
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in:

```env
# Azure OpenAI
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_MODEL_VERSION=2024-02-01
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-ada-002

# Okta (Adobe SSO)
OKTA_ISSUER=https://adobe.okta.com/oauth2/aus1gan31wnmCPyB60h8
OKTA_CLIENT_ID=your-client-id
OKTA_REDIRECT_URI=https://localhost:8000/auth/okta/callback

# Session signing key
SECRET_KEY=your-random-secret   # python -c "import secrets; print(secrets.token_hex(32))"
```

### 3. Generate a self-signed TLS certificate (one-time)

Okta requires an `https` redirect URI. If `cert.pem` and `key.pem` don't already exist in the project root:

```bash
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=localhost"
```

### 4. Run

```bash
uvicorn app:app --ssl-keyfile key.pem --ssl-certfile cert.pem --port 8000 --reload
```

Open [https://localhost:8000](https://localhost:8000). Accept the self-signed certificate warning and sign in with your Adobe account.

---

## Usage

### Adding a meeting

1. Click **+ New** in the sidebar
2. Fill in the title and paste your meeting notes (Teams AI format works best — topic headers ending with `:`)
3. Optionally add a date and recording URL
4. Click **Save** — the app calls the LLM, saves the meeting, generates embeddings in the background

### Searching

- Use the search bar at the top to search across all meetings
- Queries are matched against chunk embeddings AND tag names semantically — stop words like "meetings about" are filtered out automatically
- Clicking the app title returns to the home screen with a centered search box

### Finding related meetings

Open any meeting and click **Show related meetings**. Results show which specific topics connected the two meetings, their similarity score, and a **Why?** button that generates a one-sentence explanation.

### Tags

- Tags are auto-generated when a meeting is saved (up to 3 per chunk, deduplicated across chunks)
- Add or remove tags manually on the detail view
- Click **Trending Topics** in the sidebar to see all tags by frequency; click a tag to filter the meeting list

---

## Running tests

```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

Tests run against an in-memory SQLite database — the production `meetings.db` is never touched. All LLM calls are mocked.

---

## Notes format

The chunker is tuned for the **Teams AI meeting notes** format:

```
Topic header:
    indented content line
    another content line

Next topic:
    content
```

- Lines with no leading whitespace ending in `:` are topic headers → each becomes a chunk
- `Meeting notes:` is treated as a document label, not a header
- Everything from `Follow-up tasks:` onwards is stripped before chunking
- If no topic headers are found, the full text is treated as one chunk
