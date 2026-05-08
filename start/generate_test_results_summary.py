"""
start/generate_test_results_summary.py

Runs all tests in tests/ and writes a structured JSON summary
that evaluate_launch_gates.py can consume.

Usage:
    python start/generate_test_results_summary.py

Output:
    _bmad-output/test-artifacts/test-results-summary.json
"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "_bmad-output" / "test-artifacts" / "test-results-summary.json"

# Map from gate key → (test module, test class, test method) tuples
GATE_TEST_MAP: dict[str, list[tuple[str, str, str]]] = {
    "security_tests_all_pass": [
        ("tests.test_reliability", "SecurityDecoratorTests", "test_rejects_invalid_signature"),
        ("tests.test_reliability", "SecurityDecoratorTests", "test_rejects_malformed_signature_header"),
        ("tests.test_reliability", "SecurityDecoratorTests", "test_rejects_old_timestamp"),
        ("tests.test_reliability", "SecurityDecoratorTests", "test_rejects_replay_signature"),
        ("tests.test_release_gates", "ReleaseSecurityGateTests", "test_valid_signature_request_accepted"),
        ("tests.test_release_gates", "ReleaseSecurityGateTests", "test_rejection_does_not_expose_app_secret"),
        ("tests.test_release_gates", "ReleaseWebhookVerificationTests", "test_webhook_get_challenge_positive_path"),
        ("tests.test_release_gates", "ReleaseWebhookVerificationTests", "test_webhook_get_challenge_token_mismatch"),
        ("tests.test_release_gates", "ReleaseWebhookVerificationTests", "test_webhook_get_challenge_missing_mode"),
    ],
    "security_replay_test_pass": [
        ("tests.test_reliability", "SecurityDecoratorTests", "test_rejects_replay_signature"),
    ],
    "idempotency_memory_pass": [
        ("tests.test_reliability", "WebhookIdempotencyTests", "test_duplicate_message_is_skipped"),
    ],
    "idempotency_sqlite_pass": [
        ("tests.test_reliability", "WebhookIdempotencyTests", "test_duplicate_message_is_skipped_with_sqlite_store"),
    ],
    "sqlite_fallback_pass": [
        ("tests.test_expiring_store", "SQLiteExpiringStoreTests", "test_factory_falls_back_to_memory_when_sqlite_fails"),
    ],
    "outbound_retry_test_pass": [
        ("tests.test_release_gates", "ReleaseOutboundGateTests", "test_outbound_retry_attempts_match_spec"),
    ],
    "outbound_fallback_test_pass": [
        ("tests.test_release_gates", "ReleaseOutboundGateTests", "test_fallback_sent_after_retry_exhaustion"),
    ],
}


def _run_gate(gate_key: str, tests: list[tuple[str, str, str]]) -> bool | None:
    """Returns True if all tests pass/skip, False if any fail, None on error."""
    import io

    results = []
    for module_name, class_name, method_name in tests:
        test_id = f"{module_name}.{class_name}.{method_name}"
        suite = unittest.defaultTestLoader.loadTestsFromName(test_id)
        if suite.countTestCases() == 0:
            print(f"  WARN: Could not load test: {test_id}")
            results.append("error")
            continue

        buf = io.StringIO()
        runner = unittest.TextTestRunner(stream=buf, verbosity=0)
        result = runner.run(suite)

        if result.skipped:
            results.append("skip")
        elif result.errors or result.failures:
            results.append("fail")
        else:
            results.append("pass")

    if not results:
        return None
    if all(r in ("pass", "skip") for r in results):
        return True
    if any(r == "fail" for r in results):
        return False
    return None


def main() -> int:
    sys.path.insert(0, str(ROOT))

    summary: dict = {
        "generated": datetime.now(timezone.utc).isoformat(),
    }

    for gate_key, tests in GATE_TEST_MAP.items():
        print(f"  Checking gate: {gate_key} ...")
        result = _run_gate(gate_key, tests)
        summary[gate_key] = result
        symbol = "PASS" if result is True else ("UNKNOWN" if result is None else "FAIL")
        print(f"    {symbol} {gate_key}: {result}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nTest results summary written to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    import os
    sys.exit(main())
