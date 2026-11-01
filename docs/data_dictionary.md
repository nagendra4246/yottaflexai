# Data dictionary

The SQLAlchemy models and migrations are authoritative. `required` means
non-null in the database; API validation may impose additional constraints.
IDs are immutable primary keys. `created_at` and `updated_at` are UTC
timestamps supplied by the database on timestamped entities.

## Relationships and lifecycle

| Relationship | Cardinality | Optionality and history |
|---|---|---|
| Employee → manager (Employee) | N:1 | `manager_id` is optional; a manager may have many direct reports. Self-management and hierarchy cycles are rejected. |
| Employee → LeaveBalance | 1:N | A balance snapshot belongs to one employee and one policy. Snapshots are unique by employee, policy, and effective date. |
| Employee ↔ LeavePolicy | N:M | `LeaveBalance` is the bridge; accrued, used, pending, and effective-date values are snapshot attributes. |
| Employee → LeaveRequest | 1:N | Every request has one employee and one policy; request history is retained through lifecycle audit events. |
| LeavePolicy → LeaveRequest | 1:N | Requests reference one policy applicable to country and full date range. |
| Employee → ExpenseClaim | 1:N | Every claim belongs to one employee and one cost center. |
| CostCenter → ExpenseClaim | 1:N | A claim requires an existing cost center. Budget amounts are compared without currency conversion. |
| ExpenseClaim ↔ ExpensePolicy | N:M | `ExpenseLine` is the bridge and records amount, date, receipt metadata, and the applied policy. |
| ExpenseClaim → ExpenseLine | 1:N | A submitted claim contains 1–100 lines through the API; generated data uses 1–10. |
| ExpensePolicy → ExpenseLine | 1:N | Every line uses one policy valid for its country and expense date. |
| LeaveRequest / ExpenseClaim → ApprovalStep | 1:N | Each step references exactly one request type; sequence is unique per request and decisions are sequential. |
| Employee → ApprovalStep | 1:N | Each step has one assigned approver. |
| ExpenseClaim → Reimbursement | 1:0..1 | A reimbursement can exist only after final approval; a unique claim FK prevents duplicates. |
| AuditEvent → actor Employee | N:0..1 | Actor is optional for system events. Entity references are polymorphic; the append-only audit log records transitions and exceptions. |

Leave request states are `Draft`, `Pending`, `Approved`, `Rejected`, and
`Cancelled`. Expense claim states are `Draft`, `Pending`, `Approved`,
`Rejected`, and `Paid`. Approval steps use `Pending`, `Approved`, and
`Rejected`; reimbursements use `Pending` and `Processed`. State changes are
preserved as audit events; the current-state columns are not a substitute for
the event history.

## Entity fields

`PK` means primary key; `FK` means foreign key; `UQ` means unique. All
monetary amounts use decimal arithmetic, not binary floating point.

### Employee

| Field | Database type | Required | Allowed values / units | Uniqueness | Validation |
|---|---|---:|---|---|---|
| `employee_id` | varchar(32) | Yes | `EMP-` plus six digits | PK | Immutable; API format check. |
| `name` | varchar(160) | Yes | Nonblank text | — | API length 1–160. |
| `email` | varchar(320) | Yes | Lowercase email text | UQ | API checks basic address shape and normalizes case. |
| `manager_id` | varchar(32) | No | Employee ID or null | — | FK to Employee; cannot reference self; cycles rejected by service. |
| `department` | varchar(120) | Yes | Nonblank text | — | API length 1–120. |
| `country` | varchar(3) | Yes | `CAN`, `GER`, `IND`, `UK`, `USA` | — | API rejects unsupported codes and uppercases input. |
| `hire_date` | date | Yes | ISO calendar date | — | Required; cannot be later than termination date. |
| `termination_date` | date | No | ISO date or null | — | Must be on/after `hire_date`. |
| `status` | varchar(16) | Yes | `Active`, `Inactive`, `Terminated` | — | Database check; only active employees may submit. |
| `approval_role` | varchar(64) | No | Configured role text or null | — | Used to select eligible approvers. |
| `created_at`, `updated_at` | timestamptz | Yes | UTC | — | Database timestamps; applied to this timestamped entity. |

### LeavePolicy

| Field | Database type | Required | Allowed values / units | Uniqueness | Validation |
|---|---|---:|---|---|---|
| `policy_id` | varchar(32) | Yes | Stable policy ID | PK | Immutable. |
| `policy_name` | varchar(120) | Yes | Text | — | Required. |
| `annual_entitlement` | integer | Yes | Days/year | — | Must be nonnegative. |
| `carry_over_limit` | integer | Yes | Days | — | Must be nonnegative. |
| `accrual_rate` | numeric(8,3) | Yes | Days/month | — | Must be nonnegative. |
| `country_code` | char(3) | Yes | Supported employee country | — | Policy country must match the employee. |
| `effective_from` | date | Yes | Inclusive ISO date | — | Must not follow `effective_to`. |
| `effective_to` | date | No | Inclusive ISO date or null (open-ended) | — | Must be on/after `effective_from`. |
| `created_at`, `updated_at` | timestamptz | Yes | UTC | — | Database timestamps. |

### LeaveBalance

| Field | Database type | Required | Allowed values / units | Uniqueness | Validation |
|---|---|---:|---|---|---|
| `balance_id` | varchar(32) | Yes | Stable snapshot ID | PK | Immutable. |
| `employee_id` | varchar(32) | Yes | Employee ID | — | FK to Employee. |
| `policy_id` | varchar(32) | Yes | Leave policy ID | — | FK to LeavePolicy. |
| `accrued_balance` | numeric(10,2) | Yes | Days | — | May be negative to represent labelled anomaly records; generated negatives must have a ground-truth label. |
| `used_balance` | numeric(10,2) | Yes | Days | — | Derived from approved requests in generated data. |
| `pending_balance` | numeric(10,2) | Yes | Days | — | Reserved days for pending requests; released on rejection/cancellation. |
| `effective_date` | date | Yes | Snapshot date | — | Combined employee/policy/date key is unique. |
| `created_at`, `updated_at` | timestamptz | Yes | UTC | — | Database timestamps. |

The unique key is (`employee_id`, `policy_id`, `effective_date`). Available
balance is derived as `accrued_balance - used_balance - pending_balance`;
it is not stored independently.

### LeaveRequest

| Field | Database type | Required | Allowed values / units | Uniqueness | Validation |
|---|---|---:|---|---|---|
| `request_id` | varchar(40) | Yes | `LVE-YYYY-` plus six digits | PK | Immutable; API format check. |
| `employee_id` | varchar(32) | Yes | Employee ID | — | FK; employee must be active and employed for the request dates. |
| `policy_id` | varchar(32) | Yes | Leave policy ID | — | FK; policy country and effective dates must cover request. |
| `start_date`, `end_date` | date | Yes | Inclusive ISO dates | — | End cannot precede start. |
| `total_days` | numeric(8,2) | Yes | Business days | — | Derived by excluding weekends and country holidays; zero-day submission rejected by service. |
| `leave_type` | varchar(64) | Yes | Text (generated values: Annual, Sick, Personal) | — | Required. |
| `status` | varchar(16) | Yes | Leave lifecycle states above | — | Database check; workflow service controls transitions. |
| `requested_at` | timestamptz | Yes | UTC | — | Database default. |
| `decided_at` | timestamptz | No | UTC or null | — | Set for terminal decision/cancellation. |
| `decision_reason` | varchar(2000) | No | Text or null | — | Rejection/cancellation reasons are required by service. |
| `created_at`, `updated_at` | timestamptz | Yes | UTC | — | Database timestamps. |

### ExpensePolicy

| Field | Database type | Required | Allowed values / units | Uniqueness | Validation |
|---|---|---:|---|---|---|
| `policy_id` | varchar(32) | Yes | Stable policy ID | PK | Immutable. |
| `category` | varchar(80) | Yes | Configured category text | — | Used in approval routing. |
| `max_amount` | numeric(12,2) | Yes | Currency units per line | — | Must be nonnegative; each line must not exceed the limit. |
| `requires_receipt` | boolean | Yes | `true` / `false` | — | Required receipt hash or URL when true. |
| `country_code` | varchar(12) | Yes | `GLOBAL` or supported country | — | Must apply to employee country. |
| `effective_from` | date | Yes | Inclusive ISO date | — | Must not follow `effective_to`. |
| `effective_to` | date | No | Inclusive ISO date or null | — | Must be on/after `effective_from`. |
| `created_at`, `updated_at` | timestamptz | Yes | UTC | — | Database timestamps. |

### ExpenseClaim

| Field | Database type | Required | Allowed values / units | Uniqueness | Validation |
|---|---|---:|---|---|---|
| `claim_id` | varchar(40) | Yes | `EXP-YYYY-` plus six digits | PK | Immutable; API format check. |
| `employee_id` | varchar(32) | Yes | Employee ID | — | FK; employee must be active and employed on submission/expense dates. |
| `cost_center_id` | varchar(32) | Yes | Cost center ID | — | FK; service checks budget before submission. |
| `total_amount` | numeric(14,2) | Yes | Claim currency units | — | Must be positive and equal sum of line amounts. |
| `currency` | varchar(3) | Yes | Uppercase three-letter code | — | Database check/API validation; no conversion is performed. |
| `status` | varchar(16) | Yes | Expense lifecycle states above | — | Database check; only finally approved claims are reimbursable. |
| `submission_date` | date | Yes | ISO date | — | Must fall within employment. |
| `decided_at` | timestamptz | No | UTC or null | — | Set when approved/rejected/paid. |
| `decision_reason` | varchar(2000) | No | Text or null | — | Decision context. |
| `created_at`, `updated_at` | timestamptz | Yes | UTC | — | Database timestamps. |

### ExpenseLine

| Field | Database type | Required | Allowed values / units | Uniqueness | Validation |
|---|---|---:|---|---|---|
| `line_id` | varchar(80) | Yes | `EXPL-<claim-id>-NN` | PK | Must belong to its claim. |
| `claim_id` | varchar(40) | Yes | Expense claim ID | — | FK to ExpenseClaim. |
| `policy_id` | varchar(32) | Yes | Expense policy ID | — | FK; country/date applicability and receipt/limit rules validated by service. |
| `amount` | numeric(12,2) | Yes | Claim currency units | — | Must be positive and at/below policy maximum. |
| `description` | varchar(1000) | Yes | Text | — | Required. |
| `expense_date` | date | Yes | ISO date | — | Must fall within employment and policy effective dates. |
| `receipt_hash` | varchar(128) | No | Content hash or null | UQ when non-null | Duplicate hashes rejected globally. |
| `receipt_url` | varchar(2048) | No | HTTP(S) URL or null | — | API accepts only HTTP(S); one of hash/URL is required by receipt policy. |
| `created_at`, `updated_at` | timestamptz | Yes | UTC | — | Database timestamps. |

### CostCenter

| Field | Database type | Required | Allowed values / units | Uniqueness | Validation |
|---|---|---:|---|---|---|
| `cost_center_id` | varchar(32) | Yes | Stable cost-center ID | PK | Immutable. |
| `name` | varchar(120) | Yes | Text | — | Required. |
| `budget` | numeric(14,2) | Yes | Stored amount units; currency is not modeled | — | Must be nonnegative. |
| `department` | varchar(120) | Yes | Text | — | Required. |
| `created_at`, `updated_at` | timestamptz | Yes | UTC | — | Database timestamps. |

### ApprovalRule

| Field | Database type | Required | Allowed values / units | Uniqueness | Validation |
|---|---|---:|---|---|---|
| `rule_id` | varchar(32) | Yes | Stable rule ID | PK | Immutable. |
| `entity_type` | varchar(16) | Yes | `Leave`, `Expense` | — | Database check. |
| `threshold_amount` | numeric(14,2) | No | Amount in request currency or null (no minimum) | — | Must be nonnegative when set. Leave uses requested days as amount. |
| `country_code` | varchar(12) | No | Supported country or null (all) | — | Matched against requester country. |
| `category` | varchar(80) | No | Expense category / leave type or null (all) | — | Matched against request categories. |
| `approval_level` | integer | Yes | Positive sequence level | — | Must be greater than zero. |
| `required_role` | varchar(64) | Yes | Role text (for example `Manager`, `Finance`) | — | Active eligible employee required. |
| `effective_from` | timestamptz | Yes | Inclusive UTC instant | — | Defaults to database current time; must not follow `effective_to`. |
| `effective_to` | timestamptz | No | Inclusive UTC instant or null | — | Must be on/after `effective_from`. |
| `created_at`, `updated_at` | timestamptz | Yes | UTC | — | Database timestamps. |

### ApprovalStep

| Field | Database type | Required | Allowed values / units | Uniqueness | Validation |
|---|---|---:|---|---|---|
| `step_id` | varchar(80) | Yes | `APR-<request-id>-NN` | PK | Immutable and must identify a request step. |
| `leave_request_id` | varchar(40) | Conditional | Leave request ID or null | — | Exactly one of leave/expense request IDs must be set; FK. |
| `expense_claim_id` | varchar(40) | Conditional | Expense claim ID or null | — | Exactly one of leave/expense request IDs must be set; FK. |
| `approver_id` | varchar(32) | Yes | Employee ID | — | FK; active, not requester, and must match the assigned next step. |
| `sequence` | integer | Yes | Positive step number | UQ per request | Must be greater than zero; steps are decided in order. |
| `status` | varchar(16) | Yes | `Pending`, `Approved`, `Rejected` | — | Database check. |
| `action_date` | timestamptz | No | UTC or null | — | Null only while pending; required after decision. |
| `decision_reason` | text | No | Text or null | — | Nonblank when rejected. |
| `comments` | text | No | Text or null | — | Optional approver comments. |
| `created_at`, `updated_at` | timestamptz | Yes | UTC | — | Database timestamps. |

### Reimbursement

| Field | Database type | Required | Allowed values / units | Uniqueness | Validation |
|---|---|---:|---|---|---|
| `reimbursement_id` | varchar(40) | Yes | `RMB-YYYY-` plus six digits | PK | Immutable. |
| `claim_id` | varchar(40) | Yes | Expense claim ID | UQ | FK; one reimbursement per claim; claim must be finally approved. |
| `amount` | numeric(14,2) | Yes | Claim currency units | — | Positive and no greater than approved claim total. |
| `payment_date` | date | Yes | ISO date | — | Required. |
| `transaction_ref` | varchar(160) | Yes | Payment-system reference | UQ | Cannot be reused. |
| `status` | varchar(16) | Yes | `Pending`, `Processed` | — | Database check. |
| `processed_at` | timestamptz | No | UTC or null | — | Null while pending; required when processed. |
| `decision_reason` | varchar(2000) | No | Text or null | — | Optional processing context. |
| `created_at`, `updated_at` | timestamptz | Yes | UTC | — | Database timestamps. |

### PublicHoliday and AuditEvent

| Entity / field | Database type | Required | Allowed values / units | Uniqueness | Validation |
|---|---|---:|---|---|---|
| PublicHoliday.`holiday_id` | varchar(36) | Yes | Stable holiday ID | PK | Immutable. |
| PublicHoliday.`country_code` | varchar(3) | Yes | Supported country | — | Holiday applies to requests in that country. |
| PublicHoliday.`holiday_date` | date | Yes | ISO date | UQ with country | Unique country/date pair. |
| PublicHoliday.`name` | varchar(160) | Yes | Text | — | Required. |
| AuditEvent.`event_id` | varchar(36) | Yes | UUID text | PK | Immutable. |
| AuditEvent.`entity_type` | varchar(32) | Yes | Application entity name | — | Restricted to known entity types. |
| AuditEvent.`entity_id` | varchar(80) | Yes | Referenced entity ID | — | Polymorphic reference; checked by workflow services. |
| AuditEvent.`event_type` | varchar(80) | Yes | Event identifier | — | Required. |
| AuditEvent.`actor_employee_id` | varchar(32) | No | Employee ID or null | — | FK to Employee. |
| AuditEvent.`before_state`, `after_state` | JSON | No | JSON object or null | — | Values are serialized from source state. |
| AuditEvent.`reason` | text | No | Text or null | — | Optional rationale. |
| AuditEvent.`is_exception` | boolean | Yes | `true` / `false` | — | If true, `exception_code` is required. |
| AuditEvent.`exception_code` | varchar(80) | No | Domain error code or null | — | Required for exceptions. |
| AuditEvent.`exception_details` | JSON | No | JSON object or null | — | Structured validation details. |
| AuditEvent.`occurred_at` | timestamptz | Yes | UTC | — | Database default; updates/deletes are blocked by PostgreSQL trigger. |

## Synthetic exports

The 12 application CSV files follow the entity fields above. Date and timestamp
values are ISO-formatted; decimal values are decimal text. `seed_data.json` and
`seed_data.sql` contain application entities only. The SQL script requires the
migrated schema. `ground_truth.csv` and `ground_truth.json` contain only labels
and are excluded from application imports. `anomaly_cases.csv` contains
reproducible invalid submission fixtures separate from relational input
records. `source_manifest.json` documents synthetic provenance and
transformations; `validation_summary.json` records validation status and row
counts. `generation_metadata.json` records the seed, configuration, manifest,
validation results, table counts, and SHA-256 checksums of the generated
exports.
