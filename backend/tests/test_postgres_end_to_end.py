import csv
import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert, select
from sqlalchemy.orm import sessionmaker

from app import models
from app.db.session import get_db
from app.main import app
from app.models import (
    ApprovalStep,
    AuditEvent,
    CostCenter,
    Employee,
    ExpenseClaim,
    ExpenseLine,
    LeaveBalance,
)
from generator.config import GeneratorConfig
from generator.generator import build_dataset

MODEL_BY_TABLE = {
    "employees": models.Employee,
    "leave_policies": models.LeavePolicy,
    "expense_policies": models.ExpensePolicy,
    "cost_centers": models.CostCenter,
    "approval_rules": models.ApprovalRule,
    "public_holidays": models.PublicHoliday,
    "leave_requests": models.LeaveRequest,
    "leave_balances": models.LeaveBalance,
    "expense_claims": models.ExpenseClaim,
    "expense_lines": models.ExpenseLine,
    "approval_steps": models.ApprovalStep,
    "reimbursements": models.Reimbursement,
}


@pytest.fixture(scope="module")
def postgres_dataset():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL end-to-end validation")

    engine = create_engine(database_url, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with factory() as session:
            existing_employees = session.query(Employee.employee_id).limit(1).first()
            if existing_employees:
                pytest.fail(
                    "TEST_DATABASE_URL must point to a clean, migrated PostgreSQL database"
                )

        tables, ground_truth, anomaly_cases = build_dataset(GeneratorConfig())
        with engine.begin() as connection:
            for table, rows in tables.items():
                if rows:
                    connection.execute(insert(MODEL_BY_TABLE[table]), rows)
        yield engine, factory, ground_truth, anomaly_cases
    finally:
        engine.dispose()


@pytest.fixture
def pg_client(postgres_dataset):
    _engine, factory, _ground_truth, _anomaly_cases = postgres_dataset

    def override_database():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_database
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def _employee_payload(employee_id: str, manager_id: str = "EMP-000012") -> dict:
    return {
        "employee_id": employee_id,
        "name": f"Phase 7 {employee_id}",
        "email": f"{employee_id.lower()}@phase7.example.test",
        "manager_id": manager_id,
        "department": "Operations",
        "country": "UK",
        "hire_date": "2020-01-01",
        "status": "Active",
    }


def _create_employee(client: TestClient, employee_id: str) -> None:
    response = client.post("/employees", json=_employee_payload(employee_id))
    assert response.status_code == 201, response.text


def _create_balance(factory, employee_id: str, accrued: str = "20.00") -> None:
    with factory() as session:
        session.add(
            LeaveBalance(
                balance_id=f"LB-{employee_id[-6:]}",
                employee_id=employee_id,
                policy_id="LP-002",
                accrued_balance=Decimal(accrued),
                used_balance=Decimal("0"),
                pending_balance=Decimal("0"),
                effective_date=date(2026, 10, 31),
            )
        )
        session.commit()


def _leave_payload(
    employee_id: str,
    request_id: str,
    start_date: str,
    end_date: str,
    policy_id: str = "LP-002",
) -> dict:
    return {
        "request_id": request_id,
        "employee_id": employee_id,
        "policy_id": policy_id,
        "start_date": start_date,
        "end_date": end_date,
        "leave_type": "Annual",
    }


def _expense_payload(
    *,
    claim_id: str,
    employee_id: str,
    amount: str,
    receipt_hash: str,
    submission_date: str = "2026-10-31",
    expense_date: str = "2026-10-30",
    cost_center_id: str = "CC-001",
    policy_id: str = "EP-001",
) -> dict:
    return {
        "claim_id": claim_id,
        "employee_id": employee_id,
        "cost_center_id": cost_center_id,
        "currency": "USD",
        "submission_date": submission_date,
        "lines": [
            {
                "policy_id": policy_id,
                "amount": amount,
                "description": "Phase 7 workflow validation",
                "expense_date": expense_date,
                "receipt_hash": receipt_hash,
                "receipt_url": f"https://receipts.example.test/{receipt_hash}",
            }
        ],
    }


def _expect_domain_error(response, code: str, status_code: int | None = None) -> None:
    assert response.status_code in ({status_code} if status_code else {400, 409, 422}), response.text
    payload = response.json()
    assert payload["error"]["code"] == code, payload


def _load_ground_truth():
    path = Path(__file__).resolve().parents[2] / "data" / "generated" / "ground_truth.csv"
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_postgresql_full_workflows_and_ground_truth(pg_client, postgres_dataset):
    _engine, factory, generated_ground_truth, anomaly_cases = postgres_dataset
    client = pg_client
    employees_before = client.get("/employees?limit=1")
    assert employees_before.status_code == 200
    assert employees_before.json()["total"] == 400
    assert len(generated_ground_truth) == len(_load_ground_truth()) == 17
    assert len(anomaly_cases) == 8

    # Leave submission reserves balance; only final approval moves it to used.
    employee_id = "EMP-900001"
    _create_employee(client, employee_id)
    _create_balance(factory, employee_id)
    submitted = client.post(
        "/leave/requests",
        json=_leave_payload(
            employee_id, "LVE-2026-900001", "2026-11-02", "2026-11-03"
        ),
    )
    assert submitted.status_code == 201, submitted.text
    assert Decimal(submitted.json()["total_days"]) == Decimal("2.00")
    assert submitted.json()["status"] == "Pending"
    with factory() as session:
        balance = session.get(LeaveBalance, f"LB-{employee_id[-6:]}")
        assert balance.pending_balance == Decimal("2.00")
        assert balance.used_balance == Decimal("0.00")
        approval_steps = list(
            session.scalars(
                select(ApprovalStep)
                .where(ApprovalStep.leave_request_id == "LVE-2026-900001")
                .order_by(ApprovalStep.sequence)
            )
        )
        assert [step.approver_id for step in approval_steps] == ["EMP-000012"]

    approved = client.post(
        "/leave/requests/LVE-2026-900001/approve",
        json={"approver_id": "EMP-000012"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "Approved"
    with factory() as session:
        balance = session.get(LeaveBalance, f"LB-{employee_id[-6:]}")
        assert balance.pending_balance == Decimal("0.00")
        assert balance.used_balance == Decimal("2.00")

    overlap = client.post(
        "/leave/requests",
        json=_leave_payload(
            employee_id, "LVE-2026-900002", "2026-11-02", "2026-11-03"
        ),
    )
    _expect_domain_error(overlap, "OVERLAPPING_APPROVED_LEAVE", 409)

    rejected_leave = client.post(
        "/leave/requests",
        json=_leave_payload(
            employee_id, "LVE-2026-900003", "2026-11-09", "2026-11-09"
        ),
    )
    assert rejected_leave.status_code == 201, rejected_leave.text
    rejected_leave = client.post(
        "/leave/requests/LVE-2026-900003/reject",
        json={"approver_id": "EMP-000012", "reason": "Coverage unavailable"},
    )
    assert rejected_leave.status_code == 200
    assert rejected_leave.json()["status"] == "Rejected"
    with factory() as session:
        balance = session.get(LeaveBalance, f"LB-{employee_id[-6:]}")
        assert balance.pending_balance == Decimal("0.00")
        assert balance.used_balance == Decimal("2.00")

    insufficient_id = "EMP-900002"
    _create_employee(client, insufficient_id)
    _create_balance(factory, insufficient_id, "0.00")
    insufficient = client.post(
        "/leave/requests",
        json=_leave_payload(
            insufficient_id, "LVE-2026-900004", "2026-11-10", "2026-11-10"
        ),
    )
    _expect_domain_error(insufficient, "INSUFFICIENT_LEAVE_BALANCE", 422)

    weekend = client.post(
        "/leave/requests",
        json=_leave_payload(
            employee_id, "LVE-2026-900005", "2026-11-07", "2026-11-08"
        ),
    )
    _expect_domain_error(weekend, "NO_BUSINESS_DAYS", 422)
    holiday = client.post(
        "/leave/requests",
        json=_leave_payload(
            employee_id, "LVE-2026-900006", "2026-04-30", "2026-05-01"
        ),
    )
    assert holiday.status_code == 201, holiday.text
    assert Decimal(holiday.json()["total_days"]) == Decimal("1.00")

    negative_balance = client.post(
        "/leave/requests",
        json=_leave_payload(
            "EMP-000249", "LVE-2026-900007", "2026-12-07", "2026-12-08"
        ),
    )
    _expect_domain_error(negative_balance, "INSUFFICIENT_LEAVE_BALANCE", 422)
    overlap_from_ground_truth = client.post(
        "/leave/requests",
        json=_leave_payload(
            "EMP-000002",
            "LVE-2026-900008",
            "2026-02-02",
            "2026-02-03",
            policy_id="LP-004",
        ),
    )
    _expect_domain_error(overlap_from_ground_truth, "OVERLAPPING_APPROVED_LEAVE", 409)

    # A threshold claim routes to both a manager and a distinct Finance approver.
    exact_threshold = client.post(
        "/expenses/claims",
        json=_expense_payload(
            claim_id="EXP-2026-900001",
            employee_id=employee_id,
            amount="500.00",
            receipt_hash="phase7-threshold-500",
            submission_date="2026-11-03",
            expense_date="2026-11-02",
        ),
    )
    assert exact_threshold.status_code == 201, exact_threshold.text
    with factory() as session:
        steps = list(
            session.scalars(
                select(ApprovalStep)
                .where(ApprovalStep.expense_claim_id == "EXP-2026-900001")
                .order_by(ApprovalStep.sequence)
            )
        )
        assert len(steps) == 2
        assert steps[0].approver_id == "EMP-000012"
        assert steps[1].approver_id == "EMP-000003"

    manager_decision = client.post(
        "/expenses/claims/EXP-2026-900001/approve",
        json={"approver_id": "EMP-000012"},
    )
    assert manager_decision.status_code == 200
    assert manager_decision.json()["status"] == "Pending"
    finance_decision = client.post(
        "/expenses/claims/EXP-2026-900001/approve",
        json={"approver_id": "EMP-000003"},
    )
    assert finance_decision.status_code == 200
    assert finance_decision.json()["status"] == "Approved"

    above_threshold = client.post(
        "/expenses/claims",
        json=_expense_payload(
            claim_id="EXP-2026-900002",
            employee_id=employee_id,
            amount="501.00",
            receipt_hash="phase7-threshold-501",
            submission_date="2026-11-10",
            expense_date="2026-11-09",
        ),
    )
    assert above_threshold.status_code == 201, above_threshold.text
    with factory() as session:
        assert session.query(ApprovalStep).filter_by(
            expense_claim_id="EXP-2026-900002"
        ).count() == 2

    # Reimbursements are allowed only after final approval and move the claim to Paid.
    reimbursement = client.post(
        "/expenses/claims/EXP-2026-900001/reimbursements",
        json={
            "amount": "500.00",
            "payment_date": "2026-11-11",
            "transaction_ref": "phase7-txn-900001",
        },
    )
    assert reimbursement.status_code == 201, reimbursement.text
    reimbursement_id = reimbursement.json()["reimbursement_id"]
    processed = client.post(f"/reimbursements/{reimbursement_id}/process")
    assert processed.status_code == 200
    assert processed.json()["status"] == "Processed"
    assert client.get("/expenses/claims/EXP-2026-900001").json()["status"] == "Paid"

    # Expense rejection, self-approval, policy, budget, receipt, employment,
    # cost-center, and split-claim paths are exercised through the API.
    rejected_expense = client.post(
        "/expenses/claims",
        json=_expense_payload(
            claim_id="EXP-2026-900003",
            employee_id=employee_id,
            amount="100.00",
            receipt_hash="phase7-rejected",
            submission_date="2026-11-12",
            expense_date="2026-11-11",
            cost_center_id="CC-005",
        ),
    )
    assert rejected_expense.status_code == 201, rejected_expense.text
    self_approval = client.post(
        "/expenses/claims/EXP-2026-900003/approve",
        json={"approver_id": employee_id},
    )
    _expect_domain_error(self_approval, "SELF_APPROVAL", 409)
    rejected_expense = client.post(
        "/expenses/claims/EXP-2026-900003/reject",
        json={"approver_id": "EMP-000012", "reason": "Not business related"},
    )
    assert rejected_expense.status_code == 200
    assert rejected_expense.json()["status"] == "Rejected"

    duplicate_receipt = client.post(
        "/expenses/claims",
        json=_expense_payload(
            claim_id="EXP-2026-900004",
            employee_id=employee_id,
            amount="25.00",
            receipt_hash="phase7-threshold-500",
            submission_date="2026-11-15",
            cost_center_id="CC-005",
        ),
    )
    _expect_domain_error(duplicate_receipt, "DUPLICATE_RECEIPT", 409)

    missing_cost_center = client.post(
        "/expenses/claims",
        json=_expense_payload(
            claim_id="EXP-2026-900005",
            employee_id=employee_id,
            amount="25.00",
            receipt_hash="phase7-missing-center",
            cost_center_id="CC-MISSING",
        ),
    )
    _expect_domain_error(missing_cost_center, "COST_CENTER_NOT_FOUND", 404)

    outside_employment = client.post(
        "/expenses/claims",
        json=_expense_payload(
            claim_id="EXP-2026-900006",
            employee_id=employee_id,
            amount="25.00",
            receipt_hash="phase7-outside-employment",
            expense_date="2019-12-31",
        ),
    )
    _expect_domain_error(outside_employment, "OUTSIDE_EMPLOYMENT_PERIOD", 422)

    policy_violation = client.post(
        "/expenses/claims",
        json=_expense_payload(
            claim_id="EXP-2026-900007",
            employee_id=employee_id,
            amount="2500.00",
            receipt_hash="phase7-policy-violation",
        ),
    )
    _expect_domain_error(policy_violation, "POLICY_LIMIT_EXCEEDED", 422)

    missing_receipt = client.post(
        "/expenses/claims",
        json={
            "employee_id": employee_id,
            "cost_center_id": "CC-005",
            "currency": "USD",
            "submission_date": "2026-11-18",
            "lines": [
                {
                    "policy_id": "EP-001",
                    "amount": "25.00",
                    "description": "Receipt-required taxi",
                    "expense_date": "2026-11-17",
                    "receipt_hash": None,
                    "receipt_url": None,
                }
            ],
        },
    )
    _expect_domain_error(missing_receipt, "RECEIPT_REQUIRED", 422)

    with factory() as session:
        session.add(
            CostCenter(
                cost_center_id="CC-900001",
                name="Phase 7 constrained budget",
                budget=Decimal("10.00"),
                department="Operations",
            )
        )
        session.commit()
    budget_violation = client.post(
        "/expenses/claims",
        json=_expense_payload(
            claim_id="EXP-2026-900008",
            employee_id=employee_id,
            amount="20.00",
            receipt_hash="phase7-budget-violation",
            cost_center_id="CC-900001",
        ),
    )
    _expect_domain_error(budget_violation, "BUDGET_EXCEEDED", 422)

    split_employee = "EMP-900003"
    _create_employee(client, split_employee)
    _create_balance(factory, split_employee)
    first_split = client.post(
        "/expenses/claims",
        json=_expense_payload(
            claim_id="EXP-2026-900009",
            employee_id=split_employee,
            amount="300.00",
            receipt_hash="phase7-split-300",
            submission_date="2026-11-20",
            expense_date="2026-11-19",
            cost_center_id="CC-004",
        ),
    )
    assert first_split.status_code == 201, first_split.text
    split_attempt = client.post(
        "/expenses/claims",
        json=_expense_payload(
            claim_id="EXP-2026-900010",
            employee_id=split_employee,
            amount="250.00",
            receipt_hash="phase7-split-250",
            submission_date="2026-11-21",
            expense_date="2026-11-20",
            cost_center_id="CC-004",
        ),
    )
    _expect_domain_error(split_attempt, "POTENTIAL_SPLIT_CLAIM", 409)

    expired_policy = client.post(
        "/expenses/claims",
        json=_expense_payload(
            claim_id="EXP-2026-900011",
            employee_id="EMP-000010",
            amount="25.00",
            receipt_hash="phase7-expired-policy",
            policy_id="EP-EXP",
            expense_date="2026-01-01",
        ),
    )
    _expect_domain_error(expired_policy, "EXPENSE_POLICY_EXPIRED", 422)

    with factory() as session:
        outside_source_claim = session.get(ExpenseClaim, "EXP-2026-000003")
        outside_source_line = session.scalar(
            select(ExpenseLine)
            .where(ExpenseLine.claim_id == "EXP-2026-000003")
            .order_by(ExpenseLine.line_id)
        )
        outside_source_employee = session.get(
            Employee, outside_source_claim.employee_id
        )
        assert outside_source_line.expense_date < outside_source_employee.hire_date
    outside_ground_truth = client.post(
        "/expenses/claims",
        json=_expense_payload(
            claim_id="EXP-2026-900012",
            employee_id=outside_source_claim.employee_id,
            amount="25.00",
            receipt_hash="phase7-ground-truth-outside-employment",
            cost_center_id=outside_source_claim.cost_center_id,
            policy_id=outside_source_line.policy_id,
            expense_date=outside_source_line.expense_date.isoformat(),
        ),
    )
    _expect_domain_error(outside_ground_truth, "OUTSIDE_EMPLOYMENT_PERIOD", 422)

    duplicate_reimbursement = client.post(
        "/expenses/claims/EXP-2026-000801/reimbursements",
        json={
            "amount": "380.33",
            "payment_date": "2026-10-31",
            "transaction_ref": "phase7-duplicate-reimbursement",
        },
    )
    assert duplicate_reimbursement.status_code == 409
    actual_duplicate_code = duplicate_reimbursement.json()["error"]["code"]

    # Ground-truth labels describe cases; compare expected domain outcomes to
    # actual API decisions and preserve the observed mismatch in the report.
    expected_codes = {
        "split_claim": "POTENTIAL_SPLIT_CLAIM",
        "missing_cost_center": "COST_CENTER_NOT_FOUND",
        "duplicate_receipt": "DUPLICATE_RECEIPT",
        "duplicate_reimbursement": "DUPLICATE_REIMBURSEMENT",
        "expired_policy": "EXPENSE_POLICY_EXPIRED",
        "partial_approval_then_rejection": "PARTIAL_APPROVAL_THEN_REJECTION",
        "missing_receipt": "RECEIPT_REQUIRED",
        "policy_limit_breach": "POLICY_LIMIT_EXCEEDED",
    }
    with factory() as session:
        partial_step_statuses = list(
            session.scalars(
                select(ApprovalStep.status)
                .where(ApprovalStep.expense_claim_id == "EXP-2026-000006")
                .order_by(ApprovalStep.sequence)
            )
        )
    partial_result = (
        "PARTIAL_APPROVAL_THEN_REJECTION"
        if partial_step_statuses == ["Approved", "Rejected"]
        else f"Unexpected step statuses: {partial_step_statuses}"
    )
    replay_results = {
        "split_claim": split_attempt.json()["error"]["code"],
        "missing_cost_center": missing_cost_center.json()["error"]["code"],
        "duplicate_receipt": duplicate_receipt.json()["error"]["code"],
        "duplicate_reimbursement": actual_duplicate_code,
        "expired_policy": expired_policy.json()["error"]["code"],
        "partial_approval_then_rejection": partial_result,
        "missing_receipt": missing_receipt.json()["error"]["code"],
        "policy_limit_breach": policy_violation.json()["error"]["code"],
    }
    case_results = [
        {
            "case_type": case["case_type"],
            "expected": expected_codes.get(case["case_type"], case["expected_code"]),
            "actual": replay_results.get(case["case_type"], "Verified from persisted workflow state"),
        }
        for case in anomaly_cases
    ]
    case_matches = sum(
        item["expected"] == item["actual"]
        for item in case_results
        if item["actual"] != "Verified from persisted workflow state"
    )
    case_decisions = sum(
        item["actual"] != "Verified from persisted workflow state"
        for item in case_results
    )

    with factory() as session:
        partial_steps = list(
            session.scalars(
                select(ApprovalStep)
                .where(ApprovalStep.expense_claim_id == "EXP-2026-000006")
                .order_by(ApprovalStep.sequence)
            )
        )
        assert len(partial_steps) == 2
        assert [step.status for step in partial_steps] == ["Approved", "Rejected"]
        above_threshold_claim = session.get(ExpenseClaim, "EXP-2026-000002")
        above_threshold_steps = list(
            session.scalars(
                select(ApprovalStep)
                .where(ApprovalStep.expense_claim_id == "EXP-2026-000002")
                .order_by(ApprovalStep.sequence)
            )
        )
        assert above_threshold_claim.status == "Approved"
        assert len(above_threshold_steps) == 2
        assert all(step.status == "Approved" for step in above_threshold_steps)
        assert all(
            step.approver_id != above_threshold_claim.employee_id
            for step in above_threshold_steps
        )
        static_threshold_steps = list(
            session.scalars(
                select(ApprovalStep)
                .where(ApprovalStep.expense_claim_id == "EXP-2026-000001")
                .order_by(ApprovalStep.sequence)
            )
        )
        static_threshold_claim = session.get(ExpenseClaim, "EXP-2026-000001")
        assert static_threshold_claim.total_amount == Decimal("500.00")
        assert len(static_threshold_steps) == 2
        static_threshold_self_approval = (
            static_threshold_steps[0].approver_id == static_threshold_claim.employee_id
        )
        assert static_threshold_self_approval
        audit_events = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.entity_id.in_(
                        [
                            "LVE-2026-900001",
                            "LVE-2026-900001",
                            "EXP-2026-900001",
                            reimbursement_id,
                        ]
                    )
                )
            )
        )
        assert any(event.event_type == "leave_submitted" for event in audit_events)
        assert any(event.event_type == "request_approved" for event in audit_events)
        assert any(event.event_type == "reimbursement_processed" for event in audit_events)
        assert any(
            event.is_exception and event.exception_code == "POTENTIAL_SPLIT_CLAIM"
            for event in session.scalars(
                select(AuditEvent).where(AuditEvent.entity_id == "EXP-2026-900010")
            )
        )
        assert client.get("/employees/EMP-000001").status_code == 200

        actual_ground_truth = {
            "EXP-2026-000002": "Above Approval Threshold: Approved with ordered steps",
            "CASE-DUPLICATE-RECEIPT": replay_results["duplicate_receipt"],
            "CASE-DUPLICATE-REIMBURSEMENT": replay_results["duplicate_reimbursement"],
            "EXP-2026-000001": "Exact Approval Threshold: $500 with 2 approval steps",
            "EXPL-EXP-2026-000003-01": outside_ground_truth.json()["error"]["code"],
            "CASE-EXPIRED-POLICY": replay_results["expired_policy"],
            "LVE-2026-000004": f"Holiday leave: accepted for {Decimal(holiday.json()['total_days']).normalize()} day",
            "CASE-MISSING-COST-CENTER": replay_results["missing_cost_center"],
            "CASE-MISSING-RECEIPT": replay_results["missing_receipt"],
            "CASE-POLICY-LIMIT-BREACH": replay_results["policy_limit_breach"],
            "LB-000249": negative_balance.json()["error"]["code"],
            "EMP-000001": "Top-level employee remains readable (HTTP 200)",
            "LVE-2026-000002": overlap_from_ground_truth.json()["error"]["code"],
            "EXP-2026-000006": "Partial rejection: Approved then Rejected",
            "APR-EXP-2026-000001-01": self_approval.json()["error"]["code"],
            "EXP-2026-000004": replay_results["split_claim"],
            "LVE-2026-000003": weekend.json()["error"]["code"],
        }
        expected_decisions = {
            "EXP-2026-000002": "Above Approval Threshold: Approved with ordered steps",
            "CASE-DUPLICATE-RECEIPT": "DUPLICATE_RECEIPT",
            "CASE-DUPLICATE-REIMBURSEMENT": "DUPLICATE_REIMBURSEMENT",
            "EXP-2026-000001": "Exact Approval Threshold: $500 with 2 approval steps",
            "EXPL-EXP-2026-000003-01": "OUTSIDE_EMPLOYMENT_PERIOD",
            "CASE-EXPIRED-POLICY": "EXPENSE_POLICY_EXPIRED",
            "LVE-2026-000004": "Holiday leave: accepted for 1 day",
            "CASE-MISSING-COST-CENTER": "COST_CENTER_NOT_FOUND",
            "CASE-MISSING-RECEIPT": "RECEIPT_REQUIRED",
            "CASE-POLICY-LIMIT-BREACH": "POLICY_LIMIT_EXCEEDED",
            "LB-000249": "INSUFFICIENT_LEAVE_BALANCE",
            "EMP-000001": "Top-level employee remains readable (HTTP 200)",
            "LVE-2026-000002": "OVERLAPPING_APPROVED_LEAVE",
            "EXP-2026-000006": "Partial rejection: Approved then Rejected",
            "APR-EXP-2026-000001-01": "SELF_APPROVAL",
            "EXP-2026-000004": "POTENTIAL_SPLIT_CLAIM",
            "LVE-2026-000003": "NO_BUSINESS_DAYS",
        }
        evaluation = []
        for row in generated_ground_truth:
            expected = expected_decisions[row["entity_id"]]
            actual = actual_ground_truth[row["entity_id"]]
            evaluation.append(
                {
                    "entity_id": row["entity_id"],
                    "issue_type": row["issue_type"],
                    "label": row["label"],
                    "expected": expected,
                    "actual": actual,
                    "match": expected == actual,
                }
            )

    matches = sum(item["match"] for item in evaluation)
    positives = [item for item in evaluation if item["label"] == "Anomaly"]
    actual_positive = [
        item
        for item in evaluation
        if item["actual"] in {
            "DUPLICATE_RECEIPT",
            "DUPLICATE_REIMBURSEMENT",
            "COST_CENTER_NOT_FOUND",
            "RECEIPT_REQUIRED",
            "POLICY_LIMIT_EXCEEDED",
            "INSUFFICIENT_LEAVE_BALANCE",
            "OVERLAPPING_APPROVED_LEAVE",
            "POTENTIAL_SPLIT_CLAIM",
            "OUTSIDE_EMPLOYMENT_PERIOD",
            "SELF_APPROVAL",
            "Self-approval rejected by API",
            "Outside employment: rejected by API",
        }
    ]
    true_positives = sum(item in actual_positive for item in positives)
    false_negatives = len(positives) - true_positives
    false_positives = sum(
        item in actual_positive
        for item in evaluation
        if item["label"] != "Anomaly"
    )
    report = {
        "total_cases": len(evaluation),
        "expected_decisions": len(evaluation),
        "actual_decisions": len(evaluation),
        "matches": matches,
        "mismatches": len(evaluation) - matches,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "edge_case_coverage": sum(
            item["label"] == "Edge Case" and item["match"] for item in evaluation
        ),
        "edge_case_total": sum(item["label"] == "Edge Case" for item in evaluation),
        "anomaly_case_decisions": case_decisions,
        "anomaly_case_matches": case_matches,
        "anomaly_case_mismatches": case_decisions - case_matches,
        "ground_truth_mismatches": [item for item in evaluation if not item["match"]],
        "anomaly_case_results": case_results,
    }
    print("PHASE7_GROUND_TRUTH_EVALUATION=" + json.dumps(report, sort_keys=True))

    assert report["total_cases"] == 17
    assert report["actual_decisions"] == 17
    assert report["edge_case_coverage"] == report["edge_case_total"]
    assert report["false_negatives"] == 0
    assert report["anomaly_case_decisions"] == 8
    assert report["anomaly_case_mismatches"] == 0
    assert actual_duplicate_code == "DUPLICATE_REIMBURSEMENT"
