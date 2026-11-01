# API reference

The application is served by the frontend Nginx container at
`http://127.0.0.1:8091/`. The interactive OpenAPI UI is available at
`http://127.0.0.1:8091/api/docs`, and its OpenAPI document is served at
`http://127.0.0.1:8091/api/openapi.json`. Nginx proxies these same-origin
requests to the FastAPI Compose service. The frontend is also published on the
host port configured by `FRONTEND_PORT` in `.env` (default `8090`). The backend
itself listens on `http://127.0.0.1:8000`.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/employees` | Paginated employee list; filter by country and status |
| POST | `/employees` | Create an employee |
| GET | `/employees/{employee_id}` | Get an employee |
| GET | `/employees/{employee_id}/leave-balances` | Get latest balance snapshots and derived availability |
| POST | `/employees/{employee_id}/manager` | Change an employee's manager |
| GET | `/leave/policies` | List leave policies; optionally filter by country |
| POST | `/leave/requests` | Submit a leave request |
| GET | `/leave/requests` | Paginated leave requests; filter by employee and status |
| GET | `/leave/requests/{request_id}` | Get a leave request |
| GET | `/leave/requests/{request_id}/workflow` | Get request, balance snapshot, and ordered approval steps |
| POST | `/leave/requests/{request_id}/approve` | Approve the current step |
| POST | `/leave/requests/{request_id}/reject` | Reject the current step |
| POST | `/leave/requests/{request_id}/cancel` | Cancel a leave request |
| POST | `/expenses/claims` | Submit an expense claim with lines |
| GET | `/expenses/policies` | List expense policies; optionally filter by country |
| GET | `/cost-centers` | List cost centers and budget limits |
| GET | `/expenses/claims` | Paginated claims; filter by employee and status |
| GET | `/expenses/claims/{claim_id}` | Get an expense claim |
| GET | `/expenses/claims/{claim_id}/workflow` | Get claim lines, policy/receipt metadata, budget totals, and approval steps |
| GET | `/approvals/queue?approver_id=...` | List actionable pending steps assigned to an approver |
| POST | `/expenses/claims/{claim_id}/approve` | Approve the current step |
| POST | `/expenses/claims/{claim_id}/reject` | Reject the current step |
| POST | `/expenses/claims/{claim_id}/reimbursements` | Create an eligible reimbursement |
| GET | `/reimbursements` | Paginated reimbursements; filter by status |
| POST | `/reimbursements/{reimbursement_id}/process` | Process a pending reimbursement |
| GET | `/audit/events` | Paginated audit events; filter by entity or exception |
| GET | `/analytics/summary` | Operational counts and totals |
| GET | `/health` | Readiness check including database connectivity (not in OpenAPI) |

List endpoints accept `limit` (1–100) and `offset` (0 or greater) and return
`items`, `total`, `limit`, and `offset`. POST bodies and response shapes are
defined in `backend/app/schemas`. Errors use
`{"error":{"code":"...","message":"...","details":{...}}}`.

Approval bodies contain `approver_id` and optional `reason` and `comments`.
Rejecting requires a nonblank reason. Reimbursement creation is nested under a
claim; the body includes amount, payment date, and transaction reference.

Authentication and role-based authorization are not implemented. Approver
identity is provided by the caller and checked against the configured workflow
step, not a logged-in identity. Do not expose this API as a production service
without adding an appropriate identity and authorization layer.
