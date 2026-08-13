"""add_hype_qa_to_reports_and_tasks

Revision ID: 56b7d4a06210
Revises: c1d0f1f1c1dc
Create Date: 2026-08-13 16:32:36.733662

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '56b7d4a06210'
down_revision: Union[str, Sequence[str], None] = 'c1d0f1f1c1dc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('reports', sa.Column('hype_qa', sa.JSON(), nullable=True))
    op.add_column('tasks', sa.Column('hype_qa', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('tasks', 'hype_qa')
    op.drop_column('reports', 'hype_qa')
