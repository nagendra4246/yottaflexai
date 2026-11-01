from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .common import TimestampMixin
from ..db.base import Base

if TYPE_CHECKING:
    from .approval import ApprovalStep
    from .audit import AuditEvent
    from .expense import ExpenseClaim
    from .leave import LeaveBalance, LeaveRequest


class Employee(TimestampMixin, Base):
    __tablename__ = "employees"
    __table_args__ = (
        CheckConstraint(
            "status IN ('Active', 'Inactive', 'Terminated')",
            name="ck_employees_status",
        ),
        CheckConstraint(
            "manager_id IS NULL OR manager_id <> employee_id",
            name="ck_employees_not_own_manager",
        ),
        CheckConstraint(
            "termination_date IS NULL OR termination_date >= hire_date",
            name="ck_employees_termination_date",
        ),
        Index("ix_employees_manager_id", "manager_id"),
        Index("ix_employees_country_status", "country", "status"),
    )

    employee_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    manager_id: Mapped[str | None] = mapped_column(
        ForeignKey("employees.employee_id", ondelete="RESTRICT"), nullable=True
    )
    department: Mapped[str] = mapped_column(String(120), nullable=False)
    country: Mapped[str] = mapped_column(String(3), nullable=False)
    hire_date: Mapped[date] = mapped_column(Date, nullable=False)
    termination_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="Active")
    approval_role: Mapped[str | None] = mapped_column(String(64), nullable=True)

    manager: Mapped["Employee | None"] = relationship(
        back_populates="direct_reports", remote_side="Employee.employee_id"
    )
    direct_reports: Mapped[list["Employee"]] = relationship(back_populates="manager")
    leave_balances: Mapped[list["LeaveBalance"]] = relationship(back_populates="employee")
    leave_requests: Mapped[list["LeaveRequest"]] = relationship(back_populates="employee")
    expense_claims: Mapped[list["ExpenseClaim"]] = relationship(back_populates="employee")
    approval_steps: Mapped[list["ApprovalStep"]] = relationship(
        back_populates="approver", foreign_keys="ApprovalStep.approver_id"
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(back_populates="actor")
