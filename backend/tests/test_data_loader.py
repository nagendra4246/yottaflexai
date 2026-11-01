from pathlib import Path
from datetime import date

from sqlalchemy import func, select

from app.db.session import create_database_engine
from app.models import ApprovalStep, AuditEvent, Employee, ExpenseClaim, LeaveRequest
from generator.generator import TABLE_ORDER
from generator.load_data import seed_database


DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "generated"


def test_seed_loads_application_csvs_and_is_repeatable(tmp_path):
    engine = create_database_engine(f"sqlite:///{tmp_path / 'seed.db'}")
    try:
        from app.db.base import Base

        Base.metadata.create_all(engine)

        result = seed_database(engine, DATA_DIR)
        assert result.status == "loaded"
        assert result.table_counts["employees"] == 400
        assert result.table_counts["leave_requests"] == 800
        assert result.table_counts["expense_claims"] == 1000
        assert result.table_counts["expense_lines"] == 5415
        assert result.table_counts["reimbursements"] == 200

        repeated = seed_database(engine, DATA_DIR)
        assert repeated.status == "skipped_non_empty"
        assert repeated.table_counts == result.table_counts

        with engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(Employee.__table__)) == 400
            assert connection.scalar(select(func.count()).select_from(LeaveRequest.__table__)) == 800
            assert connection.scalar(select(func.count()).select_from(ExpenseClaim.__table__)) == 1000
            assert connection.scalar(select(func.count()).select_from(ApprovalStep.__table__)) == 1803
            assert connection.scalar(
                select(func.count()).select_from(AuditEvent.__table__)
            ) == 0
    finally:
        engine.dispose()


def test_seed_preserves_existing_database_records(tmp_path):
    engine = create_database_engine(f"sqlite:///{tmp_path / 'nonempty.db'}")
    try:
        from app.db.base import Base

        Base.metadata.create_all(engine)
        employee_table = Employee.__table__
        with engine.begin() as connection:
            connection.execute(
                employee_table.insert(),
                {
                    "employee_id": "EMP-999999",
                    "name": "Existing employee",
                    "email": "existing@example.test",
                    "manager_id": None,
                    "department": "Operations",
                    "country": "USA",
                    "hire_date": date(2020, 1, 1),
                    "termination_date": None,
                    "status": "Active",
                    "approval_role": None,
                },
            )

        result = seed_database(engine, DATA_DIR)
        assert result.status == "skipped_non_empty"
        assert result.table_counts["employees"] == 1
        assert all(result.table_counts[table] == 0 for table in TABLE_ORDER if table != "employees")
    finally:
        engine.dispose()


def test_generated_sql_seed_executes_against_migrated_schema(tmp_path):
    engine = create_database_engine(f"sqlite:///{tmp_path / 'sql-seed.db'}")
    try:
        from app.db.base import Base

        Base.metadata.create_all(engine)
        raw_connection = engine.raw_connection()
        try:
            raw_connection.driver_connection.executescript(
                (DATA_DIR / "seed_data.sql").read_text("utf-8")
            )
        finally:
            raw_connection.close()

        with engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(Employee.__table__)) == 400
            assert connection.scalar(select(func.count()).select_from(LeaveRequest.__table__)) == 800
            assert connection.scalar(select(func.count()).select_from(ExpenseClaim.__table__)) == 1000
    finally:
        engine.dispose()
