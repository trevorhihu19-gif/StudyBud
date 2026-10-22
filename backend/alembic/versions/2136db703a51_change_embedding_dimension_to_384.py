"""change embedding dimension to 384

Revision ID: 2136db703a51
Revises: 7db2015d524b
Create Date: 2026-10-22 10:35:03.918734

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2136db703a51'
down_revision: Union[str, None] = '7db2015d524b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
      op.execute("ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(384)")


def downgrade() -> None:
    op.execute("ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(1536)")