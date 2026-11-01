from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .config import ANOMALY_CASE_IDS, COUNTRIES, DEPARTMENTS, GeneratorConfig
from .ground_truth import build_ground_truth
from .validation import validate_dataset

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "generated"
TABLE_ORDER = (
    "employees",
    "leave_policies",
    "expense_policies",
    "cost_centers",
    "approval_rules",
    "public_holidays",
    "leave_requests",
    "leave_balances",
    "expense_claims",
    "expense_lines",
    "approval_steps",
    "reimbursements",
)


def _money(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"))


def _utc(value: date, hour: int = 9) -> datetime:
    return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc).replace(
        hour=hour
    )


def _weekdays(start: date, count: int, holidays: set[date]) -> tuple[date, date, int]:
    days: list[date] = []
    current = start
    while len(days) < count:
        if current.weekday() < 5 and current not in holidays:
            days.append(current)
        current += timedelta(days=1)
    return days[0], days[-1], len(days)


def _parents(config: GeneratorConfig) -> dict[str, list[dict[str, Any]]]:
    rng = random.Random(config.seed)
    employees: list[dict[str, Any]] = []
    for number in range(1, config.employees + 1):
        employee_id = f"EMP-{number:06d}"
        manager_number = None if number == 1 else max(1, number // 2)
        hire_date = date(2014 + rng.randrange(10), 1, 1) + timedelta(
            days=rng.randrange(365)
        )
        role = (
            "CEO"
            if number == 1
            else "Finance"
            if number in {2, 3}
            else "Manager"
            if number % 12 == 0
            else None
        )
        employees.append(
            {
                "employee_id": employee_id,
                "name": f"Synthetic Employee {number:03d}",
                "email": f"employee{number:03d}@example.test",
                "manager_id": f"EMP-{manager_number:06d}" if manager_number else None,
                "department": DEPARTMENTS[(number - 1) % len(DEPARTMENTS)],
                "country": COUNTRIES[(number - 1) % len(COUNTRIES)],
                "hire_date": hire_date,
                "termination_date": None,
                "status": "Active",
                "approval_role": role,
            }
        )
    employees[2]["hire_date"] = max(employees[2]["hire_date"], date(2021, 1, 1))

    leave_policies = []
    policy_countries = ["USA", "UK", "CAN", "GER", "IND", "USA"]
    for number, country in enumerate(policy_countries, start=1):
        leave_policies.append(
            {
                "policy_id": f"LP-{number:03d}",
                "policy_name": f"{country} Annual Leave {number}",
                "annual_entitlement": 30,
                "carry_over_limit": 10,
                "accrual_rate": Decimal("2.500"),
                "country_code": country,
                "effective_from": date(2020, 1, 1),
                "effective_to": None,
            }
        )

    expense_categories = (
        ("Travel", Decimal("2000")),
        ("Meals", Decimal("500")),
        ("Software", Decimal("1000")),
        ("Office Supplies", Decimal("500")),
        ("Client Entertainment", Decimal("1000")),
    )
    expense_policies = [
        {
            "policy_id": f"EP-{number:03d}",
            "category": category,
            "max_amount": maximum,
            "requires_receipt": True,
            "country_code": "GLOBAL",
            "effective_from": date(2020, 1, 1),
            "effective_to": None,
        }
        for number, (category, maximum) in enumerate(expense_categories, start=1)
    ]
    expense_policies.append(
        {
            "policy_id": "EP-EXP",
            "category": "Travel",
            "max_amount": Decimal("2000"),
            "requires_receipt": True,
            "country_code": "GLOBAL",
            "effective_from": date(2018, 1, 1),
            "effective_to": date(2025, 12, 31),
        }
    )

    cost_centers = [
        {
            "cost_center_id": f"CC-{number:03d}",
            "name": f"{department} Cost Center",
            "budget": Decimal("10000000.00"),
            "department": department,
        }
        for number, department in enumerate(DEPARTMENTS, start=1)
    ]
    approval_rules = [
        {
            "rule_id": "AR-001",
            "entity_type": "Leave",
            "threshold_amount": None,
            "country_code": None,
            "category": None,
            "approval_level": 1,
            "required_role": "Manager",
            "effective_from": _utc(date(2020, 1, 1)),
            "effective_to": None,
        },
        {
            "rule_id": "AR-002",
            "entity_type": "Expense",
            "threshold_amount": None,
            "country_code": None,
            "category": None,
            "approval_level": 1,
            "required_role": "Manager",
            "effective_from": _utc(date(2020, 1, 1)),
            "effective_to": None,
        },
        {
            "rule_id": "AR-003",
            "entity_type": "Expense",
            "threshold_amount": Decimal("500.00"),
            "country_code": None,
            "category": None,
            "approval_level": 2,
            "required_role": "Finance",
            "effective_from": _utc(date(2020, 1, 1)),
            "effective_to": None,
        },
        {
            "rule_id": "AR-004",
            "entity_type": "Expense",
            "threshold_amount": None,
            "country_code": "GER",
            "category": "Client Entertainment",
            "approval_level": 2,
            "required_role": "Finance",
            "effective_from": _utc(date(2020, 1, 1)),
            "effective_to": None,
        },
    ]

    holidays = [
        {
            "holiday_id": f"HOL-{country}-001",
            "country_code": country,
            "holiday_date": date(2026, 5, 1),
            "name": "Synthetic Spring Holiday",
        }
        for country in COUNTRIES
    ]
    return {
        "employees": employees,
        "leave_policies": leave_policies,
        "expense_policies": expense_policies,
        "cost_centers": cost_centers,
        "approval_rules": approval_rules,
        "public_holidays": holidays,
    }


def _manager_chain(
    employee: dict[str, Any], by_id: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    chain: list[dict[str, Any]] = []
    manager_id = employee["manager_id"]
    seen = {employee["employee_id"]}
    while manager_id:
        if manager_id in seen:
            raise ValueError(f"Manager cycle for {employee['employee_id']}")
        seen.add(manager_id)
        manager = by_id[manager_id]
        chain.append(manager)
        manager_id = manager["manager_id"]
    return chain


def _approvers(
    employee: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    rules: list[dict[str, Any]],
    *,
    entity_type: str,
    amount: Decimal,
    country: str,
    categories: set[str],
    effective_date: date,
) -> list[dict[str, Any]]:
    managers = _manager_chain(employee, by_id)
    chain = [managers[0]] if managers else []
    applicable = [
        row
        for row in rules
        if row["entity_type"] == entity_type
        and (row["country_code"] is None or row["country_code"] == country)
        and (row["category"] is None or row["category"] in categories)
        and (row["threshold_amount"] is None or amount >= row["threshold_amount"])
        and row["effective_from"].date() <= effective_date
        and (row["effective_to"] is None or row["effective_to"].date() >= effective_date)
    ]
    for rule in sorted(
        applicable, key=lambda row: (row["approval_level"], row["required_role"])
    ):
        if any(
            person["approval_role"] == rule["required_role"] for person in chain
        ):
            continue
        if rule["required_role"] == "Manager":
            candidate = managers[0] if managers else None
        else:
            candidate = next(
                (
                    manager
                    for manager in managers
                    if manager["approval_role"] == rule["required_role"]
                    and all(
                        row["employee_id"] != manager["employee_id"]
                        for row in chain
                    )
                ),
                None,
            )
            if candidate is None:
                candidate = next(
                    (
                        person
                        for person in by_id.values()
                        if person["approval_role"] == rule["required_role"]
                        and person["employee_id"] != employee["employee_id"]
                        and all(
                            row["employee_id"] != person["employee_id"]
                            for row in chain
                        )
                    ),
                    None,
                )
        if candidate is None or candidate["employee_id"] == employee["employee_id"]:
            raise ValueError(
                f"No eligible approver for {employee['employee_id']} and {rule['required_role']}"
            )
        if all(row["employee_id"] != candidate["employee_id"] for row in chain):
            chain.append(candidate)
    if not chain:
        raise ValueError(f"No approver chain for {employee['employee_id']}")
    return chain


def _approval_records(
    request_id: str,
    employee: dict[str, Any],
    chain: list[dict[str, Any]],
    status: str,
    *,
    partial_rejection: bool = False,
) -> list[dict[str, Any]]:
    if status in {"Draft", "Cancelled"}:
        return []
    now = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    records: list[dict[str, Any]] = []
    for sequence, approver in enumerate(chain, start=1):
        step_status = "Approved" if status == "Paid" else status
        reason = None
        action_date = now - timedelta(days=sequence)
        if status == "Pending":
            step_status = "Pending"
            action_date = None
        elif status == "Rejected":
            if partial_rejection and sequence == 1:
                step_status = "Approved"
                reason = "Initial manager review approved"
            else:
                step_status = "Rejected"
                reason = "Rejected after review" if sequence == 1 else "Closed after rejection"
        records.append(
            {
                "step_id": f"APR-{request_id}-{sequence:02d}",
                "leave_request_id": request_id if request_id.startswith("LVE-") else None,
                "expense_claim_id": request_id if request_id.startswith("EXP-") else None,
                "approver_id": approver["employee_id"],
                "sequence": sequence,
                "status": step_status,
                "action_date": action_date,
                "decision_reason": reason,
                "comments": None,
            }
        )
    return records


def _leave_requests_and_balances(
    config: GeneratorConfig,
    parents: dict[str, list[dict[str, Any]]],
    ground_cases: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    rng = random.Random(config.seed ^ 0x1EA7)
    employees = parents["employees"]
    employee_by_id = {row["employee_id"]: row for row in employees}
    policy_by_country = {
        row["country_code"]: row for row in parents["leave_policies"] if row["policy_id"] != "LP-006"
    }
    policy_by_country["USA"] = next(
        row for row in parents["leave_policies"] if row["policy_id"] == "LP-001"
    )
    holidays = {
        row["country_code"]: {row["holiday_date"]}
        for row in parents["public_holidays"]
    }
    assignments = ["EMP-000002", "EMP-000002"]
    while len(assignments) < config.leave_requests:
        assignments.extend(
            employee["employee_id"] for employee in employees[1:] for _ in range(2)
        )
    assignments = assignments[: config.leave_requests]
    leave_requests: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    per_employee_count: dict[str, int] = defaultdict(int)
    statuses = ("Approved", "Approved", "Pending", "Rejected", "Draft", "Cancelled")
    for number, employee_id in enumerate(assignments, start=1):
        person = employee_by_id[employee_id]
        ordinal = per_employee_count[employee_id]
        per_employee_count[employee_id] += 1
        start = date(2026, 2, 2) + timedelta(days=ordinal * 75 + (number % 5) * 2)
        while start.weekday() >= 5:
            start += timedelta(days=1)
        policy = policy_by_country[person["country"]]
        status = statuses[(number - 1) % len(statuses)]
        if number in {1, 2}:
            status = "Approved"
        if number == 2:
            start = date(2026, 2, 2) + timedelta(days=(1 % 5) * 2)
        duration = 1 + rng.randrange(3)
        holiday_dates = holidays.get(person["country"], set())
        start_date, end_date, days = _weekdays(start, duration, holiday_dates)
        if number in {1, 2}:
            start_date, end_date, days = date(2026, 2, 2), date(2026, 2, 3), 2
        request_id = f"LVE-{config.year}-{number:06d}"
        request = {
            "request_id": request_id,
            "employee_id": employee_id,
            "policy_id": policy["policy_id"],
            "start_date": start_date,
            "end_date": end_date,
            "total_days": Decimal(days),
            "leave_type": ("Annual", "Sick", "Personal")[(number - 1) % 3],
            "status": status,
            "requested_at": _utc(start_date - timedelta(days=10), 15),
            "decided_at": _utc(start_date - timedelta(days=2))
            if status in {"Approved", "Rejected"}
            else None,
            "decision_reason": "Synthetic decision" if status in {"Approved", "Rejected"} else None,
        }
        leave_requests.append(request)
        if status not in {"Draft", "Cancelled"}:
            chain = _approvers(
                person,
                employee_by_id,
                parents["approval_rules"],
                entity_type="Leave",
                amount=Decimal(days),
                country=person["country"],
                categories={request["leave_type"]},
                effective_date=start_date,
            )
            steps.extend(_approval_records(request_id, person, chain, status))

    ground_cases.extend(
        [
            {
                "entity_id": leave_requests[1]["request_id"],
                "issue_type": "Overlapping Approved Leave",
                "label": "Anomaly",
            },
            {
                "entity_id": "EMP-000001",
                "issue_type": "No Manager - Valid Top Level",
                "label": "Edge Case",
            },
        ]
    )
    holiday_day = date(2026, 5, 1)
    # Explicit, deterministic requests exercise weekend and public-holiday rules.
    for request in leave_requests:
        if request["request_id"] == f"LVE-{config.year}-000003":
            request.update(
                start_date=date(2026, 11, 7),
                end_date=date(2026, 11, 8),
                total_days=Decimal("0"),
                status="Draft",
                decision_reason=None,
                decided_at=None,
            )
            steps = [
                step for step in steps
                if step["leave_request_id"] != request["request_id"]
            ]
            ground_cases.append(
                {
                    "entity_id": request["request_id"],
                    "issue_type": "Weekend Leave",
                    "label": "Edge Case",
                }
            )
        elif request["request_id"] == f"LVE-{config.year}-000004":
            request.update(
                start_date=date(2026, 4, 30),
                end_date=date(2026, 5, 1),
                total_days=Decimal("1"),
            )
            ground_cases.append(
                {
                    "entity_id": request["request_id"],
                    "issue_type": "Holiday Leave",
                    "label": "Edge Case",
                }
            )

    accrued_by_employee = {
        person["employee_id"]: min(
            Decimal(policy_by_country[person["country"]]["annual_entitlement"])
            + Decimal(policy_by_country[person["country"]]["carry_over_limit"]),
            Decimal(
                max(
                    0,
                    (date(2026, 10, 31).year - person["hire_date"].year) * 12
                    + date(2026, 10, 31).month
                    - person["hire_date"].month,
                )
            )
            * Decimal(policy_by_country[person["country"]]["accrual_rate"]),
        )
        for person in employees
    }
    balances: list[dict[str, Any]] = []
    for number, person in enumerate(employees, start=1):
        policy = policy_by_country[person["country"]]
        used = sum(
            (
                row["total_days"]
                for row in leave_requests
                if row["employee_id"] == person["employee_id"]
                and row["status"] == "Approved"
                and row["request_id"] not in {"LVE-2026-000003", "LVE-2026-000004"}
            ),
            Decimal("0"),
        )
        pending = sum(
            (
                row["total_days"]
                for row in leave_requests
                if row["employee_id"] == person["employee_id"]
                and row["status"] == "Pending"
            ),
            Decimal("0"),
        )
        accrued = accrued_by_employee[person["employee_id"]]
        negative_balance_employee = employees[min(248, len(employees) - 1)]["employee_id"]
        if person["employee_id"] == negative_balance_employee:
            accrued = Decimal("-5.00")
            ground_cases.append(
                {
                    "entity_id": f"LB-{number:06d}",
                    "issue_type": "Negative Leave Balance",
                    "label": "Anomaly",
                }
            )
        balances.append(
            {
                "balance_id": f"LB-{number:06d}",
                "employee_id": person["employee_id"],
                "policy_id": policy["policy_id"],
                "accrued_balance": _money(accrued),
                "used_balance": _money(used),
                "pending_balance": _money(pending),
                "effective_date": date(2026, 10, 31),
            }
        )
    return leave_requests, balances, steps


def _expense_data(
    config: GeneratorConfig,
    parents: dict[str, list[dict[str, Any]]],
    ground_cases: list[dict[str, str]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    rng = random.Random(config.seed ^ 0xE7E5)
    employees = parents["employees"]
    employee_by_id = {row["employee_id"]: row for row in employees}
    active_expense_policies = [
        row for row in parents["expense_policies"] if row["policy_id"] != "EP-EXP"
    ]
    centers = parents["cost_centers"]
    status_by_number = (
        ["Draft"] * 200
        + ["Pending"] * 180
        + ["Approved"] * 220
        + ["Rejected"] * 200
        + ["Paid"] * 200
    )
    claims: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    reimbursements: list[dict[str, Any]] = []
    hashes: list[str] = []
    for number in range(1, config.expense_claims + 1):
        person = employees[1 + ((number - 1) % (len(employees) - 1))]
        claim_id = f"EXP-{config.year}-{number:06d}"
        submission_date = date(2026, 1, 5) + timedelta(days=(number - 1) % 300)
        status = status_by_number[(number - 1) % len(status_by_number)]
        if number == config.expense_claims and config.expense_claims < 801:
            status = "Paid"
        if number in {1, 2}:
            status = "Approved"
        if number in {4, 5}:
            person = employees[min(9, len(employees) - 1)]
            status = "Pending"
            submission_date = date(2026, 6, 1) + timedelta(days=number - 4)
        if number == 3:
            person = employees[2]
        if number == 6:
            person = employees[min(9, len(employees) - 1)]
            status = "Rejected"

        if number == 1:
            line_count = 1
            fixed_total = Decimal("500.00")
        elif number == 2:
            line_count = 1
            fixed_total = Decimal("501.00")
        elif number == 4:
            line_count = 1
            fixed_total = Decimal("300.00")
        elif number == 5:
            line_count = 1
            fixed_total = Decimal("250.00")
        elif number == 6:
            line_count = 1
            fixed_total = Decimal("600.00")
        else:
            line_count = rng.randint(config.min_expense_lines, config.max_expense_lines)
            fixed_total = None

        claim_lines: list[dict[str, Any]] = []
        for sequence in range(1, line_count + 1):
            policy = active_expense_policies[(number + sequence - 2) % len(active_expense_policies)]
            if number in {1, 2, 4, 5, 6}:
                policy = active_expense_policies[0]
            if fixed_total is not None:
                amount = fixed_total if sequence == 1 else Decimal("0")
            else:
                amount = _money(Decimal(rng.randint(1500, 18000)) / 100)
                amount = min(amount, Decimal(policy["max_amount"]))
            expense_date = submission_date - timedelta(days=rng.randint(0, 30))
            if expense_date < person["hire_date"]:
                expense_date = person["hire_date"]
            receipt_hash = f"sha256-{config.seed}-{number:06d}-{sequence:02d}"
            if number == 3 and sequence == 1:
                expense_date = person["hire_date"] - timedelta(days=1)
                ground_cases.append(
                    {
                        "entity_id": f"EXPL-{claim_id}-{sequence:02d}",
                        "issue_type": "Expense Outside Employment Dates",
                        "label": "Anomaly",
                    }
                )
            claim_lines.append(
                {
                    "line_id": f"EXPL-{claim_id}-{sequence:02d}",
                    "claim_id": claim_id,
                    "policy_id": policy["policy_id"],
                    "amount": amount,
                    "description": f"Synthetic {policy['category']} expense",
                    "expense_date": expense_date,
                    "receipt_hash": receipt_hash,
                    "receipt_url": f"https://receipts.example.test/{receipt_hash}",
                }
            )
            hashes.append(receipt_hash)

        total_amount = sum((row["amount"] for row in claim_lines), Decimal("0"))
        center = centers[(number - 1) % len(centers)]
        if number == 5:
            center = centers[3]
        claim = {
            "claim_id": claim_id,
            "employee_id": person["employee_id"],
            "cost_center_id": center["cost_center_id"],
            "total_amount": _money(total_amount),
            "currency": "USD",
            "status": status,
            "submission_date": submission_date,
            "decided_at": _utc(submission_date + timedelta(days=2))
            if status in {"Approved", "Rejected", "Paid"}
            else None,
            "decision_reason": "Synthetic decision"
            if status in {"Approved", "Rejected", "Paid"}
            else None,
        }
        claims.append(claim)
        lines.extend(claim_lines)

        if status not in {"Draft"}:
            categories = {
                next(
                    row["category"]
                    for row in active_expense_policies
                    if row["policy_id"] == line["policy_id"]
                )
                for line in claim_lines
            }
            chain = _approvers(
                person,
                employee_by_id,
                parents["approval_rules"],
                entity_type="Expense",
                amount=claim["total_amount"],
                country=person["country"],
                categories=categories,
                effective_date=submission_date,
            )
            steps.extend(
                _approval_records(
                    claim_id,
                    person,
                    chain,
                    status,
                    partial_rejection=number == 6,
                )
            )
        if status == "Paid":
            reimbursement_number = len(reimbursements) + 1
            reimbursements.append(
                {
                    "reimbursement_id": f"RMB-{config.year}-{reimbursement_number:06d}",
                    "claim_id": claim_id,
                    "amount": claim["total_amount"],
                    "payment_date": submission_date + timedelta(days=10),
                    "transaction_ref": f"TX-{config.seed}-{reimbursement_number:06d}",
                    "status": "Processed",
                    "processed_at": _utc(submission_date + timedelta(days=10)),
                    "decision_reason": "Synthetic reimbursement processed",
                }
            )

    # Force the exact-threshold and above-threshold claims to have two ordered steps.
    ground_cases.extend(
        [
            {
                "entity_id": claims[0]["claim_id"],
                "issue_type": "Exact Approval Threshold",
                "label": "Edge Case",
            },
            {
                "entity_id": claims[1]["claim_id"],
                "issue_type": "Above Approval Threshold",
                "label": "Edge Case",
            },
            {
                "entity_id": claims[3]["claim_id"],
                "issue_type": "Split Claims",
                "label": "Anomaly",
            },
            {
                "entity_id": "CASE-MISSING-COST-CENTER",
                "issue_type": "Missing Cost Center",
                "label": "Anomaly",
            },
            {
                "entity_id": "CASE-DUPLICATE-RECEIPT",
                "issue_type": "Duplicate Receipt Hash",
                "label": "Anomaly",
            },
            {
                "entity_id": "CASE-DUPLICATE-REIMBURSEMENT",
                "issue_type": "Duplicate Reimbursement",
                "label": "Anomaly",
            },
            {
                "entity_id": "CASE-EXPIRED-POLICY",
                "issue_type": "Expired Policy",
                "label": "Edge Case",
            },
            {
                "entity_id": ANOMALY_CASE_IDS["missing_receipt"],
                "issue_type": "Missing Receipt",
                "label": "Anomaly",
            },
            {
                "entity_id": ANOMALY_CASE_IDS["policy_limit_breach"],
                "issue_type": "Expense Policy Limit Breach",
                "label": "Anomaly",
            },
            {
                "entity_id": claims[5]["claim_id"],
                "issue_type": "Partial Approval Then Rejection",
                "label": "Edge Case",
            },
        ]
    )

    first_expense_approver = next(
        row for row in steps if row["expense_claim_id"] == claims[0]["claim_id"]
    )
    first_expense_approver["approver_id"] = claims[0]["employee_id"]
    ground_cases.append(
        {
            "entity_id": first_expense_approver["step_id"],
            "issue_type": "Requester Self Approval",
            "label": "Anomaly",
        }
    )
    anomaly_cases = [
        {
            "case_id": ANOMALY_CASE_IDS["split_claim"],
            "case_type": "split_claim",
            "related_entity_ids": json.dumps([claims[3]["claim_id"], claims[4]["claim_id"]]),
            "input_data": json.dumps(
                {"same_employee": claims[3]["employee_id"], "combined_amount": "550.00", "threshold": "500.00"},
                sort_keys=True,
            ),
            "expected_code": "POTENTIAL_SPLIT_CLAIM",
        },
        {
            "case_id": ANOMALY_CASE_IDS["missing_cost_center"],
            "case_type": "missing_cost_center",
            "related_entity_ids": json.dumps([]),
            "input_data": json.dumps(
                {"employee_id": "EMP-000010", "cost_center_id": "CC-MISSING"},
                sort_keys=True,
            ),
            "expected_code": "COST_CENTER_NOT_FOUND",
        },
        {
            "case_id": ANOMALY_CASE_IDS["duplicate_receipt"],
            "case_type": "duplicate_receipt",
            "related_entity_ids": json.dumps([lines[0]["line_id"]]),
            "input_data": json.dumps(
                {"receipt_hash": lines[0]["receipt_hash"]}, sort_keys=True
            ),
            "expected_code": "DUPLICATE_RECEIPT",
        },
        {
            "case_id": ANOMALY_CASE_IDS["duplicate_reimbursement"],
            "case_type": "duplicate_reimbursement",
            "related_entity_ids": json.dumps([reimbursements[0]["claim_id"]]),
            "input_data": json.dumps(
                {"claim_id": reimbursements[0]["claim_id"], "amount": str(reimbursements[0]["amount"])},
                sort_keys=True,
            ),
            "expected_code": "DUPLICATE_REIMBURSEMENT",
        },
        {
            "case_id": ANOMALY_CASE_IDS["expired_policy"],
            "case_type": "expired_policy",
            "related_entity_ids": json.dumps(["EP-EXP"]),
            "input_data": json.dumps(
                {"policy_id": "EP-EXP", "expense_date": "2026-01-01"},
                sort_keys=True,
            ),
            "expected_code": "EXPENSE_POLICY_EXPIRED",
        },
        {
            "case_id": ANOMALY_CASE_IDS["partial_rejection"],
            "case_type": "partial_approval_then_rejection",
            "related_entity_ids": json.dumps([claims[5]["claim_id"]]),
            "input_data": json.dumps(
                {"approved_steps": 1, "rejected_step": 2}, sort_keys=True
            ),
            "expected_code": "PARTIAL_APPROVAL_THEN_REJECTION",
        },
        {
            "case_id": ANOMALY_CASE_IDS["missing_receipt"],
            "case_type": "missing_receipt",
            "related_entity_ids": json.dumps([]),
            "input_data": json.dumps(
                {
                    "employee_id": claims[0]["employee_id"],
                    "cost_center_id": claims[0]["cost_center_id"],
                    "currency": claims[0]["currency"],
                    "submission_date": claims[0]["submission_date"].isoformat(),
                    "lines": [
                        {
                            "policy_id": "EP-001",
                            "amount": "25.00",
                            "description": "Receipt-required taxi",
                            "expense_date": claims[0]["submission_date"].isoformat(),
                            "receipt_hash": None,
                            "receipt_url": None,
                        }
                    ],
                },
                sort_keys=True,
            ),
            "expected_code": "RECEIPT_REQUIRED",
        },
        {
            "case_id": ANOMALY_CASE_IDS["policy_limit_breach"],
            "case_type": "policy_limit_breach",
            "related_entity_ids": json.dumps(["EP-002"]),
            "input_data": json.dumps(
                {
                    "employee_id": claims[0]["employee_id"],
                    "cost_center_id": claims[0]["cost_center_id"],
                    "currency": claims[0]["currency"],
                    "submission_date": claims[0]["submission_date"].isoformat(),
                    "lines": [
                        {
                            "policy_id": "EP-002",
                            "amount": "500.01",
                            "description": "Over-limit meal",
                            "expense_date": claims[0]["submission_date"].isoformat(),
                            "receipt_hash": "anomaly-policy-limit-breach",
                            "receipt_url": "https://receipts.example.test/anomaly-policy-limit-breach",
                        }
                    ],
                },
                sort_keys=True,
            ),
            "expected_code": "POLICY_LIMIT_EXCEEDED",
        },
    ]
    return claims, lines, steps, reimbursements, anomaly_cases


def build_dataset(
    config: GeneratorConfig,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, str]], list[dict[str, Any]]]:
    parents = _parents(config)
    ground_cases: list[dict[str, str]] = []
    leave_requests, balances, leave_steps = _leave_requests_and_balances(
        config, parents, ground_cases
    )
    claims, lines, expense_steps, reimbursements, anomaly_cases = _expense_data(
        config, parents, ground_cases
    )
    tables = {
        **parents,
        "leave_requests": leave_requests,
        "leave_balances": balances,
        "expense_claims": claims,
        "expense_lines": lines,
        "approval_steps": leave_steps + expense_steps,
        "reimbursements": reimbursements,
    }
    ground_truth = build_ground_truth(ground_cases)
    return tables, ground_truth, anomaly_cases


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if isinstance(value, bool):
        return "True" if value else "False"
    return str(value)


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, Decimal)):
        return str(value)
    if isinstance(value, (datetime, date)):
        value = value.isoformat()
    return "'" + str(value).replace("'", "''") + "'"


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"Cannot write CSV without a header: {path.name}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(
            {key: _csv_value(value) for key, value in row.items()} for row in rows
        )


def _write_sql(path: Path, tables: dict[str, list[dict[str, Any]]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("-- Application seed data only; apply after database migrations.\n")
        stream.write("-- Ground-truth labels and anomaly submissions are excluded.\n")
        stream.write("BEGIN;\n")
        for table_name in TABLE_ORDER:
            rows = tables[table_name]
            columns = list(rows[0])
            column_sql = ", ".join(columns)
            for offset in range(0, len(rows), 100):
                group = rows[offset : offset + 100]
                stream.write(
                    f"INSERT INTO {table_name} ({column_sql}) VALUES\n"
                )
                values = [
                    "(" + ", ".join(_sql_literal(row[column]) for column in columns) + ")"
                    for row in group
                ]
                stream.write(",\n".join(values))
                stream.write(";\n")
        stream.write("COMMIT;\n")


def generate(
    output: Path = DEFAULT_OUTPUT,
    seed: int = 20261022,
    *,
    config: GeneratorConfig | None = None,
) -> dict[str, Any]:
    config = config or GeneratorConfig(seed=seed)
    tables, ground_truth, anomaly_cases = build_dataset(config)
    validation = validate_dataset(tables, ground_truth, anomaly_cases, config=config)
    output.mkdir(parents=True, exist_ok=True)
    for table in TABLE_ORDER:
        _write_csv(output / f"{table}.csv", tables[table])
    _write_csv(output / "anomaly_cases.csv", anomaly_cases)
    _write_csv(output / "ground_truth.csv", ground_truth)

    source_manifest = {
        "provenance": "synthetic",
        "source": None,
        "retrieval_date": None,
        "license": "Not applicable; generated synthetic data",
        "attribution": None,
        "transformations": [
            "Deterministic generation from the configured seed and generator rules"
        ],
        "fields_discarded": [],
        "generator": "generator/generator.py",
        "generator_version": 2,
        "seed": config.seed,
        "config": {
            "employees": config.employees,
            "leave_policies": config.leave_policies,
            "leave_requests": config.leave_requests,
            "expense_claims": config.expense_claims,
            "expense_line_range": [
                config.min_expense_lines,
                config.max_expense_lines,
            ],
            "year": config.year,
        },
    }
    validation_summary = {
        "status": "passed",
        "tables": validation["tables"],
        "ground_truth_rows": validation["ground_truth_rows"],
        "anomaly_case_rows": validation["anomaly_case_rows"],
        "unlabelled_overlaps": validation["unlabelled_overlaps"],
    }
    (output / "seed_data.json").write_text(
        json.dumps(
            {
                "seed": config.seed,
                "source_manifest": source_manifest,
                "tables": _json_value(tables),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "ground_truth.json").write_text(
        json.dumps(_json_value(ground_truth), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "source_manifest.json").write_text(
        json.dumps(source_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "validation_summary.json").write_text(
        json.dumps(validation_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_sql(output / "seed_data.sql", tables)

    checksums = {}
    export_names = [
        *(f"{table}.csv" for table in TABLE_ORDER),
        "anomaly_cases.csv",
        "ground_truth.csv",
        "seed_data.json",
        "ground_truth.json",
        "source_manifest.json",
        "validation_summary.json",
        "seed_data.sql",
    ]
    export_files = sorted(output / name for name in export_names)
    for path in export_files:
        checksums[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    metadata = {
        "seed": config.seed,
        "generator_version": 2,
        "source_manifest": source_manifest,
        "validation_summary": validation_summary,
        "row_counts": validation["tables"],
        "ground_truth_rows": validation["ground_truth_rows"],
        "anomaly_case_rows": validation["anomaly_case_rows"],
        "sha256": checksums,
    }
    (output / "generation_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic YottaFlex data")
    parser.add_argument("--seed", type=int, default=20261022)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--employees", type=int, default=400)
    parser.add_argument("--leave-requests", type=int, default=800)
    parser.add_argument("--expense-claims", type=int, default=1000)
    parser.add_argument("--min-expense-lines", type=int, default=1)
    parser.add_argument("--max-expense-lines", type=int, default=10)
    args = parser.parse_args()
    config = GeneratorConfig(
        seed=args.seed,
        employees=args.employees,
        leave_requests=args.leave_requests,
        expense_claims=args.expense_claims,
        min_expense_lines=args.min_expense_lines,
        max_expense_lines=args.max_expense_lines,
    )
    metadata = generate(args.output, config=config)
    print(json.dumps(metadata, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
