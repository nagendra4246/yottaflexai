from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .common import TimestampMixin
from ..db.base import Base

if TYPE_CHECKING:
    from .approval import ApprovalStep
    from .employee import Employee


class ExpensePolicy(TimestampMixin, Base):
    __tablename__ = "expense_policies"
    __table_args__ = (
        CheckConstraint("max_amount >= 0", name="ck_expense_policies_max_amount"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_expense_policies_effective_dates",
        ),
        Index("ix_expense_policies_category_country", "category", "country_code"),
    )

    policy_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    max_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    requires_receipt: Mapped[bool] = mapped_column(nullable=False)
    country_code: Mapped[str] = mapped_column(String(12), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    expense_lines: Mapped[list["ExpenseLine"]] = relationship(back_populates="policy")


class CostCenter(TimestampMixin, Base):
    __tablename__ = "cost_centers"
    __table_args__ = (
        CheckConstraint("budget >= 0", name="ck_cost_centers_budget"),
        Index("ix_cost_centers_department", "department"),
    )

    cost_center_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    budget: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    department: Mapped[str] = mapped_column(String(120), nullable=False)

    expense_claims: Mapped[list["ExpenseClaim"]] = relationship(back_populates="cost_center")


class ExpenseClaim(TimestampMixin, Base):
    __tablename__ = "expense_claims"
    __table_args__ = (
        CheckConstraint(
            "status IN ('Draft', 'Pending', 'Approved', 'Rejected', 'Paid')",
            name="ck_expense_claims_status",
        ),
        CheckConstraint("total_amount > 0", name="ck_expense_claims_total_amount"),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_expense_claims_currency",
        ),
        Index("ix_expense_claims_employee_status", "employee_id", "status"),
        Index("ix_expense_claims_cost_center_status", "cost_center_id", "status"),
        Index("ix_expense_claims_submission_date", "submission_date"),
    )

    claim_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.employee_id", ondelete="RESTRICT"), nullable=False
    )
    cost_center_id: Mapped[str] = mapped_column(
        ForeignKey("cost_centers.cost_center_id", ondelete="RESTRICT"), nullable=False
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="Draft")
    submission_date: Mapped[date] = mapped_column(Date, nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decision_reason: Mapped[str | None] = mapped_column(String(2000))

    employee: Mapped["Employee"] = relationship(back_populates="expense_claims")
    cost_center: Mapped["CostCenter"] = relationship(back_populates="expense_claims")
    lines: Mapped[list["ExpenseLine"]] = relationship(back_populates="claim")
    approval_steps: Mapped[list["ApprovalStep"]] = relationship(
        back_populates="expense_claim"
    )
    reimbursement: Mapped["Reimbursement | None"] = relationship(
        back_populates="claim", uselist=False
    )


class ExpenseLine(TimestampMixin, Base):
    __tablename__ = "expense_lines"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_expense_lines_amount"),
        Index("ix_expense_lines_claim_id", "claim_id"),
        Index("ix_expense_lines_policy_id", "policy_id"),
        Index("ix_expense_lines_expense_date", "expense_date"),
        Index("uq_expense_lines_receipt_hash", "receipt_hash", unique=True),
    )

    line_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("expense_claims.claim_id", ondelete="RESTRICT"), nullable=False
    )
    policy_id: Mapped[str] = mapped_column(
        ForeignKey("expense_policies.policy_id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    receipt_hash: Mapped[str | None] = mapped_column(String(128))
    receipt_url: Mapped[str | None] = mapped_column(String(2048))

    claim: Mapped["ExpenseClaim"] = relationship(back_populates="lines")
    policy: Mapped["ExpensePolicy"] = relationship(back_populates="expense_lines")


class Reimbursement(TimestampMixin, Base):
    __tablename__ = "reimbursements"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_reimbursements_amount"),
        CheckConstraint(
            "status IN ('Pending', 'Processed')",
            name="ck_reimbursements_status",
        ),
        CheckConstraint(
            "(status = 'Pending' AND processed_at IS NULL) OR "
            "(status = 'Processed' AND processed_at IS NOT NULL)",
            name="ck_reimbursements_processed_at",
        ),
        Index("ix_reimbursements_payment_date", "payment_date"),
    )

    reimbursement_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("expense_claims.claim_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    transaction_ref: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="Pending")
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(String(2000))

    claim: Mapped["ExpenseClaim"] = relationship(back_populates="reimbursement")
