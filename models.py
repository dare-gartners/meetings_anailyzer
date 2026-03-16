from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class NotesRequest(BaseModel):
    title: str
    notes: str
    date: Optional[str] = None
    language: Optional[str] = None
    recording_url: Optional[str] = None


class NotesResponse(BaseModel):
    id: Optional[int] = None
    summary: str
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
    tags: List[str]
    date: Optional[str] = None
    language: Optional[str] = None
    recording_url: Optional[str] = None
    notes_raw: Optional[str] = None


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
