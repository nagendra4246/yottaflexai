from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..domain.audit import record_event
from ..domain.constants import EMPLOYEE_STATUSES, SUPPORTED_COUNTRIES
from ..domain.errors import DomainError
from ..models import Employee
from ..schemas.requests import EmployeeCreate
from .common import fail_with_audit


def validate_employee_data(data: EmployeeCreate) -> None:
    if data.country not in SUPPORTED_COUNTRIES:
        raise DomainError("INVALID_COUNTRY", "Employee country is not supported")
    if data.status not in EMPLOYEE_STATUSES:
        raise DomainError("INVALID_EMPLOYEE_STATUS", "Employee status is invalid")
    if data.termination_date and data.termination_date < data.hire_date:
        raise DomainError("INVALID_EMPLOYMENT_DATES", "Termination date precedes hire date")
    if data.manager_id == data.employee_id:
        raise DomainError("SELF_MANAGER", "Employee cannot be their own manager")


def validate_manager_chain(
    session: Session, employee_id: str, manager_id: str | None
) -> None:
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            select(func.pg_advisory_xact_lock(func.hashtext("yottaflex:employee-hierarchy")))
        )
    if manager_id is None:
        return
    if manager_id == employee_id:
        raise DomainError("SELF_MANAGER", "Employee cannot be their own manager")
    manager = session.get(Employee, manager_id)
    if manager is None:
        raise DomainError("MANAGER_NOT_FOUND", "Manager does not exist", status_code=404)
    seen = {employee_id}
    current: Employee | None = manager
    while current is not None:
        if current.employee_id in seen:
            raise DomainError("MANAGER_CYCLE", "Manager assignment would create a hierarchy cycle")
        seen.add(current.employee_id)
        current = session.get(Employee, current.manager_id) if current.manager_id else None


def create_employee(session: Session, data: EmployeeCreate) -> Employee:
    try:
        validate_employee_data(data)
        validate_manager_chain(session, data.employee_id, data.manager_id)
        if session.get(Employee, data.employee_id) is not None:
            raise DomainError("EMPLOYEE_ID_EXISTS", "Employee ID already exists", status_code=409)
        duplicate_email = session.scalar(
            select(Employee.employee_id).where(Employee.email == data.email)
        )
        if duplicate_email is not None:
            raise DomainError("EMPLOYEE_EMAIL_EXISTS", "Employee email already exists", status_code=409)

        employee = Employee(**data.model_dump())
        session.add(employee)
        session.flush()
        record_event(
            session,
            entity_type="Employee",
            entity_id=employee.employee_id,
            event_type="employee_created",
            actor_employee_id=employee.employee_id,
            after_state={
                "employee_id": employee.employee_id,
                "manager_id": employee.manager_id,
                "status": employee.status,
            },
        )
        session.commit()
        return employee
    except DomainError as error:
        session.rollback()
        fail_with_audit(
            session,
            error,
            entity_type="Employee",
            entity_id=data.employee_id,
            actor_employee_id=None,
        )


def change_manager(
    session: Session, employee_id: str, manager_id: str | None, actor_employee_id: str
) -> Employee:
    if session.get(Employee, actor_employee_id) is None:
        error = DomainError("ACTOR_NOT_FOUND", "Actor does not exist", status_code=404)
        fail_with_audit(
            session,
            error,
            entity_type="Employee",
            entity_id=employee_id,
            actor_employee_id=None,
        )
    employee = session.get(Employee, employee_id)
    if employee is None:
        error = DomainError("EMPLOYEE_NOT_FOUND", "Employee does not exist", status_code=404)
        fail_with_audit(
            session,
            error,
            entity_type="Employee",
            entity_id=employee_id,
            actor_employee_id=actor_employee_id,
        )
    try:
        validate_manager_chain(session, employee_id, manager_id)
    except DomainError as error:
        fail_with_audit(
            session,
            error,
            entity_type="Employee",
            entity_id=employee_id,
            actor_employee_id=actor_employee_id,
        )
    before = {"manager_id": employee.manager_id}
    employee.manager_id = manager_id
    record_event(
        session,
        entity_type="Employee",
        entity_id=employee_id,
        event_type="manager_changed",
        actor_employee_id=actor_employee_id,
        before_state=before,
        after_state={"manager_id": manager_id},
    )
    session.commit()
    return employee
