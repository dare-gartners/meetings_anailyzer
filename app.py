import asyncio
import json
import logging
import time
from dotenv import load_dotenv

load_dotenv()  # must be before auth import — env vars are read at module load

import auth  # noqa: E402 (intentional late import)

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import re
import numpy as np
from models import NotesRequest, NotesResponse, MeetingListItem, MeetingDetail, TagAddRequest, SimilarMeeting, ChunkMatch, ExplainRequest, TagStats, SearchRequest, SearchResult
from llm_client import analyze_notes, generate_tags, generate_description, generate_embedding, explain_match, verify_match
from sqlalchemy import func
from database import init_db, SessionLocal, Meeting, Chunk, Tag, MeetingTag
from chunking import chunk_text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
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

    t_req = time.perf_counter()
    logger.info("analyze:start title=%r", body.title)

    if body.recording_url:
        db = SessionLocal()
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

    try:
        db = SessionLocal()
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


@app.get("/meetings", response_model=list[MeetingListItem])
def list_meetings(request: Request, tag: str = None):
    if not auth.require_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    db = SessionLocal()
    try:
        q = db.query(Meeting)
        if tag:
            q = (q.join(MeetingTag, MeetingTag.meeting_id == Meeting.id)
                  .join(Tag, Tag.id == MeetingTag.tag_id)
                  .filter(Tag.name == tag))
        meetings = q.order_by(Meeting.created_at.desc()).all()
        return [MeetingListItem(id=m.id, title=m.title, created_at=m.created_at) for m in meetings]
    finally:
        db.close()


@app.get("/tags/trending", response_model=list[TagStats])
def tags_trending(request: Request):
    if not auth.require_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    db = SessionLocal()
    try:
        rows = (
            db.query(Tag.id, Tag.name, func.count(MeetingTag.id).label("cnt"))
            .join(MeetingTag, MeetingTag.tag_id == Tag.id)
            .group_by(Tag.id)
            .order_by(func.count(MeetingTag.id).desc())
            .all()
        )
        return [TagStats(id=r.id, name=r.name, count=r.cnt) for r in rows]
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
            tags=_meeting_tags(db, m.id),
            date=m.meeting_date,
            recording_url=m.recording_url,
            notes_raw=m.notes_raw,
        )
    finally:
        db.close()


@app.delete("/meetings/{meeting_id}", status_code=204)
def delete_meeting(meeting_id: int, request: Request):
    if not auth.require_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    db = SessionLocal()
    try:
        m = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not m:
            raise HTTPException(status_code=404, detail="Meeting not found")
        db.delete(m)
        db.commit()
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
            tags=_meeting_tags(db, m.id),
            date=m.meeting_date,
            recording_url=m.recording_url,
            notes_raw=m.notes_raw,
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
            tags=_meeting_tags(db, m.id),
            date=m.meeting_date,
            recording_url=m.recording_url,
            notes_raw=m.notes_raw,
        )
    finally:
        db.close()


_STOP_WORDS = {
    # articles / determiners
    "a", "an", "the",
    # prepositions
    "about", "above", "across", "after", "against", "along", "among", "around",
    "at", "before", "behind", "below", "beneath", "beside", "between", "beyond",
    "by", "down", "during", "except", "for", "from", "in", "inside", "into",
    "near", "of", "off", "on", "onto", "out", "outside", "over", "past", "re",
    "since", "through", "throughout", "till", "to", "toward", "under", "until",
    "up", "upon", "with", "within", "without",
    # conjunctions
    "and", "as", "because", "but", "either", "if", "nor", "once", "or", "since",
    "so", "than", "that", "though", "unless", "until", "when", "where",
    "whether", "while", "yet",
    # pronouns
    "all", "any", "both", "each", "few", "he", "her", "him", "his", "how",
    "i", "it", "its", "me", "more", "most", "my", "neither", "no", "none",
    "not", "nothing", "one", "other", "our", "ours", "she", "some", "such",
    "them", "these", "they", "this", "those", "us", "we", "what", "which",
    "who", "whom", "whose", "why", "you", "your",
    # auxiliary verbs
    "am", "are", "be", "been", "being", "can", "could", "did", "do", "does",
    "doing", "done", "had", "has", "have", "having", "is", "may", "might",
    "must", "shall", "should", "was", "were", "will", "would",
    # common adverbs / fillers
    "again", "also", "always", "already", "away", "back", "else", "even",
    "ever", "here", "just", "maybe", "never", "now", "often", "only",
    "perhaps", "quite", "rather", "really", "same", "still", "then", "there",
    "too", "very", "well",
    # domain fillers specific to this app
    "meeting", "meetings", "regarding", "related", "concerning", "tell",
    "show", "find", "get", "give", "list", "search",
}


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom else 0.0


@app.post("/meetings/{meeting_id}/similar", response_model=list[SimilarMeeting])
async def find_similar(meeting_id: int, request: Request):
    if not auth.require_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    t_req = time.perf_counter()
    logger.info("similar:start meeting_id=%s", meeting_id)
    db = SessionLocal()
    try:
        source_chunks = (
            db.query(Chunk)
            .filter(Chunk.meeting_id == meeting_id, Chunk.embedding.isnot(None))
            .all()
        )
        if not source_chunks:
            logger.info("similar:no_embeddings meeting_id=%s", meeting_id)
            return []

        source_vecs = [np.frombuffer(c.embedding, dtype=np.float32) for c in source_chunks]

        other_chunks = (
            db.query(Chunk)
            .filter(Chunk.meeting_id != meeting_id, Chunk.embedding.isnot(None))
            .all()
        )
        logger.info("similar:embedding_filter source_chunks=%d other_chunks=%d", len(source_chunks), len(other_chunks))

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

        logger.info("similar:candidates_above_threshold count=%d", len(best_per_source))

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

        t0 = time.perf_counter()
        verified = await asyncio.gather(*[_verify(k, v) for k, v in candidates])
        passed_count = sum(1 for _, _, p in verified if p)
        logger.info("similar:verify_batch done %.0fms candidates=%d passed=%d", (time.perf_counter() - t0) * 1000, len(candidates), passed_count)

        all_matches: dict[int, list[tuple[float, str, str | None, str, str | None]]] = {}
        for (mid, _src_id), entry, passed in verified:
            if passed:
                all_matches.setdefault(mid, []).append(entry)

        if not all_matches:
            logger.info("similar:done no_results total=%.0fms", (time.perf_counter() - t_req) * 1000)
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
        logger.info("similar:done results=%d total=%.0fms", len(results), (time.perf_counter() - t_req) * 1000)
        return results
    finally:
        db.close()


@app.post("/matches/explain")
def explain(body: ExplainRequest, request: Request):
    if not auth.require_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    explanation = explain_match(body.source_chunk, body.matched_chunk)
    return {"explanation": explanation}


@app.post("/search", response_model=list[SearchResult])
async def search(body: SearchRequest, request: Request):
    if not auth.require_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    t_req = time.perf_counter()
    logger.info("search:start query=%r", body.query[:60])

    loop = asyncio.get_event_loop()
    query_emb = await loop.run_in_executor(None, generate_embedding, body.query)
    query_vec = np.frombuffer(query_emb, dtype=np.float32)

    db = SessionLocal()
    try:
        # Tag-based matching: strip stop words from the query, embed each remaining
        # word individually, then compare word-to-word against tag name embeddings.
        # Taking max similarity across query words avoids phrase-dilution and is
        # robust to typos, plurals, and synonyms.
        TAG_MATCH_THRESHOLD = 0.75

        raw_words = re.findall(r'[a-z0-9]+', body.query.lower())
        query_words = [w for w in raw_words if w not in _STOP_WORDS] or [body.query.lower()]

        all_tags = db.query(Tag).all()

        async def _embed_text(text: str):
            try:
                emb = await loop.run_in_executor(None, generate_embedding, text)
                return np.frombuffer(emb, dtype=np.float32)
            except Exception as e:
                logger.warning("search:embed_failed text=%r err=%s", text, e)
                return None

        # Embed query words and tag names in one parallel batch
        all_texts = query_words + [t.name for t in all_tags]
        all_vecs = await asyncio.gather(*[_embed_text(txt) for txt in all_texts])
        word_vecs = [v for v in all_vecs[:len(query_words)] if v is not None]
        tag_vecs  = all_vecs[len(query_words):]

        matching_tag_names: set[str] = set()
        if word_vecs:
            for t, tvec in zip(all_tags, tag_vecs):
                if tvec is not None and any(_cosine(wv, tvec) >= TAG_MATCH_THRESHOLD for wv in word_vecs):
                    matching_tag_names.add(t.name)

        tag_matched_ids: set[int] = set()
        if matching_tag_names:
            rows = (
                db.query(MeetingTag.meeting_id)
                .join(Tag, Tag.id == MeetingTag.tag_id)
                .filter(Tag.name.in_(matching_tag_names))
                .all()
            )
            tag_matched_ids = {r.meeting_id for r in rows}
            logger.info("search:tag_match words=%s tags=%s meetings=%d", query_words, list(matching_tag_names), len(tag_matched_ids))

        # Embedding search — track best per meeting with and without the threshold
        chunks = db.query(Chunk).filter(Chunk.embedding.isnot(None)).all()
        logger.info("search:chunks_loaded count=%d", len(chunks))

        best_per_meeting: dict[int, tuple[float, str, str | None]] = {}      # above threshold
        best_per_meeting_all: dict[int, tuple[float, str, str | None]] = {}  # no threshold

        for c in chunks:
            vec = np.frombuffer(c.embedding, dtype=np.float32)
            score = _cosine(query_vec, vec)
            existing_all = best_per_meeting_all.get(c.meeting_id)
            if existing_all is None or score > existing_all[0]:
                best_per_meeting_all[c.meeting_id] = (score, c.text, c.description)
            if score < 0.45:
                continue
            existing = best_per_meeting.get(c.meeting_id)
            if existing is None or score > existing[0]:
                best_per_meeting[c.meeting_id] = (score, c.text, c.description)

        # Include tag-matched meetings that didn't pass the embedding threshold
        for mid in tag_matched_ids:
            if mid not in best_per_meeting:
                if mid in best_per_meeting_all:
                    best_per_meeting[mid] = best_per_meeting_all[mid]
                else:
                    # No embeddings at all — fall back to meeting summary
                    m = db.query(Meeting).filter(Meeting.id == mid).first()
                    if m:
                        best_per_meeting[mid] = (0.0, m.summary or m.title, None)

        if not best_per_meeting:
            logger.info("search:done no_results total=%.0fms", (time.perf_counter() - t_req) * 1000)
            return []

        sorted_meetings = sorted(best_per_meeting.items(), key=lambda x: x[1][0], reverse=True)

        results = []
        for mid, (score, chunk_text, chunk_desc) in sorted_meetings:
            m = db.query(Meeting).filter(Meeting.id == mid).first()
            if not m:
                continue
            results.append(SearchResult(
                id=m.id,
                title=m.title,
                created_at=m.created_at,
                matched_chunk=chunk_text,
                matched_description=chunk_desc,
                score=round(score, 3),
            ))

        logger.info("search:done results=%d total=%.0fms", len(results), (time.perf_counter() - t_req) * 1000)
        return results
    finally:
        db.close()
