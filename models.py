from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class NotesRequest(BaseModel):
    title: str
    notes: str


class NotesResponse(BaseModel):
    summary: str
    action_items: List[str]
    tags: List[str]


class MeetingListItem(BaseModel):
    id: int
    title: str
    created_at: datetime


class MeetingDetail(BaseModel):
    id: int
    title: str
    created_at: datetime
    summary: str
    action_items: List[str]
    tags: List[str]


class TagAddRequest(BaseModel):
    name: str
