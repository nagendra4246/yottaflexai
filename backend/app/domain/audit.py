from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from ..models import AuditEvent


def json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def record_event(
    session: Session,
    *,
    entity_type: str,
    entity_id: str,
    event_type: str,
    actor_employee_id: str | None = None,
    before_state: dict | None = None,
    after_state: dict | None = None,
    reason: str | None = None,
    exception_code: str | None = None,
    exception_details: dict | None = None,
) -> AuditEvent:
    event = AuditEvent(
        event_id=str(uuid4()),
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        actor_employee_id=actor_employee_id,
        before_state=json_value(before_state),
        after_state=json_value(after_state),
        reason=reason,
        is_exception=exception_code is not None,
        exception_code=exception_code,
        exception_details=json_value(exception_details),
    )
    session.add(event)
    return event
