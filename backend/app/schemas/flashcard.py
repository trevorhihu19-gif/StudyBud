"""Request and response shapes for flashcards."""

import uuid
from datetime import datetime
from pydantic import BaseModel, Field

from app.services.spaced_repetition import Rating

class FlashCardGenerateRequest(BaseModel):
    """Body for generating flashcards from a document."""
    
    document_id: uuid.UUID
    num_cards: int = Field(default=10, ge=3, le=20)
    
class FlashcardOut(BaseModel):
    """A flashcard as shown to the student."""
    
    id: uuid.UUID
    document_id: uuid.UUID | None
    front: str
    back: str
    next_review_at: datetime
    interval_days: int
    repetitions: int
    
class GenerateResult(BaseModel):
    """Result of generation, the new cards and how many were skipped as duplicates."""
    
    created: list[FlashcardOut]
    skipped_duplicates: int
    
class ReviewRequest(BaseModel):
    """The student's self-rating.Nothing else is accepted, the server owns the schedule."""
    
    rating: Rating
    
class ReviewResult(BaseModel):
    """A cards new schedule after a review."""
    
    id: uuid.UUID
    next_review_at: datetime
    interval_days: int
    repetitions: int
    ease_factor: float
    
class FlashcardStats(BaseModel):
    """Numbers for the dashboard's flashcard practice card."""
    
    due_count: int
    total_count: int
    next_due_at: datetime | None