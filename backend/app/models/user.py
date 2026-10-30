import uuid
from typing import TYPE_CHECKING
from datetime import datetime
from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, gen_uuid

if TYPE_CHECKING:
    from app.models.flashcard import Flashcard
    from app.models.quiz import Quiz
    from app.models.topic import Topic
    from app.models.chat import ChatSession
    from app.models.document import Document

class User(Base):
    __tablename__ = "users"

    id:Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=gen_uuid
    )
    clerk_id: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )
    email:Mapped[str] = mapped_column(
        String(320), unique=True, nullable=False
    )
    name:Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    study_streak_days: Mapped[int] = mapped_column(
        Integer, default=0
    )
    last_active_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="UTC")

    documents: Mapped[list["Document"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    topics: Mapped[list["Topic"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    quizzes: Mapped[list["Quiz"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    flashcards: Mapped[list["Flashcard"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    chat_sessions: Mapped[list["ChatSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")