import uuid
from typing import TYPE_CHECKING
from datetime import datetime
from enum import Enum as PyEnum
from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, gen_uuid

if TYPE_CHECKING:
    from app.models.user import User

class DocumentStatus(str, PyEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"

class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)  
    storage_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus), default=DocumentStatus.PROCESSING, nullable=False
    )
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    summaries: Mapped[list["Summary"]] = relationship(back_populates="document", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_documents_user_created", "user_id", "created_at"),
        Index("ix_documents_user_status", "user_id", "status"),
    )

class DocumentChunk(Base):
    """
    One retrievable unit for hybrid search.
    - embedding: vector similarity search (pgvector, HNSW index)
    - content_tsv: keyword search (Postgres GIN index, populated by a DB trigger)
    Results from both are combined with Reciprocal Rank Fusion in the retrieval layer.
    """
    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(384), nullable=True)
    content_tsv = mapped_column(TSVECTOR, nullable=True)  
    document: Mapped["Document"] = relationship(back_populates="chunks")

    __table_args__ = (
        Index("ix_chunks_document", "document_id"),
        Index("ix_chunks_document_index", "document_id", "chunk_index"),
    )


class Summary(Base):
    __tablename__ = "summaries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="processing")
    key_points: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    full_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunks_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunks_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_messages: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    
    document: Mapped["Document"] = relationship(back_populates="summaries")
    
    __table_args__ = (
        # One summary per document
        UniqueConstraint("document_id", name="uq_summaries_document"),
        CheckConstraint("status IN ('processing', 'ready', 'failed')", name="ck_summaries_status"),
    )