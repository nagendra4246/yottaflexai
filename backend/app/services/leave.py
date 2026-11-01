from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.audit import record_event
from ..domain.errors import DomainError
from ..models import ApprovalStep, Employee, LeaveBalance, LeaveRequest
from ..repositories.repository import Repository
from ..rules.approval import approval_chain
from ..rules.leave import (
    applicable_leave_policy,
    business_days,
    calculated_available_balance,
    detect_approved_overlap,
    validate_employment_period,
)
from ..schemas.requests import LeaveRequestCreate
from .common import fail_with_audit, next_id


def submit_leave_request(session: Session, data: LeaveRequestCreate) -> LeaveRequest:
    request_id = data.request_id or next_id(
        session, LeaveRequest, "request_id", f"LVE-{data.start_date.year}-"
    )
    employee = session.get(Employee, data.employee_id)
    try:
        if employee is None:
            raise DomainError("EMPLOYEE_NOT_FOUND", "Employee does not exist", status_code=404)
        validate_employment_period(employee, data.start_date, data.end_date)
        policy = applicable_leave_policy(
            session, employee, data.start_date, data.end_date, data.policy_id
        )
        if session.get(LeaveRequest, request_id) is not None:
            raise DomainError("LEAVE_REQUEST_EXISTS", "Leave request ID already exists", status_code=409)

        holidays = Repository(session).holidays(
            employee.country, data.start_date, data.end_date
        )
        requested_days = business_days(data.start_date, data.end_date, holidays)
        if requested_days == 0:
            raise DomainError(
                "NO_BUSINESS_DAYS",
                "Leave request contains no business days after weekends and holidays are excluded",
            )
        balance = Repository(session).latest_leave_balance(employee.employee_id, policy.policy_id)
        if balance is None:
            raise DomainError("LEAVE_BALANCE_NOT_FOUND", "No leave balance exists for this policy")
        available = calculated_available_balance(
            Decimal(balance.accrued_balance),
            Decimal(balance.used_balance),
            Decimal(balance.pending_balance),
        )
        if available < requested_days:
            raise DomainError(
                "INSUFFICIENT_LEAVE_BALANCE",
                "Available leave balance is insufficient",
                details={"available": available, "requested": requested_days},
            )
        overlap = detect_approved_overlap(
            Repository(session).approved_leave_requests(employee.employee_id),
            data.start_date,
            data.end_date,
        )
        if overlap is not None:
            raise DomainError(
                "OVERLAPPING_APPROVED_LEAVE",
                "Leave dates overlap an already approved request",
                status_code=409,
                details={"overlapping_request_id": overlap.request_id},
            )
        chain = approval_chain(
            session,
            employee=employee,
            entity_type="Leave",
            amount=Decimal(requested_days),
            country=employee.country,
            categories={data.leave_type},
            effective_date=data.start_date,
        )
    except DomainError as error:
        fail_with_audit(
            session,
            error,
            entity_type="LeaveRequest",
            entity_id=request_id,
            actor_employee_id=data.employee_id,
        )

    request = LeaveRequest(
        request_id=request_id,
        employee_id=employee.employee_id,
        policy_id=policy.policy_id,
        start_date=data.start_date,
        end_date=data.end_date,
        total_days=Decimal(requested_days),
        leave_type=data.leave_type,
        status="Pending",
    )
    balance.pending_balance = Decimal(balance.pending_balance) + Decimal(requested_days)
    session.add(request)
    session.flush()
    for sequence, approver in enumerate(chain, start=1):
        session.add(
            ApprovalStep(
                step_id=f"APR-{request.request_id}-{sequence:02d}",
                leave_request_id=request.request_id,
                approver_id=approver.employee_id,
                sequence=sequence,
                status="Pending",
            )
        )
    record_event(
        session,
        entity_type="LeaveRequest",
        entity_id=request.request_id,
        event_type="leave_submitted",
        actor_employee_id=employee.employee_id,
        after_state={
            "status": request.status,
            "total_days": request.total_days,
            "policy_id": request.policy_id,
        },
    )
    record_event(
        session,
        entity_type="LeaveBalance",
        entity_id=balance.balance_id,
        event_type="leave_balance_reserved",
        actor_employee_id=employee.employee_id,
        before_state={"pending_balance": balance.pending_balance - Decimal(requested_days)},
        after_state={"pending_balance": balance.pending_balance},
        reason=f"Reserved {requested_days} days for {request.request_id}",
    )
    session.commit()
    return request


def available_leave_balance(session: Session, employee_id: str, policy_id: str) -> Decimal:
    balance = Repository(session).latest_leave_balance(employee_id, policy_id)
    if balance is None:
        raise DomainError("LEAVE_BALANCE_NOT_FOUND", "No leave balance exists for this policy")
    return calculated_available_balance(
        Decimal(balance.accrued_balance),
        Decimal(balance.used_balance),
        Decimal(balance.pending_balance),
    )


def cancel_leave_request(
    session: Session, request_id: str, employee_id: str, reason: str
) -> LeaveRequest:
    request = session.get(LeaveRequest, request_id)
    try:
        if request is None:
            raise DomainError(
                "LEAVE_REQUEST_NOT_FOUND",
                "Leave request does not exist",
                status_code=404,
            )
        if request.employee_id != employee_id:
            raise DomainError(
                "NOT_REQUEST_OWNER",
                "Only the requester may cancel this leave request",
                status_code=403,
            )
        if request.status != "Pending":
            raise DomainError(
                "INVALID_LIFECYCLE_TRANSITION",
                "Only pending leave requests may be cancelled",
                status_code=409,
            )
        if not reason.strip():
            raise DomainError("DECISION_REASON_REQUIRED", "Cancellation reason is required")
        balance = Repository(session).latest_leave_balance(
            request.employee_id, request.policy_id
        )
        if balance is None:
            raise DomainError(
                "LEAVE_BALANCE_NOT_FOUND",
                "No leave balance exists for this policy",
            )
    except DomainError as error:
        fail_with_audit(
            session,
            error,
            entity_type="LeaveRequest",
            entity_id=request_id,
            actor_employee_id=employee_id,
        )

    now = datetime.now(timezone.utc)
    steps = Repository(session).approval_steps(request.request_id, None)
    for step in steps:
        if step.status != "Pending":
            continue
        before = {"status": step.status, "action_date": step.action_date}
        step.status = "Rejected"
        step.action_date = now
        step.decision_reason = f"Closed after cancellation: {reason.strip()}"
        record_event(
            session,
            entity_type="ApprovalStep",
            entity_id=step.step_id,
            event_type="approval_closed_after_cancellation",
            actor_employee_id=employee_id,
            before_state=before,
            after_state={"status": step.status, "action_date": now},
            reason=step.decision_reason,
        )
    before_balance = {
        "pending_balance": balance.pending_balance,
        "used_balance": balance.used_balance,
    }
    balance.pending_balance -= request.total_days
    before_request = {"status": request.status, "decision_reason": request.decision_reason}
    request.status = "Cancelled"
    request.decision_reason = reason.strip()
    request.decided_at = now
    record_event(
        session,
        entity_type="LeaveBalance",
        entity_id=balance.balance_id,
        event_type="leave_balance_released",
        actor_employee_id=employee_id,
        before_state=before_balance,
        after_state={
            "pending_balance": balance.pending_balance,
            "used_balance": balance.used_balance,
        },
        reason=f"Cancellation of {request.request_id}",
    )
    record_event(
        session,
        entity_type="LeaveRequest",
        entity_id=request.request_id,
        event_type="leave_cancelled",
        actor_employee_id=employee_id,
        before_state=before_request,
        after_state={"status": request.status, "decision_reason": request.decision_reason},
        reason=request.decision_reason,
    )
    session.commit()
    return request
