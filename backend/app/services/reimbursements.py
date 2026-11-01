from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..domain.audit import record_event
from ..domain.errors import DomainError
from ..models import Employee, ExpenseClaim, Reimbursement
from ..schemas.requests import ReimbursementCreate
from .common import constraint_name, fail_with_audit, next_id


def create_reimbursement(
    session: Session, claim_id: str, data: ReimbursementCreate, actor_employee_id: str | None = None
) -> Reimbursement:
    reimbursement_id = data.reimbursement_id or next_id(
        session, Reimbursement, "reimbursement_id", f"RMB-{data.payment_date.year}-"
    )
    claim = session.scalar(
        select(ExpenseClaim)
        .where(ExpenseClaim.claim_id == claim_id)
        .with_for_update()
    )
    try:
        if actor_employee_id is not None and session.get(Employee, actor_employee_id) is None:
            raise DomainError(
                "ACTOR_NOT_FOUND",
                "Reimbursement actor does not exist",
                status_code=404,
            )
        if claim is None:
            raise DomainError("EXPENSE_CLAIM_NOT_FOUND", "Expense claim does not exist", status_code=404)
        if session.scalar(
            select(Reimbursement.reimbursement_id).where(
                Reimbursement.claim_id == claim_id
            )
        ):
            raise DomainError(
                "DUPLICATE_REIMBURSEMENT",
                "Claim already has a reimbursement",
                status_code=409,
            )
        if claim.status != "Approved":
            raise DomainError(
                "CLAIM_NOT_FINALLY_APPROVED",
                "Reimbursement can only be created after final approval",
                status_code=409,
            )
        if session.scalar(
            select(Reimbursement.reimbursement_id).where(
                Reimbursement.transaction_ref == data.transaction_ref
            )
        ):
            raise DomainError(
                "DUPLICATE_TRANSACTION_REFERENCE",
                "Transaction reference has already been used",
                status_code=409,
            )
        if data.amount > Decimal(claim.total_amount):
            raise DomainError(
                "REIMBURSEMENT_EXCEEDS_APPROVED_AMOUNT",
                "Reimbursement amount exceeds the approved claim amount",
                status_code=409,
                details={"approved_amount": claim.total_amount, "amount": data.amount},
            )
        if session.get(Reimbursement, reimbursement_id) is not None:
            raise DomainError("REIMBURSEMENT_ID_EXISTS", "Reimbursement ID already exists", status_code=409)
    except DomainError as error:
        fail_with_audit(
            session,
            error,
            entity_type="Reimbursement",
            entity_id=reimbursement_id,
            actor_employee_id=actor_employee_id,
        )

    reimbursement = Reimbursement(
        reimbursement_id=reimbursement_id,
        claim_id=claim_id,
        amount=data.amount,
        payment_date=data.payment_date,
        transaction_ref=data.transaction_ref,
        status="Pending",
    )
    session.add(reimbursement)
    record_event(
        session,
        entity_type="Reimbursement",
        entity_id=reimbursement_id,
        event_type="reimbursement_created",
        actor_employee_id=actor_employee_id,
        after_state={
            "claim_id": claim_id,
            "amount": data.amount,
            "status": reimbursement.status,
        },
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        constraint = constraint_name(error)
        if "reimbursements.claim_id" in constraint or constraint.endswith(
            "reimbursements_claim_id_key"
        ):
            fail_with_audit(
                session,
                DomainError(
                    "DUPLICATE_REIMBURSEMENT",
                    "Claim already has a reimbursement",
                    status_code=409,
                ),
                entity_type="Reimbursement",
                entity_id=reimbursement_id,
                actor_employee_id=actor_employee_id,
            )
        if "reimbursements.transaction_ref" in constraint or constraint.endswith(
            "reimbursements_transaction_ref_key"
        ):
            fail_with_audit(
                session,
                DomainError(
                    "DUPLICATE_TRANSACTION_REFERENCE",
                    "Transaction reference has already been used",
                    status_code=409,
                ),
                entity_type="Reimbursement",
                entity_id=reimbursement_id,
                actor_employee_id=actor_employee_id,
            )
        raise
    return reimbursement


def process_reimbursement(
    session: Session, reimbursement_id: str, actor_employee_id: str | None = None
) -> Reimbursement:
    if actor_employee_id is not None and session.get(Employee, actor_employee_id) is None:
        error = DomainError(
            "ACTOR_NOT_FOUND",
            "Reimbursement actor does not exist",
            status_code=404,
        )
        fail_with_audit(
            session,
            error,
            entity_type="Reimbursement",
            entity_id=reimbursement_id,
            actor_employee_id=None,
        )
    reimbursement = session.get(Reimbursement, reimbursement_id)
    if reimbursement is None:
        error = DomainError("REIMBURSEMENT_NOT_FOUND", "Reimbursement does not exist", status_code=404)
        fail_with_audit(
            session,
            error,
            entity_type="Reimbursement",
            entity_id=reimbursement_id,
            actor_employee_id=actor_employee_id,
        )
    if reimbursement.status != "Pending":
        error = DomainError(
            "INVALID_REIMBURSEMENT_TRANSITION",
            "Only pending reimbursements may be processed",
            status_code=409,
        )
        fail_with_audit(
            session,
            error,
            entity_type="Reimbursement",
            entity_id=reimbursement_id,
            actor_employee_id=actor_employee_id,
        )
    claim = reimbursement.claim
    if claim.status != "Approved":
        error = DomainError(
            "CLAIM_NOT_FINALLY_APPROVED",
            "Claim must remain approved until reimbursement processing",
            status_code=409,
        )
        fail_with_audit(
            session,
            error,
            entity_type="Reimbursement",
            entity_id=reimbursement_id,
            actor_employee_id=actor_employee_id,
        )
    before = {"status": reimbursement.status, "processed_at": reimbursement.processed_at}
    now = datetime.now(timezone.utc)
    reimbursement.status = "Processed"
    reimbursement.processed_at = now
    claim.status = "Paid"
    claim.decided_at = now
    record_event(
        session,
        entity_type="Reimbursement",
        entity_id=reimbursement_id,
        event_type="reimbursement_processed",
        actor_employee_id=actor_employee_id,
        before_state=before,
        after_state={"status": reimbursement.status, "processed_at": now},
    )
    record_event(
        session,
        entity_type="ExpenseClaim",
        entity_id=claim.claim_id,
        event_type="claim_paid",
        actor_employee_id=actor_employee_id,
        before_state={"status": "Approved"},
        after_state={"status": "Paid", "reimbursement_id": reimbursement_id},
    )
    session.commit()
    return reimbursement
