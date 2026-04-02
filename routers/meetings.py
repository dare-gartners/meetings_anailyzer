"""Meeting CRUD, tag management, and analytics endpoints."""

import logging
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func

import auth
import database
from database import Meeting, Tag, MeetingTag
from models import MeetingListItem, MeetingDetail, TagAddRequest, TagStats
from routers.common import _meeting_tags, TAG_PATTERN

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/meetings", response_model=list[MeetingListItem])
def list_meetings(request: Request, tag: str = None):
    if not auth.require_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    db = database.SessionLocal()
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


@router.get("/tags/trending", response_model=list[TagStats])
def tags_trending(request: Request):
    if not auth.require_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    db = database.SessionLocal()
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


@router.get("/meetings/{meeting_id}", response_model=MeetingDetail)
def get_meeting(meeting_id: int, request: Request):
    if not auth.require_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    db = database.SessionLocal()
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


@router.delete("/meetings/{meeting_id}", status_code=204)
def delete_meeting(meeting_id: int, request: Request):
    if not auth.require_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    db = database.SessionLocal()
    try:
        m = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not m:
            raise HTTPException(status_code=404, detail="Meeting not found")
        db.delete(m)
        db.commit()
    finally:
        db.close()


@router.post("/meetings/{meeting_id}/tags", response_model=MeetingDetail)
def add_tag(meeting_id: int, body: TagAddRequest, request: Request):
    if not auth.require_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    name = body.name.strip().lower()
    if not TAG_PATTERN.match(name):
        raise HTTPException(status_code=422, detail="Invalid tag format")
    db = database.SessionLocal()
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


@router.delete("/meetings/{meeting_id}/tags/{tag_name}", response_model=MeetingDetail)
def remove_tag(meeting_id: int, tag_name: str, request: Request):
    if not auth.require_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    db = database.SessionLocal()
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
