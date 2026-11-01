from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.domain.errors import DomainError
from app.models import (
    ApprovalRule,
    ApprovalStep,
    AuditEvent,
    CostCenter,
    Employee,
    ExpenseClaim,
    ExpenseLine,
    ExpensePolicy,
    LeaveBalance,
    LeavePolicy,
    LeaveRequest,
    PublicHoliday,
    Reimbursement,
)
from app.schemas.requests import (
    EmployeeCreate,
    ExpenseClaimCreate,
    ExpenseLineCreate,
    LeaveRequestCreate,
    ReimbursementCreate,
)
from app.rules.approval import approval_chain
from app.rules.leave import business_days
from app.services.approvals import decide_approval
from app.services.employees import change_manager, create_employee
from app.services.expenses import submit_expense_claim
from app.services.leave import (
    available_leave_balance,
    cancel_leave_request,
    submit_leave_request,
)
from app.services.reimbursements import create_reimbursement, process_reimbursement

TODAY = date(2026, 10, 31)


def employee(session, employee_id, *, manager_id=None, role=None, country="USA"):
    existing = session.get(Employee, employee_id)
    if existing is not None:
        existing.approval_role = role or existing.approval_role
        return existing
    if manager_id is not None and session.get(Employee, manager_id) is None:
        employee(session, manager_id)
    value = Employee(
        employee_id=employee_id,
        name=employee_id,
        email=f"{employee_id.lower()}@example.test",
        manager_id=manager_id,
        department="Operations",
        country=country,
        hire_date=date(2020, 1, 1),
        status="Active",
        approval_role=role,
    )
    session.add(value)
    session.flush()
    return value


def leave_policy(session, policy_id="LP-001", *, country="USA", end=None):
    value = LeavePolicy(
        policy_id=policy_id,
        policy_name="Annual",
        annual_entitlement=20,
        carry_over_limit=5,
        accrual_rate=Decimal("1.667"),
        country_code=country,
        effective_from=date(2020, 1, 1),
        effective_to=end,
    )
    session.add(value)
    session.flush()
    return value


def leave_balance(
    session,
    employee_id="EMP-000001",
    policy_id="LP-001",
    *,
    accrued="20",
    used="0",
    pending="0",
):
    value = LeaveBalance(
        balance_id=f"LB-{employee_id[-6:]}",
        employee_id=employee_id,
        policy_id=policy_id,
        accrued_balance=Decimal(accrued),
        used_balance=Decimal(used),
        pending_balance=Decimal(pending),
        effective_date=TODAY,
    )
    session.add(value)
    session.flush()
    return value


def expense_policy(session, policy_id="EP-001", *, maximum="2000", end=None):
    value = ExpensePolicy(
        policy_id=policy_id,
        category="Travel",
        max_amount=Decimal(maximum),
        requires_receipt=True,
        country_code="GLOBAL",
        effective_from=date(2020, 1, 1),
        effective_to=end,
    )
    session.add(value)
    session.flush()
    return value


def cost_center(session, cost_center_id="CC-001", *, budget="10000"):
    value = CostCenter(
        cost_center_id=cost_center_id,
        name="Operations",
        budget=Decimal(budget),
        department="Operations",
    )
    session.add(value)
    session.flush()
    return value


def request_leave(
    employee_id="EMP-000001",
    *,
    start=date(2026, 11, 2),
    end=date(2026, 11, 3),
    policy_id="LP-001",
):
    return LeaveRequestCreate(
        employee_id=employee_id,
        policy_id=policy_id,
        start_date=start,
        end_date=end,
        leave_type="Annual",
    )


def request_expense(
    *,
    employee_id="EMP-000001",
    cost_center_id="CC-001",
    amount="100",
    expense_date=TODAY,
    submission_date=TODAY,
    receipt_hash="hash-1",
    policy_id="EP-001",
):
    return ExpenseClaimCreate(
        employee_id=employee_id,
        cost_center_id=cost_center_id,
        currency="usd",
        submission_date=submission_date,
        lines=[
            ExpenseLineCreate(
                policy_id=policy_id,
                amount=Decimal(amount),
                description="Taxi",
                expense_date=expense_date,
                receipt_hash=receipt_hash,
                receipt_url=f"https://example.test/{receipt_hash}" if receipt_hash else None,
            )
        ],
    )


def rule(session, rule_id, *, threshold, role, category=None):
    value = ApprovalRule(
        rule_id=rule_id,
        entity_type="Expense",
        threshold_amount=Decimal(threshold) if threshold is not None else None,
        country_code=None,
        category=category,
        approval_level=1 if role == "Manager" else 2,
        required_role=role,
        effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    session.add(value)
    session.flush()
    return value


def test_employee_manager_country_and_hierarchy_validation(database_session):
    root = employee(database_session, "EMP-000001")
    child = employee(database_session, "EMP-000002", manager_id=root.employee_id)
    grandchild = employee(database_session, "EMP-000003", manager_id=child.employee_id)
    with pytest.raises(DomainError, match="cycle"):
        change_manager(database_session, root.employee_id, grandchild.employee_id, root.employee_id)
    with pytest.raises(DomainError, match="does not exist"):
        change_manager(database_session, child.employee_id, "EMP-MISSING", child.employee_id)

    with pytest.raises(ValueError):
        EmployeeCreate(
            employee_id="EMP-000004",
            name="Bad",
            email="bad@example.test",
            manager_id="EMP-000004",
            department="Ops",
            country="XYZ",
            hire_date=TODAY,
        )
    assert root.manager_id is None


def test_employee_self_manager_and_invalid_employment_dates_are_rejected(database_session):
    base_data = {
        "employee_id": "EMP-000004",
        "name": "Bad",
        "email": "bad@example.test",
        "department": "Ops",
        "country": "USA",
        "hire_date": TODAY,
    }
    self_managed = EmployeeCreate(**base_data, manager_id="EMP-000004")
    with pytest.raises(DomainError) as error:
        create_employee(database_session, self_managed)
    assert error.value.code == "SELF_MANAGER"
    with pytest.raises(ValueError):
        EmployeeCreate(
            **base_data,
            termination_date=date(2026, 10, 30),
        )


def test_leave_policy_country_applicability_is_enforced(database_session):
    employee(database_session, "EMP-000001", manager_id="EMP-000002")
    employee(database_session, "EMP-000002")
    leave_policy(database_session, country="GER")
    leave_balance(database_session)
    with pytest.raises(DomainError) as error:
        submit_leave_request(database_session, request_leave())
    assert error.value.code == "LEAVE_POLICY_NOT_APPLICABLE"


def test_negative_leave_balance_is_rejected_and_audited(database_session):
    employee(database_session, "EMP-000001", manager_id="EMP-000002")
    employee(database_session, "EMP-000002")
    leave_policy(database_session)
    leave_balance(database_session, accrued="-2")

    with pytest.raises(DomainError) as error:
        submit_leave_request(database_session, request_leave())

    assert error.value.code == "INSUFFICIENT_LEAVE_BALANCE"
    assert available_leave_balance(database_session, "EMP-000001", "LP-001") == Decimal("-2")
    assert database_session.scalar(
        select(AuditEvent).where(AuditEvent.exception_code == error.value.code)
    )


def test_approved_leave_overlap_is_rejected(database_session):
    employee(database_session, "EMP-000001", manager_id="EMP-000002")
    employee(database_session, "EMP-000002")
    policy = leave_policy(database_session)
    leave_balance(database_session)
    database_session.add(
        LeaveRequest(
            request_id="LVE-2026-000099",
            employee_id="EMP-000001",
            policy_id=policy.policy_id,
            start_date=date(2026, 11, 2),
            end_date=date(2026, 11, 4),
            total_days=Decimal("3"),
            leave_type="Annual",
            status="Approved",
        )
    )
    database_session.commit()

    with pytest.raises(DomainError) as error:
        submit_leave_request(database_session, request_leave())
    assert error.value.code == "OVERLAPPING_APPROVED_LEAVE"


def test_final_approval_rechecks_overlapping_approved_leave(database_session):
    employee(database_session, "EMP-000001", manager_id="EMP-000002")
    employee(database_session, "EMP-000002")
    policy = leave_policy(database_session)
    leave_balance(database_session)
    request = submit_leave_request(database_session, request_leave())
    database_session.add(
        LeaveRequest(
            request_id="LVE-2026-000099",
            employee_id="EMP-000001",
            policy_id=policy.policy_id,
            start_date=date(2026, 11, 2),
            end_date=date(2026, 11, 3),
            total_days=Decimal("2"),
            leave_type="Annual",
            status="Approved",
        )
    )
    database_session.commit()
    with pytest.raises(DomainError) as error:
        decide_approval(
            database_session, request.request_id, "EMP-000002", decision="Approved"
        )
    assert error.value.code == "OVERLAPPING_APPROVED_LEAVE"
    assert request.status == "Pending"


def test_weekend_and_public_holiday_leave_calculation(database_session):
    saturday = date(2026, 11, 7)
    sunday = date(2026, 11, 8)
    assert business_days(saturday, sunday) == 0
    assert business_days(date(2026, 11, 2), date(2026, 11, 6), {date(2026, 11, 4)}) == 4

    employee(database_session, "EMP-000001", manager_id="EMP-000002")
    employee(database_session, "EMP-000002")
    leave_policy(database_session)
    leave_balance(database_session)
    database_session.add(
        PublicHoliday(
            holiday_id="HOL-1",
            country_code="USA",
            holiday_date=date(2026, 11, 4),
            name="Synthetic holiday",
        )
    )
    database_session.commit()
    request = submit_leave_request(
        database_session,
        request_leave(start=date(2026, 11, 2), end=date(2026, 11, 6)),
    )
    assert request.total_days == Decimal("4")


def test_weekend_only_leave_is_rejected(database_session):
    employee(database_session, "EMP-000001", manager_id="EMP-000002")
    employee(database_session, "EMP-000002")
    leave_policy(database_session)
    leave_balance(database_session)

    with pytest.raises(DomainError) as error:
        submit_leave_request(
            database_session,
            request_leave(start=date(2026, 11, 7), end=date(2026, 11, 8)),
        )
    assert error.value.code == "NO_BUSINESS_DAYS"


def test_leave_balance_deducted_only_on_final_approval(database_session):
    employee(database_session, "EMP-000001", manager_id="EMP-000002")
    employee(database_session, "EMP-000002", role="Manager")
    employee(database_session, "EMP-000003", role="Finance")
    leave_policy(database_session)
    balance = leave_balance(database_session)
    database_session.add_all(
        [
            ApprovalRule(
                rule_id="AR-LEAVE-MANAGER",
                entity_type="Leave",
                threshold_amount=None,
                country_code=None,
                category=None,
                approval_level=1,
                required_role="Manager",
                effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
            ),
            ApprovalRule(
                rule_id="AR-LEAVE-FINANCE",
                entity_type="Leave",
                threshold_amount=Decimal("2"),
                country_code=None,
                category=None,
                approval_level=2,
                required_role="Finance",
                effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
            ),
        ]
    )
    database_session.commit()

    request = submit_leave_request(database_session, request_leave())
    assert balance.pending_balance == Decimal("2.00")
    decide_approval(
        database_session, request.request_id, "EMP-000002", decision="Approved"
    )
    assert balance.pending_balance == Decimal("2.00")
    assert balance.used_balance == Decimal("0.00")
    decide_approval(
        database_session, request.request_id, "EMP-000003", decision="Approved"
    )
    assert request.status == "Approved"
    assert balance.pending_balance == Decimal("0.00")
    assert balance.used_balance == Decimal("2.00")


def test_leave_cancellation_releases_reserved_balance_and_closes_steps(database_session):
    employee(database_session, "EMP-000001", manager_id="EMP-000002")
    employee(database_session, "EMP-000002")
    leave_policy(database_session)
    balance = leave_balance(database_session)
    request = submit_leave_request(database_session, request_leave())
    assert balance.pending_balance == Decimal("2.00")

    cancelled = cancel_leave_request(
        database_session, request.request_id, "EMP-000001", "Plans changed"
    )
    assert cancelled.status == "Cancelled"
    assert balance.pending_balance == Decimal("0.00")
    assert database_session.scalar(
        select(ApprovalStep).where(
            ApprovalStep.leave_request_id == request.request_id
        )
    ).status == "Rejected"


def test_expense_outside_employment_period_is_rejected(database_session):
    employee(database_session, "EMP-000001", manager_id="EMP-000002")
    employee(database_session, "EMP-000002")
    cost_center(database_session)
    expense_policy(database_session)

    with pytest.raises(DomainError) as error:
        submit_expense_claim(
            database_session,
            request_expense(expense_date=date(2019, 12, 31)),
        )
    assert error.value.code == "OUTSIDE_EMPLOYMENT_PERIOD"


def test_missing_cost_center_is_rejected_and_audited(database_session):
    employee(database_session, "EMP-000001", manager_id="EMP-000002")
    employee(database_session, "EMP-000002")
    expense_policy(database_session)

    with pytest.raises(DomainError) as error:
        submit_expense_claim(
            database_session,
            request_expense(cost_center_id="CC-MISSING"),
        )
    assert error.value.code == "COST_CENTER_NOT_FOUND"
    assert database_session.scalar(
        select(AuditEvent).where(AuditEvent.exception_code == error.value.code)
    )


def test_policy_limit_and_cost_center_budget_are_enforced(database_session):
    employee(database_session, "EMP-000001", manager_id="EMP-000002")
    employee(database_session, "EMP-000002")
    cost_center(database_session, budget="150")
    expense_policy(database_session, maximum="100")
    with pytest.raises(DomainError) as policy_error:
        submit_expense_claim(
            database_session,
            request_expense(amount="101", receipt_hash="over-limit"),
        )
    assert policy_error.value.code == "POLICY_LIMIT_EXCEEDED"

    approved = ExpenseClaim(
        claim_id="EXP-2026-000050",
        employee_id="EMP-000001",
        cost_center_id="CC-001",
        total_amount=Decimal("100"),
        currency="USD",
        status="Approved",
        submission_date=TODAY,
    )
    database_session.add(approved)
    database_session.commit()
    with pytest.raises(DomainError) as budget_error:
        submit_expense_claim(
            database_session,
            request_expense(amount="60", receipt_hash="over-budget"),
        )
    assert budget_error.value.code == "BUDGET_EXCEEDED"


def test_receipt_required_policy_rejects_missing_metadata(database_session):
    employee(database_session, "EMP-000001", manager_id="EMP-000002")
    employee(database_session, "EMP-000002")
    cost_center(database_session)
    expense_policy(database_session)
    invalid = request_expense(receipt_hash=None)
    invalid.lines[0].receipt_url = None

    with pytest.raises(DomainError) as error:
        submit_expense_claim(database_session, invalid)
    assert error.value.code == "RECEIPT_REQUIRED"


def test_expired_expense_policy_is_rejected(database_session):
    employee(database_session, "EMP-000001", manager_id="EMP-000002")
    employee(database_session, "EMP-000002")
    cost_center(database_session)
    expense_policy(database_session, end=date(2026, 10, 30))

    with pytest.raises(DomainError) as error:
        submit_expense_claim(database_session, request_expense())
    assert error.value.code == "EXPENSE_POLICY_EXPIRED"


def test_duplicate_receipt_hash_is_rejected(database_session):
    employee(database_session, "EMP-000001", manager_id="EMP-000002")
    employee(database_session, "EMP-000002")
    cost_center(database_session)
    expense_policy(database_session)
    previous_claim = ExpenseClaim(
        claim_id="EXP-2026-000010",
        employee_id="EMP-000001",
        cost_center_id="CC-001",
        total_amount=Decimal("50"),
        currency="USD",
        status="Approved",
        submission_date=TODAY,
    )
    database_session.add(previous_claim)
    database_session.flush()
    database_session.add(
        ExpenseLine(
            line_id="EXPL-EXP-2026-000010-01",
            claim_id=previous_claim.claim_id,
            policy_id="EP-001",
            amount=Decimal("50"),
            description="Taxi",
            expense_date=TODAY,
            receipt_hash="shared",
        )
    )
    database_session.commit()

    with pytest.raises(DomainError) as error:
        submit_expense_claim(
            database_session,
            request_expense(amount="50", receipt_hash="shared"),
        )
    assert error.value.code == "DUPLICATE_RECEIPT"


def test_threshold_exact_and_above_route_additional_approver(database_session):
    employee(database_session, "EMP-000001", manager_id="EMP-000002")
    employee(database_session, "EMP-000002", role="Manager")
    employee(database_session, "EMP-000003", role="Finance")
    cost_center(database_session)
    expense_policy(database_session, maximum="2000")
    rule(database_session, "AR-MANAGER", threshold=None, role="Manager")
    rule(database_session, "AR-FINANCE", threshold="500", role="Finance")
    database_session.commit()

    exact = submit_expense_claim(
        database_session,
        request_expense(amount="500", receipt_hash="exact"),
    )
    above = submit_expense_claim(
        database_session,
        request_expense(amount="501", receipt_hash="above", submission_date=date(2026, 10, 29)),
    )
    exact_approvers = database_session.scalars(
        select(ApprovalStep.approver_id)
        .where(ApprovalStep.expense_claim_id == exact.claim_id)
        .order_by(ApprovalStep.sequence)
    ).all()
    above_approvers = database_session.scalars(
        select(ApprovalStep.approver_id)
        .where(ApprovalStep.expense_claim_id == above.claim_id)
        .order_by(ApprovalStep.sequence)
    ).all()
    assert exact_approvers == ["EMP-000002", "EMP-000003"]
    assert above_approvers == ["EMP-000002", "EMP-000003"]


def test_approval_rules_match_category_and_country(database_session):
    requester = employee(
        database_session, "EMP-000001", manager_id="EMP-000002", country="USA"
    )
    employee(database_session, "EMP-000002", role="Manager")
    employee(database_session, "EMP-000003", role="Finance")
    database_session.add_all(
        [
            ApprovalRule(
                rule_id="AR-TRAVEL-GER",
                entity_type="Expense",
                threshold_amount=Decimal("100"),
                country_code="GER",
                category="Travel",
                approval_level=2,
                required_role="Finance",
                effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
            ),
            ApprovalRule(
                rule_id="AR-MEALS-USA",
                entity_type="Expense",
                threshold_amount=Decimal("100"),
                country_code="USA",
                category="Meals",
                approval_level=2,
                required_role="Finance",
                effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
            ),
        ]
    )
    database_session.flush()

    travel = approval_chain(
        database_session,
        employee=requester,
        entity_type="Expense",
        amount=Decimal("500"),
        country="USA",
        categories={"Travel"},
        effective_date=TODAY,
    )
    meals = approval_chain(
        database_session,
        employee=requester,
        entity_type="Expense",
        amount=Decimal("500"),
        country="USA",
        categories={"Meals"},
        effective_date=TODAY,
    )
    assert [approver.employee_id for approver in travel] == ["EMP-000002"]
    assert [approver.employee_id for approver in meals] == [
        "EMP-000002",
        "EMP-000003",
    ]


def test_threshold_requires_distinct_manager_and_finance_authorities(database_session):
    requester = employee(
        database_session, "EMP-000001", manager_id="EMP-000002", country="USA"
    )
    employee(database_session, "EMP-000002", role="Finance")
    employee(database_session, "EMP-000003", role="Finance")
    database_session.add_all(
        [
            ApprovalRule(
                rule_id="AR-EXP-MANAGER",
                entity_type="Expense",
                threshold_amount=None,
                country_code=None,
                category=None,
                approval_level=1,
                required_role="Manager",
                effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
            ),
            ApprovalRule(
                rule_id="AR-EXP-FINANCE",
                entity_type="Expense",
                threshold_amount=Decimal("500"),
                country_code=None,
                category=None,
                approval_level=2,
                required_role="Finance",
                effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
            ),
        ]
    )
    database_session.flush()
    chain = approval_chain(
        database_session,
        employee=requester,
        entity_type="Expense",
        amount=Decimal("500"),
        country="USA",
        categories={"Travel"},
        effective_date=TODAY,
    )
    assert [approver.employee_id for approver in chain] == [
        "EMP-000002",
        "EMP-000003",
    ]


def test_split_claim_is_detected(database_session):
    employee(database_session, "EMP-000001", manager_id="EMP-000002")
    employee(database_session, "EMP-000002", role="Manager")
    employee(database_session, "EMP-000003", role="Finance")
    cost_center(database_session)
    expense_policy(database_session, maximum="2000")
    rule(database_session, "AR-MANAGER", threshold=None, role="Manager")
    rule(database_session, "AR-FINANCE", threshold="500", role="Finance")
    database_session.commit()
    submit_expense_claim(
        database_session,
        request_expense(amount="300", receipt_hash="split-1"),
    )

    with pytest.raises(DomainError) as error:
        submit_expense_claim(
            database_session,
            request_expense(amount="250", receipt_hash="split-2"),
        )
    assert error.value.code == "POTENTIAL_SPLIT_CLAIM"


def test_employee_without_manager_is_rejected_for_approval(database_session):
    employee(database_session, "EMP-000001")
    leave_policy(database_session)
    leave_balance(database_session)

    with pytest.raises(DomainError) as error:
        submit_leave_request(database_session, request_leave())
    assert error.value.code == "APPROVER_UNAVAILABLE"


def test_self_approval_and_duplicate_approval_are_prevented(database_session):
    requester = employee(database_session, "EMP-000001", manager_id="EMP-000002")
    manager = employee(database_session, "EMP-000002")
    policy = leave_policy(database_session)
    leave_balance(database_session)
    request = LeaveRequest(
        request_id="LVE-2026-000010",
        employee_id=requester.employee_id,
        policy_id=policy.policy_id,
        start_date=date(2026, 11, 2),
        end_date=date(2026, 11, 2),
        total_days=Decimal("1"),
        leave_type="Annual",
        status="Pending",
    )
    database_session.add(request)
    database_session.flush()
    database_session.add(
        ApprovalStep(
            step_id="APR-LVE-2026-000010-01",
            leave_request_id=request.request_id,
            approver_id=requester.employee_id,
            sequence=1,
        )
    )
    database_session.commit()
    with pytest.raises(DomainError) as self_approval:
        decide_approval(
            database_session,
            request.request_id,
            requester.employee_id,
            decision="Approved",
        )
    assert self_approval.value.code == "SELF_APPROVAL"

    step = database_session.get(ApprovalStep, "APR-LVE-2026-000010-01")
    step.approver_id = manager.employee_id
    database_session.commit()
    decide_approval(
        database_session, request.request_id, manager.employee_id, decision="Approved"
    )
    with pytest.raises(DomainError) as duplicate:
        decide_approval(
            database_session, request.request_id, manager.employee_id, decision="Approved"
        )
    assert duplicate.value.code in {"INVALID_LIFECYCLE_TRANSITION", "NO_PENDING_APPROVAL"}


def test_rejection_closes_remaining_approvals_and_releases_balance(database_session):
    employee(database_session, "EMP-000001", manager_id="EMP-000002")
    employee(database_session, "EMP-000002")
    employee(database_session, "EMP-000003", role="Finance")
    policy = leave_policy(database_session)
    balance = leave_balance(database_session)
    request = LeaveRequest(
        request_id="LVE-2026-000020",
        employee_id="EMP-000001",
        policy_id=policy.policy_id,
        start_date=date(2026, 11, 2),
        end_date=date(2026, 11, 2),
        total_days=Decimal("1"),
        leave_type="Annual",
        status="Pending",
    )
    database_session.add(request)
    database_session.flush()
    database_session.add_all(
        [
            ApprovalStep(
                step_id="APR-LVE-2026-000020-01",
                leave_request_id=request.request_id,
                approver_id="EMP-000002",
                sequence=1,
            ),
            ApprovalStep(
                step_id="APR-LVE-2026-000020-02",
                leave_request_id=request.request_id,
                approver_id="EMP-000003",
                sequence=2,
            ),
        ]
    )
    balance.pending_balance = Decimal("1")
    database_session.commit()

    decide_approval(
        database_session,
        request.request_id,
        "EMP-000002",
        decision="Approved",
    )
    rejected = decide_approval(
        database_session,
        request.request_id,
        "EMP-000003",
        decision="Rejected",
        reason="Policy review",
    )
    assert rejected.status == "Rejected"
    assert balance.pending_balance == Decimal("0.00")
    assert {
        step.status
        for step in database_session.scalars(
            select(ApprovalStep).where(ApprovalStep.leave_request_id == request.request_id)
        )
    } == {"Approved", "Rejected"}


def test_reimbursement_requires_final_approval_and_enforces_amount(database_session):
    employee(database_session, "EMP-000001")
    center = cost_center(database_session)
    approved_claim = ExpenseClaim(
        claim_id="EXP-2026-000030",
        employee_id="EMP-000001",
        cost_center_id=center.cost_center_id,
        total_amount=Decimal("100"),
        currency="USD",
        status="Approved",
        submission_date=TODAY,
    )
    pending_claim = ExpenseClaim(
        claim_id="EXP-2026-000031",
        employee_id="EMP-000001",
        cost_center_id=center.cost_center_id,
        total_amount=Decimal("100"),
        currency="USD",
        status="Pending",
        submission_date=TODAY,
    )
    database_session.add_all([approved_claim, pending_claim])
    database_session.commit()
    with pytest.raises(DomainError) as excessive:
        create_reimbursement(
            database_session,
            approved_claim.claim_id,
            ReimbursementCreate(
                amount=Decimal("101"),
                payment_date=TODAY,
                transaction_ref="TX-EXCESS",
            ),
        )
    assert excessive.value.code == "REIMBURSEMENT_EXCEEDS_APPROVED_AMOUNT"
    with pytest.raises(DomainError) as unapproved:
        create_reimbursement(
            database_session,
            pending_claim.claim_id,
            ReimbursementCreate(
                amount=Decimal("50"),
                payment_date=TODAY,
                transaction_ref="TX-PENDING",
            ),
        )
    assert unapproved.value.code == "CLAIM_NOT_FINALLY_APPROVED"


def test_duplicate_reimbursement_and_processing_lifecycle(database_session):
    employee(database_session, "EMP-000001")
    center = cost_center(database_session)
    claim = ExpenseClaim(
        claim_id="EXP-2026-000040",
        employee_id="EMP-000001",
        cost_center_id=center.cost_center_id,
        total_amount=Decimal("100"),
        currency="USD",
        status="Approved",
        submission_date=TODAY,
    )
    database_session.add(claim)
    database_session.commit()
    reimbursement = create_reimbursement(
        database_session,
        claim.claim_id,
        ReimbursementCreate(
            amount=Decimal("100"),
            payment_date=TODAY,
            transaction_ref="TX-40",
        ),
    )
    with pytest.raises(DomainError) as duplicate:
        create_reimbursement(
            database_session,
            claim.claim_id,
            ReimbursementCreate(
                amount=Decimal("100"),
                payment_date=TODAY,
                transaction_ref="TX-41",
            ),
        )
    assert duplicate.value.code == "DUPLICATE_REIMBURSEMENT"
    assert database_session.scalar(
        select(AuditEvent).where(
            AuditEvent.exception_code == "DUPLICATE_REIMBURSEMENT"
        )
    )
    processed = process_reimbursement(database_session, reimbursement.reimbursement_id)
    assert processed.status == "Processed"
    assert claim.status == "Paid"
    with pytest.raises(DomainError) as duplicate_process:
        process_reimbursement(database_session, reimbursement.reimbursement_id)
    assert duplicate_process.value.code == "INVALID_REIMBURSEMENT_TRANSITION"
