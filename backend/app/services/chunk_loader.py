"""Loads a document's chunks from the database, but only for the document's owner."""

import uuid

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import Document, DocumentChunk


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