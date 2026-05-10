"""Validate mandatory contract-test categories for CI governance."""

from __future__ import annotations

from pathlib import Path

REQUIRED_CATEGORY_PATTERNS = {
    "adapter": ["test_channel_delivery_contract.py"],
    "analytics": ["test_conversation_analytics_event_foundation.py"],
}


def validate_contract_test_categories(
    tests_root: Path,
    required_patterns: dict[str, list[str]] | None = None,
) -> list[str]:
    """Return validation issues for mandatory contract-test categories."""
    issues: list[str] = []
    mapping = required_patterns or REQUIRED_CATEGORY_PATTERNS

    if not tests_root.exists():
        return [f"tests directory not found: {tests_root}"]

    discovered = {p.name for p in tests_root.glob("test_*.py")}

    for category, patterns in mapping.items():
        matched = any(pattern in discovered for pattern in patterns)
        if not matched:
            issues.append(
                "Missing mandatory contract-test category "
                f"'{category}'. Expected one of: {patterns}"
            )

    return issues


def main() -> int:
    project_root = Path(__file__).parent
    tests_root = project_root / "tests"

    issues = validate_contract_test_categories(tests_root)
    if issues:
        print("❌ FAIL: mandatory contract-test category validation failed")
        for issue in issues:
            print(f"  - {issue}")
        return 1

    print("✅ PASS: mandatory contract-test categories are present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
