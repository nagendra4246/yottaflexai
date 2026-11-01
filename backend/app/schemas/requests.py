from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from ..domain.constants import SUPPORTED_COUNTRIES


class EmployeeCreate(BaseModel):
    employee_id: str = Field(pattern=r"^EMP-\d{6}$", max_length=32)
    name: str = Field(min_length=1, max_length=160)
    email: str = Field(min_length=3, max_length=320)
    manager_id: str | None = Field(default=None, max_length=32)
    department: str = Field(min_length=1, max_length=120)
    country: str = Field(min_length=2, max_length=3)
    hire_date: date
    termination_date: date | None = None
    status: str = "Active"
    approval_role: str | None = Field(default=None, max_length=64)

    @field_validator("country")
    @classmethod
    def country_must_be_supported(cls, value: str) -> str:
        value = value.upper()
        if value not in SUPPORTED_COUNTRIES:
            raise ValueError(f"Unsupported country code: {value}")
        return value

    @field_validator("email")
    @classmethod
    def email_has_valid_shape(cls, value: str) -> str:
        local, separator, domain = value.strip().partition("@")
        if not separator or not local or "." not in domain or domain.startswith("."):
            raise ValueError("email must be a valid email address")
        return value.strip().lower()

    @model_validator(mode="after")
    def employment_dates_are_ordered(self):
        if self.termination_date and self.termination_date < self.hire_date:
            raise ValueError("termination_date must not precede hire_date")
        return self


class LeaveRequestCreate(BaseModel):
    request_id: str | None = Field(
        default=None, pattern=r"^LVE-\d{4}-\d{6}$", max_length=40
    )
    employee_id: str = Field(pattern=r"^EMP-\d{6}$", max_length=32)
    policy_id: str | None = Field(default=None, max_length=32)
    start_date: date
    end_date: date
    leave_type: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def dates_are_ordered(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class ExpenseLineCreate(BaseModel):
    line_id: str | None = Field(
        default=None, pattern=r"^EXPL-EXP-\d{4}-\d{6}-\d{2}$", max_length=80
    )
    policy_id: str = Field(min_length=1, max_length=32)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    description: str = Field(min_length=1, max_length=1000)
    expense_date: date
    receipt_hash: str | None = Field(default=None, max_length=128)
    receipt_url: str | None = Field(default=None, max_length=2048)


class ExpenseClaimCreate(BaseModel):
    claim_id: str | None = Field(
        default=None, pattern=r"^EXP-\d{4}-\d{6}$", max_length=40
    )
    employee_id: str = Field(pattern=r"^EMP-\d{6}$", max_length=32)
    cost_center_id: str = Field(min_length=1, max_length=32)
    currency: str = Field(min_length=3, max_length=3)
    submission_date: date
    lines: list[ExpenseLineCreate] = Field(min_length=1, max_length=100)

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        value = value.upper()
        if len(value) != 3 or not value.isalpha():
            raise ValueError("currency must be a three-letter code")
        return value


class ApprovalDecision(BaseModel):
    approver_id: str = Field(pattern=r"^EMP-\d{6}$", max_length=32)
    reason: str | None = Field(default=None, max_length=2000)
    comments: str | None = Field(default=None, max_length=2000)


class CancellationRequest(BaseModel):
    employee_id: str = Field(pattern=r"^EMP-\d{6}$", max_length=32)
    reason: str = Field(min_length=1, max_length=2000)


class ReimbursementCreate(BaseModel):
    reimbursement_id: str | None = Field(
        default=None, pattern=r"^RMB-\d{4}-\d{6}$", max_length=40
    )
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    payment_date: date
    transaction_ref: str = Field(min_length=1, max_length=160)
