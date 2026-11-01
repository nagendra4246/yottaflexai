from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from app.models import (
    ApprovalRule,
    CostCenter,
    Employee,
    ExpensePolicy,
    LeaveBalance,
    LeavePolicy,
)


@pytest.fixture
def client(database_session):
    def override_database():
        yield database_session

    app.dependency_overrides[get_db] = override_database
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def seed_employee(
    database_session, employee_id, *, manager_id=None, approval_role=None
):
    employee = Employee(
        employee_id=employee_id,
        name=employee_id,
        email=f"{employee_id.lower()}@example.test",
        manager_id=manager_id,
        department="Operations",
        country="USA",
        hire_date=date(2020, 1, 1),
        status="Active",
        approval_role=approval_role,
    )
    database_session.add(employee)
    database_session.flush()
    return employee


def seed_workflow_data(database_session, *, with_manager=True):
    manager = None
    if with_manager:
        manager = seed_employee(
            database_session, "EMP-000001", approval_role="Manager"
        )
    employee = seed_employee(
        database_session,
        "EMP-000002" if with_manager else "EMP-000003",
        manager_id=manager.employee_id if manager else None,
    )
    database_session.add_all(
        [
            LeavePolicy(
                policy_id="LP-001",
                policy_name="Annual",
                annual_entitlement=20,
                carry_over_limit=5,
                accrual_rate=Decimal("1.667"),
                country_code="USA",
                effective_from=date(2020, 1, 1),
            ),
            LeaveBalance(
                balance_id=f"LB-{employee.employee_id[-6:]}",
                employee_id=employee.employee_id,
                policy_id="LP-001",
                accrued_balance=Decimal("20"),
                used_balance=Decimal("0"),
                pending_balance=Decimal("0"),
                effective_date=date(2026, 10, 31),
            ),
            ExpensePolicy(
                policy_id="EP-001",
                category="Travel",
                max_amount=Decimal("2000"),
                requires_receipt=True,
                country_code="GLOBAL",
                effective_from=date(2020, 1, 1),
            ),
            CostCenter(
                cost_center_id="CC-001",
                name="Operations",
                budget=Decimal("10000"),
                department="Operations",
            ),
        ]
    )
    database_session.commit()
    return employee, manager


def test_employee_endpoints_validation_and_pagination(client):
    for number in range(1, 4):
        response = client.post(
            "/employees",
            json={
                "employee_id": f"EMP-00000{number}",
                "name": f"Employee {number}",
                "email": f"employee{number}@example.test",
                "department": "Operations",
                "country": "UK",
                "hire_date": "2020-01-01",
            },
        )
        assert response.status_code == 201

    page = client.get("/employees?country=uk&limit=2&offset=1")
    assert page.status_code == 200
    assert page.json()["total"] == 3
    assert page.json()["limit"] == 2
    assert len(page.json()["items"]) == 2

    detail = client.get("/employees/EMP-000001")
    assert detail.status_code == 200
    assert detail.json()["country"] == "UK"

    invalid = client.post(
        "/employees",
        json={
            "employee_id": "bad-id",
            "name": "Invalid User",
            "email": "not-an-email",
            "department": "Operations",
            "country": "XYZ",
            "hire_date": "2020-01-01",
        },
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"


def test_health_check_reports_database_connectivity(client, monkeypatch):
    monkeypatch.setattr("app.main.check_database_connection", lambda: True)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


def test_health_check_returns_service_unavailable_when_database_is_down(
    client, monkeypatch
):
    monkeypatch.setattr("app.main.check_database_connection", lambda: False)

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["error"]["message"] == "Database unavailable"
    assert client.get("/employees?limit=0").json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.get("/employees?status=unknown").status_code == 422
    missing = client.get("/employees/EMP-999999")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "EMPLOYEE_NOT_FOUND"


def test_leave_submission_approval_rejection_and_audit(
    client, database_session
):
    employee, manager = seed_workflow_data(database_session)
    base_payload = {
        "employee_id": employee.employee_id,
        "policy_id": "LP-001",
        "leave_type": "Annual",
    }

    approved_id = "LVE-2026-000001"
    submitted = client.post(
        "/leave/requests",
        json={
            **base_payload,
            "request_id": approved_id,
            "start_date": "2026-11-02",
            "end_date": "2026-11-03",
        },
    )
    assert submitted.status_code == 201
    assert submitted.json()["status"] == "Pending"
    assert client.get("/leave/requests?status=Pending&limit=1").json()["total"] == 1
    assert client.get(f"/leave/requests/{approved_id}").status_code == 200

    approved = client.post(
        f"/leave/requests/{approved_id}/approve",
        json={"approver_id": manager.employee_id, "comments": "Approved"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "Approved"

    rejected_id = "LVE-2026-000002"
    rejected_submission = client.post(
        "/leave/requests",
        json={
            **base_payload,
            "request_id": rejected_id,
            "start_date": "2026-11-04",
            "end_date": "2026-11-05",
        },
    )
    assert rejected_submission.status_code == 201
    rejected = client.post(
        f"/leave/requests/{rejected_id}/reject",
        json={"approver_id": manager.employee_id, "reason": "Insufficient coverage"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "Rejected"
    assert rejected.json()["decision_reason"] == "Insufficient coverage"

    events = client.get(f"/audit/events?entity_id={approved_id}")
    assert events.status_code == 200
    assert any(event["event_type"] == "leave_submitted" for event in events.json()["items"])
    assert events.json()["total"] >= 2


def test_expense_reimbursement_restrictions_and_analytics(
    client, database_session
):
    employee, manager = seed_workflow_data(database_session)

    def submit_claim(claim_id, receipt_hash):
        return client.post(
            "/expenses/claims",
            json={
                "claim_id": claim_id,
                "employee_id": employee.employee_id,
                "cost_center_id": "CC-001",
                "currency": "usd",
                "submission_date": "2026-10-31",
                "lines": [
                    {
                        "policy_id": "EP-001",
                        "amount": "100.00",
                        "description": "Taxi",
                        "expense_date": "2026-10-30",
                        "receipt_hash": receipt_hash,
                        "receipt_url": f"https://example.test/{receipt_hash}",
                    }
                ],
            },
        )

    claim_id = "EXP-2026-000001"
    claim = submit_claim(claim_id, "receipt-1")
    assert claim.status_code == 201
    assert claim.json()["total_amount"] == "100.00"
    assert client.get("/expenses/claims?status=Pending").json()["total"] == 1
    assert client.get(f"/expenses/claims/{claim_id}").status_code == 200

    blocked_reimbursement = client.post(
        f"/expenses/claims/{claim_id}/reimbursements",
        json={
            "amount": "100.00",
            "payment_date": "2026-11-01",
            "transaction_ref": "txn-blocked",
        },
    )
    assert blocked_reimbursement.status_code == 409
    assert blocked_reimbursement.json()["error"]["code"] == "CLAIM_NOT_FINALLY_APPROVED"

    approved = client.post(
        f"/expenses/claims/{claim_id}/approve",
        json={"approver_id": manager.employee_id},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "Approved"

    excessive = client.post(
        f"/expenses/claims/{claim_id}/reimbursements",
        json={
            "amount": "100.01",
            "payment_date": "2026-11-01",
            "transaction_ref": "txn-too-large",
        },
    )
    assert excessive.status_code == 409
    assert excessive.json()["error"]["code"] == "REIMBURSEMENT_EXCEEDS_APPROVED_AMOUNT"

    reimbursement = client.post(
        f"/expenses/claims/{claim_id}/reimbursements",
        json={
            "amount": "100.00",
            "payment_date": "2026-11-01",
            "transaction_ref": "txn-valid",
        },
    )
    assert reimbursement.status_code == 201
    reimbursement_id = reimbursement.json()["reimbursement_id"]
    processed = client.post(f"/reimbursements/{reimbursement_id}/process")
    assert processed.status_code == 200
    assert processed.json()["status"] == "Processed"
    assert client.get("/reimbursements?status=Processed").json()["total"] == 1
    assert client.get(f"/expenses/claims/{claim_id}").json()["status"] == "Paid"

    duplicate_receipt = submit_claim("EXP-2026-000002", "receipt-1")
    assert duplicate_receipt.status_code == 409
    assert duplicate_receipt.json()["error"]["code"] == "DUPLICATE_RECEIPT"

    summary = client.get("/analytics/summary")
    assert summary.status_code == 200
    assert summary.json()["employees_total"] == 2
    assert summary.json()["expense_claims_by_status"]["Paid"] == 1
    assert summary.json()["expense_claims_total_amount"] == "100.00"


def test_missing_manager_rejected_and_openapi_documents_api(client, database_session):
    employee, _ = seed_workflow_data(database_session, with_manager=False)
    response = client.post(
        "/leave/requests",
        json={
            "employee_id": employee.employee_id,
            "policy_id": "LP-001",
            "start_date": "2026-11-02",
            "end_date": "2026-11-02",
            "leave_type": "Annual",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "APPROVER_UNAVAILABLE"

    schema = client.get("/openapi.json").json()
    assert "/analytics/summary" in schema["paths"]
    assert "/leave/requests/{request_id}/approve" in schema["paths"]


def test_expense_rejection_flow(client, database_session):
    employee, manager = seed_workflow_data(database_session)
    submitted = client.post(
        "/expenses/claims",
        json={
            "claim_id": "EXP-2026-000003",
            "employee_id": employee.employee_id,
            "cost_center_id": "CC-001",
            "currency": "USD",
            "submission_date": "2026-10-31",
            "lines": [
                {
                    "policy_id": "EP-001",
                    "amount": "40.00",
                    "description": "Taxi",
                    "expense_date": "2026-10-30",
                    "receipt_hash": "receipt-rejected",
                    "receipt_url": "https://example.test/receipt-rejected",
                }
            ],
        },
    )
    assert submitted.status_code == 201

    rejected = client.post(
        "/expenses/claims/EXP-2026-000003/reject",
        json={"approver_id": manager.employee_id, "reason": "Missing business purpose"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "Rejected"
    assert rejected.json()["decision_reason"] == "Missing business purpose"


def test_reference_workflow_and_approver_queue_endpoints(client, database_session):
    employee, manager = seed_workflow_data(database_session)
    finance = seed_employee(
        database_session, "EMP-000003", approval_role="Finance"
    )
    database_session.add(
        ApprovalRule(
            rule_id="AR-EXP-FINANCE",
            entity_type="Expense",
            threshold_amount=Decimal("50.00"),
            country_code="USA",
            category="Travel",
            approval_level=2,
            required_role="Finance",
            effective_from=date(2020, 1, 1),
        )
    )
    database_session.commit()
    leave = client.post(
        "/leave/requests",
        json={
            "employee_id": employee.employee_id,
            "policy_id": "LP-001",
            "start_date": "2026-11-02",
            "end_date": "2026-11-03",
            "leave_type": "Annual",
        },
    )
    expense = client.post(
        "/expenses/claims",
        json={
            "employee_id": employee.employee_id,
            "cost_center_id": "CC-001",
            "currency": "USD",
            "submission_date": "2026-10-31",
            "lines": [
                {
                    "policy_id": "EP-001",
                    "amount": "75.00",
                    "description": "Taxi",
                    "expense_date": "2026-10-30",
                    "receipt_hash": "workflow-receipt",
                }
            ],
        },
    )
    assert leave.status_code == 201
    assert expense.status_code == 201

    balances = client.get(f"/employees/{employee.employee_id}/leave-balances")
    assert balances.status_code == 200
    assert balances.json()[0]["pending_balance"] == "2.00"
    assert balances.json()[0]["available_balance"] == "18.00"
    assert client.get("/leave/policies?country=usa").json()[0]["country_code"] == "USA"
    assert client.get("/expenses/policies?country=USA").status_code == 200
    assert client.get("/cost-centers").json()[0]["cost_center_id"] == "CC-001"

    leave_workflow = client.get(
        f"/leave/requests/{leave.json()['request_id']}/workflow"
    )
    assert leave_workflow.status_code == 200
    assert leave_workflow.json()["approval_steps"][0]["approver_id"] == manager.employee_id

    expense_workflow = client.get(
        f"/expenses/claims/{expense.json()['claim_id']}/workflow"
    )
    assert expense_workflow.status_code == 200
    assert expense_workflow.json()["lines"][0]["policy_category"] == "Travel"
    assert expense_workflow.json()["budget_remaining"] == "9925.00"

    queue = client.get(f"/approvals/queue?approver_id={manager.employee_id}")
    assert queue.status_code == 200
    assert {item["request_id"] for item in queue.json()} == {
        leave.json()["request_id"],
        expense.json()["claim_id"],
    }
    assert client.get(
        f"/approvals/queue?approver_id={finance.employee_id}"
    ).json() == []
    approved_manager_step = client.post(
        f"/expenses/claims/{expense.json()['claim_id']}/approve",
        json={"approver_id": manager.employee_id},
    )
    assert approved_manager_step.status_code == 200
    finance_queue = client.get(
        f"/approvals/queue?approver_id={finance.employee_id}"
    ).json()
    assert [item["request_id"] for item in finance_queue] == [
        expense.json()["claim_id"]
    ]
