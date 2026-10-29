"""Loads a document's chunks from the database, but only for the document's owner."""

import uuid
import random
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import Document, DocumentChunk
from app.services.chunk_selection import select_representative


async def load_owned_chunks(user_id: uuid.UUID, document_id: uuid.UUID) -> list[dict]:
    """Fetch every chunk of a document, in reading order, if the user owns it.

    The ownership check is part of the query itself (a join on documents.user_id),
    so a wrong or someone else's document id simply returns an empty list.

    Args:
        user_id: The logged-in user.
        document_id: The document whose chunks we want.

    Returns:
        A list of dicts with chunk_id, chunk_index, page_number, content,
        token_count and embedding. Empty if the user doesn't own the document.
    """
    async with AsyncSessionLocal() as db, db.begin():
        rows = await db.execute(
            select(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(DocumentChunk.document_id == document_id, Document.user_id == user_id)
            .order_by(DocumentChunk.chunk_index)
        )
        return [
            {
                "chunk_id": str(c.id),
                "chunk_index": c.chunk_index,
                "page_number": c.page_number,
                "content": c.content,
                "token_count": c.token_count,
                "embedding": c.embedding,
            }
            for c in rows.scalars()
        ]
        

async def load_study_sample(
    user_id: uuid.UUID, document_id: uuid.UUID, budget_tokens: int, sample_fraction: float = 1.0
) -> list[dict]:
    """Load a varied, representative slice of a document's chunks for AI generation.

    Optionally takes a random fraction first (so repeated requests differ), then
    keeps the most representative chunks that fit the token budget. No AI call.

    Args:
        user_id: The logged-in user (ownership is checked while loading).
        document_id: The document to sample from.
        budget_tokens: Most document text (in tokens) to return.
        sample_fraction: Share of chunks to consider, from 0 to 1.

    Returns:
        Chunk dicts in reading order, without embeddings. Empty if the user
        doesn't own the document or it has no usable content.
    """
    all_chunks = await load_owned_chunks(user_id, document_id)
    usable = [c for c in all_chunks if c["embedding"] is not None]
    if len(usable) > 10 and sample_fraction < 1.0:
        usable = random.sample(usable, int(len(usable) * sample_fraction))
    if not usable:
        return []

    selected = select_representative(usable, budget_tokens)
    for c in selected:
        c.pop("embedding")  
    return selected