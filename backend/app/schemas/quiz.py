"""Request and response shapes for quizzes, attempts and weak areas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.quiz import QuestionType

class QuizCreateRequest(BaseModel):
    """Body for generating a new quiz"""
    
    document_id: uuid.UUID
    num_questions: int = Field(default=5, ge=3, le=10)
    
class QuestionOut(BaseModel):
    """A question as the student sees it. Deliberately has NO answer or explanation."""
    
    id: uuid.UUID
    question_type: QuestionType
    question_text: str
    options: list[str]
    
class QuizOut(BaseModel):
    """A quiz with its questions in order."""
    
    id: uuid.UUID
    title: str
    document_id: uuid.UUID | None
    created_at: datetime
    questions: list[QuestionOut]
    
class AttemptStarted(BaseModel):
    """Returned when a student begins a quiz."""
    
    attempt_id: uuid.UUID
    quiz_id: uuid.UUID
    total_questions: int
    
class AnswerIn(BaseModel):
    """One answer submitted by the student."""
    
    question_id: uuid.UUID
    selected_answer: str = Field(min_length=1, max_length=300)
    
class AnswerFeedback(BaseModel):
    """Instant feedback for one answered question."""
    
    question_id: uuid.UUID
    is_correct: str | None
    correct_answer: str
    explanation: str | None

class QuestionResult(BaseModel):
    """Final result line for one question. selected_answer is None if it was skipped."""

    question_id: uuid.UUID
    selected_answer: str | None
    is_correct: bool | None
    correct_answer: str
    explanation: str | None


class AttemptResult(BaseModel):
    """The finished attempt: score plus a breakdown of every question."""

    attempt_id: uuid.UUID
    score_percent: float
    correct_count: int
    answered_count: int
    total_questions: int
    results: list[QuestionResult]


class WeakTopicOut(BaseModel):
    """A topic the student is struggling with (powers the Weak Areas panel)."""

    topic_id: uuid.UUID
    name: str
    mastery_score: float
    answered_count: int
    
