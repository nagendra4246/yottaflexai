from datetime import date, datetime
from decimal import Decimal
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict


T = TypeVar("T")


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PageResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class APIError(BaseModel):
    code: str
    message: str
    details: dict


class APIErrorResponse(BaseModel):
    error: APIError


class AnalyticsSummaryResponse(BaseModel):
    employees_total: int
    employees_active: int
    leave_requests_by_status: dict[str, int]
    expense_claims_by_status: dict[str, int]
    expense_claims_total_amount: Decimal
    reimbursements_by_status: dict[str, int]


class EmployeeResponse(APIModel):
    employee_id: str
    name: str
    email: str
    manager_id: str | None
    department: str
    country: str
    hire_date: date
    termination_date: date | None
    status: str
    approval_role: str | None


class LeavePolicyResponse(APIModel):
    policy_id: str
    policy_name: str
    annual_entitlement: int
    carry_over_limit: int
    accrual_rate: Decimal
    country_code: str
    effective_from: date
    effective_to: date | None


class LeaveBalanceResponse(APIModel):
    balance_id: str
    employee_id: str
    policy_id: str
    accrued_balance: Decimal
    used_balance: Decimal
    pending_balance: Decimal
    available_balance: Decimal
    effective_date: date


class LeaveRequestResponse(APIModel):
    request_id: str
    employee_id: str
    policy_id: str
    start_date: date
    end_date: date
    total_days: Decimal
    leave_type: str
    status: str
    requested_at: datetime
    decided_at: datetime | None
    decision_reason: str | None


class ApprovalStepResponse(APIModel):
    step_id: str
    leave_request_id: str | None
    expense_claim_id: str | None
    approver_id: str
    sequence: int
    status: str
    action_date: datetime | None
    decision_reason: str | None
    comments: str | None


class LeaveWorkflowResponse(BaseModel):
    request: LeaveRequestResponse
    balance: LeaveBalanceResponse
    approval_steps: list[ApprovalStepResponse]


class ExpensePolicyResponse(APIModel):
    policy_id: str
    category: str
    max_amount: Decimal
    requires_receipt: bool
    country_code: str
    effective_from: date
    effective_to: date | None


class CostCenterResponse(APIModel):
    cost_center_id: str
    name: str
    budget: Decimal
    department: str


class ExpenseClaimResponse(APIModel):
    claim_id: str
    employee_id: str
    cost_center_id: str
    total_amount: Decimal
    currency: str
    status: str
    submission_date: date
    decided_at: datetime | None
    decision_reason: str | None


class ExpenseLineResponse(APIModel):
    line_id: str
    claim_id: str
    policy_id: str
    policy_category: str
    policy_max_amount: Decimal
    receipt_required: bool
    amount: Decimal
    description: str
    expense_date: date
    receipt_hash: str | None
    receipt_url: str | None


class ExpenseWorkflowResponse(BaseModel):
    claim: ExpenseClaimResponse
    lines: list[ExpenseLineResponse]
    approval_steps: list[ApprovalStepResponse]
    cost_center_budget: Decimal
    budget_committed: Decimal
    budget_remaining: Decimal


class ApprovalQueueItemResponse(BaseModel):
    request_id: str
    entity_type: str
    step_id: str
    sequence: int
    approver_id: str
    employee_id: str
    amount: Decimal | None
    currency: str | None
    total_days: Decimal | None
    start_date: date | None
    end_date: date | None
    submission_date: date | None


class ReimbursementResponse(APIModel):
    reimbursement_id: str
    claim_id: str
    amount: Decimal
    payment_date: date
    transaction_ref: str
    status: str
    processed_at: datetime | None
    decision_reason: str | None


class AuditEventResponse(APIModel):
    event_id: str
    entity_type: str
    entity_id: str
    event_type: str
    actor_employee_id: str | None
    before_state: dict | None
    after_state: dict | None
    reason: str | None
    is_exception: bool
    exception_code: str | None
    exception_details: dict | None
    occurred_at: datetime
