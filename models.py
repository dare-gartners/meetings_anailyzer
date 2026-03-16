from pydantic import BaseModel
from typing import List


class NotesRequest(BaseModel):
    title: str
    notes: str


class NotesResponse(BaseModel):
    summary: str
    action_items: List[str]
    tags: List[str]
