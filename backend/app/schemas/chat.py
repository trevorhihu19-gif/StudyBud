import uuid

from pydantic import BaseModel, Field, field_validator

from app.core.sanitize import clean_text

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    
    @field_validator("message")
    @classmethod
    def clean_message(cls, v:str) -> str:
        return clean_text(v)
    
class Citation(BaseModel):
    source: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    page: int | None
    
class ChatResponse(BaseModel):
    session_id: uuid.UUID
    answer: str
    citations: list[Citation]