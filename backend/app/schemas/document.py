import uuid
from datetime import datetime
from pydantic import BaseModel, Field

from app.models.document import DocumentStatus

class DocumentResponse(BaseModel):
    id: uuid.UUID
    title: str
    file_type: str
    status: DocumentStatus
    page_count: int | None
    created_at: datetime

    model_config = {"from_attributes": True}

class DocumentTitleUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=500)