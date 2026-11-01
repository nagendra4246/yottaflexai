# Backend domain layer

The backend entry point is `backend.app.main:app`. Domain services are separated
from HTTP route handlers under `backend/app/services`; pure validation and
routing components are under `backend/app/rules`. Database reads and ID
allocation are grouped in `backend/app/repositories`.

Run the API locally after applying database migrations:

```powershell
$env:PYTHONPATH = (Resolve-Path .\backend).Path
$env:DATABASE_URL = "postgresql+psycopg2://yottaflex:<password>@localhost:5432/yottaflex"
uvicorn app.main:app --app-dir backend --reload
```

`POST /leave/requests` reserves available balance when routing begins. Final
approval moves the reserved days to used balance; rejection or cancellation
releases the reservation. Public holidays are loaded by country and are
excluded with weekends.

Expense claim totals are calculated from submitted lines. Policy caps, receipt
metadata, employment dates, cost-center budget, duplicate receipt hashes, and
near-date split claims are checked before a claim and its approval chain are
persisted. Budget comparisons currently use stored claim amounts as-is because
the data model defines no cost-center currency or exchange-rate source.

Approval steps are processed in sequence. A rejection closes later pending
steps while retaining an audit event per transition. Reimbursement records have
Pending and Processed states and may be created only for finally approved
claims.

## REST API

The API is exposed by `backend.app.main:app` and documents its request and
response schemas in the generated OpenAPI document at `/openapi.json` (Swagger
UI at `/docs`). Employee, leave-request, expense-claim, reimbursement, and
audit-event list endpoints accept `limit` (1-100) and `offset` parameters and
return `items`, `total`, `limit`, and `offset`. Other useful filters are
documented in OpenAPI.

Errors use a stable envelope with `error.code`, `error.message`, and
`error.details`. Domain validation, approval, and reimbursement behavior
remains in service functions; route handlers delegate writes to those services.
The current API does not implement authentication or role-based authorization.

Run backend tests from the repository root:

```powershell
$env:PYTHONPATH = (Resolve-Path .\backend).Path
python -m pytest .\backend\tests -q
```
