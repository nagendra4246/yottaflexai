from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import (
    ApprovalStep,
    AuditEvent,
    CostCenter,
    Employee,
    ExpenseClaim,
    ExpenseLine,
    ExpensePolicy,
    LeavePolicy,
    LeaveRequest,
    Reimbursement,
)


def add_employee(session, employee_id="EMP-000001"):
    employee = Employee(
        employee_id=employee_id,
        name="Synthetic Employee",
        email=f"{employee_id.lower()}@example.test",
        department="Operations",
        country="USA",
        hire_date=date(2020, 1, 1),
    )
    session.add(employee)
    session.flush()
    return employee


def test_relationships_and_referential_integrity(database_session):
    employee = add_employee(database_session)
    policy = LeavePolicy(
        policy_id="LP-001",
        policy_name="Annual",
        annual_entitlement=20,
        carry_over_limit=5,
        accrual_rate=Decimal("1.667"),
        country_code="USA",
        effective_from=date(2026, 1, 1),
    )
    database_session.add(policy)
    database_session.flush()
    request = LeaveRequest(
        request_id="LVE-2026-000001",
        employee_id=employee.employee_id,
        policy_id=policy.policy_id,
        start_date=date(2026, 5, 4),
        end_date=date(2026, 5, 5),
        total_days=Decimal("2"),
        leave_type="Annual",
        status="Pending",
    )
    database_session.add(request)
    database_session.flush()
    step = ApprovalStep(
        step_id="APR-LVE-2026-000001-01",
        leave_request_id=request.request_id,
        approver_id=employee.employee_id,
        sequence=1,
        status="Pending",
    )
    database_session.add(step)
    database_session.commit()

    assert request.employee is employee
    assert request.policy is policy
    assert step.leave_request is request
    assert step.request_id == request.request_id

    database_session.add(
        LeaveRequest(
            request_id="LVE-2026-000002",
            employee_id="EMP-MISSING",
            policy_id=policy.policy_id,
            start_date=date(2026, 5, 4),
            end_date=date(2026, 5, 5),
            total_days=Decimal("2"),
            leave_type="Annual",
        )
    )
    with pytest.raises(IntegrityError):
        database_session.commit()
    database_session.rollback()


def test_expense_relationships_and_duplicate_reimbursement_are_constrained(
    database_session,
):
    employee = add_employee(database_session)
    center = CostCenter(
        cost_center_id="CC-001",
        name="Operations",
        budget=Decimal("10000.00"),
        department="Operations",
    )
    policy = ExpensePolicy(
        policy_id="EP-001",
        category="Travel",
        max_amount=Decimal("500.00"),
        requires_receipt=True,
        country_code="GLOBAL",
        effective_from=date(2026, 1, 1),
    )
    claim = ExpenseClaim(
        claim_id="EXP-2026-000001",
        employee_id=employee.employee_id,
        cost_center_id=center.cost_center_id,
        total_amount=Decimal("50.00"),
        currency="USD",
        submission_date=date(2026, 5, 4),
    )
    database_session.add_all([center, policy, claim])
    database_session.flush()
    database_session.add(
        ExpenseLine(
            line_id="EXPL-EXP-2026-000001-01",
            claim_id=claim.claim_id,
            policy_id=policy.policy_id,
            amount=Decimal("50.00"),
            description="Taxi",
            expense_date=date(2026, 5, 3),
        )
    )
    database_session.add(
        Reimbursement(
            reimbursement_id="RMB-2026-000001",
            claim_id=claim.claim_id,
            amount=Decimal("50.00"),
            payment_date=date(2026, 5, 10),
            transaction_ref="TX-001",
        )
    )
    database_session.commit()
    assert claim.lines[0].policy is policy
    assert claim.reimbursement.claim_id == claim.claim_id

    database_session.add(
        Reimbursement(
            reimbursement_id="RMB-2026-000002",
            claim_id=claim.claim_id,
            amount=Decimal("10.00"),
            payment_date=date(2026, 5, 11),
            transaction_ref="TX-002",
        )
    )
    with pytest.raises(IntegrityError):
        database_session.commit()
    database_session.rollback()


def test_check_constraints_and_approval_target_integrity(database_session):
    employee = add_employee(database_session)
    database_session.add(
        Employee(
            employee_id="EMP-000002",
            name="Bad status",
            email="bad-status@example.test",
            department="Operations",
            country="USA",
            hire_date=date(2020, 1, 1),
            status="Unknown",
        )
    )
    with pytest.raises(IntegrityError):
        database_session.commit()
    database_session.rollback()

    database_session.add(
        ApprovalStep(
            step_id="APR-INVALID-01",
            approver_id=employee.employee_id,
            sequence=1,
            status="Pending",
        )
    )
    with pytest.raises(IntegrityError):
        database_session.commit()
    database_session.rollback()


def test_audit_exception_fields_and_relationship(database_session):
    employee = add_employee(database_session)
    event = AuditEvent(
        entity_type="LeaveRequest",
        entity_id="LVE-2026-000001",
        event_type="request_rejected",
        actor_employee_id=employee.employee_id,
        before_state={"status": "Pending"},
        after_state={"status": "Rejected"},
        reason="Insufficient balance",
        is_exception=True,
        exception_code="INSUFFICIENT_LEAVE_BALANCE",
        exception_details={"available": -1},
    )
    database_session.add(event)
    database_session.commit()
    assert event.actor is employee
    assert event.event_id
