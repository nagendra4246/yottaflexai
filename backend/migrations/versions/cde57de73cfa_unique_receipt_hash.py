"""unique_receipt_hash

Revision ID: cde57de73cfa
Revises: 5d6b67a9c2f1
Create Date: 2026-10-31 12:09:16.887444
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'cde57de73cfa'
down_revision: Union[str, None] = '5d6b67a9c2f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_expense_lines_receipt_hash", table_name="expense_lines")
    op.create_index(
        "uq_expense_lines_receipt_hash",
        "expense_lines",
        ["receipt_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_expense_lines_receipt_hash", table_name="expense_lines")
    op.create_index(
        "ix_expense_lines_receipt_hash",
        "expense_lines",
        ["receipt_hash"],
        unique=False,
    )
