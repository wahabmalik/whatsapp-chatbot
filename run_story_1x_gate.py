"""Story 1.x quality gate runner with artifact output.

Runs Story 1.1, 1.2a, 1.2b, and 1.3 suites and writes a JSON report
for release evidence.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

TEST_TARGETS = [
    "tests/test_saas_1_1_schema_and_tenant_model.py",
    "tests/test_saas_1_2a_auth_flow.py",
    "tests/test_saas_1_2b_password_reset_flow.py",
    "tests/test_saas_1_3_tenant_isolation.py",
]

ARTIFACT_PATH = Path("_bmad-output/test-artifacts/story-1x-gate-report.json")


def run_story_gate() -> int:
    started_at = time.time()
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *TEST_TARGETS,
        "-q",
    ]

    print("=" * 70)
    print("STORY 1.X GATE")
    print("=" * 70)
    print(f"Command: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    duration_seconds = round(time.time() - started_at, 2)

    report = {
        "gate": "story-1x",
        "timestamp_epoch": int(started_at),
        "duration_seconds": duration_seconds,
        "passed": result.returncode == 0,
        "exit_code": result.returncode,
        "targets": TEST_TARGETS,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }

    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)

    print("-" * 70)
    print(f"Artifact: {ARTIFACT_PATH}")
    print(f"Duration: {duration_seconds}s")
    print("Result: PASS" if result.returncode == 0 else "Result: FAIL")

    return result.returncode


def main() -> None:
    raise SystemExit(run_story_gate())


if __name__ == "__main__":
    main()
