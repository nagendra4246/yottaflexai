from datetime import datetime, timezone
from typing import NoReturn

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from ..domain.audit import record_event
from ..domain.errors import DomainError
from ..models import Employee, ExpenseClaim, LeaveRequest
from ..repositories.repository import Repository


def fail_with_audit(
    session: Session,
    error: DomainError,
    *,
    entity_type: str,
    entity_id: str,
    actor_employee_id: str | None,
) -> NoReturn:
    if actor_employee_id and session.get(Employee, actor_employee_id) is None:
        actor_employee_id = None
    record_event(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        event_type="validation_failed",
        actor_employee_id=actor_employee_id,
        reason=error.message,
        exception_code=error.code,
        exception_details=error.details,
    )
    session.commit()
    raise error


def next_id(session: Session, model, key: str, prefix: str) -> str:
    return Repository(session).next_id(model, key, prefix)


def constraint_name(error: IntegrityError) -> str:
    diagnostic = getattr(error.orig, "diag", None)
    return getattr(diagnostic, "constraint_name", None) or str(error.orig)


def set_target_status(target: LeaveRequest | ExpenseClaim, status: str, reason: str | None):
    target.status = status
    target.decision_reason = reason
    target.decided_at = datetime.now(timezone.utc)
