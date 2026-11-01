from datetime import datetime, timezone
from typing import NoReturn

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.audit import record_event
from ..domain.errors import DomainError
from ..models import (
    ApprovalStep,
    Employee,
    ExpenseClaim,
    LeaveRequest,
)
from ..repositories.repository import Repository
from ..rules.leave import detect_approved_overlap
from .common import set_target_status


def _approval_failure(
    session: Session,
    error: DomainError,
    request_id: str,
    approver_id: str | None,
    entity_type: str = "ApprovalStep",
) -> NoReturn:
    record_event(
        session,
        entity_type=entity_type,
        entity_id=request_id,
        event_type="approval_validation_failed",
        actor_employee_id=(
            approver_id
            if approver_id is not None and session.get(Employee, approver_id)
            else None
        ),
        reason=error.message,
        exception_code=error.code,
        exception_details=error.details,
    )
    session.commit()
    raise error


def _apply_leave_balance_transition(
    session: Session, request: LeaveRequest, *, approved: bool
) -> None:
    balance = Repository(session).latest_leave_balance(
        request.employee_id, request.policy_id
    )
    if balance is None:
        raise DomainError("LEAVE_BALANCE_NOT_FOUND", "No leave balance exists for this policy")
    days = request.total_days
    before = {
        "accrued_balance": balance.accrued_balance,
        "used_balance": balance.used_balance,
        "pending_balance": balance.pending_balance,
    }
    if approved:
        balance.used_balance += days
    balance.pending_balance -= days
    record_event(
        session,
        entity_type="LeaveBalance",
        entity_id=balance.balance_id,
        event_type="leave_balance_deducted" if approved else "leave_balance_released",
        actor_employee_id=None,
        before_state=before,
        after_state={
            "accrued_balance": balance.accrued_balance,
            "used_balance": balance.used_balance,
            "pending_balance": balance.pending_balance,
        },
        reason=f"Final approval outcome for {request.request_id}",
    )


def decide_approval(
    session: Session,
    request_id: str,
    approver_id: str,
    *,
    decision: str,
    reason: str | None = None,
    comments: str | None = None,
):
    if decision not in {"Approved", "Rejected"}:
        _approval_failure(
            session,
            DomainError("INVALID_APPROVAL_DECISION", "Decision must be Approved or Rejected"),
            request_id,
            approver_id,
        )
    approver = session.get(Employee, approver_id)
    if approver is None or approver.status != "Active":
        _approval_failure(
            session,
            DomainError("APPROVER_NOT_FOUND", "Active approver does not exist", status_code=404),
            request_id,
            approver_id,
        )

    request = session.get(LeaveRequest, request_id)
    claim = session.get(ExpenseClaim, request_id) if request is None else None
    target = request or claim
    if target is None:
        _approval_failure(
            session,
            DomainError(
                "REQUEST_NOT_FOUND",
                "Leave request or expense claim does not exist",
                status_code=404,
            ),
            request_id,
            approver_id,
            "LeaveRequest",
        )
    if target.status != "Pending":
        _approval_failure(
            session,
            DomainError(
                "INVALID_LIFECYCLE_TRANSITION",
                f"Cannot decide a request in {target.status} state",
                status_code=409,
            ),
            request_id,
            approver_id,
            "LeaveRequest" if request is not None else "ExpenseClaim",
        )
    if decision == "Rejected" and (not reason or not reason.strip()):
        _approval_failure(
            session,
            DomainError("DECISION_REASON_REQUIRED", "A rejection reason is required"),
            request_id,
            approver_id,
        )
    if target.employee_id == approver_id:
        _approval_failure(
            session,
            DomainError(
                "SELF_APPROVAL",
                "Requester cannot approve their own request",
                status_code=409,
            ),
            request_id,
            approver_id,
        )

    steps = Repository(session).approval_steps(
        request.request_id if request is not None else None,
        claim.claim_id if claim is not None else None,
    )
    pending = next((step for step in steps if step.status == "Pending"), None)
    if pending is None:
        _approval_failure(
            session,
            DomainError(
                "NO_PENDING_APPROVAL",
                "Request has no pending approval step",
                status_code=409,
            ),
            request_id,
            approver_id,
        )
    if pending.approver_id != approver_id:
        _approval_failure(
            session,
            DomainError(
                "APPROVAL_OUT_OF_SEQUENCE",
                "Only the next assigned approver may decide this request",
                status_code=409,
                details={
                    "next_approver_id": pending.approver_id,
                    "sequence": pending.sequence,
                },
            ),
            request_id,
            approver_id,
        )
    if decision == "Approved" and request is not None and all(
        step.status == "Approved" or step is pending for step in steps
    ):
        session.scalar(
            select(Employee)
            .where(Employee.employee_id == request.employee_id)
            .with_for_update()
        )
        overlap = detect_approved_overlap(
            Repository(session).approved_leave_requests(request.employee_id),
            request.start_date,
            request.end_date,
        )
        if overlap is not None:
            _approval_failure(
                session,
                DomainError(
                    "OVERLAPPING_APPROVED_LEAVE",
                    "Leave dates overlap another approved request",
                    status_code=409,
                    details={"overlapping_request_id": overlap.request_id},
                ),
                request_id,
                approver_id,
            )

    now = datetime.now(timezone.utc)
    before_step = {"status": pending.status, "action_date": pending.action_date}
    pending.status = decision
    pending.action_date = now
    decision_reason = reason or f"Approved by {approver_id}"
    pending.decision_reason = decision_reason
    pending.comments = comments
    record_event(
        session,
        entity_type="ApprovalStep",
        entity_id=pending.step_id,
        event_type=f"approval_{decision.lower()}",
        actor_employee_id=approver_id,
        before_state=before_step,
        after_state={"status": decision, "action_date": now},
        reason=decision_reason,
    )

    if decision == "Rejected":
        for remaining in steps:
            if remaining.status != "Pending":
                continue
            before = {"status": remaining.status, "action_date": remaining.action_date}
            remaining.status = "Rejected"
            remaining.action_date = now
            remaining.decision_reason = f"Closed after rejection by {pending.step_id}"
            record_event(
                session,
                entity_type="ApprovalStep",
                entity_id=remaining.step_id,
                event_type="approval_closed_after_rejection",
                actor_employee_id=approver_id,
                before_state=before,
                after_state={"status": remaining.status, "action_date": now},
                reason=remaining.decision_reason,
            )
        if request is not None:
            _apply_leave_balance_transition(session, request, approved=False)
        before_target = {"status": target.status, "decision_reason": target.decision_reason}
        set_target_status(target, "Rejected", reason)
        record_event(
            session,
            entity_type="LeaveRequest" if request is not None else "ExpenseClaim",
            entity_id=request_id,
            event_type="request_rejected",
            actor_employee_id=approver_id,
            before_state=before_target,
            after_state={"status": target.status, "decision_reason": target.decision_reason},
            reason=reason,
        )
    elif all(step.status == "Approved" for step in steps):
        if request is not None:
            _apply_leave_balance_transition(session, request, approved=True)
        before_target = {"status": target.status, "decision_reason": target.decision_reason}
        set_target_status(target, "Approved", decision_reason)
        record_event(
            session,
            entity_type="LeaveRequest" if request is not None else "ExpenseClaim",
            entity_id=request_id,
            event_type="request_approved",
            actor_employee_id=approver_id,
            before_state=before_target,
            after_state={"status": target.status, "decision_reason": target.decision_reason},
            reason=decision_reason,
        )

    session.commit()
    return target
