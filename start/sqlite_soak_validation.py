"""SQLite soak validation harness for Story 11.1.

Runs a configurable soak against SQLiteExpiringKeyStore and generates
an evidence artifact at _bmad-output/test-artifacts/sqlite-soak-evidence-<date>.md.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import tracemalloc
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask

from app.services.expiring_store import ExpiringKeyStore, SQLiteExpiringKeyStore, create_expiring_store


ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_DIR = ROOT / "_bmad-output" / "test-artifacts"


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = lower if lower >= len(ordered) - 1 else lower + 1
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * weight)


@dataclass
class SetupCheckResult:
    name: str
    passed: bool
    details: str


def run_enablement_check(db_path: str, window_seconds: int) -> SetupCheckResult:
    try:
        store = SQLiteExpiringKeyStore(
            db_path=db_path,
            namespace="soak_enablement",
            window_seconds=window_seconds,
        )
        first = store.seen_recently("enablement-key")
        second = store.seen_recently("enablement-key")
        store.close()
        passed = (first is False) and (second is True)
        if passed:
            return SetupCheckResult("sqlite_enablement", True, "SQLite store accepted writes and duplicate detection")
        return SetupCheckResult("sqlite_enablement", False, "Unexpected seen_recently behavior during setup")
    except Exception as exc:  # pragma: no cover - defensive
        return SetupCheckResult("sqlite_enablement", False, f"SQLite setup failed: {exc}")


def run_failover_check(window_seconds: int) -> SetupCheckResult:
    app = Flask(__name__)
    app.config["STATE_STORE_BACKEND"] = "sqlite"
    app.config["STATE_STORE_SQLITE_PATH"] = "?:/invalid/runtime_state.db"
    app.config["STATE_STORE_FALLBACK_TO_MEMORY"] = True

    try:
        store = create_expiring_store(
            app=app,
            extension_key="sqlite_soak_failover_store",
            namespace="sqlite_soak_failover",
            window_seconds=window_seconds,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return SetupCheckResult("sqlite_failover_to_memory", False, f"Failover check raised: {exc}")

    passed = isinstance(store, ExpiringKeyStore) and not isinstance(store, SQLiteExpiringKeyStore)
    if passed:
        return SetupCheckResult(
            "sqlite_failover_to_memory",
            True,
            "SQLite init failure degraded to memory store as configured",
        )
    return SetupCheckResult(
        "sqlite_failover_to_memory",
        False,
        "Expected memory fallback store was not returned",
    )


def _evidence_path(now: datetime | None = None) -> Path:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d")
    return ARTIFACT_DIR / f"sqlite-soak-evidence-{stamp}.md"


def _latest_evidence_path() -> Path:
    return ARTIFACT_DIR / "sqlite-soak-evidence-latest.md"


def run_soak(
    *,
    duration_seconds: int,
    operations_per_second: int,
    restart_at_seconds: int,
    window_seconds: int,
    sqlite_path: str,
    target_os: str,
) -> dict[str, Any]:
    duration_seconds = max(1, int(duration_seconds))
    operations_per_second = max(1, int(operations_per_second))
    restart_at_seconds = max(0, min(int(restart_at_seconds), max(0, duration_seconds - 1)))

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)

    setup_checks = [
        run_enablement_check(sqlite_path, window_seconds),
        run_failover_check(window_seconds),
    ]

    store = SQLiteExpiringKeyStore(
        db_path=sqlite_path,
        namespace="sqlite_soak",
        window_seconds=window_seconds,
    )

    tracemalloc.start()
    started = time.monotonic()
    next_tick = started
    restarted = False
    continuity_probe_key = "continuity-probe-key"
    continuity_pre_restart_seen = False
    continuity_post_restart_seen = False

    total_ops = 0
    successful_ops = 0
    failed_ops = 0
    duplicate_hits = 0
    latencies_ms: list[float] = []
    exceptions: list[str] = []
    memory_samples: list[dict[str, float]] = []

    while True:
        now = time.monotonic()
        elapsed = now - started
        if elapsed >= duration_seconds:
            break

        if not restarted and elapsed >= restart_at_seconds:
            continuity_pre_restart_seen = store.seen_recently(continuity_probe_key)
            if not continuity_pre_restart_seen:
                store.seen_recently(continuity_probe_key)
            store.close()
            store = SQLiteExpiringKeyStore(
                db_path=sqlite_path,
                namespace="sqlite_soak",
                window_seconds=window_seconds,
            )
            continuity_post_restart_seen = store.seen_recently(continuity_probe_key)
            restarted = True

        for step in range(operations_per_second):
            key = f"k-{int(elapsed)}-{step % max(1, operations_per_second // 5)}"
            op_start = time.perf_counter()
            try:
                seen = store.seen_recently(key)
                successful_ops += 1
                if seen:
                    duplicate_hits += 1
            except Exception as exc:  # pragma: no cover - defensive
                failed_ops += 1
                exceptions.append(str(exc))
            finally:
                total_ops += 1
                latencies_ms.append((time.perf_counter() - op_start) * 1000.0)

        current_mem, peak_mem = tracemalloc.get_traced_memory()
        memory_samples.append(
            {
                "elapsed_seconds": round(elapsed, 2),
                "current_mb": round(current_mem / (1024 * 1024), 4),
                "peak_mb": round(peak_mem / (1024 * 1024), 4),
            }
        )

        next_tick += 1.0
        sleep_for = next_tick - time.monotonic()
        if sleep_for > 0:
            time.sleep(min(sleep_for, 1.0))

    store.close()
    tracemalloc.stop()

    error_rate_pct = (failed_ops / total_ops * 100.0) if total_ops else 0.0
    sev_incidents: list[str] = []
    if exceptions:
        sev_incidents.append("sqlite_runtime_exception")
    if not restarted:
        sev_incidents.append("restart_continuity_not_executed")
    elif not continuity_post_restart_seen:
        sev_incidents.append("restart_continuity_failure")
    for check in setup_checks:
        if not check.passed:
            sev_incidents.append(f"setup_check_failed:{check.name}")

    report = {
        "story": "11.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_os": target_os,
        "duration_seconds": duration_seconds,
        "operations_per_second": operations_per_second,
        "restart_at_seconds": restart_at_seconds,
        "sqlite_path": sqlite_path,
        "setup_checks": [check.__dict__ for check in setup_checks],
        "results": {
            "total_operations": total_ops,
            "successful_operations": successful_ops,
            "failed_operations": failed_ops,
            "duplicate_hits": duplicate_hits,
            "error_rate_pct": round(error_rate_pct, 4),
            "latency_p50_ms": round(_percentile(latencies_ms, 0.50), 4),
            "latency_p95_ms": round(_percentile(latencies_ms, 0.95), 4),
            "latency_p99_ms": round(_percentile(latencies_ms, 0.99), 4),
            "latency_mean_ms": round(sum(latencies_ms) / len(latencies_ms), 4) if latencies_ms else 0.0,
        },
        "memory_trend": memory_samples,
        "crash_or_exception_events": exceptions,
        "restart_continuity": {
            "restart_performed": restarted,
            "key_seen_after_restart": continuity_post_restart_seen,
        },
        "pass_criteria": {
            "zero_sev1_sev2_incidents": len(sev_incidents) == 0,
            "sev_incidents": sev_incidents,
        },
    }
    report["passed"] = report["pass_criteria"]["zero_sev1_sev2_incidents"]
    return report


def _render_markdown(report: dict[str, Any]) -> str:
    results = report["results"]
    setup_checks = report["setup_checks"]
    restart = report["restart_continuity"]
    criterion = report["pass_criteria"]
    memory_samples = report.get("memory_trend") or []
    first_mem = memory_samples[0] if memory_samples else {"current_mb": 0.0, "peak_mb": 0.0}
    last_mem = memory_samples[-1] if memory_samples else {"current_mb": 0.0, "peak_mb": 0.0}

    lines = [
        "# SQLite Soak Evidence",
        "",
        f"Generated: {report['generated_at']}",
        f"Story: {report['story']}",
        f"Target OS: {report['target_os']}",
        f"Soak Duration: {report['duration_seconds']} seconds",
        f"SQLite Path: {report['sqlite_path']}",
        "",
        "## Setup Checks",
        "",
        "| Check | Result | Details |",
        "|---|---|---|",
    ]

    for check in setup_checks:
        marker = "PASS" if check["passed"] else "FAIL"
        lines.append(f"| {check['name']} | {marker} | {check['details']} |")

    lines.extend(
        [
            "",
            "## Soak Metrics",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| Total operations | {results['total_operations']} |",
            f"| Successful operations | {results['successful_operations']} |",
            f"| Failed operations | {results['failed_operations']} |",
            f"| Error rate | {results['error_rate_pct']}% |",
            f"| Latency p50 | {results['latency_p50_ms']} ms |",
            f"| Latency p95 | {results['latency_p95_ms']} ms |",
            f"| Latency p99 | {results['latency_p99_ms']} ms |",
            f"| Latency mean | {results['latency_mean_ms']} ms |",
            "",
            "## Memory Trend",
            "",
            "| Snapshot | Current MB | Peak MB |",
            "|---|---|---|",
            f"| Start | {first_mem['current_mb']} | {first_mem['peak_mb']} |",
            f"| End | {last_mem['current_mb']} | {last_mem['peak_mb']} |",
            "",
            "## Restart Continuity",
            "",
            f"- Restart performed: {'yes' if restart['restart_performed'] else 'no'}",
            f"- Continuity assertion (key survives restart): {'pass' if restart['key_seen_after_restart'] else 'fail'}",
            "",
            "## Sev-1/Sev-2 Incident Gate",
            "",
            f"- Zero incidents required: {'pass' if criterion['zero_sev1_sev2_incidents'] else 'fail'}",
        ]
    )

    sev_incidents = criterion.get("sev_incidents") or []
    if sev_incidents:
        lines.append(f"- Incident list: {', '.join(sev_incidents)}")
    else:
        lines.append("- Incident list: none")

    lines.extend(
        [
            "",
            "## Final Determination",
            "",
            f"**{'PASS' if report.get('passed') else 'FAIL'}**",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run SQLite soak automation and emit evidence artifact")
    parser.add_argument("--duration-seconds", type=int, default=86400)
    parser.add_argument("--operations-per-second", type=int, default=20)
    parser.add_argument("--restart-at-seconds", type=int, default=43200)
    parser.add_argument("--window-seconds", type=int, default=300)
    parser.add_argument(
        "--sqlite-path",
        default=os.getenv("STATE_STORE_SQLITE_PATH", str(ROOT / "data" / "runtime_state.db")),
    )
    parser.add_argument("--target-os", default=os.getenv("SOAK_TARGET_OS", "linux"))
    parser.add_argument("--json-output", default=str(ARTIFACT_DIR / "sqlite-soak-report.json"))
    args = parser.parse_args(argv)

    report = run_soak(
        duration_seconds=args.duration_seconds,
        operations_per_second=args.operations_per_second,
        restart_at_seconds=args.restart_at_seconds,
        window_seconds=args.window_seconds,
        sqlite_path=args.sqlite_path,
        target_os=args.target_os,
    )

    json_path = Path(args.json_output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    evidence_markdown = _render_markdown(report)
    evidence_path = _evidence_path()
    evidence_path.write_text(evidence_markdown, encoding="utf-8")
    _latest_evidence_path().write_text(evidence_markdown, encoding="utf-8")

    print("=" * 64)
    print("SQLITE SOAK VALIDATION")
    print("=" * 64)
    print(f"report_json={json_path}")
    print(f"evidence_md={evidence_path}")
    print(f"passed={'yes' if report.get('passed') else 'no'}")
    print(f"total_operations={report['results']['total_operations']}")
    print(f"error_rate_pct={report['results']['error_rate_pct']}")
    print("=" * 64)

    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
