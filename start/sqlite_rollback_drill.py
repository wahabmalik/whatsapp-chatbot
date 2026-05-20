"""SQLite rollback drill automation harness for Story 11.2.

Runs a timed rollback simulation from SQLite to memory backend and emits
JSON + markdown evidence artifacts under _bmad-output/test-artifacts/.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask

from app.services.expiring_store import ExpiringKeyStore, SQLiteExpiringKeyStore, create_expiring_store


ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_DIR = ROOT / "_bmad-output" / "test-artifacts"
DRILL_DURATION_LIMIT_SECONDS = 15 * 60
ROLLBACK_NAMESPACE = "sqlite_rollback_drill"


@dataclass
class DrillStepResult:
    name: str
    passed: bool
    elapsed_seconds: float
    details: str


def _evidence_path(now: datetime | None = None) -> Path:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d")
    return ARTIFACT_DIR / f"sqlite-rollback-drill-{stamp}.md"


def _latest_evidence_path() -> Path:
    return ARTIFACT_DIR / "sqlite-rollback-drill-latest.md"


def _step_precheck_sqlite(sqlite_path: str, window_seconds: int) -> tuple[DrillStepResult, dict[str, Any]]:
    started = time.monotonic()
    transition_key = "rollback-transition-key"
    try:
        store = SQLiteExpiringKeyStore(
            db_path=sqlite_path,
            namespace=ROLLBACK_NAMESPACE,
            window_seconds=window_seconds,
        )
        first = store.seen_recently("rollback-health-key")
        second = store.seen_recently("rollback-health-key")
        transition_seen_first = store.seen_recently(transition_key)
        store.close()
        passed = (first is False) and (second is True) and (transition_seen_first is False)
        details = "SQLite precheck passed and transition key seeded" if passed else "Unexpected SQLite precheck behavior"
        step = DrillStepResult(
            name="sqlite_precheck",
            passed=passed,
            elapsed_seconds=round(time.monotonic() - started, 4),
            details=details,
        )
        return step, {"transition_key": transition_key}
    except Exception as exc:  # pragma: no cover - defensive
        step = DrillStepResult(
            name="sqlite_precheck",
            passed=False,
            elapsed_seconds=round(time.monotonic() - started, 4),
            details=f"SQLite precheck failed: {exc}",
        )
        return step, {"transition_key": transition_key}


def _step_rollback_transition(
    *,
    sqlite_path: str,
    window_seconds: int,
    transition_key: str,
    simulate_restart: bool,
) -> tuple[DrillStepResult, dict[str, Any]]:
    started = time.monotonic()

    try:
        if simulate_restart:
            # Simulate pre-restart app state with SQLite enabled.
            pre_restart_app = Flask(__name__)
            pre_restart_app.config["STATE_STORE_BACKEND"] = "sqlite"
            pre_restart_app.config["STATE_STORE_SQLITE_PATH"] = sqlite_path
            pre_restart_app.config["STATE_STORE_FALLBACK_TO_MEMORY"] = True
            pre_restart_store = create_expiring_store(
                app=pre_restart_app,
                extension_key="sqlite_rollback_drill_store",
                namespace=ROLLBACK_NAMESPACE,
                window_seconds=window_seconds,
            )
            pre_restart_store.close()

        # Post-restart app context with memory backend after rollback toggle.
        app = Flask(__name__)
        app.config["STATE_STORE_BACKEND"] = "memory"
        app.config["STATE_STORE_SQLITE_PATH"] = sqlite_path
        app.config["STATE_STORE_FALLBACK_TO_MEMORY"] = True

        store = create_expiring_store(
            app=app,
            extension_key="sqlite_rollback_drill_store",
            namespace=ROLLBACK_NAMESPACE,
            window_seconds=window_seconds,
        )

        backend_is_memory = isinstance(store, ExpiringKeyStore) and not isinstance(store, SQLiteExpiringKeyStore)
        post_transition_first = store.seen_recently(transition_key)
        memory_probe_first = store.seen_recently("memory-probe-key")
        memory_probe_second = store.seen_recently("memory-probe-key")

        no_corruption_signal = (
            (post_transition_first is False)
            and (memory_probe_first is False)
            and (memory_probe_second is True)
        )
        store.close()
        passed = backend_is_memory and no_corruption_signal
        details = (
            "Rollback activated memory backend and transition integrity checks passed"
            if passed
            else "Rollback transition checks failed"
        )
        step = DrillStepResult(
            name="rollback_transition",
            passed=passed,
            elapsed_seconds=round(time.monotonic() - started, 4),
            details=details,
        )

        return step, {
            "backend": "memory" if backend_is_memory else type(store).__name__,
            "post_transition_first_seen": post_transition_first,
            "memory_probe_first": memory_probe_first,
            "memory_probe_second": memory_probe_second,
        }
    except Exception as exc:  # pragma: no cover - defensive
        step = DrillStepResult(
            name="rollback_transition",
            passed=False,
            elapsed_seconds=round(time.monotonic() - started, 4),
            details=f"Rollback transition failed: {exc}",
        )
        return step, {
            "backend": "unknown",
            "post_transition_first_seen": None,
            "memory_probe_first": None,
            "memory_probe_second": None,
        }


def run_rollback_drill(
    *,
    window_seconds: int,
    sqlite_path: str,
    target_os: str,
    simulate_restart: bool,
    duration_limit_seconds: int = DRILL_DURATION_LIMIT_SECONDS,
) -> dict[str, Any]:
    started = time.monotonic()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)

    steps: list[DrillStepResult] = []

    precheck_step, precheck_meta = _step_precheck_sqlite(sqlite_path=sqlite_path, window_seconds=window_seconds)
    steps.append(precheck_step)

    rollback_step, rollback_meta = _step_rollback_transition(
        sqlite_path=sqlite_path,
        window_seconds=window_seconds,
        transition_key=precheck_meta["transition_key"],
        simulate_restart=simulate_restart,
    )
    steps.append(rollback_step)

    elapsed_seconds = round(time.monotonic() - started, 4)
    within_limit = elapsed_seconds <= duration_limit_seconds
    steps_passed = all(step.passed for step in steps)
    passed = steps_passed and within_limit

    report = {
        "story": "11.2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_os": target_os,
        "sqlite_path": sqlite_path,
        "simulate_restart": simulate_restart,
        "duration_limit_seconds": duration_limit_seconds,
        "elapsed_seconds": elapsed_seconds,
        "elapsed_minutes": round(elapsed_seconds / 60.0, 4),
        "steps": [step.__dict__ for step in steps],
        "transition_summary": {
            "transition_key": precheck_meta["transition_key"],
            "backend_after_rollback": rollback_meta["backend"],
            "post_transition_first_seen": rollback_meta["post_transition_first_seen"],
            "memory_probe_first": rollback_meta["memory_probe_first"],
            "memory_probe_second": rollback_meta["memory_probe_second"],
        },
        "acceptance": {
            "steps_passed": steps_passed,
            "within_15_minutes": within_limit,
            "duration_limit_minutes": round(duration_limit_seconds / 60.0, 2),
        },
    }
    report["passed"] = passed
    return report


def _render_markdown(report: dict[str, Any]) -> str:
    acceptance = report["acceptance"]
    transition = report["transition_summary"]

    lines = [
        "# SQLite Rollback Drill Evidence",
        "",
        f"Generated: {report['generated_at']}",
        f"Story: {report['story']}",
        f"Target OS: {report['target_os']}",
        f"SQLite Path: {report['sqlite_path']}",
        f"Elapsed Seconds: {report['elapsed_seconds']}",
        f"Elapsed Minutes: {report['elapsed_minutes']}",
        f"Drill Threshold: <= {acceptance['duration_limit_minutes']} minutes",
        "",
        "## Steps Executed",
        "",
        "| Step | Result | Elapsed (s) | Details |",
        "|---|---|---|---|",
    ]

    for step in report["steps"]:
        marker = "PASS" if step["passed"] else "FAIL"
        lines.append(f"| {step['name']} | {marker} | {step['elapsed_seconds']} | {step['details']} |")

    lines.extend(
        [
            "",
            "## Transition Integrity",
            "",
            f"- Backend after rollback: {transition['backend_after_rollback']}",
            f"- Transition key first seen after rollback: {transition['post_transition_first_seen']}",
            f"- Memory probe first call result: {transition['memory_probe_first']}",
            f"- Memory probe second call result: {transition['memory_probe_second']}",
            "",
            "## Timing Acceptance",
            "",
            f"- Steps passed: {'yes' if acceptance['steps_passed'] else 'no'}",
            f"- Completed within 15 minutes: {'yes' if acceptance['within_15_minutes'] else 'no'}",
            "",
            "## Final Determination",
            "",
            f"**{'PASS' if report.get('passed') else 'FAIL'}**",
            "",
            "## Sign-off",
            "",
            "- Operator: ____________________",
            "- Date: ____________________",
            "- Notes: ____________________",
        ]
    )

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run SQLite rollback drill and emit acceptance artifact")
    parser.add_argument("--window-seconds", type=int, default=300)
    parser.add_argument(
        "--sqlite-path",
        default=os.getenv("STATE_STORE_SQLITE_PATH", str(ROOT / "data" / "runtime_state.db")),
    )
    parser.add_argument("--target-os", default=os.getenv("ROLLBACK_DRILL_TARGET_OS", "linux"))
    parser.add_argument("--simulate-restart", action="store_true")
    parser.add_argument(
        "--duration-limit-seconds",
        type=int,
        default=DRILL_DURATION_LIMIT_SECONDS,
    )
    parser.add_argument(
        "--json-output",
        default=str(ARTIFACT_DIR / "sqlite-rollback-drill-report.json"),
    )

    args = parser.parse_args(argv)

    report = run_rollback_drill(
        window_seconds=args.window_seconds,
        sqlite_path=args.sqlite_path,
        target_os=args.target_os,
        simulate_restart=args.simulate_restart,
        duration_limit_seconds=args.duration_limit_seconds,
    )

    json_path = Path(args.json_output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    evidence_markdown = _render_markdown(report)
    evidence_path = _evidence_path()
    evidence_path.write_text(evidence_markdown, encoding="utf-8")
    _latest_evidence_path().write_text(evidence_markdown, encoding="utf-8")

    print("=" * 64)
    print("SQLITE ROLLBACK DRILL")
    print("=" * 64)
    print(f"report_json={json_path}")
    print(f"evidence_md={evidence_path}")
    print(f"passed={'yes' if report.get('passed') else 'no'}")
    print(f"elapsed_seconds={report['elapsed_seconds']}")
    print("=" * 64)

    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())