"""Add reimbursement processing lifecycle.

Revision ID: 5d6b67a9c2f1
Revises: 820a06e3b989
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5d6b67a9c2f1"
down_revision: Union[str, None] = "820a06e3b989"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("reimbursements") as batch_op:
        batch_op.add_column(
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="Pending",
            )
        )
        batch_op.add_column(
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("decision_reason", sa.String(length=2000), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_reimbursements_status", "status IN ('Pending', 'Processed')"
        )
        batch_op.create_check_constraint(
            "ck_reimbursements_processed_at",
            "(status = 'Pending' AND processed_at IS NULL) OR "
            "(status = 'Processed' AND processed_at IS NOT NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("reimbursements") as batch_op:
        batch_op.drop_constraint("ck_reimbursements_processed_at", type_="check")
        batch_op.drop_constraint("ck_reimbursements_status", type_="check")
        batch_op.drop_column("decision_reason")
        batch_op.drop_column("processed_at")
        batch_op.drop_column("status")
