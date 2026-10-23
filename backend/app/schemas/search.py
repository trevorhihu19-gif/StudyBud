import re
import uuid

from pydantic import BaseModel, Field, field_validator

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)
    document_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)

    @field_validator("query")
    @classmethod
    def clean_query(cls, v: str) -> str:
        v = _CONTROL_CHARS.sub("", v).strip()
        if not v:
            raise ValueError("Query cannot be empty")
        return v

class ChunkResult(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    page_number: int | None
    content: str
    score: float