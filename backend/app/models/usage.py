import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, gen_uuid

class UsageCounter(Base):
    __tablename__ = "usage_counters"
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    resource: Mapped[str] = mapped_column(String(50), nullable=False, default="llm_tokens")
    used: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    
    __table_args__ = (
        UniqueConstraint(
            "user_id", "day", "resource",
            name="uq_usage_scope_day_resource",
            postgresql_nulls_not_distinct=True,
        ),
    )