import asyncio
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.core.database import AsyncSessionLocal
from app.models import Document, DocumentChunk, DocumentStatus
from app.services.chunking import chunk_documents
from app.services.embeddings import embed_chunks
from app.services.extraction import ExtractionError, extract_pages

logger = get_logger(__name__)

async def process_document(document_id: UUID) -> None:
    """
    Runs as a background task after upload. Owns its own DB session since
    it executes outside any request's dependency-injected session.

    NOTE: this function takes only a document_id (a plain, serializable
    argument) rather than any ORM object or session — that's deliberate,
    so this can be handed to Celery/ARQ later with zero changes to its
    signature or body.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Document).where(Document.id == document_id))
        document = result.scalar_one_or_none()
        if document is None:
            logger.error("document_not_found_for_processing", document_id=str(document_id))
            return
        
        try:
            file_path = Path(settings.storage_dir) / document.storage_url
            pages = await asyncio.to_thread(extract_pages, file_path, document.file_type)
            chunks = await asyncio.to_thread(chunk_documents, pages)
            chunks = await embed_chunks(chunks)
            
            for chunk in chunks:
                db.add(
                    DocumentChunk(
                        document_id=document.id,
                        chunk_index=chunk["chunk_index"],
                        page_number=chunk["page_number"],
                        content=chunk["content"],
                        token_count=chunk["token_count"],
                        embedding=chunk["embedding"],
                    )
                )

            document.status = DocumentStatus.READY
            document.page_count = max((c["page_number"] or 0 for c in chunks), default=None)
            await db.commit()

            logger.info(
                "document_processed", document_id=str(document.id), chunk_count=len(chunks)
            )
                
        except ExtractionError as e:
            document.status = DocumentStatus.FAILED
            document.error_message = str(e)
            await db.commit()
            
            logger.warning("document_processing_failed", document_id=str(document.id), reason=str(e))
            
        except Exception as e:
            await db.rollback()
            document.status = DocumentStatus.FAILED
            document.error_message = "Processing failed unexpectedly"
            await db.commit()
            
            logger.exception("document_processing_error", document_id=str(document.id), error=str(e))