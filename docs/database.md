# Database and migrations

PostgreSQL 16 is the supported application database. The default Docker Compose
deployment keeps it on the private Compose network and stores its files in the
named `yottaflex_postgres_data` volume.

The SQLAlchemy models are in `backend/app/models`; Alembic revisions are in
`backend/migrations/versions`. The backend container runs `alembic upgrade head`
before starting Uvicorn. A failed migration exits the container rather than
starting the API against an outdated schema.

```powershell
docker compose exec backend alembic current
docker compose exec backend alembic upgrade head
```

For host-based development, set `DATABASE_URL` to a PostgreSQL connection URL
reachable from the host. The Compose database is intentionally not published
to a host port; use `docker compose exec postgres psql -U yottaflex -d yottaflex`
for local inspection. Configure a non-placeholder `POSTGRES_PASSWORD` in `.env`
and URL-encode special characters if supplying a custom `DATABASE_URL`.

The schema uses real foreign keys, unique constraints, indexes, and checks.
Approval steps reference exactly one leave request or expense claim. Audit
events preserve transitions and exceptions; negative leave balances remain
representable so the required anomaly can be modeled.
