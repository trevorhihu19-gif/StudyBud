"""Quiz endpoints: generate a quiz, take it question by question, and get the score."""

import uuid
from datetime import UTC, datetime
from functools import partial

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.quiz_graph import QuizContext, QuizGenerationError, quiz_graph
from app.api.deps import get_current_user
from app.core.analytics import track
from app.core.logging import get_logger, request_id_var
from app.core.rate_limit import rate_limit
from app.core.database import get_db
from app.models import (
    Document, DocumentStatus, Quiz, QuizAttempt,QuizAttemptAnswer, QuizQuestion, User, 
)
from app.schemas.quiz import(
    AnswerFeedback, AnswerIn, AttemptResult, AttemptStarted, QuestionOut, QuestionResult, QuizCreateRequest, QuizOut, 
)
from app.services.mastery import update_topic_mastery
from app.services.quiz_store import save_quiz

router = APIRouter(prefix="/quizzes", tags=["quizzes"])
attempts_router = APIRouter(prefix="/quiz-attempts", tags=["quizzes"])
logger = get_logger(__name__)

def _question_out(q: QuizQuestion) -> QuestionOut:
    """Convert a stored question into the student-safe version (no answer, no explanation)."""
    
    return QuestionOut(
        id=q.id, question_type=q.question_type, question_text=q.question_text, options=q.options or []
    )
    
def _quiz_out(quiz: QuizQuestion, questions: list[QuizQuestion]) -> QuizOut:
    """Build the quiz response from a quiz and its already-ordered questions."""
    
    return QuizOut(
        id=quiz.id,
        title=quiz.title,
        document_id=quiz.document_id,
        created_at=quiz.created_at,
        questions=[_question_out(q) for q in questions]
    )
    
async def _owned_quiz(db: AsyncSession, user_id: uuid.UUID, quiz_id: uuid.UUID) -> Quiz:
    """Load a quiz only if it belongs to the user; otherwise answer 404.

    404 (not 403) for other people's quizzes, so we never confirm they exist.
    """
    
    quiz = (await db.execute(select(Quiz).where(Quiz.id == quiz_id, Quiz.user_id == user_id))).scalar_one_or_none()
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return quiz

async def _questions_of(db: AsyncSession, quiz_id: uuid.UUID) -> list[QuizQuestion]:
    """Load a quiz's questions in display order."""
    rows = await db.execute(select(QuizQuestion).where(QuizQuestion.quiz_id == quiz_id).order_by(QuizQuestion.position))
    return list(rows.scalars())


async def _owned_attempt(db: AsyncSession, user_id: uuid.UUID, attempt_id: uuid.UUID) -> QuizAttempt:
    """Load a quiz attempt only if it belongs to the user; otherwise answer 404."""
    attempt = (
        await db.execute(select(QuizAttempt).where(QuizAttempt.id == attempt_id, QuizAttempt.user_id == user_id))
    ).scalar_one_or_none()
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found")
    return attempt

@router.post("", response_model=QuizOut)
async def generate_quiz(
    body: QuizCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(partial(rate_limit, requested=5)),
):
    """Create a new quiz from one of the user's processed documents.

    Each call makes a fresh quiz and spends AI tokens from the daily quota.
    The response contains questions and options only, never the answers.
    """
    
    found = await db.execute(select(Document).where(Document.id == body.document_id, Document.user-id == user.id))
    document = found.scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.status != DocumentStatus.READY:
        raise HTTPException(status_code=409, detail="This document isn't ready yet")
    
    title = f"Quiz: {document.title}"[:200]
    await db.commit() #free the pooled connection
    
    try:
        result = await quiz_graph.ainvoke(
            {"document_id": str(document.id), "num_questions": body.num_questions},
            context=QuizContext(user_id=user.id),
            config={"tags": ["quiz"], "metadata": {"user_id": str(user.id), "request_id": request_id_var.get()}},
        )
    except QuizGenerationError as e:
        raise HTTPException(status_code=502, detail=str(e))
    
    quiz = await save_quiz(db, user.id, document.id, title, result["questions"])
    await db.commit()
    
    logger.info("quiz_generated", user_id=str(user.id), quiz_id=str(quiz.id), questions=len(quiz.questions))
    track("quiz_generated", user_id=str(user.id), properties={"questions": len(quiz.questions)})
    return _quiz_out(quiz, quiz.questions)

@router.get("/{quiz_id}", response_model=QuizOut)
async def get_quiz(
    quiz_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(rate_limit),
):
    """Fetch a quiz to display. Never includes correct answers or explanations."""
    
    quiz = await _owned_quiz(db, user.id, quiz_id)
    return _quiz_out(quiz, await _questions_of(db, quiz.id))

@router.post("/{quiz_id}/attempts", response_model=AttemptStarted)
async def start_attempt(
    quiz_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(rate_limit)
):
    """Begin taking a quiz. Students can retake a quiz as many times as they like."""
    
    quiz = await _owned_quiz(db, user.id, quiz_id)
    total = (
        await db.execute(select(func.count()).select_from(QuizQuestion).where(QuizQuestion.quiz_id == quiz.id))
    ).scalar_one()
    
    attempt = QuizAttempt(quiz_id=quiz.id, user_id=user.id, score_percent=0.0)
    db.add(attempt)
    await db.commit()
    return AttemptStarted(attempt_id=attempt.id, quiz_id=quiz.id, total_questions=total)

@attempts_router.post("/{attempt_id}/answers", response_model=AnswerFeedback)
async def submit_answer(
    attempt_id: uuid.UUID,
    body: AnswerIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(rate_limit),
):
    """Answer one question and get instant feedback.

    The answer is graded on the server and locked: a second answer for the same
    question is refused, so students can't try every option to find the right one.
    """
    attempt = await _owned_attempt(db, user.id, attempt_id)
    if attempt.completed_at is not None:
        raise HTTPException(status_code=409, detail="This attempt is already finished")

    question = (
        await db.execute(
            select(QuizQuestion).where(QuizQuestion.id == body.question_id, QuizQuestion.quiz_id == attempt.quiz_id)
        )
    ).scalar_one_or_none()
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found in this quiz")

    if body.selected_answer not in (question.options or []):
        raise HTTPException(status_code=422, detail="Selected answer is not one of the options")

    is_correct = body.selected_answer == question.correct_answer
    inserted = await db.execute(
        pg_insert(QuizAttemptAnswer)
        .values(
            attempt_id=attempt.id,
            question_id=question.id,
            topic_id=question.topic_id,
            selected_answer=body.selected_answer,
            is_correct=is_correct,
        )
        .on_conflict_do_nothing(constraint="uq_attempt_question")
        .returning(QuizAttemptAnswer.id)
    )
    if inserted.scalar_one_or_none() is None:
        raise HTTPException(status_code=409, detail="This question was already answered")
    await db.commit()

    return AnswerFeedback(
        question_id=question.id,
        is_correct=is_correct,
        correct_answer=question.correct_answer,
        explanation=question.explanation,
    )


@attempts_router.post("/{attempt_id}/complete", response_model=AttemptResult)
async def complete_attempt(
    attempt_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(rate_limit),
):
    """Finish the attempt: compute the score and update topic mastery.

    Skipped questions count as wrong for the score. Calling this again on a
    finished attempt returns the same result and does NOT update mastery twice.
    """
    attempt = await _owned_attempt(db, user.id, attempt_id)
    questions = await _questions_of(db, attempt.quiz_id)
    answer_rows = await db.execute(select(QuizAttemptAnswer).where(QuizAttemptAnswer.attempt_id == attempt.id))
    answers = {a.question_id: a for a in answer_rows.scalars()}

    correct = sum(1 for a in answers.values() if a.is_correct)
    score = round(100 * correct / len(questions), 1) if questions else 0.0

    if attempt.completed_at is None:
        # Atomic claim: only one concurrent request gets to finish the attempt
        claimed = await db.execute(
            update(QuizAttempt)
            .where(QuizAttempt.id == attempt.id, QuizAttempt.completed_at.is_(None))
            .values(completed_at=datetime.now(UTC), score_percent=score)
            .returning(QuizAttempt.id)
        )
        if claimed.scalar_one_or_none() is not None:
            await update_topic_mastery(db, user.id, {a.topic_id for a in answers.values() if a.topic_id})
            track("quiz_completed", user_id=str(user.id), properties={"score_percent": score, "questions": len(questions)})
    else:
        score = attempt.score_percent
    await db.commit()

    results = [
        QuestionResult(
            question_id=q.id,
            selected_answer=answers[q.id].selected_answer if q.id in answers else None,
            is_correct=answers[q.id].is_correct if q.id in answers else None,
            correct_answer=q.correct_answer,
            explanation=q.explanation,
        )
        for q in questions
    ]
    return AttemptResult(
        attempt_id=attempt.id,
        score_percent=score,
        correct_count=correct,
        answered_count=len(answers),
        total_questions=len(questions),
        results=results,
    )