from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.errors import DomainError
from ..models import CostCenter, Employee, ExpenseClaim, ExpenseLine, ExpensePolicy
from ..repositories.repository import Repository


def validate_expense_date(employee: Employee, expense_date: date) -> None:
    if expense_date < employee.hire_date or (
        employee.termination_date is not None and expense_date > employee.termination_date
    ):
        raise DomainError(
            "OUTSIDE_EMPLOYMENT_PERIOD",
            "Expense date must fall within the employee's employment period",
        )
    if employee.status != "Active":
        raise DomainError("EMPLOYEE_NOT_ACTIVE", "Only active employees may submit expenses")


def applicable_expense_policy(
    session: Session, policy_id: str, country: str, expense_date: date
) -> ExpensePolicy:
    policy = Repository(session).get_expense_policy(policy_id)
    if policy is None:
        raise DomainError("EXPENSE_POLICY_NOT_FOUND", "Expense policy does not exist", status_code=404)
    if policy.country_code not in {"GLOBAL", country}:
        raise DomainError("EXPENSE_POLICY_NOT_APPLICABLE", "Policy does not apply to employee country")
    if policy.effective_from > expense_date or (
        policy.effective_to is not None and policy.effective_to < expense_date
    ):
        raise DomainError("EXPENSE_POLICY_EXPIRED", "Expense policy is not active on expense date")
    return policy


def validate_receipt(policy: ExpensePolicy, receipt_hash: str | None, receipt_url: str | None):
    if policy.requires_receipt and not (receipt_hash or receipt_url):
        raise DomainError("RECEIPT_REQUIRED", "Expense policy requires receipt metadata")
    if receipt_hash is not None and not receipt_hash.strip():
        raise DomainError("INVALID_RECEIPT_HASH", "Receipt hash cannot be blank")
    if receipt_url is not None and not receipt_url.startswith(("https://", "http://")):
        raise DomainError("INVALID_RECEIPT_URL", "Receipt URL must be an HTTP(S) URL")


def check_policy_limit(policy: ExpensePolicy, amount: Decimal) -> None:
    if amount > policy.max_amount:
        raise DomainError(
            "POLICY_LIMIT_EXCEEDED",
            f"Expense line exceeds policy limit of {policy.max_amount}",
            details={"limit": policy.max_amount, "amount": amount},
        )


def check_budget(cost_center: CostCenter, reserved: Decimal, amount: Decimal) -> None:
    if reserved + amount > cost_center.budget:
        raise DomainError(
            "BUDGET_EXCEEDED",
            "Claim would exceed the cost-center budget",
            details={"budget": cost_center.budget, "reserved": reserved, "claim_amount": amount},
        )


def find_split_claim(
    session: Session,
    *,
    employee_id: str,
    cost_center_id: str,
    submission_date: date,
    categories: set[str],
    amount: Decimal,
    currency: str,
) -> tuple[ExpenseClaim, Decimal] | None:
    repository = Repository(session)
    for existing in repository.expense_claims_by_employee(employee_id):
        if existing.cost_center_id != cost_center_id:
            continue
        if existing.currency != currency:
            continue
        if abs((existing.submission_date - submission_date).days) > 1:
            continue
        existing_categories = set(
            session.scalars(
                select(ExpensePolicy.category)
                .join(ExpenseLine, ExpenseLine.policy_id == ExpensePolicy.policy_id)
                .where(ExpenseLine.claim_id == existing.claim_id)
            )
        )
        common_categories = categories & existing_categories
        if not common_categories:
            continue
        rules = repository.approval_rules(
            "Expense", existing.employee.country, next(iter(common_categories))
        )
        for rule in rules:
            if rule.threshold_amount is None:
                continue
            if (
                rule.effective_from.date() > submission_date
                or (
                    rule.effective_to is not None
                    and rule.effective_to.date() < submission_date
                )
            ):
                continue
            threshold = Decimal(rule.threshold_amount)
            if existing.total_amount < threshold and amount < threshold:
                combined = existing.total_amount + amount
                if combined >= threshold:
                    return existing, threshold
    return None
