"""Saves generated quizzes and their topics to the database."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Quiz, QuizQuestion, Topic
from app.models.quiz import QuestionType


async def get_or_create_topics(db: AsyncSession, user_id: uuid.UUID, names: set[str]) -> dict[str, uuid.UUID]:
    """Find the user's topics by name, creating any that don't exist yet.

    Matching ignores upper/lower case ("Memory management" == "memory management").
    Creation uses ON CONFLICT DO NOTHING so two requests creating the same topic
    at once can't crash or duplicate it.

    Args:
        db: Open database session.
        user_id: Owner of the topics.
        names: Topic names to look up or create.

    Returns:
        Dict mapping each lowercase topic name to its topic id.
    """
    wanted = {n.lower(): n for n in names}
    rows = await db.execute(
        select(Topic).where(Topic.user_id == user_id, func.lower(Topic.name).in_(list(wanted)))
    )
    mapping = {t.name.lower(): t.id for t in rows.scalars()}

    for lowered, display in wanted.items():
        if lowered in mapping:
            continue
        stmt = (
            pg_insert(Topic)
            .values(user_id=user_id, name=display)
            .on_conflict_do_nothing(constraint="uq_topic_user_name")
            .returning(Topic.id)
        )
        new_id = (await db.execute(stmt)).scalar_one_or_none()
        if new_id is None:  # someone created it a moment ago; fetch theirs
            new_id = (
                await db.execute(select(Topic.id).where(Topic.user_id == user_id, func.lower(Topic.name) == lowered))
            ).scalar_one()
        mapping[lowered] = new_id
    return mapping


async def save_quiz(
    db: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID, title: str, questions: list[dict]
) -> Quiz:
    """Store a quiz and all its questions (the caller commits).

    Args:
        db: Open database session.
        user_id: Owner of the quiz.
        document_id: The document the quiz was made from.
        title: Display title.
        questions: Validated question dicts from build_valid_questions().

    Returns:
        The new Quiz, with its questions loaded in order.
    """
    topic_ids = await get_or_create_topics(db, user_id, {q["topic"] for q in questions})

    quiz = Quiz(user_id=user_id, document_id=document_id, title=title)
    quiz.questions = [
        QuizQuestion(
            position=i,
            question_type=QuestionType(q["question_type"]),
            question_text=q["question_text"],
            options=q["options"],
            correct_answer=q["correct_answer"],
            explanation=q["explanation"],
            source_chunk_id=uuid.UUID(q["chunk_id"]) if q["chunk_id"] else None,
            topic_id=topic_ids[q["topic"].lower()],
        )
        for i, q in enumerate(questions)
    ]
    db.add(quiz)
    await db.flush()
    return quiz