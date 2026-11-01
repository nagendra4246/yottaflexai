from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..domain.errors import DomainError
from ..models import (
    ApprovalStep,
    CostCenter,
    ExpenseClaim,
    ExpenseLine,
    LeaveRequest,
)
from ..repositories.repository import Repository
from ..rules.leave import calculated_available_balance


def leave_workflow(session: Session, request_id: str) -> dict:
    request = session.get(LeaveRequest, request_id)
    if request is None:
        raise DomainError(
            "LEAVE_REQUEST_NOT_FOUND",
            "Leave request does not exist",
            status_code=404,
        )
    balance = Repository(session).latest_leave_balance(
        request.employee_id, request.policy_id, for_update=False
    )
    if balance is None:
        raise DomainError("LEAVE_BALANCE_NOT_FOUND", "No leave balance exists for this policy")
    steps = Repository(session).approval_steps(request_id, None)
    return {
        "request": request,
        "balance": {
            "balance_id": balance.balance_id,
            "employee_id": balance.employee_id,
            "policy_id": balance.policy_id,
            "accrued_balance": balance.accrued_balance,
            "used_balance": balance.used_balance,
            "pending_balance": balance.pending_balance,
            "available_balance": calculated_available_balance(
                Decimal(balance.accrued_balance),
                Decimal(balance.used_balance),
                Decimal(balance.pending_balance),
            ),
            "effective_date": balance.effective_date,
        },
        "approval_steps": steps,
    }


def expense_workflow(session: Session, claim_id: str) -> dict:
    claim = session.scalar(
        select(ExpenseClaim)
        .options(
            selectinload(ExpenseClaim.lines).selectinload(ExpenseLine.policy),
            selectinload(ExpenseClaim.approval_steps),
        )
        .where(ExpenseClaim.claim_id == claim_id)
    )
    if claim is None:
        raise DomainError(
            "EXPENSE_CLAIM_NOT_FOUND",
            "Expense claim does not exist",
            status_code=404,
        )
    cost_center = session.get(CostCenter, claim.cost_center_id)
    if cost_center is None:
        raise DomainError(
            "COST_CENTER_NOT_FOUND",
            "Claim cost center does not exist",
            status_code=409,
        )
    committed = Decimal(
        Repository(session).expense_amount_for_budget(cost_center.cost_center_id)
    )
    return {
        "claim": claim,
        "lines": [
            {
                "line_id": line.line_id,
                "claim_id": line.claim_id,
                "policy_id": line.policy_id,
                "policy_category": line.policy.category,
                "policy_max_amount": line.policy.max_amount,
                "receipt_required": line.policy.requires_receipt,
                "amount": line.amount,
                "description": line.description,
                "expense_date": line.expense_date,
                "receipt_hash": line.receipt_hash,
                "receipt_url": line.receipt_url,
            }
            for line in sorted(claim.lines, key=lambda item: item.line_id)
        ],
        "approval_steps": sorted(claim.approval_steps, key=lambda item: item.sequence),
        "cost_center_budget": cost_center.budget,
        "budget_committed": committed,
        "budget_remaining": Decimal(cost_center.budget) - committed,
    }
