"""Update embedding dimension to 384

Revision ID: d956007f9d39
Revises: 6c88f56ded27
Create Date: 2025-12-14 10:50:43.392293

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd956007f9d39'
down_revision: Union[str, None] = '6c88f56ded27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Recreate embedding column with 384 dimensions
    op.execute('ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(384)')


def downgrade() -> None:
    # Revert to 768 dimensions
    op.execute('ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(768)')
