from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from ..db.session import get_db
from ..domain.errors import DomainError
from ..models import (
    AuditEvent,
    ApprovalStep,
    Employee,
    ExpensePolicy,
    CostCenter,
    ExpenseClaim,
    LeaveBalance,
    LeavePolicy,
    LeaveRequest,
    Reimbursement,
)
from ..schemas.requests import (
    ApprovalDecision,
    CancellationRequest,
    EmployeeCreate,
    ExpenseClaimCreate,
    LeaveRequestCreate,
    ReimbursementCreate,
)
from ..schemas.responses import (
    AuditEventResponse,
    AnalyticsSummaryResponse,
    ApprovalQueueItemResponse,
    CostCenterResponse,
    EmployeeResponse,
    ExpenseClaimResponse,
    ExpensePolicyResponse,
    ExpenseWorkflowResponse,
    LeaveBalanceResponse,
    LeavePolicyResponse,
    LeaveRequestResponse,
    LeaveWorkflowResponse,
    APIErrorResponse,
    PageResponse,
    ReimbursementResponse,
)
from ..services.analytics import get_summary
from ..services.approvals import decide_approval
from ..services.employees import change_manager, create_employee
from ..services.expenses import submit_expense_claim
from ..services.leave import cancel_leave_request, submit_leave_request
from ..services.reimbursements import create_reimbursement, process_reimbursement
from ..services.workflows import expense_workflow, leave_workflow

router = APIRouter(
    responses={
        403: {"model": APIErrorResponse, "description": "Forbidden"},
        404: {"model": APIErrorResponse, "description": "Resource not found"},
        409: {"model": APIErrorResponse, "description": "Conflicting state"},
        422: {"model": APIErrorResponse, "description": "Invalid request"},
    }
)


@router.post("/employees", response_model=EmployeeResponse, status_code=201)
def post_employee(data: EmployeeCreate, session: Session = Depends(get_db)):
    return create_employee(session, data)


@router.get("/employees", response_model=PageResponse[EmployeeResponse], summary="List employees")
def get_employees(
    country: str | None = Query(default=None, min_length=2, max_length=3),
    status: Literal["Active", "Inactive", "Terminated"] | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
):
    statement = select(Employee)
    count_statement = select(func.count()).select_from(Employee)
    if country:
        statement = statement.where(Employee.country == country.upper())
        count_statement = count_statement.where(Employee.country == country.upper())
    if status:
        statement = statement.where(Employee.status == status)
        count_statement = count_statement.where(Employee.status == status)
    return {
        "items": list(
            session.scalars(
                statement.order_by(Employee.employee_id).limit(limit).offset(offset)
            )
        ),
        "total": session.scalar(count_statement) or 0,
        "limit": limit,
        "offset": offset,
    }


@router.get("/employees/{employee_id}", response_model=EmployeeResponse)
def get_employee(employee_id: str, session: Session = Depends(get_db)):
    employee = session.get(Employee, employee_id)
    if employee is None:
        raise DomainError("EMPLOYEE_NOT_FOUND", "Employee does not exist", status_code=404)
    return employee


@router.get(
    "/employees/{employee_id}/leave-balances",
    response_model=list[LeaveBalanceResponse],
)
def get_employee_leave_balances(employee_id: str, session: Session = Depends(get_db)):
    if session.get(Employee, employee_id) is None:
        raise DomainError("EMPLOYEE_NOT_FOUND", "Employee does not exist", status_code=404)
    balances = session.scalars(
        select(LeaveBalance)
        .where(LeaveBalance.employee_id == employee_id)
        .order_by(LeaveBalance.policy_id, LeaveBalance.effective_date.desc())
    ).all()
    latest_by_policy = {}
    for balance in balances:
        latest_by_policy.setdefault(balance.policy_id, balance)
    return [
        {
            "balance_id": balance.balance_id,
            "employee_id": balance.employee_id,
            "policy_id": balance.policy_id,
            "accrued_balance": balance.accrued_balance,
            "used_balance": balance.used_balance,
            "pending_balance": balance.pending_balance,
            "available_balance": (
                balance.accrued_balance
                - balance.used_balance
                - balance.pending_balance
            ),
            "effective_date": balance.effective_date,
        }
        for balance in latest_by_policy.values()
    ]


@router.get("/leave/policies", response_model=list[LeavePolicyResponse])
def get_leave_policies(
    country: str | None = Query(default=None, min_length=2, max_length=3),
    session: Session = Depends(get_db),
):
    statement = select(LeavePolicy)
    if country:
        statement = statement.where(LeavePolicy.country_code == country.upper())
    return list(
        session.scalars(statement.order_by(LeavePolicy.country_code, LeavePolicy.policy_id))
    )


@router.post("/employees/{employee_id}/manager", response_model=EmployeeResponse)
def post_manager(
    employee_id: str,
    manager_id: str | None = None,
    actor_employee_id: str = Query(min_length=1),
    session: Session = Depends(get_db),
):
    return change_manager(session, employee_id, manager_id, actor_employee_id)


@router.post("/leave/requests", response_model=LeaveRequestResponse, status_code=201)
def post_leave_request(data: LeaveRequestCreate, session: Session = Depends(get_db)):
    return submit_leave_request(session, data)


@router.get("/leave/requests", response_model=PageResponse[LeaveRequestResponse], summary="List leave requests")
def get_leave_requests(
    employee_id: str | None = None,
    status: Literal["Draft", "Pending", "Approved", "Rejected", "Cancelled"] | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
):
    statement = select(LeaveRequest)
    count_statement = select(func.count()).select_from(LeaveRequest)
    if employee_id:
        statement = statement.where(LeaveRequest.employee_id == employee_id)
        count_statement = count_statement.where(LeaveRequest.employee_id == employee_id)
    if status:
        statement = statement.where(LeaveRequest.status == status)
        count_statement = count_statement.where(LeaveRequest.status == status)
    return {
        "items": list(
            session.scalars(
                statement.order_by(LeaveRequest.requested_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ),
        "total": session.scalar(count_statement) or 0,
        "limit": limit,
        "offset": offset,
    }


@router.get("/leave/requests/{request_id}", response_model=LeaveRequestResponse)
def get_leave_request(request_id: str, session: Session = Depends(get_db)):
    request = session.get(LeaveRequest, request_id)
    if request is None:
        raise DomainError("LEAVE_REQUEST_NOT_FOUND", "Leave request does not exist", status_code=404)
    return request


@router.get(
    "/leave/requests/{request_id}/workflow",
    response_model=LeaveWorkflowResponse,
)
def get_leave_workflow(request_id: str, session: Session = Depends(get_db)):
    return leave_workflow(session, request_id)


@router.post("/leave/requests/{request_id}/approve", response_model=LeaveRequestResponse)
def approve_leave(
    request_id: str, data: ApprovalDecision, session: Session = Depends(get_db)
):
    return decide_approval(
        session,
        request_id,
        data.approver_id,
        decision="Approved",
        reason=data.reason,
        comments=data.comments,
    )


@router.post("/leave/requests/{request_id}/reject", response_model=LeaveRequestResponse)
def reject_leave(
    request_id: str, data: ApprovalDecision, session: Session = Depends(get_db)
):
    return decide_approval(
        session,
        request_id,
        data.approver_id,
        decision="Rejected",
        reason=data.reason,
        comments=data.comments,
    )


@router.post("/leave/requests/{request_id}/cancel", response_model=LeaveRequestResponse)
def cancel_leave(
    request_id: str,
    data: CancellationRequest,
    session: Session = Depends(get_db),
):
    return cancel_leave_request(
        session, request_id, data.employee_id, data.reason
    )


@router.post("/expenses/claims", response_model=ExpenseClaimResponse, status_code=201)
def post_expense_claim(data: ExpenseClaimCreate, session: Session = Depends(get_db)):
    return submit_expense_claim(session, data)


@router.get("/expenses/policies", response_model=list[ExpensePolicyResponse])
def get_expense_policies(
    country: str | None = Query(default=None, min_length=2, max_length=12),
    session: Session = Depends(get_db),
):
    statement = select(ExpensePolicy)
    if country:
        statement = statement.where(
            ExpensePolicy.country_code.in_(("GLOBAL", country.upper()))
        )
    return list(
        session.scalars(
            statement.order_by(ExpensePolicy.category, ExpensePolicy.policy_id)
        )
    )


@router.get("/cost-centers", response_model=list[CostCenterResponse])
def get_cost_centers(session: Session = Depends(get_db)):
    return list(
        session.scalars(select(CostCenter).order_by(CostCenter.cost_center_id))
    )


@router.get("/expenses/claims", response_model=PageResponse[ExpenseClaimResponse], summary="List expense claims")
def get_expense_claims(
    employee_id: str | None = None,
    status: Literal["Draft", "Pending", "Approved", "Rejected", "Paid"] | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
):
    statement = select(ExpenseClaim)
    count_statement = select(func.count()).select_from(ExpenseClaim)
    if employee_id:
        statement = statement.where(ExpenseClaim.employee_id == employee_id)
        count_statement = count_statement.where(ExpenseClaim.employee_id == employee_id)
    if status:
        statement = statement.where(ExpenseClaim.status == status)
        count_statement = count_statement.where(ExpenseClaim.status == status)
    return {
        "items": list(
            session.scalars(
                statement.order_by(ExpenseClaim.submission_date.desc())
                .limit(limit)
                .offset(offset)
            )
        ),
        "total": session.scalar(count_statement) or 0,
        "limit": limit,
        "offset": offset,
    }


@router.get("/expenses/claims/{claim_id}", response_model=ExpenseClaimResponse)
def get_expense_claim(claim_id: str, session: Session = Depends(get_db)):
    claim = session.get(ExpenseClaim, claim_id)
    if claim is None:
        raise DomainError("EXPENSE_CLAIM_NOT_FOUND", "Expense claim does not exist", status_code=404)
    return claim


@router.get(
    "/expenses/claims/{claim_id}/workflow",
    response_model=ExpenseWorkflowResponse,
)
def get_expense_workflow(claim_id: str, session: Session = Depends(get_db)):
    return expense_workflow(session, claim_id)


@router.get(
    "/approvals/queue",
    response_model=list[ApprovalQueueItemResponse],
    summary="List pending approvals assigned to an approver",
)
def get_approval_queue(
    approver_id: str = Query(pattern=r"^EMP-\d{6}$"),
    session: Session = Depends(get_db),
):
    approver = session.get(Employee, approver_id)
    if approver is None or approver.status != "Active":
        raise DomainError(
            "APPROVER_NOT_FOUND",
            "Active approver does not exist",
            status_code=404,
        )
    earlier_step = aliased(ApprovalStep)
    same_workflow = or_(
        and_(
            ApprovalStep.leave_request_id.is_not(None),
            earlier_step.leave_request_id == ApprovalStep.leave_request_id,
        ),
        and_(
            ApprovalStep.expense_claim_id.is_not(None),
            earlier_step.expense_claim_id == ApprovalStep.expense_claim_id,
        ),
    )
    earlier_unresolved_step = exists(
        select(earlier_step.step_id).where(
            same_workflow,
            earlier_step.sequence < ApprovalStep.sequence,
            earlier_step.status != "Approved",
        )
    )
    steps = session.scalars(
        select(ApprovalStep)
        .where(
            ApprovalStep.approver_id == approver_id,
            ApprovalStep.status == "Pending",
            ~earlier_unresolved_step,
        )
        .order_by(ApprovalStep.created_at, ApprovalStep.step_id)
    ).all()
    items = []
    for step in steps:
        if step.leave_request is not None:
            request = step.leave_request
            items.append(
                {
                    "request_id": request.request_id,
                    "entity_type": "Leave",
                    "step_id": step.step_id,
                    "sequence": step.sequence,
                    "approver_id": step.approver_id,
                    "employee_id": request.employee_id,
                    "amount": None,
                    "currency": None,
                    "total_days": request.total_days,
                    "start_date": request.start_date,
                    "end_date": request.end_date,
                    "submission_date": request.requested_at.date(),
                }
            )
        elif step.expense_claim is not None:
            claim = step.expense_claim
            items.append(
                {
                    "request_id": claim.claim_id,
                    "entity_type": "Expense",
                    "step_id": step.step_id,
                    "sequence": step.sequence,
                    "approver_id": step.approver_id,
                    "employee_id": claim.employee_id,
                    "amount": claim.total_amount,
                    "currency": claim.currency,
                    "total_days": None,
                    "start_date": None,
                    "end_date": None,
                    "submission_date": claim.submission_date,
                }
            )
    return items


@router.post("/expenses/claims/{claim_id}/approve", response_model=ExpenseClaimResponse)
def approve_expense(
    claim_id: str, data: ApprovalDecision, session: Session = Depends(get_db)
):
    return decide_approval(
        session,
        claim_id,
        data.approver_id,
        decision="Approved",
        reason=data.reason,
        comments=data.comments,
    )


@router.post("/expenses/claims/{claim_id}/reject", response_model=ExpenseClaimResponse)
def reject_expense(
    claim_id: str, data: ApprovalDecision, session: Session = Depends(get_db)
):
    return decide_approval(
        session,
        claim_id,
        data.approver_id,
        decision="Rejected",
        reason=data.reason,
        comments=data.comments,
    )


@router.post(
    "/expenses/claims/{claim_id}/reimbursements",
    response_model=ReimbursementResponse,
    status_code=201,
)
def post_reimbursement(
    claim_id: str,
    data: ReimbursementCreate,
    actor_employee_id: str | None = None,
    session: Session = Depends(get_db),
):
    return create_reimbursement(session, claim_id, data, actor_employee_id)


@router.get("/reimbursements", response_model=PageResponse[ReimbursementResponse], summary="List reimbursements")
def get_reimbursements(
    status: Literal["Pending", "Processed"] | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
):
    statement = select(Reimbursement)
    count_statement = select(func.count()).select_from(Reimbursement)
    if status:
        statement = statement.where(Reimbursement.status == status)
        count_statement = count_statement.where(Reimbursement.status == status)
    return {
        "items": list(
            session.scalars(
                statement.order_by(Reimbursement.payment_date.desc())
                .limit(limit)
                .offset(offset)
            )
        ),
        "total": session.scalar(count_statement) or 0,
        "limit": limit,
        "offset": offset,
    }


@router.post(
    "/reimbursements/{reimbursement_id}/process",
    response_model=ReimbursementResponse,
)
def post_process_reimbursement(
    reimbursement_id: str,
    actor_employee_id: str | None = None,
    session: Session = Depends(get_db),
):
    return process_reimbursement(session, reimbursement_id, actor_employee_id)


@router.get("/audit/events", response_model=PageResponse[AuditEventResponse], summary="List audit events")
def get_audit_events(
    entity_type: str | None = None,
    entity_id: str | None = None,
    exceptions_only: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
):
    statement = select(AuditEvent)
    count_statement = select(func.count()).select_from(AuditEvent)
    if entity_type:
        statement = statement.where(AuditEvent.entity_type == entity_type)
        count_statement = count_statement.where(AuditEvent.entity_type == entity_type)
    if entity_id:
        statement = statement.where(AuditEvent.entity_id == entity_id)
        count_statement = count_statement.where(AuditEvent.entity_id == entity_id)
    if exceptions_only:
        statement = statement.where(AuditEvent.is_exception.is_(True))
        count_statement = count_statement.where(AuditEvent.is_exception.is_(True))
    return {
        "items": list(
            session.scalars(
                statement.order_by(AuditEvent.occurred_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ),
        "total": session.scalar(count_statement) or 0,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/analytics/summary",
    response_model=AnalyticsSummaryResponse,
    summary="Get operational summary",
)
def get_analytics_summary(session: Session = Depends(get_db)):
    return get_summary(session)
