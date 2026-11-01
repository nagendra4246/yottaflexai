from typing import Any


def build_ground_truth(cases: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "entity_id": case["entity_id"],
            "issue_type": case["issue_type"],
            "label": case["label"],
        }
        for case in sorted(cases, key=lambda row: (row["issue_type"], row["entity_id"]))
    ]
