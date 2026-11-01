from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..domain.audit import record_event
from ..domain.errors import DomainError
from ..models import (
    ApprovalStep,
    CostCenter,
    Employee,
    ExpenseClaim,
    ExpenseLine,
    ExpensePolicy,
)
from ..repositories.repository import Repository
from ..rules.approval import approval_chain
from ..rules.expense import (
    applicable_expense_policy,
    check_budget,
    check_policy_limit,
    find_split_claim,
    validate_expense_date,
    validate_receipt,
)
from ..schemas.requests import ExpenseClaimCreate
from .common import constraint_name, fail_with_audit, next_id


def submit_expense_claim(session: Session, data: ExpenseClaimCreate) -> ExpenseClaim:
    claim_id = data.claim_id or next_id(
        session, ExpenseClaim, "claim_id", f"EXP-{data.submission_date.year}-"
    )
    employee = session.get(Employee, data.employee_id)
    cost_center = session.scalar(
        select(CostCenter)
        .where(CostCenter.cost_center_id == data.cost_center_id)
        .with_for_update()
    )
    try:
        if employee is None:
            raise DomainError("EMPLOYEE_NOT_FOUND", "Employee does not exist", status_code=404)
        validate_expense_date(employee, data.submission_date)
        validate_expense_date(employee, min(line.expense_date for line in data.lines))
        validate_expense_date(employee, max(line.expense_date for line in data.lines))
        if cost_center is None:
            raise DomainError("COST_CENTER_NOT_FOUND", "Cost center does not exist", status_code=404)
        if session.get(ExpenseClaim, claim_id) is not None:
            raise DomainError("EXPENSE_CLAIM_EXISTS", "Expense claim ID already exists", status_code=409)

        amount = sum((line.amount for line in data.lines), start=Decimal("0.00"))
        categories: set[str] = set()
        line_policies: list[ExpensePolicy] = []
        seen_hashes: set[str] = set()
        repository = Repository(session)
        for line in data.lines:
            policy = applicable_expense_policy(
                session, line.policy_id, employee.country, line.expense_date
            )
            validate_expense_date(employee, line.expense_date)
            check_policy_limit(policy, line.amount)
            validate_receipt(policy, line.receipt_hash, line.receipt_url)
            if line.receipt_hash:
                if line.receipt_hash in seen_hashes or repository.duplicate_receipt(line.receipt_hash):
                    raise DomainError(
                        "DUPLICATE_RECEIPT",
                        "Receipt hash has already been used",
                        status_code=409,
                        details={"receipt_hash": line.receipt_hash},
                    )
                seen_hashes.add(line.receipt_hash)
            categories.add(policy.category)
            line_policies.append(policy)
        line_ids = [
            line.line_id or f"EXPL-{claim_id}-{sequence:02d}"
            for sequence, line in enumerate(data.lines, start=1)
        ]
        if any(not line_id.startswith(f"EXPL-{claim_id}-") for line_id in line_ids):
            raise DomainError(
                "INVALID_EXPENSE_LINE_ID",
                "Expense line IDs must belong to their claim",
            )
        if len(set(line_ids)) != len(line_ids) or any(
            session.get(ExpenseLine, line_id) is not None for line_id in line_ids
        ):
            raise DomainError(
                "EXPENSE_LINE_EXISTS",
                "Expense line ID already exists",
                status_code=409,
            )
        check_budget(
            cost_center,
            Decimal(repository.expense_amount_for_budget(cost_center.cost_center_id)),
            amount,
        )
        split = find_split_claim(
            session,
            employee_id=employee.employee_id,
            cost_center_id=cost_center.cost_center_id,
            submission_date=data.submission_date,
            categories=categories,
            amount=amount,
            currency=data.currency,
        )
        if split is not None:
            existing, threshold = split
            raise DomainError(
                "POTENTIAL_SPLIT_CLAIM",
                "Claim may be split to evade an approval threshold",
                status_code=409,
                details={
                    "related_claim_id": existing.claim_id,
                    "threshold": threshold,
                    "combined_amount": existing.total_amount + amount,
                },
            )
        chain = approval_chain(
            session,
            employee=employee,
            entity_type="Expense",
            amount=amount,
            country=employee.country,
            categories=categories,
            effective_date=data.submission_date,
        )
    except DomainError as error:
        fail_with_audit(
            session,
            error,
            entity_type="ExpenseClaim",
            entity_id=claim_id,
            actor_employee_id=data.employee_id,
        )

    claim = ExpenseClaim(
        claim_id=claim_id,
        employee_id=employee.employee_id,
        cost_center_id=cost_center.cost_center_id,
        total_amount=amount,
        currency=data.currency,
        status="Pending",
        submission_date=data.submission_date,
    )
    session.add(claim)
    session.flush()
    for sequence, (input_line, policy) in enumerate(
        zip(data.lines, line_policies, strict=True), start=1
    ):
        line_id = input_line.line_id or f"EXPL-{claim_id}-{sequence:02d}"
        session.add(
            ExpenseLine(
                line_id=line_id,
                claim_id=claim_id,
                policy_id=policy.policy_id,
                amount=input_line.amount,
                description=input_line.description,
                expense_date=input_line.expense_date,
                receipt_hash=input_line.receipt_hash,
                receipt_url=input_line.receipt_url,
            )
        )
    for sequence, approver in enumerate(chain, start=1):
        session.add(
            ApprovalStep(
                step_id=f"APR-{claim_id}-{sequence:02d}",
                expense_claim_id=claim_id,
                approver_id=approver.employee_id,
                sequence=sequence,
                status="Pending",
            )
        )
    record_event(
        session,
        entity_type="ExpenseClaim",
        entity_id=claim_id,
        event_type="expense_submitted",
        actor_employee_id=employee.employee_id,
        after_state={
            "status": claim.status,
            "total_amount": amount,
            "currency": claim.currency,
        },
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        constraint = constraint_name(error)
        if (
            constraint == "uq_expense_lines_receipt_hash"
            or "expense_lines.receipt_hash" in constraint
        ):
            fail_with_audit(
                session,
                DomainError(
                    "DUPLICATE_RECEIPT",
                    "Receipt hash has already been used",
                    status_code=409,
                ),
                entity_type="ExpenseClaim",
                entity_id=claim_id,
                actor_employee_id=employee.employee_id,
            )
        if "expense_lines.line_id" in constraint:
            fail_with_audit(
                session,
                DomainError(
                    "EXPENSE_LINE_EXISTS",
                    "Expense line ID already exists",
                    status_code=409,
                ),
                entity_type="ExpenseClaim",
                entity_id=claim_id,
                actor_employee_id=employee.employee_id,
            )
        if (
            "expense_claims.claim_id" in constraint
            or constraint.endswith("expense_claims_pkey")
        ):
            fail_with_audit(
                session,
                DomainError(
                    "EXPENSE_CLAIM_EXISTS",
                    "Expense claim ID already exists",
                    status_code=409,
                ),
                entity_type="ExpenseClaim",
                entity_id=claim_id,
                actor_employee_id=employee.employee_id,
            )
        raise
    return claim
