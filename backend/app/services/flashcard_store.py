"""Saves generated flashcards to the database."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Flashcard

MAX_CARDS_PER_USER = 2000  # keeps one account from filling the table


async def count_user_cards(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Count how many flashcards the user already has."""
    result = await db.execute(select(func.count()).select_from(Flashcard).where(Flashcard.user_id == user_id))
    return result.scalar_one()


async def save_flashcards(
    db: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID, cards: list[dict]
) -> list[dict]:
    """Insert new flashcards, silently skipping ones the user already has (the caller commits).

    The unique (user_id, front_hash) constraint plus ON CONFLICT DO NOTHING means
    duplicates are skipped atomically, even if two requests run at the same time.

    Args:
        db: Open database session.
        user_id: Owner of the cards.
        document_id: The document the cards came from.
        cards: Validated dicts from build_valid_cards().

    Returns:
        Only the cards that were actually created, as dicts with id, document_id,
        front, back, next_review_at, interval_days and repetitions.
    """
    stmt = (
        pg_insert(Flashcard)
        .values([{"user_id": user_id, "document_id": document_id, **c} for c in cards])
        .on_conflict_do_nothing(constraint="uq_flashcard_user_front")
        .returning(
            Flashcard.id,
            Flashcard.document_id,
            Flashcard.front,
            Flashcard.back,
            Flashcard.next_review_at,
            Flashcard.interval_days,
            Flashcard.repetitions,
        )
    )
    result = await db.execute(stmt)
    return [dict(row._mapping) for row in result]