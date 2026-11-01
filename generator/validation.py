from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from .config import CLAIM_STATUSES, COUNTRIES, GeneratorConfig


class DatasetValidationError(ValueError):
    pass


TABLE_KEYS = {
    "employees": "employee_id",
    "leave_policies": "policy_id",
    "leave_balances": "balance_id",
    "leave_requests": "request_id",
    "expense_policies": "policy_id",
    "expense_claims": "claim_id",
    "expense_lines": "line_id",
    "cost_centers": "cost_center_id",
    "approval_rules": "rule_id",
    "approval_steps": "step_id",
    "reimbursements": "reimbursement_id",
    "public_holidays": "holiday_id",
}


def _fail(message: str) -> None:
    raise DatasetValidationError(message)


def _unique(rows: list[dict[str, Any]], key: str, table: str) -> None:
    values = [row[key] for row in rows]
    duplicates = [value for value, count in Counter(values).items() if count > 1]
    if duplicates:
        _fail(f"{table}.{key} contains duplicates: {duplicates[:3]}")


def _reference(
    rows: list[dict[str, Any]], field: str, parent_ids: set[str], table: str
) -> None:
    missing = [
        row[field]
        for row in rows
        if row.get(field) not in (None, "") and row.get(field) not in parent_ids
    ]
    if missing:
        _fail(f"{table}.{field} has missing references: {missing[:3]}")


def business_days(start: date, end: date, holidays: set[date]) -> int:
    count = 0
    current = start
    while current <= end:
        if current.weekday() < 5 and current not in holidays:
            count += 1
        current += timedelta(days=1)
    return count


def validate_dataset(
    tables: dict[str, list[dict[str, Any]]],
    ground_truth: list[dict[str, str]],
    anomaly_cases: list[dict[str, Any]],
    *,
    config: GeneratorConfig | None = None,
) -> dict[str, Any]:
    config = config or GeneratorConfig()
    expected_counts = {
        "employees": config.employees,
        "leave_policies": config.leave_policies,
        "leave_balances": config.employees,
        "leave_requests": config.leave_requests,
        "expense_claims": config.expense_claims,
    }
    for table, count in expected_counts.items():
        if len(tables[table]) != count:
            _fail(f"{table} expected {count} records, got {len(tables[table])}")

    for table, key in TABLE_KEYS.items():
        _unique(tables[table], key, table)
    if len(tables["expense_lines"]) < len(tables["expense_claims"]):
        _fail("Each expense claim must have at least one expense line")

    employees = {row["employee_id"]: row for row in tables["employees"]}
    leave_policies = {row["policy_id"]: row for row in tables["leave_policies"]}
    expense_policies = {row["policy_id"]: row for row in tables["expense_policies"]}
    centers = {row["cost_center_id"]: row for row in tables["cost_centers"]}
    claims = {row["claim_id"]: row for row in tables["expense_claims"]}
    leave_requests = {row["request_id"]: row for row in tables["leave_requests"]}
    lines_by_claim: dict[str, list[dict[str, Any]]] = defaultdict(list)
    steps_by_request: dict[str, list[dict[str, Any]]] = defaultdict(list)
    approvals = tables["approval_steps"]
    reimbursements = tables["reimbursements"]
    intentional = {row["entity_id"]: row for row in ground_truth}
    unexpected_overlap = 0

    if len({row["email"].casefold() for row in tables["employees"]}) != len(
        tables["employees"]
    ):
        _fail("Employee email addresses must be unique")
    if len(
        {
            (row["employee_id"], row["policy_id"], row["effective_date"])
            for row in tables["leave_balances"]
        }
    ) != len(tables["leave_balances"]):
        _fail("Leave balance employee/policy/effective-date snapshots must be unique")
    if len(
        {(row["country_code"], row["holiday_date"]) for row in tables["public_holidays"]}
    ) != len(tables["public_holidays"]):
        _fail("Public holidays must be unique by country and date")
    if len({row["entity_id"] for row in ground_truth}) != len(ground_truth):
        _fail("Ground-truth entity IDs must be unique")
    if len({row["case_id"] for row in anomaly_cases}) != len(anomaly_cases):
        _fail("Anomaly case IDs must be unique")

    _reference(tables["employees"], "manager_id", set(employees) | {""}, "employees")
    _reference(tables["leave_balances"], "employee_id", set(employees), "leave_balances")
    _reference(tables["leave_balances"], "policy_id", set(leave_policies), "leave_balances")
    _reference(tables["leave_requests"], "employee_id", set(employees), "leave_requests")
    _reference(tables["leave_requests"], "policy_id", set(leave_policies), "leave_requests")
    _reference(tables["expense_claims"], "employee_id", set(employees), "expense_claims")
    _reference(tables["expense_claims"], "cost_center_id", set(centers), "expense_claims")
    _reference(tables["expense_lines"], "claim_id", set(claims), "expense_lines")
    _reference(tables["expense_lines"], "policy_id", set(expense_policies), "expense_lines")
    _reference(tables["approval_steps"], "approver_id", set(employees), "approval_steps")
    _reference(
        tables["reimbursements"], "claim_id", set(claims), "reimbursements"
    )

    supported = set(COUNTRIES)
    for employee_id, row in employees.items():
        if row["country"] not in supported:
            _fail(f"Unsupported country on employee {employee_id}")
        if row["status"] not in {"Active", "Inactive", "Terminated"}:
            _fail(f"Invalid employee status on {employee_id}")
        if row["manager_id"] == employee_id:
            _fail(f"Employee {employee_id} manages themself")
        if row["termination_date"] and row["termination_date"] < row["hire_date"]:
            _fail(f"Invalid employment dates for employee {employee_id}")
        seen = {employee_id}
        manager_id = row["manager_id"]
        while manager_id:
            if manager_id in seen:
                _fail(f"Manager hierarchy cycle at employee {employee_id}")
            seen.add(manager_id)
            manager_id = employees[manager_id]["manager_id"]

    holidays_by_country: dict[str, set[date]] = defaultdict(set)
    for row in tables["public_holidays"]:
        if row["country_code"] not in supported:
            _fail(f"Unsupported public-holiday country {row['country_code']}")
        holidays_by_country[row["country_code"]].add(row["holiday_date"])

    for row in tables["leave_policies"]:
        if row["country_code"] not in supported:
            _fail(f"Unsupported leave-policy country {row['country_code']}")
        if row["annual_entitlement"] < 0 or row["carry_over_limit"] < 0:
            _fail(f"Negative leave entitlement or carry-over in {row['policy_id']}")
        if row["accrual_rate"] < 0 or (
            row["effective_to"] is not None
            and row["effective_to"] < row["effective_from"]
        ):
            _fail(f"Invalid leave policy values or dates in {row['policy_id']}")

    for row in tables["expense_policies"]:
        if row["country_code"] not in {"GLOBAL", *supported}:
            _fail(f"Unsupported expense-policy country {row['country_code']}")
        if row["max_amount"] < 0 or (
            row["effective_to"] is not None
            and row["effective_to"] < row["effective_from"]
        ):
            _fail(f"Invalid expense policy values or dates in {row['policy_id']}")

    for row in tables["cost_centers"]:
        if row["budget"] < 0:
            _fail(f"Negative cost-center budget in {row['cost_center_id']}")

    balance_by_employee = {row["employee_id"]: row for row in tables["leave_balances"]}
    for row in tables["leave_balances"]:
        employee = employees[row["employee_id"]]
        policy = leave_policies[row["policy_id"]]
        if policy["country_code"] != employee["country"]:
            _fail(f"Leave balance {row['balance_id']} has a non-applicable policy")

    for row in tables["leave_requests"]:
        if not row["request_id"].startswith("LVE-"):
            _fail(f"Invalid leave request ID: {row['request_id']}")
        if row["end_date"] < row["start_date"]:
            _fail(f"Leave request {row['request_id']} has reversed dates")
        if row["status"] not in {
            "Draft", "Pending", "Approved", "Rejected", "Cancelled"
        }:
            _fail(f"Invalid leave status on {row['request_id']}")
        employee = employees[row["employee_id"]]
        if row["start_date"] < employee["hire_date"] or (
            employee["termination_date"]
            and row["end_date"] > employee["termination_date"]
        ):
            _fail(f"Leave request {row['request_id']} is outside employment dates")
        expected = business_days(
            row["start_date"],
            row["end_date"],
            holidays_by_country[employee["country"]],
        )
        if Decimal(row["total_days"]) != Decimal(expected):
            _fail(f"Leave request {row['request_id']} has an incorrect day total")
        policy = leave_policies[row["policy_id"]]
        if policy["country_code"] != employee["country"]:
            _fail(f"Leave request {row['request_id']} has a non-applicable policy")
        if (
            policy["effective_from"] > row["start_date"]
            or (
                policy["effective_to"] is not None
                and policy["effective_to"] < row["end_date"]
            )
        ):
            _fail(f"Leave request {row['request_id']} is outside policy dates")

    approved_by_employee: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in tables["leave_requests"]:
        if row["status"] == "Approved":
            approved_by_employee[row["employee_id"]].append(row)
    for employee_id, approved in approved_by_employee.items():
        approved.sort(key=lambda row: row["start_date"])
        for previous, current in zip(approved, approved[1:]):
            if current["start_date"] <= previous["end_date"]:
                if current["request_id"] not in intentional:
                    unexpected_overlap += 1
                    _fail(f"Unlabelled overlapping approved leave for {employee_id}")

    for row in tables["expense_lines"]:
        lines_by_claim[row["claim_id"]].append(row)
    for claim_id, claim in claims.items():
        if not claim_id.startswith("EXP-"):
            _fail(f"Invalid expense claim ID: {claim_id}")
        lines = lines_by_claim[claim_id]
        if not config.min_expense_lines <= len(lines) <= config.max_expense_lines:
            _fail(f"Claim {claim_id} has {len(lines)} lines")
        if sum((Decimal(line["amount"]) for line in lines), Decimal("0")) != Decimal(
            claim["total_amount"]
        ):
            _fail(f"Claim {claim_id} total does not equal its line total")
        if claim["status"] not in CLAIM_STATUSES:
            _fail(f"Invalid status on claim {claim_id}")
        employee = employees[claim["employee_id"]]
        if (
            len(claim["currency"]) != 3
            or not claim["currency"].isalpha()
            or claim["currency"] != claim["currency"].upper()
        ):
            _fail(f"Invalid currency on claim {claim_id}")
        if claim["submission_date"] < employee["hire_date"] or (
            employee["termination_date"]
            and claim["submission_date"] > employee["termination_date"]
        ):
            _fail(f"Claim {claim_id} submission is outside employment dates")
        for line in lines:
            if not line["line_id"].startswith(f"EXPL-{claim_id}-"):
                _fail(f"Expense line {line['line_id']} does not belong to {claim_id}")
            policy = expense_policies[line["policy_id"]]
            if policy["country_code"] not in {"GLOBAL", employee["country"]}:
                _fail(f"Expense line {line['line_id']} has a non-applicable policy")
            if (
                policy["effective_from"] > line["expense_date"]
                or (
                    policy["effective_to"] is not None
                    and policy["effective_to"] < line["expense_date"]
                )
            ):
                _fail(f"Expense line {line['line_id']} uses an inactive policy")
            if line["expense_date"] < employee["hire_date"] or (
                employee["termination_date"]
                and line["expense_date"] > employee["termination_date"]
            ):
                if line["line_id"] not in intentional:
                    _fail(f"Expense line {line['line_id']} outside employment dates is unlabeled")
            if Decimal(line["amount"]) <= 0 or Decimal(line["amount"]) > Decimal(
                policy["max_amount"]
            ):
                _fail(f"Expense line {line['line_id']} violates its policy amount")
            if policy["requires_receipt"] and not (
                line["receipt_hash"] or line["receipt_url"]
            ):
                _fail(f"Expense line {line['line_id']} is missing required receipt metadata")

    receipt_hashes = Counter(
        row["receipt_hash"] for row in tables["expense_lines"] if row["receipt_hash"]
    )
    duplicate_hashes = [key for key, count in receipt_hashes.items() if count > 1]
    if duplicate_hashes:
        _fail(f"Duplicate receipt hashes in normal data: {duplicate_hashes[:3]}")

    negative_balance_ids = {
        row["entity_id"]
        for row in ground_truth
        if row["issue_type"] == "Negative Leave Balance"
    }
    for row in tables["leave_balances"]:
        available = (
            Decimal(row["accrued_balance"])
            - Decimal(row["used_balance"])
            - Decimal(row["pending_balance"])
        )
        if available < 0 and row["balance_id"] not in negative_balance_ids:
            _fail(f"Unlabelled negative leave balance: {row['balance_id']}")
        if available >= 0 and row["balance_id"] in negative_balance_ids:
            _fail(f"Ground-truth negative balance is not negative: {row['balance_id']}")
        if row["balance_id"] not in negative_balance_ids:
            policy = leave_policies[row["policy_id"]]
            employee = employees[row["employee_id"]]
            effective = row["effective_date"]
            months = max(
                0,
                (effective.year - employee["hire_date"].year) * 12
                + effective.month
                - employee["hire_date"].month,
            )
            expected_accrued = min(
                Decimal(policy["annual_entitlement"] + policy["carry_over_limit"]),
                Decimal(months) * Decimal(policy["accrual_rate"]),
            ).quantize(Decimal("0.01"))
            if Decimal(row["accrued_balance"]) != expected_accrued:
                _fail(f"Accrued balance is not derived from policy for {row['employee_id']}")

    for employee_id, row in balance_by_employee.items():
        expected_used = sum(
            (
                Decimal(request["total_days"])
                for request in leave_requests.values()
                if request["employee_id"] == employee_id
                and request["status"] == "Approved"
            ),
            Decimal("0"),
        )
        expected_pending = sum(
            (
                Decimal(request["total_days"])
                for request in leave_requests.values()
                if request["employee_id"] == employee_id
                and request["status"] == "Pending"
            ),
            Decimal("0"),
        )
        if Decimal(row["used_balance"]) != expected_used:
            _fail(f"Leave balance used amount is not derived for {employee_id}")
        if Decimal(row["pending_balance"]) != expected_pending:
            _fail(f"Leave balance pending amount is not derived for {employee_id}")

    split_candidates: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for claim_id, claim in claims.items():
        claim_categories = {expense_policies[line["policy_id"]]["category"] for line in lines_by_claim[claim_id]}
        if len(claim_categories) != 1:
            continue
        category = next(iter(claim_categories))
        split_candidates[
            (
                claim["employee_id"],
                claim["cost_center_id"],
                claim["currency"],
                category,
            )
        ].append(claim)
    for key, candidate_claims in split_candidates.items():
        candidate_claims.sort(key=lambda row: row["submission_date"])
        for previous, current in zip(candidate_claims, candidate_claims[1:]):
            if abs((current["submission_date"] - previous["submission_date"]).days) > 1:
                continue
            previous_amount = Decimal(previous["total_amount"])
            current_amount = Decimal(current["total_amount"])
            if previous_amount < Decimal("500") and current_amount < Decimal("500"):
                if previous_amount + current_amount >= Decimal("500"):
                    if previous["claim_id"] not in intentional and current["claim_id"] not in intentional:
                        _fail(f"Unlabelled split-claim pair: {previous['claim_id']}, {current['claim_id']}")

    for row in approvals:
        has_leave_request = row["leave_request_id"] not in (None, "")
        has_expense_claim = row["expense_claim_id"] not in (None, "")
        if has_leave_request == has_expense_claim:
            _fail(f"Approval step {row['step_id']} must reference exactly one request")
        if row["status"] not in {"Pending", "Approved", "Rejected"}:
            _fail(f"Invalid approval status on {row['step_id']}")
        expected_prefix = f"APR-{row['leave_request_id'] or row['expense_claim_id']}-"
        if not row["step_id"].startswith(expected_prefix):
            _fail(f"Approval ID does not match request: {row['step_id']}")
        request_id = row["leave_request_id"] or row["expense_claim_id"]
        target = leave_requests.get(request_id) or claims.get(request_id)
        if target is None:
            _fail(f"Approval step {row['step_id']} has no request")
        if target["employee_id"] == row["approver_id"]:
            if row["step_id"] not in intentional:
                _fail(f"Self-approval {row['step_id']} is not labelled")
        if row["status"] == "Pending" and row["action_date"] is not None:
            _fail(f"Pending approval {row['step_id']} has an action timestamp")
        if row["status"] != "Pending" and row["action_date"] is None:
            _fail(f"Resolved approval {row['step_id']} has no action timestamp")
        steps_by_request[request_id].append(row)

    for request_id, request_steps in steps_by_request.items():
        sequences = [step["sequence"] for step in request_steps]
        if len(sequences) != len(set(sequences)):
            _fail(f"Approval sequences are duplicated for {request_id}")

    for request_id, request in {**leave_requests, **claims}.items():
        steps = sorted(steps_by_request.get(request_id, []), key=lambda row: row["sequence"])
        if request["status"] in {"Pending", "Approved", "Paid", "Rejected"} and not steps:
            _fail(f"Workflow request {request_id} has no approval steps")
        if request["status"] in {"Approved", "Paid"} and any(
            step["status"] != "Approved" for step in steps
        ):
            _fail(f"Final request {request_id} has unresolved approval steps")
        if request["status"] == "Rejected" and any(
            step["status"] == "Pending" for step in steps
        ):
            _fail(f"Rejected request {request_id} has pending approval steps")
        if request["status"] == "Rejected" and not any(
            step["status"] == "Rejected" for step in steps
        ):
            _fail(f"Rejected request {request_id} has no rejected approval")
        if request["status"] == "Pending" and steps and all(
            step["status"] != "Pending" for step in steps
        ):
            _fail(f"Pending request {request_id} has no pending approval")
        if steps and [step["sequence"] for step in steps] != list(
            range(1, len(steps) + 1)
        ):
            _fail(f"Approval sequence is not contiguous for {request_id}")
        if request_id in claims and request["status"] != "Draft":
            employee = employees[request["employee_id"]]
            if employee["manager_id"] and (
                not steps
                or steps[0]["approver_id"] != employee["manager_id"]
            ):
                if request_id not in intentional:
                    _fail(f"Manager is not first approver for {request_id}")
            if Decimal(request["total_amount"]) >= Decimal("500") and not any(
                employees[step["approver_id"]]["approval_role"] == "Finance"
                for step in steps
            ):
                if request_id not in intentional:
                    _fail(f"Finance approval missing above threshold for {request_id}")

    reimbursed_claim_ids = set()
    for row in reimbursements:
        claim = claims[row["claim_id"]]
        if row["status"] not in {"Pending", "Processed"}:
            _fail(f"Invalid reimbursement status on {row['reimbursement_id']}")
        if Decimal(row["amount"]) <= 0:
            _fail(f"Reimbursement {row['reimbursement_id']} must be positive")
        if (row["status"] == "Processed") != (row["processed_at"] is not None):
            _fail(f"Reimbursement {row['reimbursement_id']} has inconsistent lifecycle fields")
        if claim["status"] != "Paid":
            _fail(f"Reimbursement {row['reimbursement_id']} is not for a paid claim")
        if Decimal(row["amount"]) > Decimal(claim["total_amount"]):
            _fail(f"Reimbursement {row['reimbursement_id']} exceeds claim amount")
        if row["claim_id"] in reimbursed_claim_ids:
            _fail(f"Duplicate reimbursement for {row['claim_id']}")
        reimbursed_claim_ids.add(row["claim_id"])
    if any(row["status"] == "Paid" and row["claim_id"] not in reimbursed_claim_ids for row in tables["expense_claims"]):
        _fail("Paid expense claim is missing reimbursement")

    valid_ground_labels = {"Anomaly", "Edge Case"}
    for row in ground_truth:
        if row["label"] not in valid_ground_labels:
            _fail(f"Invalid ground-truth label {row['label']}")
    required_issues = {
        "Negative Leave Balance",
        "Overlapping Approved Leave",
        "Expense Outside Employment Dates",
        "Split Claims",
        "Missing Cost Center",
        "Requester Self Approval",
        "Duplicate Reimbursement",
        "Weekend Leave",
        "Holiday Leave",
        "Exact Approval Threshold",
        "Above Approval Threshold",
        "Duplicate Receipt Hash",
        "Expired Policy",
        "No Manager - Valid Top Level",
        "Partial Approval Then Rejection",
        "Missing Receipt",
        "Expense Policy Limit Breach",
    }
    missing_issues = required_issues - {row["issue_type"] for row in ground_truth}
    if missing_issues:
        _fail(f"Required ground-truth cases are missing: {sorted(missing_issues)}")
    case_ids = {row["case_id"] for row in anomaly_cases}
    record_ids: set[str] = set()
    for table, rows in tables.items():
        key = TABLE_KEYS.get(table)
        if key is not None:
            record_ids.update(row[key] for row in rows)
        elif table == "expense_lines":
            record_ids.update(row["line_id"] for row in rows)
    record_ids.update(row["case_id"] for row in anomaly_cases)
    for row in ground_truth:
        entity_id = row["entity_id"]
        if entity_id not in record_ids:
            _fail(f"Ground-truth entity does not exist: {entity_id}")

    return {
        "tables": {table: len(rows) for table, rows in tables.items()},
        "ground_truth_rows": len(ground_truth),
        "anomaly_case_rows": len(anomaly_cases),
        "unlabelled_overlaps": unexpected_overlap,
    }
