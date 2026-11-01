from dataclasses import dataclass


@dataclass(frozen=True)
class GeneratorConfig:
    seed: int = 20261022
    employees: int = 400
    leave_policies: int = 6
    leave_requests: int = 800
    expense_claims: int = 1000
    min_expense_lines: int = 1
    max_expense_lines: int = 10
    year: int = 2026

    def __post_init__(self) -> None:
        if self.employees < 3:
            raise ValueError("employees must be at least 3")
        if self.leave_policies != 6:
            raise ValueError("leave_policies must be exactly 6")
        if self.leave_requests < 4:
            raise ValueError("leave_requests must be at least 4")
        if self.expense_claims < 7:
            raise ValueError("expense_claims must be at least 7")
        if not 1 <= self.min_expense_lines <= self.max_expense_lines <= 10:
            raise ValueError("expense line counts must satisfy 1 <= min <= max <= 10")


COUNTRIES = ("CAN", "GER", "IND", "UK", "USA")
DEPARTMENTS = ("Engineering", "Finance", "Operations", "Sales", "People")
LEAVE_TYPES = ("Annual", "Sick", "Personal")
CLAIM_STATUSES = ("Draft", "Pending", "Approved", "Rejected", "Paid")

ANOMALY_CASE_IDS = {
    "split_claim": "CASE-SPLIT-CLAIM",
    "missing_cost_center": "CASE-MISSING-COST-CENTER",
    "duplicate_receipt": "CASE-DUPLICATE-RECEIPT",
    "duplicate_reimbursement": "CASE-DUPLICATE-REIMBURSEMENT",
    "expired_policy": "CASE-EXPIRED-POLICY",
    "partial_rejection": "CASE-PARTIAL-REJECTION",
    "missing_receipt": "CASE-MISSING-RECEIPT",
    "policy_limit_breach": "CASE-POLICY-LIMIT-BREACH",
}
