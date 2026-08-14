"""add_language_to_task

Revision ID: c1d0f1f1c1dc
Revises: b58bb7a19939
Create Date: 2026-08-06 18:13:17.250271

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1d0f1f1c1dc'
down_revision: Union[str, Sequence[str], None] = 'b58bb7a19939'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Add the column as nullable first (safe on existing rows)
    op.add_column('tasks', sa.Column('language', sa.String(), nullable=True))
    # 2. Backfill existing rows with the default language used elsewhere in the app
    op.execute("UPDATE tasks SET language = 'es' WHERE language IS NULL")
    # 3. Now that every row has a value, enforce NOT NULL using batch_alter_table for SQLite compatibility
    with op.batch_alter_table('tasks') as batch_op:
        batch_op.alter_column('language', existing_type=sa.String(), nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('tasks') as batch_op:
        batch_op.drop_column('language')
