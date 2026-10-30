
"""flashcard front hash uniqueness

Revision ID: c308b5dac6bd
Revises: 5218e83f5074
Create Date: 2026-10-28 10:43:06.949876
"""

import hashlib
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c308b5dac6bd"
down_revision: Union[str, None] = "5218e83f5074"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add the column as nullable so existing rows can be backfilled.
    op.add_column(
        "flashcards",
        sa.Column("front_hash", sa.String(length=64), nullable=True),
    )

    flashcards = sa.table(
        "flashcards",
        sa.column("id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()),
        sa.column("front", sa.Text()),
        sa.column("front_hash", sa.String(length=64)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )

    connection = op.get_bind()

    rows = connection.execute(
        sa.select(
            flashcards.c.id,
            flashcards.c.user_id,
            flashcards.c.front,
            flashcards.c.created_at,
        ).order_by(
            flashcards.c.created_at.asc().nullsfirst(),
            flashcards.c.id.asc(),
        )
    ).mappings().all()

    # Use the same normalization and hashing as front_fingerprint().
    seen: set[tuple[object, str]] = set()

    for row in rows:
        normalized = re.sub(r"\W+", " ", row["front"].lower()).strip()
        front_hash = hashlib.sha256(
            normalized.encode("utf-8")
        ).hexdigest()

        duplicate_key = (row["user_id"], front_hash)

        if duplicate_key in seen:
            # Retention policy: keep the oldest matching card per user.
            connection.execute(
                sa.delete(flashcards).where(
                    flashcards.c.id == row["id"]
                )
            )
            continue

        seen.add(duplicate_key)

        connection.execute(
            sa.update(flashcards)
            .where(flashcards.c.id == row["id"])
            .values(front_hash=front_hash)
        )

    # Enforce NOT NULL after all existing rows have been backfilled.
    op.alter_column(
        "flashcards",
        "front_hash",
        existing_type=sa.String(length=64),
        nullable=False,
    )

    # Prevent duplicate normalized fronts for the same user.
    op.create_unique_constraint(
        "uq_flashcard_user_front",
        "flashcards",
        ["user_id", "front_hash"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_flashcard_user_front",
        "flashcards",
        type_="unique",
    )
    op.drop_column("flashcards", "front_hash")
