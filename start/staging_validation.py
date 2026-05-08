"""
start/staging_validation.py

Runs a controlled batch of message-flow checks against the running Flask app,
collects latency, success rate, throughput, and fallback timing evidence,
and writes gate-ready JSON and human-readable Markdown reports.

Usage (app must already be running locally or pointed via --base-url):
    python start/staging_validation.py
    python start/staging_validation.py --base-url https://staging.example.com --count 1000

The script uses only the /webhook, /health, and /api/metrics endpoints,
sending properly signed payloads so the existing security middleware is exercised.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional in constrained environments
    load_dotenv = None

try:
    import requests
except ImportError:
    print("ERROR: requests required.  pip install requests", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
REPORT_JSON = ROOT / "_bmad-output" / "test-artifacts" / "staging-validation-report.json"
REPORT_MD = ROOT / "_bmad-output" / "test-artifacts" / "staging-validation-summary.md"

if load_dotenv is not None:
    load_dotenv(ROOT / ".env")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# PRD gate thresholds
# ---------------------------------------------------------------------------
LATENCY_P50_THRESHOLD_S = 4.0
LATENCY_P95_THRESHOLD_S = 8.0
SUCCESS_RATE_THRESHOLD_PCT = 99.0
THROUGHPUT_THRESHOLD_MSG_S = 10.0
FALLBACK_TIMING_THRESHOLD_S = 10.0
MIN_STAGING_SAMPLE_COUNT = 1000

# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------

def _sign_payload(body: str, app_secret: str) -> str:
    digest = hmac.new(
        app_secret.encode("latin-1"),
        msg=body.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def _build_message_payload(wa_id: str, message_id: str, text: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"wa_id": wa_id, "profile": {"name": "StagingUser"}}],
                            "messages": [{"id": message_id, "text": {"body": text}}],
                        }
                    }
                ]
            }
        ],
    }


def _build_status_payload() -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [
                                {
                                    "id": f"status-{uuid.uuid4().hex}",
                                    "status": "delivered",
                                }
                            ]
                        }
                    }
                ]
            }
        ],
    }


def _probe_fallback_timing() -> tuple[bool | None, float | None, str]:
    """Run a local deterministic probe of retry+fallback timing."""
    try:
        import requests as requests_lib
        from flask import Flask
        from app.utils.whatsapp_utils import get_text_message_input, send_message

        app = Flask(__name__)
        app.config.update(
            {
                "ACCESS_TOKEN": "probe-token",
                "VERSION": "v18.0",
                "PHONE_NUMBER_ID": "1234567890",
                "RECIPIENT_WAID": "15551234567",
            }
        )

        payload = get_text_message_input("15551234567", "fallback timing probe")

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.headers = {"content-type": "application/json"}
        success_response.text = "{\"messages\":[{\"id\":\"probe\"}]}"
        success_response.raise_for_status.return_value = None

        # Four failed attempts (initial + 3 retries), then fallback send succeeds.
        side_effects = [
            requests_lib.Timeout(),
            requests_lib.Timeout(),
            requests_lib.Timeout(),
            requests_lib.Timeout(),
            success_response,
        ]

        start = time.monotonic()
        with app.app_context():
            with patch("app.utils.whatsapp_utils.requests.post", side_effect=side_effects):
                result = send_message(payload, request_id="staging-fallback-probe")
        elapsed = time.monotonic() - start

        if not result.get("fallback_sent"):
            return False, round(elapsed, 4), "Fallback probe did not send fallback message"

        if elapsed <= FALLBACK_TIMING_THRESHOLD_S:
            return True, round(elapsed, 4), "Fallback probe passed"

        return (
            False,
            round(elapsed, 4),
            f"Fallback probe exceeded threshold ({elapsed:.3f}s > {FALLBACK_TIMING_THRESHOLD_S:.1f}s)",
        )
    except Exception as exc:
        return None, None, f"Fallback probe error: {exc}"


# ---------------------------------------------------------------------------
# Main validation
# ---------------------------------------------------------------------------

def run_validation(
    base_url: str,
    app_secret: str,
    count: int,
    concurrency: int,
    payload_kind: str,
) -> dict:
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})

    webhook_url = f"{base_url.rstrip('/')}/webhook"
    health_url = f"{base_url.rstrip('/')}/health"
    metrics_url = f"{base_url.rstrip('/')}/api/metrics"

    # --- Health pre-check ---
    try:
        h = session.get(health_url, timeout=5)
        health_ok = h.status_code == 200
        health_status = h.json().get("status", "unknown") if health_ok else "unreachable"
    except Exception as exc:
        print(f"WARN: Health check failed: {exc}", file=sys.stderr)
        health_ok = False
        health_status = "unreachable"

    if not health_ok:
        print("ERROR: App is not healthy. Aborting staging run.", file=sys.stderr)
        sys.exit(1)

    print(f"[staging] Health check: {health_status}")
    print(f"[staging] Sending {count} {payload_kind} events to {webhook_url} ...")

    latencies: list[float] = []
    successes = 0
    failures = 0
    duplicates_sent = 0

    # Capture metrics snapshot before run
    try:
        pre_metrics = session.get(metrics_url, timeout=5).json()
    except Exception:
        pre_metrics = {}

    run_start = time.monotonic()

    for i in range(count):
        wa_id = f"1555{i:07d}"
        message_id = f"staging-wamid-{uuid.uuid4().hex}"
        text = f"staging test message {i}"
        if payload_kind == "status":
            payload_dict = _build_status_payload()
        else:
            payload_dict = _build_message_payload(wa_id, message_id, text)
        body = json.dumps(payload_dict)
        ts = str(int(time.time()))
        sig = _sign_payload(body, app_secret)
        request_id = f"staging-{i:06d}"

        t0 = time.monotonic()
        try:
            resp = session.post(
                webhook_url,
                data=body,
                headers={
                    "X-Hub-Signature-256": sig,
                    "X-Hub-Signature-Timestamp": ts,
                    "X-Request-ID": request_id,
                },
                timeout=LATENCY_P95_THRESHOLD_S + 2,
            )
            elapsed = time.monotonic() - t0
            latencies.append(elapsed)

            if resp.status_code == 200:
                successes += 1
            else:
                failures += 1
        except requests.Timeout:
            latencies.append(LATENCY_P95_THRESHOLD_S + 5)  # record as outlier
            failures += 1
        except Exception as exc:
            latencies.append(LATENCY_P95_THRESHOLD_S + 5)
            failures += 1
            print(f"WARN: Request {i} failed: {exc}", file=sys.stderr)

        if (i + 1) % max(1, count // 10) == 0:
            print(f"  [{i+1}/{count}] successes={successes} failures={failures}")

    run_duration = time.monotonic() - run_start
    throughput = count / run_duration if run_duration > 0 else 0.0

    # Capture metrics snapshot after run
    try:
        post_metrics = session.get(metrics_url, timeout=5).json()
    except Exception:
        post_metrics = {}

    # --- Latency stats ---
    sorted_lat = sorted(latencies)
    n = len(sorted_lat)
    p50 = statistics.median(sorted_lat) if sorted_lat else 0.0
    p95_idx = max(0, int(0.95 * n) - 1)
    p95 = sorted_lat[p95_idx] if sorted_lat else 0.0

    # --- Fallback timing probe ---
    fallback_timing_ok, fallback_timing_seconds, fallback_note = _probe_fallback_timing()

    # --- Gate evaluations ---
    success_rate = (successes / count * 100) if count > 0 else 0.0
    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "payload_kind": payload_kind,
        "sample_count": count,
        "sample_count_ok": count >= MIN_STAGING_SAMPLE_COUNT,
        "run_duration_seconds": round(run_duration, 3),
        "successes": successes,
        "failures": failures,
        "success_rate_pct": round(success_rate, 3),
        "latency_p50_seconds": round(p50, 4),
        "latency_p95_seconds": round(p95, 4),
        "throughput_msg_per_sec": round(throughput, 3),
        # Gate boolean keys (consumed by evaluate_launch_gates.py)
        "latency_p50_ok": p50 <= LATENCY_P50_THRESHOLD_S,
        "latency_p95_ok": p95 <= LATENCY_P95_THRESHOLD_S,
        "success_rate_ok": success_rate >= SUCCESS_RATE_THRESHOLD_PCT,
        "throughput_ok": throughput >= THROUGHPUT_THRESHOLD_MSG_S,
        "fallback_timing_ok": fallback_timing_ok,
        "fallback_timing_seconds": fallback_timing_seconds,
        "fallback_timing_note": fallback_note,
        "health_pre_check": health_status,
        "pre_run_metrics": pre_metrics,
        "post_run_metrics": post_metrics,
    }
    return report


def _render_markdown(report: dict) -> str:
    now = report["generated"]
    lines = [
        "# Staging Validation Summary",
        f"",
        f"Generated: {now}",
        f"Base URL: {report['base_url']}",
        f"Payload kind: {report['payload_kind']}",
        f"Sample count: {report['sample_count']}",
        f"",
        "## Results",
        "",
        f"| Metric | Value | Gate Threshold | Pass? |",
        f"|--------|-------|----------------|-------|",
        (
            f"| P50 Latency | {report['latency_p50_seconds']:.3f}s "
            f"| <= {LATENCY_P50_THRESHOLD_S}s "
            f"| {'✅' if report['latency_p50_ok'] else '❌'} |"
        ),
        (
            f"| P95 Latency | {report['latency_p95_seconds']:.3f}s "
            f"| <= {LATENCY_P95_THRESHOLD_S}s "
            f"| {'✅' if report['latency_p95_ok'] else '❌'} |"
        ),
        (
            f"| Success Rate | {report['success_rate_pct']:.2f}% "
            f"| >= {SUCCESS_RATE_THRESHOLD_PCT}% "
            f"| {'✅' if report['success_rate_ok'] else '❌'} |"
        ),
        (
            f"| Throughput | {report['throughput_msg_per_sec']:.2f} msg/s "
            f"| >= {THROUGHPUT_THRESHOLD_MSG_S} msg/s "
            f"| {'✅' if report['throughput_ok'] else '❌'} |"
        ),
        (
            f"| Fallback Timing | {report['fallback_timing_seconds'] if report.get('fallback_timing_seconds') is not None else 'n/a'}s "
            f"| <= {FALLBACK_TIMING_THRESHOLD_S}s "
            f"| {'✅' if report.get('fallback_timing_ok') is True else ('❌' if report.get('fallback_timing_ok') is False else '⚠️ unknown')} |"
        ),
        (
            f"| Sample Count | {report['sample_count']} "
            f"| >= {MIN_STAGING_SAMPLE_COUNT} "
            f"| {'✅' if report['sample_count_ok'] else '❌'} |"
        ),
        "",
        "## Notes",
        "",
        f"- {report['fallback_timing_note']}",
        f"- Run duration: {report['run_duration_seconds']}s",
        f"- Health pre-check: {report['health_pre_check']}",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run staging validation for launch gates")
    parser.add_argument(
        "--base-url",
        default=os.getenv("STAGING_BASE_URL", "http://127.0.0.1:8000"),
        help="Base URL of the running Flask app",
    )
    parser.add_argument(
        "--app-secret",
        nargs="?",
        default=os.getenv("APP_SECRET", ""),
        const=os.getenv("APP_SECRET", ""),
        help=(
            "APP_SECRET for HMAC signing; if omitted (or passed without value), "
            "falls back to APP_SECRET from environment/.env"
        ),
    )
    parser.add_argument(
        "--count",
        type=int,
        default=100,
        help="Number of synthetic messages to send (1000 for full staging gate)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Reserved for future parallel mode (currently sequential)",
    )
    parser.add_argument(
        "--payload-kind",
        choices=("message", "status"),
        default="status",
        help=(
            "Webhook payload type: 'status' runs deterministic synthetic checks without "
            "external outbound dependencies; 'message' exercises full inbound-to-outbound path"
        ),
    )
    args = parser.parse_args(argv)

    if not args.app_secret:
        print(
            "ERROR: APP_SECRET is required. Set --app-secret or APP_SECRET env var.",
            file=sys.stderr,
        )
        return 1

    report = run_validation(
        base_url=args.base_url,
        app_secret=args.app_secret,
        count=args.count,
        concurrency=args.concurrency,
        payload_kind=args.payload_kind,
    )

    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    REPORT_MD.write_text(_render_markdown(report), encoding="utf-8")

    print(f"\n{'='*55}")
    print(f"  STAGING VALIDATION COMPLETE")
    print(f"{'='*55}")
    print(f"  Success rate : {report['success_rate_pct']:.2f}% "
          f"({'PASS' if report['success_rate_ok'] else 'FAIL'})")
    print(f"  P50 latency  : {report['latency_p50_seconds']:.3f}s "
          f"({'PASS' if report['latency_p50_ok'] else 'FAIL'})")
    print(f"  P95 latency  : {report['latency_p95_seconds']:.3f}s "
          f"({'PASS' if report['latency_p95_ok'] else 'FAIL'})")
    print(f"  Throughput   : {report['throughput_msg_per_sec']:.2f} msg/s "
          f"({'PASS' if report['throughput_ok'] else 'FAIL'})")
    fallback_state = report.get("fallback_timing_ok")
    if fallback_state is True:
        fallback_label = "PASS"
    elif fallback_state is False:
        fallback_label = "FAIL"
    else:
        fallback_label = "UNKNOWN"
    print(
        f"  Fallback timing: {report['fallback_timing_seconds'] if report.get('fallback_timing_seconds') is not None else 'n/a'}s "
        f"({fallback_label})"
    )
    print(f"\n  Reports written to _bmad-output/test-artifacts/")
    print(f"{'='*55}\n")

    all_auto_pass = all([
        report["latency_p50_ok"],
        report["latency_p95_ok"],
        report["success_rate_ok"],
        report["throughput_ok"],
        report.get("fallback_timing_ok") is True,
    ])
    return 0 if all_auto_pass else 1


if __name__ == "__main__":
    sys.exit(main())
