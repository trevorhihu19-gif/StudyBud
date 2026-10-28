import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

class KeyPointOut(BaseModel):
    title: str
    explanation: str
    category: Literal["concept", "definition", "exam_tip"]
    importance: Literal["very_important", "important", "useful"]
    page: int | None
    chunk_id: uuid.UUID | None
    
class SummaryResponse(BaseModel):
    document_id: uuid.UUID
    status: Literal["processing", "ready", "failed"]
    overview: str | None
    key_points: list[KeyPointOut]
    chunks_used: int | None
    chunks_total: int | None
    error: str | None
    created_at: datetime
