from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .common import TimestampMixin
from ..db.base import Base

if TYPE_CHECKING:
    from .approval import ApprovalStep
    from .employee import Employee


class LeavePolicy(TimestampMixin, Base):
    __tablename__ = "leave_policies"
    __table_args__ = (
        CheckConstraint("annual_entitlement >= 0", name="ck_leave_policies_entitlement"),
        CheckConstraint("carry_over_limit >= 0", name="ck_leave_policies_carry_over"),
        CheckConstraint("accrual_rate >= 0", name="ck_leave_policies_accrual"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_leave_policies_effective_dates",
        ),
        Index("ix_leave_policies_country_effective", "country_code", "effective_from"),
    )

    policy_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    policy_name: Mapped[str] = mapped_column(String(120), nullable=False)
    annual_entitlement: Mapped[int] = mapped_column(Integer, nullable=False)
    carry_over_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    accrual_rate: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    country_code: Mapped[str] = mapped_column(String(3), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    leave_balances: Mapped[list["LeaveBalance"]] = relationship(back_populates="policy")
    leave_requests: Mapped[list["LeaveRequest"]] = relationship(back_populates="policy")


class LeaveBalance(TimestampMixin, Base):
    __tablename__ = "leave_balances"
    __table_args__ = (
        UniqueConstraint(
            "employee_id", "policy_id", "effective_date", name="uq_leave_balances_snapshot"
        ),
        Index("ix_leave_balances_employee_policy", "employee_id", "policy_id"),
    )

    balance_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.employee_id", ondelete="RESTRICT"), nullable=False
    )
    policy_id: Mapped[str] = mapped_column(
        ForeignKey("leave_policies.policy_id", ondelete="RESTRICT"), nullable=False
    )
    accrued_balance: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    used_balance: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    pending_balance: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)

    employee: Mapped["Employee"] = relationship(back_populates="leave_balances")
    policy: Mapped["LeavePolicy"] = relationship(back_populates="leave_balances")


class LeaveRequest(TimestampMixin, Base):
    __tablename__ = "leave_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('Draft', 'Pending', 'Approved', 'Rejected', 'Cancelled')",
            name="ck_leave_requests_status",
        ),
        CheckConstraint("end_date >= start_date", name="ck_leave_requests_date_order"),
        CheckConstraint("total_days >= 0", name="ck_leave_requests_total_days"),
        Index("ix_leave_requests_employee_status", "employee_id", "status"),
        Index("ix_leave_requests_status_start_date", "status", "start_date"),
    )

    request_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.employee_id", ondelete="RESTRICT"), nullable=False
    )
    policy_id: Mapped[str] = mapped_column(
        ForeignKey("leave_policies.policy_id", ondelete="RESTRICT"), nullable=False
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_days: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    leave_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="Draft")
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(String(2000))

    employee: Mapped["Employee"] = relationship(back_populates="leave_requests")
    policy: Mapped["LeavePolicy"] = relationship(back_populates="leave_requests")
    approval_steps: Mapped[list["ApprovalStep"]] = relationship(
        back_populates="leave_request"
    )


class PublicHoliday(Base):
    __tablename__ = "public_holidays"
    __table_args__ = (
        UniqueConstraint("country_code", "holiday_date", name="uq_public_holidays_country_date"),
        Index("ix_public_holidays_country_date", "country_code", "holiday_date"),
    )

    holiday_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    country_code: Mapped[str] = mapped_column(String(3), nullable=False)
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
