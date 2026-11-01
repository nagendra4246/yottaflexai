# YottaFlex AI frontend

React and Vite frontend for the existing FastAPI service. All business records
and decisions are loaded from the API; the frontend does not contain synthetic
records or duplicate domain validation.

## Run locally

From the repository root, start the FastAPI application:

```powershell
$env:PYTHONPATH = (Resolve-Path .\backend).Path
$env:DATABASE_URL = "postgresql+psycopg2://yottaflex:<password>@localhost:5432/yottaflex"
uvicorn app.main:app --app-dir backend --reload
```

In another terminal:

```powershell
Set-Location .\frontend
npm install
npm run dev
```

Vite proxies `/api` to `http://127.0.0.1:8000` by default. Override
`VITE_DEV_API_TARGET` for a different development API host. Set
`VITE_API_BASE_URL` to the deployed API base URL when building for deployment.
The backend must be reachable and its database migrated for records to load.

## API capabilities and display limitations

The interface supports leave and expense submission, assigned-step approval
queue inspection, approve/reject decisions, reimbursement creation and
processing, exception review, and workflow detail views. The backend exposes
leave balance snapshots, ordered approval steps, expense lines and receipt
metadata, cost-center budget calculations, and applicable policies for these
flows. Authentication is not implemented: the operator selects an actor ID,
and the backend validates assignment and sequence but cannot verify identity.
