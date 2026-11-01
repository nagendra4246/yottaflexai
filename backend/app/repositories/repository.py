from datetime import date
from decimal import Decimal
from typing import TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    ApprovalRule,
    ApprovalStep,
    CostCenter,
    Employee,
    ExpenseClaim,
    ExpenseLine,
    ExpensePolicy,
    LeaveBalance,
    LeavePolicy,
    LeaveRequest,
    PublicHoliday,
    Reimbursement,
)

ModelT = TypeVar("ModelT")


class Repository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_employee(self, employee_id: str) -> Employee | None:
        return self.session.get(Employee, employee_id)

    def get_leave_policy(self, policy_id: str) -> LeavePolicy | None:
        return self.session.get(LeavePolicy, policy_id)

    def get_expense_policy(self, policy_id: str) -> ExpensePolicy | None:
        return self.session.get(ExpensePolicy, policy_id)

    def get_cost_center(self, cost_center_id: str) -> CostCenter | None:
        return self.session.get(CostCenter, cost_center_id)

    def latest_leave_balance(
        self, employee_id: str, policy_id: str, *, for_update: bool = True
    ) -> LeaveBalance | None:
        statement = (
            select(LeaveBalance)
            .where(
                LeaveBalance.employee_id == employee_id,
                LeaveBalance.policy_id == policy_id,
            )
            .order_by(LeaveBalance.effective_date.desc(), LeaveBalance.balance_id.desc())
            .limit(1)
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def holidays(self, country_code: str, start: date, end: date) -> set[date]:
        return set(
            self.session.scalars(
                select(PublicHoliday.holiday_date).where(
                    PublicHoliday.country_code == country_code,
                    PublicHoliday.holiday_date.between(start, end),
                )
            )
        )

    def next_id(self, model: type[ModelT], key: str, prefix: str) -> str:
        if self.session.get_bind().dialect.name == "postgresql":
            self.session.execute(
                select(func.pg_advisory_xact_lock(func.hashtext(f"yottaflex:{key}:{prefix}")))
            )
        values = self.session.scalars(
            select(getattr(model, key)).where(getattr(model, key).like(f"{prefix}%"))
        )
        highest = 0
        for value in values:
            suffix = value[len(prefix) :]
            if suffix.isdigit():
                highest = max(highest, int(suffix))
        return f"{prefix}{highest + 1:06d}"

    def approval_steps(self, leave_request_id: str | None, expense_claim_id: str | None):
        statement = select(ApprovalStep)
        if leave_request_id is not None:
            statement = statement.where(ApprovalStep.leave_request_id == leave_request_id)
        else:
            statement = statement.where(ApprovalStep.expense_claim_id == expense_claim_id)
        return list(
            self.session.scalars(
                statement.order_by(ApprovalStep.sequence).with_for_update()
            )
        )

    def expense_amount_for_budget(self, cost_center_id: str) -> Decimal:
        return self.session.scalar(
            select(func.coalesce(func.sum(ExpenseClaim.total_amount), 0)).where(
                ExpenseClaim.cost_center_id == cost_center_id,
                ExpenseClaim.status.in_(("Pending", "Approved", "Paid")),
            )
        ) or 0

    def duplicate_receipt(self, receipt_hash: str, *, excluding_claim_id: str | None = None):
        statement = select(ExpenseLine).where(ExpenseLine.receipt_hash == receipt_hash)
        if excluding_claim_id is not None:
            statement = statement.where(ExpenseLine.claim_id != excluding_claim_id)
        return self.session.scalar(statement.limit(1))

    def reimbursement_for_claim(self, claim_id: str) -> Reimbursement | None:
        return self.session.scalar(
            select(Reimbursement).where(Reimbursement.claim_id == claim_id)
        )

    def approval_rules(self, entity_type: str, country: str, category: str | None):
        statement = select(ApprovalRule).where(
            ApprovalRule.entity_type == entity_type,
            (ApprovalRule.country_code.is_(None)) | (ApprovalRule.country_code == country),
        )
        if category is not None:
            statement = statement.where(
                (ApprovalRule.category.is_(None)) | (ApprovalRule.category == category)
            )
        return list(
            self.session.scalars(
                statement.order_by(ApprovalRule.approval_level, ApprovalRule.threshold_amount)
            )
        )

    def expense_claims_by_employee(self, employee_id: str):
        return list(
            self.session.scalars(
                select(ExpenseClaim).where(
                    ExpenseClaim.employee_id == employee_id,
                    ExpenseClaim.status.in_(("Pending", "Approved", "Paid")),
                )
            )
        )

    def approved_leave_requests(self, employee_id: str):
        return list(
            self.session.scalars(
                select(LeaveRequest).where(
                    LeaveRequest.employee_id == employee_id,
                    LeaveRequest.status == "Approved",
                )
            )
        )
