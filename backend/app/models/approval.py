from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .common import TimestampMixin
from ..db.base import Base

if TYPE_CHECKING:
    from .employee import Employee
    from .expense import ExpenseClaim
    from .leave import LeaveRequest


class ApprovalRule(TimestampMixin, Base):
    __tablename__ = "approval_rules"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('Leave', 'Expense')", name="ck_approval_rules_entity_type"
        ),
        CheckConstraint(
            "threshold_amount IS NULL OR threshold_amount >= 0",
            name="ck_approval_rules_threshold",
        ),
        CheckConstraint("approval_level > 0", name="ck_approval_rules_level"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_approval_rules_effective_dates",
        ),
        Index(
            "ix_approval_rules_match",
            "entity_type",
            "country_code",
            "category",
            "threshold_amount",
        ),
    )

    rule_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    threshold_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    country_code: Mapped[str | None] = mapped_column(String(12))
    category: Mapped[str | None] = mapped_column(String(80))
    approval_level: Mapped[int] = mapped_column(nullable=False)
    required_role: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApprovalStep(TimestampMixin, Base):
    __tablename__ = "approval_steps"
    __table_args__ = (
        CheckConstraint(
            "status IN ('Pending', 'Approved', 'Rejected')",
            name="ck_approval_steps_status",
        ),
        CheckConstraint("sequence > 0", name="ck_approval_steps_sequence"),
        CheckConstraint(
            "(leave_request_id IS NOT NULL AND expense_claim_id IS NULL) OR "
            "(leave_request_id IS NULL AND expense_claim_id IS NOT NULL)",
            name="ck_approval_steps_one_request",
        ),
        CheckConstraint(
            "(status = 'Pending' AND action_date IS NULL) OR "
            "(status IN ('Approved', 'Rejected') AND action_date IS NOT NULL)",
            name="ck_approval_steps_action_date",
        ),
        CheckConstraint(
            "status <> 'Rejected' OR (decision_reason IS NOT NULL AND length(trim(decision_reason)) > 0)",
            name="ck_approval_steps_rejection_reason",
        ),
        UniqueConstraint(
            "leave_request_id", "sequence", name="uq_approval_steps_leave_sequence"
        ),
        UniqueConstraint(
            "expense_claim_id", "sequence", name="uq_approval_steps_expense_sequence"
        ),
        Index("ix_approval_steps_approver_status", "approver_id", "status"),
        Index("ix_approval_steps_status_action_date", "status", "action_date"),
    )

    step_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    leave_request_id: Mapped[str | None] = mapped_column(
        ForeignKey("leave_requests.request_id", ondelete="RESTRICT")
    )
    expense_claim_id: Mapped[str | None] = mapped_column(
        ForeignKey("expense_claims.claim_id", ondelete="RESTRICT")
    )
    approver_id: Mapped[str] = mapped_column(
        ForeignKey("employees.employee_id", ondelete="RESTRICT"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="Pending")
    action_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    comments: Mapped[str | None] = mapped_column(Text)

    leave_request: Mapped["LeaveRequest | None"] = relationship(
        back_populates="approval_steps"
    )
    expense_claim: Mapped["ExpenseClaim | None"] = relationship(
        back_populates="approval_steps"
    )
    approver: Mapped["Employee"] = relationship(
        back_populates="approval_steps", foreign_keys=[approver_id]
    )

    @property
    def request_id(self) -> str:
        if self.leave_request_id is not None:
            return self.leave_request_id
        if self.expense_claim_id is not None:
            return self.expense_claim_id
        raise ValueError("Approval step must reference a leave request or expense claim")
