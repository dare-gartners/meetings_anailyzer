"""Similarity search and match explanation endpoints."""

import asyncio
import logging
import time

import numpy as np
from fastapi import APIRouter, HTTPException, Request

import auth
import core.database as database
from core.database import Meeting, Chunk
from llm.client import explain_match, verify_match
from core.models import SimilarMeeting, ChunkMatch, ExplainRequest
from routers.common import _cosine, _meeting_tags

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/meetings/{meeting_id}/similar", response_model=list[SimilarMeeting])
async def find_similar(meeting_id: int, request: Request):
    if not auth.require_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    t_req = time.perf_counter()
    logger.info("similar:start meeting_id=%s", meeting_id)
    db = database.SessionLocal()
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

        # Best match per (meeting_id, source_chunk_id)
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

        # LLM re-ranking in parallel
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


@router.post("/matches/explain")
def explain(body: ExplainRequest, request: Request):
    if not auth.require_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    explanation = explain_match(body.source_chunk, body.matched_chunk)
    return {"explanation": explanation}
