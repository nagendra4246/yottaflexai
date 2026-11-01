from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import Date, DateTime, Integer, Numeric, Table, func, insert, select, text
from sqlalchemy.engine import Engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.db.session import create_database_engine
from app.models import (
    ApprovalRule,
    ApprovalStep,
    CostCenter,
    Employee,
    ExpenseClaim,
    ExpenseLine,
    ExpensePolicy,
    LeaveBalance,
    LeavePolicy,
    LeaveRequest,
    PublicHoliday,
    Reimbursement,
)
from generator.generator import TABLE_ORDER

MODEL_BY_TABLE: dict[str, type] = {
    "employees": Employee,
    "leave_policies": LeavePolicy,
    "expense_policies": ExpensePolicy,
    "cost_centers": CostCenter,
    "approval_rules": ApprovalRule,
    "public_holidays": PublicHoliday,
    "leave_requests": LeaveRequest,
    "leave_balances": LeaveBalance,
    "expense_claims": ExpenseClaim,
    "expense_lines": ExpenseLine,
    "approval_steps": ApprovalStep,
    "reimbursements": Reimbursement,
}
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "generated"
POSTGRES_SEED_LOCK_ID = 20261022


class SeedDataError(ValueError):
    """Raised when source CSVs do not match the application schema."""


@dataclass(frozen=True)
class SeedResult:
    status: str
    table_counts: dict[str, int]


def _convert_value(value: str, column: Any, file_name: str, row_number: int) -> Any:
    if value == "":
        if not column.nullable and column.default is None and column.server_default is None:
            raise SeedDataError(
                f"{file_name}:{row_number}: {column.name} cannot be blank"
            )
        return None

    column_type = column.type
    try:
        if isinstance(column_type, DateTime):
            return datetime.fromisoformat(value)
        if isinstance(column_type, Date):
            return date.fromisoformat(value)
        if isinstance(column_type, Numeric):
            return Decimal(value)
        if isinstance(column_type, Integer):
            return int(value)
        if column_type.python_type is bool:
            normalized = value.casefold()
            if normalized not in {"true", "false"}:
                raise ValueError("expected True or False")
            return normalized == "true"
        if column_type.python_type in {dict, list}:
            return json.loads(value)
    except (InvalidOperation, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SeedDataError(
            f"{file_name}:{row_number}: invalid {column.name}: {value!r}"
        ) from error
    return value


def _read_table_csv(data_dir: Path, table_name: str) -> list[dict[str, Any]]:
    file_name = f"{table_name}.csv"
    path = data_dir / file_name
    if not path.is_file():
        raise SeedDataError(f"Required source file is missing: {path}")

    table: Table = MODEL_BY_TABLE[table_name].__table__
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise SeedDataError(f"{file_name} has no CSV header")
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise SeedDataError(f"{file_name} contains duplicate column names")
        columns = {column.name: column for column in table.columns}
        unknown = set(reader.fieldnames) - set(columns)
        missing = {
            column.name
            for column in table.columns
            if not column.nullable
            and column.default is None
            and column.server_default is None
            and column.name not in reader.fieldnames
        }
        if unknown or missing:
            raise SeedDataError(
                f"{file_name} does not match {table_name}: "
                f"unknown columns={sorted(unknown)}, missing required columns={sorted(missing)}"
            )

        rows: list[dict[str, Any]] = []
        primary_key = next(iter(table.primary_key.columns))
        seen_ids: set[Any] = set()
        for row_number, raw_row in enumerate(reader, start=2):
            if None in raw_row:
                raise SeedDataError(
                    f"{file_name}:{row_number}: row contains more fields than its header"
                )
            row = {
                name: _convert_value(value, columns[name], file_name, row_number)
                for name, value in raw_row.items()
                if name is not None
            }
            row_id = row.get(primary_key.name)
            if row_id in seen_ids:
                raise SeedDataError(
                    f"{file_name}:{row_number}: duplicate {primary_key.name} {row_id!r}"
                )
            seen_ids.add(row_id)
            rows.append(row)

    if not rows:
        raise SeedDataError(f"{file_name} contains no data rows")
    return rows


def read_seed_data(data_dir: Path = DEFAULT_DATA_DIR) -> dict[str, list[dict[str, Any]]]:
    """Read only application entity CSVs; evaluation labels/cases are never loaded."""
    return {
        table_name: _read_table_csv(data_dir, table_name)
        for table_name in TABLE_ORDER
    }


def _row_count(connection: Any, table: Table) -> int:
    return connection.scalar(select(func.count()).select_from(table)) or 0


def seed_database(engine: Engine, data_dir: Path = DEFAULT_DATA_DIR) -> SeedResult:
    rows_by_table = read_seed_data(data_dir)
    tables = {
        name: MODEL_BY_TABLE[name].__table__
        for name in TABLE_ORDER
    }

    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": POSTGRES_SEED_LOCK_ID},
            )

        existing_counts = {
            name: _row_count(connection, table) for name, table in tables.items()
        }
        if any(existing_counts.values()):
            return SeedResult("skipped_non_empty", existing_counts)

        for name in TABLE_ORDER:
            connection.execute(insert(tables[name]), rows_by_table[name])

        loaded_counts = {
            name: _row_count(connection, table) for name, table in tables.items()
        }
        expected_counts = {
            name: len(rows_by_table[name]) for name in TABLE_ORDER
        }
        if loaded_counts != expected_counts:
            raise RuntimeError(
                f"Seed row-count verification failed: expected {expected_counts}, "
                f"found {loaded_counts}"
            )

    return SeedResult("loaded", loaded_counts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load generated application CSV data into an empty PostgreSQL database."
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    arguments = parser.parse_args()

    engine = create_database_engine()
    try:
        result = seed_database(engine, arguments.data_dir)
    finally:
        engine.dispose()

    if result.status == "skipped_non_empty":
        print(
            "Seed skipped: application tables already contain data; no rows were changed.",
            file=sys.stderr,
        )
    print(json.dumps(asdict(result), sort_keys=True))


if __name__ == "__main__":
    main()
