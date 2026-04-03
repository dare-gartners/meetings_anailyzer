"""Free-text hybrid search — chunk embeddings + semantic tag matching."""

import asyncio
import logging
import re
import time

import numpy as np
from fastapi import APIRouter, Request, HTTPException

import auth
import core.database as database
from core.database import Chunk, Tag, MeetingTag, Meeting
from llm.client import generate_embedding
from core.models import SearchRequest, SearchResult
from routers.common import _cosine, _STOP_WORDS

logger = logging.getLogger(__name__)
router = APIRouter()

TAG_MATCH_THRESHOLD = 0.75


@router.post("/search", response_model=list[SearchResult])
async def search(body: SearchRequest, request: Request):
    if not auth.require_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    t_req = time.perf_counter()
    logger.info("search:start query=%r", body.query[:60])

    loop = asyncio.get_event_loop()
    query_emb = await loop.run_in_executor(None, generate_embedding, body.query)
    query_vec = np.frombuffer(query_emb, dtype=np.float32)

    db = database.SessionLocal()
    try:
        # Tag-based matching: strip stop words, embed each remaining word individually,
        # compare word-to-word against tag embeddings to avoid phrase-dilution.
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

        # Embedding search — track best per meeting with and without threshold
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
