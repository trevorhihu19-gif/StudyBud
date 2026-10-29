"""Flashcard endpoints: generate cards, fetch due cards, review them, and delete them."""

import uuid
from functools import partial

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.flashcard_graph import FlashcardContext, FlashcardGenerationError, flashcard_graph
from app.api.deps import get_current_user
from app.core.analytics import track
from app.core.logging import get_logger, request_id_var
from app.core.rate_limit import rate_limit
from app.core.database import get_db
from app.models import Document, DocumentStatus, Flashcard, User
from app.schemas.flashcard import (
    FlashCardGenerateRequest, FlashcardOut, FlashcardStats, GenerateResult, ReviewResult, ReviewRequest
)
from app.services.flashcard_store import MAX_CARDS_PER_USER, count_user_cards, save_flashcards
from app.services.spaced_repetition import ReviewState, schedule_next

router = APIRouter(prefix="/flashcards", tags=["flashcards"])
logger = get_logger(__name__)

@router.post("/generate", response_model=GenerateResult)
async def generate_flashcards(
    body: FlashCardGenerateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(partial(rate_limit, requested=5))
):
    """Create flashcards from one of the user's processed documents.

    Spends AI tokens from the daily quota. Cards the user already has (same front
    text) are skipped, and the response says how many.
    """
    
    found = await db.execute(select(Document).where(Document.id == body.document_id, Document.user_id == user.id))
    document = found.scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.status != DocumentStatus.READY:
        raise HTTPException(status_code=409, detail="This document isn't ready yet")
    if await count_user_cards(db, user.id) >= MAX_CARDS_PER_USER:
        raise HTTPException(status_code=409, detail=f"You've reached the limit of {MAX_CARDS_PER_USER} flashcards")
    
    await db.commit() #free the pooled connection
    
    try:
        result = await flashcard_graph.ainvoke(
            {"document_id": str(document.id), "num_cards": body.num_cards},
            context=FlashcardContext(user_id=user.id),
            config={"tags": ["flashcards"], "metadata": {"user_id": str(user.id), "request_id": request_id_var.get()}}
        )
    except FlashcardGenerationError as e:
        raise HTTPException(status_code=502, detail=str(e))
    
    created = await save_flashcards(db, user.id, document.id, result["cards"])
    await db.commit()
    
    skipped = len(result["cards"]) - len(created)
    logger.info("flashcards_generated", user_id=str(user.id), created=len(created), skipped=skipped)
    track("flashcards_generated", user_id=str(user.id), properties={"created": len(created)})
    return GenerateResult(created=[FlashcardOut(**c) for c in created], skipped_duplicates=skipped)

@router.get("/due", response_model=list[FlashcardOut])
async def due_cards(
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(rate_limit)
):
    """Get the cards that are due for review right now, oldest first (one study session's worth)."""
    
    rows = await db.execute(
        select(Flashcard)
        .where(Flashcard.user_id == user.id, Flashcard.next_review_at <= func.now())
        .order_by(Flashcard.next_review_at)
        .limit(limit)
    )
    return [FlashcardOut.model_validate(c, from_attributes=True) for c in rows.scalars()]

@router.get("/stats", response_model=FlashcardStats)
async def flashcard_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(rate_limit),
):
    """Get how many cards are due, how many exist, and when the next one comes up."""
    row = (
        await db.execute(
            select(
                func.count(Flashcard.id).label("total"),
                func.count(Flashcard.id).filter(Flashcard.next_review_at <= func.now()).label("due"),
                func.min(Flashcard.next_review_at).filter(Flashcard.next_review_at > func.now()).label("next_due"),
            ).where(Flashcard.user_id == user.id)
        )
    ).one()
    return FlashcardStats(due_count=row.due, total_count=row.total, next_due_at=row.next_due)

@router.post("/{card_id}/review", response_model=ReviewResult)
async def review_card(
    card_id: uuid.UUID,
    body: ReviewRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(rate_limit),
):
    """Record a review (again / hard / good / easy) and schedule the card's next appearance.

    The card row is locked while we update it, so a double-tap can't apply the
    review twice: the second request finds the card no longer due and gets a 409.
    Time comes from the database clock, the same one the "due" query uses.
    """
    card = (
        await db.execute(
            select(Flashcard).where(Flashcard.id == card_id, Flashcard.user_id == user.id).with_for_update()
        )
    ).scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="Flashcard not found")

    now = (await db.execute(select(func.now()))).scalar_one()
    if card.next_review_at > now:
        raise HTTPException(status_code=409, detail="This card isn't due yet")

    new_state, next_at = schedule_next(
        ReviewState(card.ease_factor, card.interval_days, card.repetitions), body.rating, now
    )
    card.ease_factor = new_state.ease_factor
    card.interval_days = new_state.interval_days
    card.repetitions = new_state.repetitions
    card.next_review_at = next_at
    await db.commit()

    track("flashcard_reviewed", user_id=str(user.id), properties={"rating": body.rating.value})
    return ReviewResult(
        id=card.id,
        next_review_at=card.next_review_at,
        interval_days=card.interval_days,
        repetitions=card.repetitions,
        ease_factor=card.ease_factor,
    )


@router.delete("/{card_id}", status_code=204)
async def delete_card(
    card_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(rate_limit),
):
    """Delete one of the user's flashcards (for example, a badly written one)."""
    deleted = await db.execute(
        delete(Flashcard).where(Flashcard.id == card_id, Flashcard.user_id == user.id).returning(Flashcard.id)
    )
    if deleted.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Flashcard not found")
    await db.commit()