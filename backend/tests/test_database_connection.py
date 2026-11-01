import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.db.connection import check_database_connection


def test_database_connectivity():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run the configured database connectivity test")
    assert check_database_connection(database_url)


def test_postgresql_protects_primary_keys_and_audit_history():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL trigger tests")

    engine = create_engine(database_url)
    employee_id = f"EMP-{uuid4().hex[:12]}"
    event_id = str(uuid4())
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(
                text(
                    "INSERT INTO employees "
                    "(employee_id, name, email, department, country, hire_date, status) "
                    "VALUES (:id, 'Test', :email, 'Test', 'USA', '2026-01-01', 'Active')"
                ),
                {"id": employee_id, "email": f"{employee_id}@example.test"},
            )

            primary_key_update = connection.begin_nested()
            with pytest.raises(DBAPIError):
                connection.execute(
                    text("UPDATE employees SET employee_id = :new_id WHERE employee_id = :id"),
                    {"new_id": f"{employee_id}-changed", "id": employee_id},
                )
            primary_key_update.rollback()

            connection.execute(
                text(
                    "INSERT INTO audit_events "
                    "(event_id, entity_type, entity_id, event_type, actor_employee_id, is_exception) "
                    "VALUES (:event_id, 'Employee', :employee_id, 'created', :employee_id, false)"
                ),
                {"event_id": event_id, "employee_id": employee_id},
            )
            audit_update = connection.begin_nested()
            with pytest.raises(DBAPIError):
                connection.execute(
                    text("UPDATE audit_events SET event_type = 'changed' WHERE event_id = :id"),
                    {"id": event_id},
                )
            audit_update.rollback()

            audit_delete = connection.begin_nested()
            with pytest.raises(DBAPIError):
                connection.execute(
                    text("DELETE FROM audit_events WHERE event_id = :id"),
                    {"id": event_id},
                )
            audit_delete.rollback()
            transaction.rollback()
    finally:
        engine.dispose()
