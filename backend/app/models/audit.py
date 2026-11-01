from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base

if TYPE_CHECKING:
    from .employee import Employee


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('Employee', 'LeavePolicy', 'LeaveBalance', 'LeaveRequest', "
            "'ExpensePolicy', 'ExpenseClaim', 'ExpenseLine', 'CostCenter', "
            "'ApprovalRule', 'ApprovalStep', 'Reimbursement', 'PublicHoliday')",
            name="ck_audit_events_entity_type",
        ),
        CheckConstraint(
            "is_exception IS FALSE OR exception_code IS NOT NULL",
            name="ck_audit_events_exception_code",
        ),
        Index("ix_audit_events_entity", "entity_type", "entity_id", "occurred_at"),
        Index("ix_audit_events_actor_occurred", "actor_employee_id", "occurred_at"),
        Index("ix_audit_events_exception", "is_exception", "occurred_at"),
    )

    event_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_employee_id: Mapped[str | None] = mapped_column(
        ForeignKey("employees.employee_id", ondelete="RESTRICT")
    )
    before_state: Mapped[dict | None] = mapped_column(JSON)
    after_state: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)
    is_exception: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    exception_code: Mapped[str | None] = mapped_column(String(80))
    exception_details: Mapped[dict | None] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    actor: Mapped["Employee | None"] = relationship(back_populates="audit_events")
