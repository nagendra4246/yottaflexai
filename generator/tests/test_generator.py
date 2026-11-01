import csv
import json

from generator.config import GeneratorConfig
from generator.generator import build_dataset, generate
from generator.validation import validate_dataset


def _read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_default_dataset_counts_and_required_ground_truth():
    tables, ground_truth, anomaly_cases = build_dataset(GeneratorConfig())
    report = validate_dataset(tables, ground_truth, anomaly_cases)
    assert report["tables"]["employees"] == 400
    assert report["tables"]["leave_policies"] == 6
    assert report["tables"]["leave_requests"] == 800
    assert report["tables"]["expense_claims"] == 1000
    assert report["tables"]["expense_lines"] >= 1000
    assert all(
        1 <= sum(line["claim_id"] == claim["claim_id"] for line in tables["expense_lines"]) <= 10
        for claim in tables["expense_claims"]
    )
    employees = {row["employee_id"]: row for row in tables["employees"]}
    policies = {
        row["policy_id"]: row["category"] for row in tables["expense_policies"]
    }
    claims = {row["claim_id"]: row for row in tables["expense_claims"]}
    routed_claim_ids = {
        line["claim_id"]
        for line in tables["expense_lines"]
        if employees[claims[line["claim_id"]]["employee_id"]]["country"] == "GER"
        and policies[line["policy_id"]] == "Client Entertainment"
        and claims[line["claim_id"]]["status"] != "Draft"
    }
    assert routed_claim_ids
    for claim_id in routed_claim_ids:
        assert any(
            employees[row["approver_id"]]["approval_role"] == "Finance"
            for row in tables["approval_steps"]
            if row["expense_claim_id"] == claim_id
        )
    issues = {row["issue_type"] for row in ground_truth}
    assert {
        "Negative Leave Balance",
        "Overlapping Approved Leave",
        "Expense Outside Employment Dates",
        "Split Claims",
        "Missing Cost Center",
        "Requester Self Approval",
        "Duplicate Reimbursement",
        "Weekend Leave",
        "Holiday Leave",
        "Exact Approval Threshold",
        "Above Approval Threshold",
        "Duplicate Receipt Hash",
        "Expired Policy",
        "No Manager - Valid Top Level",
        "Partial Approval Then Rejection",
        "Missing Receipt",
        "Expense Policy Limit Breach",
    }.issubset(issues)


def test_same_seed_produces_identical_files_and_checksums(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_metadata = generate(first, 20261022)
    second_metadata = generate(second, 20261022)

    assert first_metadata == second_metadata
    first_files = {path.name: path.read_bytes() for path in first.iterdir()}
    second_files = {path.name: path.read_bytes() for path in second.iterdir()}
    assert first_files.keys() == second_files.keys()
    assert first_files == second_files

    metadata_file = json.loads((first / "generation_metadata.json").read_text("utf-8"))
    assert metadata_file["seed"] == 20261022
    assert metadata_file["sha256"] == first_metadata["sha256"]
    assert metadata_file["validation_summary"]["status"] == "passed"
    assert set(metadata_file["sha256"]) == {
        path.name for path in first.iterdir() if path.name != "generation_metadata.json"
    }
    assert len(_read_csv(first / "ground_truth.csv")) == 17
    assert json.loads((first / "ground_truth.json").read_text("utf-8")) == _read_csv(
        first / "ground_truth.csv"
    )
    assert len(_read_csv(first / "anomaly_cases.csv")) == 8
    seed_json = json.loads((first / "seed_data.json").read_text("utf-8"))
    assert "ground_truth" not in seed_json
    assert seed_json["tables"]["employees"]
    sql = (first / "seed_data.sql").read_text("utf-8")
    assert sql.startswith("-- Application seed data only")
    assert "INSERT INTO employees" in sql
    assert "INSERT INTO ground_truth" not in sql
    assert json.loads((first / "validation_summary.json").read_text("utf-8"))[
        "status"
    ] == "passed"


def test_alternate_seed_is_reproducible_but_changes_generated_records(tmp_path):
    first = tmp_path / "alternate-first"
    second = tmp_path / "alternate-second"
    metadata_a = generate(first, 7)
    metadata_b = generate(second, 7)
    assert metadata_a == metadata_b
    assert (first / "employees.csv").read_bytes() == (second / "employees.csv").read_bytes()
    assert metadata_a["sha256"]["employees.csv"] != generate(
        tmp_path / "default", 20261022
    )["sha256"]["employees.csv"]


def test_starter_scale_keeps_required_cases_and_source_manifest(tmp_path):
    config = GeneratorConfig(
        seed=20261022,
        employees=20,
        leave_requests=40,
        expense_claims=30,
        min_expense_lines=1,
        max_expense_lines=3,
    )
    metadata = generate(tmp_path / "starter", config=config)
    tables, ground_truth, anomaly_cases = build_dataset(config)
    validation = validate_dataset(tables, ground_truth, anomaly_cases, config=config)

    assert validation["tables"]["employees"] == 20
    assert validation["tables"]["leave_requests"] == 40
    assert validation["tables"]["expense_claims"] == 30
    assert all(
        1 <= sum(line["claim_id"] == claim["claim_id"] for line in tables["expense_lines"]) <= 3
        for claim in tables["expense_claims"]
    )
    metadata_file = json.loads(
        (tmp_path / "starter" / "generation_metadata.json").read_text("utf-8")
    )
    assert metadata_file["source_manifest"]["provenance"].startswith("synthetic")
    assert metadata_file["source_manifest"]["config"]["employees"] == 20
    assert len(ground_truth) == 17
    assert metadata["row_counts"]["expense_claims"] == 30
