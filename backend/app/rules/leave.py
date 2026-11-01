from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from ..domain.errors import DomainError
from ..models import Employee, LeavePolicy, LeaveRequest
from ..repositories.repository import Repository


def business_days(start: date, end: date, holidays: set[date] | None = None) -> int:
    if end < start:
        raise DomainError("INVALID_DATE_RANGE", "end_date must not precede start_date")
    holidays = holidays or set()
    day_count = 0
    current = start
    while current <= end:
        if current.weekday() < 5 and current not in holidays:
            day_count += 1
        current += timedelta(days=1)
    return day_count


def validate_employment_period(employee: Employee, start: date, end: date) -> None:
    if start < employee.hire_date or (
        employee.termination_date is not None and end > employee.termination_date
    ):
        raise DomainError(
            "OUTSIDE_EMPLOYMENT_PERIOD",
            "Request dates must fall within the employee's employment period",
            details={"hire_date": employee.hire_date, "termination_date": employee.termination_date},
        )
    if employee.status != "Active":
        raise DomainError("EMPLOYEE_NOT_ACTIVE", "Only active employees may submit requests")


def applicable_leave_policy(
    session: Session,
    employee: Employee,
    start: date,
    end: date,
    policy_id: str | None,
) -> LeavePolicy:
    repository = Repository(session)
    policy = repository.get_leave_policy(policy_id) if policy_id else None
    if policy_id is not None and policy is None:
        raise DomainError("LEAVE_POLICY_NOT_FOUND", "Leave policy does not exist", status_code=404)
    if policy is None:
        candidates = [
            item
            for item in session.query(LeavePolicy).filter(
                LeavePolicy.country_code == employee.country
            )
            if item.effective_from <= start
            and (item.effective_to is None or item.effective_to >= end)
        ]
        if len(candidates) != 1:
            raise DomainError(
                "LEAVE_POLICY_NOT_APPLICABLE",
                "Exactly one active leave policy must apply to the employee and requested dates",
                details={"candidate_count": len(candidates), "country": employee.country},
            )
        policy = candidates[0]
    if (
        policy.country_code != employee.country
        or policy.effective_from > start
        or (policy.effective_to is not None and policy.effective_to < end)
    ):
        code = (
            "LEAVE_POLICY_EXPIRED"
            if policy.effective_to is not None and policy.effective_to < end
            else "LEAVE_POLICY_NOT_APPLICABLE"
        )
        raise DomainError(code, "Leave policy does not cover the employee's country and dates")
    return policy


def calculated_available_balance(
    accrued: Decimal, used: Decimal, pending: Decimal
) -> Decimal:
    return accrued - used - pending


def detect_approved_overlap(
    requests: list[LeaveRequest], start: date, end: date
) -> LeaveRequest | None:
    return next(
        (
            request
            for request in requests
            if request.start_date <= end and request.end_date >= start
        ),
        None,
    )
