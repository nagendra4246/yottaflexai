# Architecture

## Runtime

```text
Browser
  -> React single-page application (Nginx)
  -> /api reverse proxy
  -> FastAPI routes
  -> domain services, policy/rule components, and repositories
  -> SQLAlchemy models
  -> PostgreSQL
```

Docker Compose defines three services:

- `frontend`: builds the React/Vite application and serves its static output
  with Nginx. Nginx sends `/api/*` requests to the backend and supports
  client-side routes.
- `backend`: FastAPI/Uvicorn application. Its startup script applies Alembic
  migrations, optionally loads the generated entity CSVs into an empty
  database, then starts the API. `/health` checks PostgreSQL connectivity and
  is used as the backend readiness check.
- `postgres`: PostgreSQL 16 with a health check and persistent named volume.

Only the frontend and backend are published on loopback host ports by default.
PostgreSQL is reachable by other Compose services on the private network only.
Compose waits for PostgreSQL health before starting the backend and for backend
readiness before starting the frontend.

## Code organization

- `backend/app/api`: HTTP routes
- `backend/app/schemas`: Pydantic request and response models
- `backend/app/services`: transactional application workflows
- `backend/app/rules`: policy, leave, expense, and approval decisions
- `backend/app/repositories`: database query helpers
- `backend/app/models`: SQLAlchemy entities and integrity constraints
- `backend/migrations`: Alembic schema history
- `frontend/src`: React pages, reusable components, and API client
- `generator`: deterministic CSV/JSON generation and validation
- `data/generated`: checked-in generated dataset and ground truth
- `docs`: operational and domain documentation

The API currently has no authentication or role-based authorization. Docker
port bindings are local-development defaults, not a production security
boundary.

The backend image contains only the 12 entity CSVs needed for initial seeding;
it excludes `ground_truth.csv` and `anomaly_cases.csv`. Startup seeding skips
any database that already contains application rows and never overwrites data.
Synthetic imports do not create historical audit events, so audit and
exception metrics reflect subsequent workflow activity.
