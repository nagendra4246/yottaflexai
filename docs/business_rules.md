# Business rules

Business decisions live in services and policy/rule modules under
`backend/app/services` and `backend/app/rules`; HTTP handlers delegate to them.
Database models enforce structural integrity but do not implement workflows.

## Employees

- Country codes are restricted to `CAN`, `GER`, `IND`, `UK`, and `USA`.
- Hire and termination dates must be ordered; active manager references must
  exist, cannot point to the employee, and hierarchy cycles are rejected.
- Only active employees can submit leave or expense claims.

## Leave

- A policy must cover the employee's country and the full requested date range.
- Requested days exclude Saturday, Sunday, and persisted public holidays.
- A request with no business days is rejected.
- The latest balance snapshot determines availability:
  `accrued_balance - used_balance - pending_balance`.
- Submission reserves pending balance. Final approval moves reserved days to
  used balance; rejection or cancellation releases the reservation.
- Insufficient balances and overlaps with already approved requests are
  rejected. Pending requests also consume reserved balance.
- Approval follows ordered configured steps, and the requester cannot approve
  their own request. Rejections require a reason and preserve approval history.

## Expenses

- A claim requires an active employee, existing cost center, at least one line,
  and expense/submission dates within employment.
- Claim total is calculated from line amounts. Each line must reference an
  applicable active policy, satisfy its maximum, and provide receipt metadata
  when required.
- Duplicate receipt hashes, over-budget submissions, and detected split claims
  are rejected and recorded as audit exceptions.
- Split-claim detection looks for a recent same-employee, same-cost-center,
  same-currency claim in a shared category where two below-threshold claims
  would reach an approval threshold. Budgets compare stored amounts directly;
  no currency conversion is defined.

## Approval, reimbursement, and audit

- Approval steps are sequential. Only the next pending assigned approver may
  act; requesters cannot self-approve and a step cannot be decided twice.
- Applicable approval rules use entity type, country, category, amount
  threshold, effective dates, and required role.
- The generated seed includes an additional Finance approval rule for German
  Client Entertainment claims, alongside the general expense threshold rule.
- The approval queue exposes only the first unresolved step for each request
  and only when that step is assigned to the requested approver.
- A reimbursement can only be created for a finally approved claim, cannot
  exceed the claim amount, and is unique per claim and transaction reference.
- Processing a pending reimbursement marks it processed and the claim paid.
- Workflow transitions and rejected business decisions create audit events;
  audit history is append-only in PostgreSQL.

There is no authentication or role-based authorization layer. Actor and
approver IDs are supplied in API requests, so identity is not independently
verified.
