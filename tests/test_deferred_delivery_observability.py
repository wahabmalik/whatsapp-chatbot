"""Reliability stress tests for deferred delivery completion logging and
operator artifact queueing (Epic 5 Retro Action Item 4).

Verifies:
- BackgroundDeliveryService submits work and wait_for_idle() signals completion
- _complete_deferred_delivery() adds a log entry to the message log buffer
- _complete_deferred_delivery() queues an operator artifact when delivery fails
- No artifact is queued on a successful delivery
- Concurrent submissions all complete and all produce log entries
- wait_for_idle() respects its timeout and returns False when work is still pending
- Escalation queue file receives well-formed JSONL on artifact append
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import Future
from unittest.mock import Mock, patch

import requests

DELIVERY_ENV = {
    "WHATSAPP_PROVIDER": "meta",
    "ACCESS_TOKEN": "test-token",
    "APP_SECRET": "test-secret",
    "VERSION": "v18.0",
    "PHONE_NUMBER_ID": "1234567890",
    "VERIFY_TOKEN": "verify-token",
    "OPENAI_API_KEY": "sk-test",
    "RECIPIENT_WAID": "15551234567",
    "YOUR_PHONE_NUMBER": "15551234567",
    "APP_ID": "123456789",
}


def _make_app(extra_config: dict | None = None):
    with patch.dict(os.environ, DELIVERY_ENV, clear=False):
        from app import create_app
        app = create_app()
    if extra_config:
        app.config.update(extra_config)
    return app


def _ok_response() -> Mock:
    resp = Mock()
    resp.status_code = 200
    resp.headers = {"content-type": "application/json"}
    resp.text = '{"messages": [{"id": "wamid-test"}]}'
    resp.raise_for_status = Mock()
    return resp


# ---------------------------------------------------------------------------
# BackgroundDeliveryService unit tests
# ---------------------------------------------------------------------------

class BackgroundDeliveryServiceTests(unittest.TestCase):
    """BackgroundDeliveryService correctly tracks and drains submitted work."""

    def test_wait_for_idle_returns_true_after_completion(self):
        """Submitted work completes; wait_for_idle() returns True."""
        from app.services.outbound_delivery import BackgroundDeliveryService

        svc = BackgroundDeliveryService(max_workers=2)
        results = []
        svc.submit(results.append, "done")
        idle = svc.wait_for_idle(timeout=5.0)
        svc.shutdown(wait=True)
        self.assertTrue(idle)
        self.assertEqual(results, ["done"])

    def test_wait_for_idle_times_out_when_work_is_slow(self):
        """wait_for_idle() returns False when work cannot finish within the timeout."""
        from app.services.outbound_delivery import BackgroundDeliveryService

        svc = BackgroundDeliveryService(max_workers=1)
        barrier = threading.Event()

        def _slow():
            barrier.wait(timeout=10)

        svc.submit(_slow)
        idle = svc.wait_for_idle(timeout=0.05)
        barrier.set()
        svc.shutdown(wait=True)
        self.assertFalse(idle)

    def test_multiple_concurrent_submissions_all_complete(self):
        """Several submissions all run and are tracked until idle."""
        from app.services.outbound_delivery import BackgroundDeliveryService

        svc = BackgroundDeliveryService(max_workers=4)
        counter = [0]
        lock = threading.Lock()

        def _increment():
            with lock:
                counter[0] += 1

        for _ in range(10):
            svc.submit(_increment)

        idle = svc.wait_for_idle(timeout=5.0)
        svc.shutdown(wait=True)
        self.assertTrue(idle)
        self.assertEqual(counter[0], 10)

    def test_idle_immediately_when_no_work_submitted(self):
        """Service with no submissions is immediately idle."""
        from app.services.outbound_delivery import BackgroundDeliveryService

        svc = BackgroundDeliveryService(max_workers=1)
        idle = svc.wait_for_idle(timeout=0.1)
        svc.shutdown(wait=True)
        self.assertTrue(idle)

    def test_future_exception_does_not_block_idle(self):
        """A submission that raises an exception still completes; idle is reached."""
        from app.services.outbound_delivery import BackgroundDeliveryService

        svc = BackgroundDeliveryService(max_workers=1)

        def _raise():
            raise RuntimeError("task error")

        svc.submit(_raise)
        idle = svc.wait_for_idle(timeout=5.0)
        svc.shutdown(wait=True)
        self.assertTrue(idle)

    def test_get_background_delivery_service_returns_singleton_per_app(self):
        """get_background_delivery_service() returns the same object for the same app."""
        app = _make_app()
        with app.app_context():
            from app.services.outbound_delivery import get_background_delivery_service
            svc1 = get_background_delivery_service(app)
            svc2 = get_background_delivery_service(app)
        self.assertIs(svc1, svc2)


# ---------------------------------------------------------------------------
# _complete_deferred_delivery log entry tests
# ---------------------------------------------------------------------------

class DeferredDeliveryLogEntryTests(unittest.TestCase):
    """_complete_deferred_delivery adds a log entry for every outcome."""

    def setUp(self):
        self._env = patch.dict(os.environ, DELIVERY_ENV, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def _run_deferred(self, send_side_effect, delivery_context: dict | None = None,
                      extra_config: dict | None = None) -> tuple:
        """Run _complete_deferred_delivery and return (result, log_entries)."""
        app = _make_app(extra_config)
        delivery_context = delivery_context or {
            "wa_id": "15551234567",
            "message_id": "wamid-def-001",
            "to_num": "15551234567",
            "agent": "TestAgent",
            "input_text": "hello",
            "reply_text": "reply",
        }
        with patch("app.utils.whatsapp_utils._send_request",
                   side_effect=send_side_effect), \
             patch("app.utils.whatsapp_utils.time.sleep"):
            with app.app_context():
                from app.utils.whatsapp_utils import _complete_deferred_delivery
                from app.services.message_log import get_message_log_buffer
                result = _complete_deferred_delivery(
                    app, '{"to":"15551234567","text":"hi"}',
                    "req-deferred-001",
                    delivery_context=delivery_context,
                )
                log_entries = get_message_log_buffer(app).get_all()
        return result, log_entries

    def test_successful_delivery_adds_log_entry_with_sent_status(self):
        """Successful deferred send → log entry with status='sent'."""
        _, logs = self._run_deferred(send_side_effect=_ok_response())
        self.assertGreater(len(logs), 0)
        statuses = [e.get("status") for e in logs]
        self.assertIn("sent", statuses)

    def test_failed_delivery_adds_log_entry_with_error_or_fallback_status(self):
        """All retries fail → log entry with status in ('error', 'fallback_sent')."""
        _, logs = self._run_deferred(
            send_side_effect=requests.Timeout("always fail"),
        )
        self.assertGreater(len(logs), 0)
        statuses = [e.get("status") for e in logs]
        self.assertTrue(
            any(s in ("error", "fallback_sent") for s in statuses),
            f"Expected error/fallback_sent status, got: {statuses}",
        )

    def test_log_entry_includes_correlation_fields(self):
        """Log entry contains from, message_id, agent, and status fields."""
        _, logs = self._run_deferred(send_side_effect=_ok_response())
        entry = logs[0]
        for field in ("from", "message_id", "agent", "status"):
            self.assertIn(field, entry, f"Log entry missing field '{field}'")

    def test_log_entry_from_matches_wa_id(self):
        """Log entry 'from' field matches the wa_id in delivery_context."""
        _, logs = self._run_deferred(send_side_effect=_ok_response())
        self.assertEqual(logs[0].get("from"), "15551234567")

    def test_log_entry_operator_review_flagged_on_failure(self):
        """When delivery fails, log entry has operator_review_flagged=True."""
        _, logs = self._run_deferred(
            send_side_effect=requests.Timeout("always fail"),
        )
        self.assertTrue(logs[0].get("operator_review_flagged"))

    def test_terminal_success_log_contains_stable_outcome_fields(self):
        """Successful background completion emits a terminal record with stable fields."""
        result, logs = self._run_deferred(send_side_effect=_ok_response())

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "sent")
        self.assertEqual(len(logs), 1)

        entry = logs[0]
        self.assertEqual(entry.get("correlation_id"), "req-deferred-001")
        self.assertEqual(entry.get("message_id"), "wamid-def-001")
        self.assertEqual(entry.get("status"), "sent")
        self.assertFalse(entry.get("operator_review_flagged"))
        self.assertFalse(entry.get("review_artifact_queued"))
        self.assertIsNone(entry.get("review_artifact_error"))


# ---------------------------------------------------------------------------
# Operator artifact queueing tests
# ---------------------------------------------------------------------------

class OperatorArtifactQueueingTests(unittest.TestCase):
    """_complete_deferred_delivery writes JSONL artifact on fallback failure."""

    def setUp(self):
        self._env = patch.dict(os.environ, DELIVERY_ENV, clear=False)
        self._env.start()
        self._tmpdir = tempfile.TemporaryDirectory()
        self._queue_path = os.path.join(self._tmpdir.name, "operator_review_queue.jsonl")

    def tearDown(self):
        self._env.stop()
        self._tmpdir.cleanup()

    def _run_deferred(self, send_side_effect, delivery_context: dict | None = None):
        app = _make_app({"ESCALATION_QUEUE_PATH": self._queue_path})
        delivery_context = delivery_context or {
            "wa_id": "15551234567",
            "message_id": "wamid-artifact-001",
            "to_num": "15551234567",
            "agent": "TestAgent",
            "input_text": "test",
            "reply_text": "reply",
        }
        with patch("app.utils.whatsapp_utils._send_request",
                   side_effect=send_side_effect), \
             patch("app.utils.whatsapp_utils.time.sleep"):
            with app.app_context():
                from app.utils.whatsapp_utils import _complete_deferred_delivery
                return _complete_deferred_delivery(
                    app,
                    '{"to":"15551234567","text":"hi"}',
                    "req-artifact-001",
                    delivery_context=delivery_context,
                )

    def test_artifact_written_on_fallback_failure(self):
        """All retries fail → operator review artifact written to queue file."""
        self._run_deferred(send_side_effect=requests.Timeout("always fail"))
        self.assertTrue(os.path.exists(self._queue_path),
                        "Escalation queue file not created")
        with open(self._queue_path, encoding="utf-8") as fh:
            lines = [l.strip() for l in fh if l.strip()]
        self.assertGreater(len(lines), 0, "Queue file is empty")

    def test_artifact_is_valid_jsonl(self):
        """Each line in the queue file is parseable JSON."""
        self._run_deferred(send_side_effect=requests.Timeout("always fail"))
        with open(self._queue_path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    record = json.loads(line)
                    self.assertIsInstance(record, dict)

    def test_artifact_contains_required_fields(self):
        """Artifact record contains timestamp, correlation_id, reason, and masked_user_handle."""
        self._run_deferred(send_side_effect=requests.Timeout("always fail"))
        with open(self._queue_path, encoding="utf-8") as fh:
            record = json.loads(next(l for l in fh if l.strip()))
        for field in ("timestamp", "correlation_id", "reason", "masked_user_handle"):
            self.assertIn(field, record, f"Artifact missing field '{field}'")

    def test_artifact_correlation_id_matches_request_id(self):
        """correlation_id in artifact equals the request_id passed to deferred delivery."""
        self._run_deferred(send_side_effect=requests.Timeout("always fail"))
        with open(self._queue_path, encoding="utf-8") as fh:
            record = json.loads(next(l for l in fh if l.strip()))
        self.assertEqual(record["correlation_id"], "req-artifact-001")

    def test_no_artifact_on_successful_delivery(self):
        """Successful delivery must NOT create an operator review artifact."""
        self._run_deferred(send_side_effect=_ok_response())
        self.assertFalse(
            os.path.exists(self._queue_path),
            "Artifact queue file should not exist after successful delivery",
        )

    def test_artifact_user_handle_is_masked(self):
        """User phone number in artifact is masked, not stored in full."""
        self._run_deferred(send_side_effect=requests.Timeout("always fail"))
        with open(self._queue_path, encoding="utf-8") as fh:
            record = json.loads(next(l for l in fh if l.strip()))
        handle = record.get("masked_user_handle", "")
        # Full number "15551234567" must not appear verbatim
        self.assertNotIn("15551234567", handle)

    def test_multiple_failures_produce_multiple_artifacts(self):
        """Each independent failing delivery appends its own artifact line."""
        app = _make_app({"ESCALATION_QUEUE_PATH": self._queue_path})
        for i in range(3):
            with patch("app.utils.whatsapp_utils._send_request",
                       side_effect=requests.Timeout("fail")), \
                 patch("app.utils.whatsapp_utils.time.sleep"):
                with app.app_context():
                    from app.utils.whatsapp_utils import _complete_deferred_delivery
                    _complete_deferred_delivery(
                        app,
                        '{"to":"15551234567","text":"hi"}',
                        f"req-multi-{i:03d}",
                        delivery_context={
                            "wa_id": "15551234567",
                            "message_id": f"wamid-multi-{i:03d}",
                            "to_num": "15551234567",
                            "agent": "Bot",
                            "input_text": "x",
                            "reply_text": "y",
                        },
                    )
        with open(self._queue_path, encoding="utf-8") as fh:
            lines = [l.strip() for l in fh if l.strip()]
        self.assertEqual(len(lines), 3)

    def test_terminal_fallback_sent_evidence_shares_stable_fields_across_log_and_artifact(self):
        """Fallback delivery still emits a terminal record and operator artifact."""
        app = _make_app({"ESCALATION_QUEUE_PATH": self._queue_path})
        delivery_context = {
            "wa_id": "15551234567",
            "message_id": "wamid-artifact-001",
            "to_num": "15551234567",
            "agent": "TestAgent",
            "input_text": "test",
            "reply_text": "reply",
        }

        with patch(
            "app.utils.whatsapp_utils._send_request",
            side_effect=[
                requests.Timeout("attempt-1"),
                requests.Timeout("attempt-2"),
                requests.Timeout("attempt-3"),
                _ok_response(),
            ],
        ), patch("app.utils.whatsapp_utils.time.sleep"):
            with app.app_context():
                from app.services.message_log import get_message_log_buffer
                from app.utils.whatsapp_utils import _complete_deferred_delivery

                result = _complete_deferred_delivery(
                    app,
                    '{"to":"15551234567","text":"hi"}',
                    "req-artifact-001",
                    delivery_context=delivery_context,
                )
                logs = get_message_log_buffer(app).get_all()

        with open(self._queue_path, encoding="utf-8") as fh:
            artifact = json.loads(next(l for l in fh if l.strip()))

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "fallback_sent")
        self.assertTrue(result["review_artifact_queued"])
        self.assertIsNone(result["review_artifact_error"])
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].get("correlation_id"), artifact.get("correlation_id"))
        self.assertEqual(logs[0].get("message_id"), artifact.get("message_id"))
        self.assertEqual(logs[0].get("status"), result.get("status"))
        self.assertEqual(logs[0].get("operator_review_reason"), artifact.get("reason"))
        self.assertTrue(logs[0].get("operator_review_flagged"))
        self.assertTrue(logs[0].get("review_artifact_queued"))
        self.assertIsNone(logs[0].get("review_artifact_error"))
        self.assertEqual(artifact.get("correlation_id"), "req-artifact-001")

    def test_terminal_failure_evidence_shares_stable_fields_across_log_and_artifact(self):
        """Failure path emits matching terminal evidence for dashboards and operators."""
        app = _make_app({"ESCALATION_QUEUE_PATH": self._queue_path})
        delivery_context = {
            "wa_id": "15551234567",
            "message_id": "wamid-artifact-001",
            "to_num": "15551234567",
            "agent": "TestAgent",
            "input_text": "test",
            "reply_text": "reply",
        }

        with patch("app.utils.whatsapp_utils._send_request",
                   side_effect=requests.Timeout("always fail")), \
             patch("app.utils.whatsapp_utils.time.sleep"):
            with app.app_context():
                from app.services.message_log import get_message_log_buffer
                from app.utils.whatsapp_utils import _complete_deferred_delivery

                result = _complete_deferred_delivery(
                    app,
                    '{"to":"15551234567","text":"hi"}',
                    "req-artifact-001",
                    delivery_context=delivery_context,
                )
                logs = get_message_log_buffer(app).get_all()

        with open(self._queue_path, encoding="utf-8") as fh:
            artifact = json.loads(next(l for l in fh if l.strip()))

        self.assertFalse(result["ok"])
        self.assertTrue(result["review_artifact_queued"])
        self.assertIsNone(result["review_artifact_error"])
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].get("correlation_id"), artifact.get("correlation_id"))
        self.assertEqual(logs[0].get("message_id"), artifact.get("message_id"))
        self.assertEqual(logs[0].get("status"), result.get("status"))
        self.assertEqual(logs[0].get("operator_review_reason"), artifact.get("reason"))
        self.assertTrue(logs[0].get("operator_review_flagged"))
        self.assertTrue(logs[0].get("review_artifact_queued"))
        self.assertIsNone(logs[0].get("review_artifact_error"))
        self.assertEqual(artifact.get("correlation_id"), "req-artifact-001")

    def test_artifact_write_failure_is_visible_in_result_and_log(self):
        """Artifact persistence failures stay observable in the deferred terminal outcome."""
        app = _make_app({"ESCALATION_QUEUE_PATH": self._queue_path})
        delivery_context = {
            "wa_id": "15551234567",
            "message_id": "wamid-artifact-001",
            "to_num": "15551234567",
            "agent": "TestAgent",
            "input_text": "test",
            "reply_text": "reply",
        }

        with patch("app.utils.whatsapp_utils._send_request", side_effect=requests.Timeout("always fail")), \
             patch("app.utils.whatsapp_utils.append_review_artifact", return_value=(False, "disk full")), \
             patch("app.utils.whatsapp_utils.time.sleep"):
            with app.app_context():
                from app.services.message_log import get_message_log_buffer
                from app.utils.whatsapp_utils import _complete_deferred_delivery

                with self.assertLogs("root", level="WARNING") as captured:
                    result = _complete_deferred_delivery(
                        app,
                        '{"to":"15551234567","text":"hi"}',
                        "req-artifact-001",
                        delivery_context=delivery_context,
                    )
                logs = get_message_log_buffer(app).get_all()

        self.assertFalse(result["ok"])
        self.assertFalse(result["review_artifact_queued"])
        self.assertEqual(result["review_artifact_error"], "disk full")
        self.assertEqual(len(logs), 1)
        self.assertFalse(logs[0].get("review_artifact_queued"))
        self.assertEqual(logs[0].get("review_artifact_error"), "disk full")
        self.assertIn("req-artifact-001", "\n".join(captured.output))
        self.assertIn("disk full", "\n".join(captured.output))


# ---------------------------------------------------------------------------
# Concurrent deferred delivery stress test
# ---------------------------------------------------------------------------

class ConcurrentDeferredDeliveryTests(unittest.TestCase):
    """Multiple deferred deliveries complete concurrently with correct logging."""

    def setUp(self):
        self._env = patch.dict(os.environ, DELIVERY_ENV, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_concurrent_successful_deliveries_all_logged(self):
        """N concurrent deferred deliveries all complete and produce N log entries."""
        N = 5
        app = _make_app({"WHATSAPP_DEFER_RETRIES": True})

        results = []
        lock = threading.Lock()

        def _run_one(index: int):
            with app.app_context():
                from app.utils.whatsapp_utils import _complete_deferred_delivery
                result = _complete_deferred_delivery(
                    app,
                    '{"to":"15551234567","text":"hi"}',
                    f"req-concurrent-{index:03d}",
                    delivery_context={
                        "wa_id": "15551234567",
                        "message_id": f"wamid-c-{index:03d}",
                        "to_num": "15551234567",
                        "agent": "Bot",
                        "input_text": "x",
                        "reply_text": "y",
                    },
                )
                with lock:
                    results.append(result)

        # Apply the patch once at test level so all threads share the same mock
        # and there are no inter-thread patch/unpatch races.
        with patch("app.utils.whatsapp_utils._send_request", return_value=_ok_response()):
            threads = [threading.Thread(target=_run_one, args=(i,)) for i in range(N)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

        self.assertEqual(len(results), N)
        self.assertTrue(all(r["ok"] for r in results), "Not all deliveries succeeded")

        from app.services.message_log import get_message_log_buffer
        with app.app_context():
            log_entries = get_message_log_buffer(app).get_all()
        self.assertGreaterEqual(len(log_entries), N,
                                f"Expected >= {N} log entries, got {len(log_entries)}")

    def test_background_service_wait_for_idle_after_burst(self):
        """After a burst of submissions, wait_for_idle() eventually returns True."""
        from app.services.outbound_delivery import BackgroundDeliveryService

        svc = BackgroundDeliveryService(max_workers=4)
        completed = []

        for i in range(20):
            svc.submit(completed.append, i)

        idle = svc.wait_for_idle(timeout=10.0)
        svc.shutdown(wait=True)
        self.assertTrue(idle)
        self.assertEqual(len(completed), 20)


if __name__ == "__main__":
    unittest.main()
