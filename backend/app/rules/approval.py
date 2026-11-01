from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.errors import DomainError
from ..models import ApprovalRule, Employee
from ..repositories.repository import Repository


def _active_role_approver(
    session: Session,
    role: str,
    requester_id: str,
    manager_chain: list[Employee],
    excluded_ids: set[str],
) -> Employee | None:
    for candidate in manager_chain:
        if (
            candidate.employee_id != requester_id
            and candidate.employee_id not in excluded_ids
            and candidate.status == "Active"
            and candidate.approval_role == role
        ):
            return candidate
    return session.scalar(
        select(Employee)
        .where(
            Employee.approval_role == role,
            Employee.status == "Active",
            Employee.employee_id != requester_id,
            Employee.employee_id.not_in(excluded_ids),
        )
        .order_by(Employee.employee_id)
        .limit(1)
    )


def approval_chain(
    session: Session,
    *,
    employee: Employee,
    entity_type: str,
    amount: Decimal,
    country: str,
    categories: set[str],
    effective_date: date,
) -> list[Employee]:
    chain: list[Employee] = []
    ancestors: list[Employee] = []
    manager_id = employee.manager_id
    seen = {employee.employee_id}
    while manager_id is not None:
        if manager_id in seen:
            raise DomainError("MANAGER_CYCLE", "Employee hierarchy contains a cycle")
        seen.add(manager_id)
        manager = session.get(Employee, manager_id)
        if manager is None or manager.status != "Active":
            raise DomainError("INVALID_MANAGER", "Employee manager is missing or inactive")
        ancestors.append(manager)
        manager_id = manager.manager_id

    if ancestors:
        chain.append(ancestors[0])

    rules = Repository(session).approval_rules(
        entity_type, country, next(iter(categories)) if len(categories) == 1 else None
    )
    applicable = [
        rule
        for rule in rules
        if (rule.threshold_amount is None or amount >= rule.threshold_amount)
        and (rule.category is None or rule.category in categories)
        and rule.effective_from.date() <= effective_date
        and (rule.effective_to is None or rule.effective_to.date() >= effective_date)
    ]
    for rule in sorted(applicable, key=lambda item: (item.approval_level, item.required_role)):
        if rule.required_role.casefold() == "manager":
            candidate = ancestors[0] if ancestors else None
        else:
            candidate = _active_role_approver(
                session,
                rule.required_role,
                employee.employee_id,
                ancestors,
                {person.employee_id for person in chain},
            )
        if candidate is None:
            raise DomainError(
                "APPROVER_UNAVAILABLE",
                f"No eligible approver is available for role {rule.required_role}",
                details={"required_role": rule.required_role},
            )
        if candidate.employee_id == employee.employee_id:
            raise DomainError("SELF_APPROVAL", "Requester cannot approve their own request", status_code=409)
        if all(existing.employee_id != candidate.employee_id for existing in chain):
            chain.append(candidate)

    if not chain:
        raise DomainError(
            "APPROVER_UNAVAILABLE",
            "No manager or approval rule produced an eligible approver",
        )
    return chain


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
