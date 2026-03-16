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


class ChunkMatch(BaseModel):
    source_chunk: str
    matched_chunk: str
    source_description: Optional[str] = None
    matched_description: Optional[str] = None
    score: float
    is_best: bool


class SimilarMeeting(BaseModel):
    id: int
    title: str
    created_at: datetime
    tags: List[str]
    score: float          # best score
    all_matches: List[ChunkMatch]


class ExplainRequest(BaseModel):
    source_chunk: str
    matched_chunk: str
