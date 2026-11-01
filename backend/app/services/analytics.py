from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Employee, ExpenseClaim, LeaveRequest, Reimbursement


def _counts_by_status(
    session: Session,
    model: type[LeaveRequest] | type[ExpenseClaim] | type[Reimbursement],
) -> dict[str, int]:
    rows = session.execute(
        select(model.status, func.count()).group_by(model.status)
    )
    return {status: count for status, count in rows}


def get_summary(session: Session) -> dict:
    return {
        "employees_total": session.scalar(
            select(func.count()).select_from(Employee)
        )
        or 0,
        "employees_active": session.scalar(
            select(func.count())
            .select_from(Employee)
            .where(Employee.status == "Active")
        )
        or 0,
        "leave_requests_by_status": _counts_by_status(session, LeaveRequest),
        "expense_claims_by_status": _counts_by_status(session, ExpenseClaim),
        "expense_claims_total_amount": session.scalar(
            select(func.coalesce(func.sum(ExpenseClaim.total_amount), 0))
        )
        or Decimal("0"),
        "reimbursements_by_status": _counts_by_status(session, Reimbursement),
    }
