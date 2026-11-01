from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_alembic_upgrade_creates_schema(tmp_path, monkeypatch):
    database_path = tmp_path / "migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert {
            "employees",
            "leave_policies",
            "leave_balances",
            "leave_requests",
            "expense_policies",
            "expense_claims",
            "expense_lines",
            "cost_centers",
            "approval_rules",
            "approval_steps",
            "reimbursements",
            "audit_events",
            "public_holidays",
            "alembic_version",
        }.issubset(tables)
        assert inspector.get_foreign_keys("approval_steps")
        assert inspector.get_check_constraints("approval_steps")
    finally:
        engine.dispose()
