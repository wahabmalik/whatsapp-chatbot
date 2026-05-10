"""Validate launch-gate artifact structure and source-key completeness."""

from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path

import logging
import yaml

VALID_SOURCES = {"test_results", "staging_report", "file_exists", "file_contains", "manual"}
REQUIRED_GATE_FIELDS = ("id", "label", "domain", "blocking", "source", "key")
logger = logging.getLogger(__name__)


def _load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _load_json_safely(path: Path, *, artifact_label: str, issues: list[str]) -> dict | None:
    try:
        return _load_json(path)
    except (OSError, JSONDecodeError) as exc:
        logger.error(f"Critical error loading {artifact_label} JSON ({path.name}): {exc}")
        issues.append(f"Invalid {artifact_label} JSON ({path.name}): {exc}")
        return None


def validate_launch_gate_artifact_completeness(project_root: Path) -> list[str]:
    """Validate launch-gates and mapped evidence artifacts are complete."""
    issues: list[str] = []

    artifacts_dir = project_root / "_bmad-output" / "test-artifacts"
    launch_gates_path = artifacts_dir / "launch-gates.yaml"
    test_results_path = artifacts_dir / "test-results-summary.json"
    staging_report_path = artifacts_dir / "staging-validation-report.json"

    if not launch_gates_path.exists():
        return [f"Missing launch gate artifact: {launch_gates_path}"]

    try:
        doc = _load_yaml(launch_gates_path)
    except yaml.YAMLError as e:
        issues.append(f"YAML parsing error in {launch_gates_path.name}: {e}")
        return issues
    except OSError as e:
        issues.append(f"Unable to read {launch_gates_path.name}: {e}")
        return issues

    for root_field in ("version", "generated", "gates"):
        if root_field not in doc:
            issues.append(f"launch-gates.yaml missing required root field: {root_field}")

    gates = doc.get("gates")
    if not isinstance(gates, list) or not gates:
        issues.append("launch-gates.yaml gates must be a non-empty list")
        return issues

    test_results_doc = (
        _load_json_safely(
            test_results_path,
            artifact_label="test-results summary",
            issues=issues,
        )
        if test_results_path.exists()
        else None
    )
    staging_report_doc = (
        _load_json_safely(
            staging_report_path,
            artifact_label="staging validation report",
            issues=issues,
        )
        if staging_report_path.exists()
        else None
    )

    for index, gate in enumerate(gates):
        if not isinstance(gate, dict):
            issues.append(f"gate[{index}] is not an object")
            continue

        missing_fields = [field for field in REQUIRED_GATE_FIELDS if field not in gate]
        if missing_fields:
            issues.append(
                f"gate[{index}] missing required fields: {missing_fields}"
            )
            continue

        source = gate["source"]
        key = str(gate["key"])

        if source not in VALID_SOURCES:
            issues.append(f"gate[{index}] has invalid source '{source}'")
            continue

        if source == "test_results":
            if test_results_doc is None:
                issues.append("test-results-summary.json is required for test_results gates")
            elif key not in test_results_doc:
                issues.append(f"test_results key missing in evidence: {key}")

        elif source == "staging_report":
            if staging_report_doc is None:
                issues.append("staging-validation-report.json is required for staging_report gates")
            elif key not in staging_report_doc:
                issues.append(f"staging_report key missing in evidence: {key}")

        elif source == "file_exists":
            target = project_root / key
            if not target.exists():
                issues.append(f"file_exists target missing: {key}")

        elif source == "file_contains":
            path_part, sep, needle = key.partition("::")
            if not sep:
                issues.append(f"file_contains key must use 'path::substring' format: {key}")
                continue
            if not needle.strip():
                issues.append(
                    f"file_contains key must include a non-empty substring after '::': {key}"
                )
                continue
            target = project_root / path_part.strip()
            if not target.exists():
                issues.append(f"file_contains target missing: {path_part.strip()}")
                continue
            text = target.read_text(encoding="utf-8").lower()
            if needle.strip().lower() not in text:
                issues.append(
                    f"file_contains substring missing in {path_part.strip()}: {needle.strip()}"
                )

        elif source == "manual":
            raw_key = gate.get("key")
            logger.debug("Manual source detected. Key type=%s", type(raw_key).__name__)
            if not isinstance(raw_key, str) or not raw_key.strip():
                issues.append(f"gate[{index}] manual source has an empty key")
                continue
            continue

    return issues


def main() -> int:
    project_root = Path(__file__).parent
    issues = validate_launch_gate_artifact_completeness(project_root)

    if issues:
        print("❌ FAIL: launch-gate artifact completeness validation failed")
        for issue in issues:
            print(f"  - {issue}")
        return 1

    print("✅ PASS: launch-gate artifact completeness validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
