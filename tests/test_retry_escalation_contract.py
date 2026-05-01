"""Contract tests for retry/escalation policies (Epic 5 Retro Action Item 1).

Verifies the explicit behaviour contracts for:
- Retry schedule: exactly 3 retries → 4 total primary attempts before fallback
- Mixed failure sequences: partial failures recover correctly on a subsequent attempt
- Fallback semantics: operator_review_flagged is always set when fallback path is reached
- WHATSAPP_FALLBACK_MAX_RETRIES config is honoured by the fallback loop
- Deferred delivery (WHATSAPP_DEFER_RETRIES) returns the correct "retrying" envelope
- Escalation-reason priority order is deterministic
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

import requests

RETRY_ENV = {
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
    with patch.dict(os.environ, RETRY_ENV, clear=False):
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


def _counter_side_effect(fail_count: int, ok_response: Mock | None = None):
    """Return a side-effect function that raises on the first *fail_count* calls then succeeds."""
    ok = ok_response or _ok_response()
    call_count = [0]

    def _effect(data, timeout):
        call_count[0] += 1
        if call_count[0] <= fail_count:
            raise requests.Timeout(f"simulated timeout #{call_count[0]}")
        return ok

    return _effect, call_count


# ---------------------------------------------------------------------------
# Retry schedule contract
# ---------------------------------------------------------------------------

class RetryScheduleContractTests(unittest.TestCase):
    """The retry backoff schedule defines 4 total primary attempts."""

    def setUp(self):
        self._env = patch.dict(os.environ, RETRY_ENV, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_retry_schedule_has_three_backoff_slots(self):
        """Contract: schedule length == 3 → attempts 0,1,2,3 before fallback."""
        app = _make_app()
        with app.app_context():
            from app.utils.whatsapp_utils import _retry_backoff_schedule
            schedule = _retry_backoff_schedule()
        self.assertEqual(len(schedule), 3)
        self.assertEqual(schedule, (1, 2, 4))

    def test_schedule_values_are_increasing(self):
        """Each successive backoff delay must be larger than the previous."""
        app = _make_app()
        with app.app_context():
            from app.utils.whatsapp_utils import _retry_backoff_schedule
            schedule = _retry_backoff_schedule()
        for i in range(len(schedule) - 1):
            self.assertLess(schedule[i], schedule[i + 1], msg=f"index {i} >= index {i+1}")


# ---------------------------------------------------------------------------
# Mixed failure sequence contracts
# ---------------------------------------------------------------------------

class MixedFailureSequenceTests(unittest.TestCase):
    """_complete_send_message handles all partial-failure patterns correctly."""

    def setUp(self):
        self._env = patch.dict(os.environ, RETRY_ENV, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def _run(self, side_effect, extra_config=None):
        app = _make_app(extra_config)
        with app.app_context():
            from app.utils.whatsapp_utils import _complete_send_message, get_text_message_input
            data = get_text_message_input("15551234567", "hello")
            with patch("app.utils.whatsapp_utils._send_request", side_effect=side_effect), \
                 patch("app.utils.whatsapp_utils.time.sleep"):
                return _complete_send_message(data, "req-contract-001")

    def test_immediate_success_attempt_zero(self):
        """Succeed on attempt 0 → ok=True, no fallback, attempts=1."""
        result = self._run(side_effect=_ok_response())
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "sent")
        self.assertFalse(result["operator_review_flagged"])
        self.assertFalse(result["fallback_sent"])

    def test_fail_once_then_succeed_on_retry_one(self):
        """Fail attempt 0, succeed attempt 1 → ok=True, no fallback."""
        effect, count = _counter_side_effect(fail_count=1)
        result = self._run(side_effect=effect)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "sent")
        self.assertFalse(result["operator_review_flagged"])
        self.assertEqual(count[0], 2)

    def test_fail_twice_then_succeed_on_retry_two(self):
        """Fail attempts 0 and 1, succeed attempt 2 → ok=True."""
        effect, count = _counter_side_effect(fail_count=2)
        result = self._run(side_effect=effect)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "sent")
        self.assertEqual(count[0], 3)

    def test_fail_three_times_then_succeed_on_retry_three(self):
        """Fail attempts 0,1,2 — succeed on attempt 3 (last primary attempt)."""
        effect, count = _counter_side_effect(fail_count=3)
        result = self._run(side_effect=effect)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "sent")
        self.assertEqual(count[0], 4)

    def test_all_four_primary_attempts_fail_triggers_fallback(self):
        """All 4 primary attempts fail → fallback path entered, operator_review_flagged=True."""
        result = self._run(side_effect=requests.Timeout("always fail"))
        self.assertFalse(result["ok"])
        self.assertTrue(result["operator_review_flagged"])
        self.assertEqual(result["operator_review_reason"], "outbound_fallback_failure")


# ---------------------------------------------------------------------------
# Fallback semantics contracts
# ---------------------------------------------------------------------------

class FallbackSemanticsTests(unittest.TestCase):
    """Fallback outcomes are correctly encoded in the result dict."""

    def setUp(self):
        self._env = patch.dict(os.environ, RETRY_ENV, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def _run(self, side_effect, extra_config=None):
        app = _make_app(extra_config)
        with app.app_context():
            from app.utils.whatsapp_utils import _complete_send_message, get_text_message_input
            data = get_text_message_input("15551234567", "hello")
            with patch("app.utils.whatsapp_utils._send_request", side_effect=side_effect), \
                 patch("app.utils.whatsapp_utils.time.sleep"):
                return _complete_send_message(data, "req-fallback-001")

    def test_fallback_succeeds_produces_fallback_sent_status(self):
        """First fallback attempt fails; next fallback retry succeeds within configured limit."""
        # 4 primary failures + 1 fallback failure; final allowed fallback retry succeeds.
        effect, count = _counter_side_effect(fail_count=5)
        result = self._run(
            side_effect=effect,
            extra_config={"WHATSAPP_FALLBACK_MAX_RETRIES": 2},
        )
        self.assertFalse(result["ok"])
        self.assertTrue(result["fallback_sent"])
        self.assertEqual(result["status"], "fallback_sent")
        self.assertTrue(result["operator_review_flagged"])
        self.assertEqual(count[0], 6)

    def test_fallback_fails_all_attempts_produces_error_status(self):
        """All primary attempts and all configured fallback retries fail deterministically."""
        effect, count = _counter_side_effect(fail_count=99)
        result = self._run(
            side_effect=effect,
            extra_config={"WHATSAPP_FALLBACK_MAX_RETRIES": 2},
        )
        self.assertFalse(result["ok"])
        self.assertFalse(result["fallback_sent"])
        self.assertEqual(result["status"], "error")
        self.assertTrue(result["operator_review_flagged"])
        self.assertEqual(count[0], 6)

    def test_fallback_max_retries_one_limits_fallback_calls(self):
        """WHATSAPP_FALLBACK_MAX_RETRIES=1 → exactly 1 fallback attempt (total 5 calls)."""
        effect, count = _counter_side_effect(fail_count=4)
        result = self._run(
            side_effect=effect,
            extra_config={"WHATSAPP_FALLBACK_MAX_RETRIES": 1},
        )
        # 4 primary + 1 fallback = 5 total calls; fallback call succeeds
        self.assertEqual(count[0], 5)
        self.assertTrue(result["fallback_sent"])

    def test_fallback_max_retries_zero_clamps_to_minimum(self):
        """WHATSAPP_FALLBACK_MAX_RETRIES <= 0 behaves gracefully (zero or one attempts)."""
        result = self._run(
            side_effect=requests.Timeout("always fail"),
            extra_config={"WHATSAPP_FALLBACK_MAX_RETRIES": 0},
        )
        # Should not raise; result must encode a failure state
        self.assertFalse(result["ok"])
        self.assertTrue(result["operator_review_flagged"])

    def test_operator_review_reason_is_always_set_on_fallback_path(self):
        """operator_review_reason must be non-empty whenever operator_review_flagged is True."""
        result = self._run(side_effect=requests.Timeout("always fail"))
        if result["operator_review_flagged"]:
            self.assertTrue(result.get("operator_review_reason"), "reason must be set")


# ---------------------------------------------------------------------------
# Deferred retry (WHATSAPP_DEFER_RETRIES) contracts
# ---------------------------------------------------------------------------

class DeferredRetryContractTests(unittest.TestCase):
    """send_message with WHATSAPP_DEFER_RETRIES=True returns correct deferred envelope."""

    def setUp(self):
        self._env = patch.dict(os.environ, RETRY_ENV, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_first_attempt_failure_returns_retrying_envelope(self):
        """With DEFER_RETRIES=True, initial failure → deferred=True, status='retrying'."""
        app = _make_app({"WHATSAPP_DEFER_RETRIES": True})
        with app.app_context():
            from app.utils.whatsapp_utils import send_message, get_text_message_input
            data = get_text_message_input("15551234567", "hello")
            with patch("app.utils.whatsapp_utils._send_request",
                       side_effect=requests.Timeout("fail")), \
                 patch("app.services.outbound_delivery.BackgroundDeliveryService.submit"):
                result = send_message(data, "req-defer-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "retrying")
        self.assertTrue(result.get("deferred"))

    def test_first_attempt_success_not_deferred(self):
        """With DEFER_RETRIES=True, initial success → ok=True, no deferral."""
        app = _make_app({"WHATSAPP_DEFER_RETRIES": True})
        with app.app_context():
            from app.utils.whatsapp_utils import send_message, get_text_message_input
            data = get_text_message_input("15551234567", "hello")
            with patch("app.utils.whatsapp_utils._send_request",
                       return_value=_ok_response()):
                result = send_message(data, "req-defer-002")
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "sent")
        self.assertFalse(result.get("deferred", False))

    def test_deferred_false_by_default(self):
        """WHATSAPP_DEFER_RETRIES defaults to True; with it disabled, runs sync retry."""
        app = _make_app({"WHATSAPP_DEFER_RETRIES": False})
        with app.app_context():
            from app.utils.whatsapp_utils import send_message, get_text_message_input
            data = get_text_message_input("15551234567", "hello")
            with patch("app.utils.whatsapp_utils._send_request",
                       side_effect=requests.Timeout("fail")), \
                 patch("app.utils.whatsapp_utils.time.sleep"):
                result = send_message(data, "req-sync-001")
        # Sync path exhausts retries → fallback path, not deferred
        self.assertFalse(result.get("deferred", False))
        self.assertTrue(result["operator_review_flagged"])


# ---------------------------------------------------------------------------
# Escalation-reason priority order contracts
# ---------------------------------------------------------------------------

class EscalationReasonPriorityTests(unittest.TestCase):
    """_resolve_escalation_reason follows a fixed priority order."""

    def setUp(self):
        self._env = patch.dict(os.environ, RETRY_ENV, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def _resolve(self, *, message_body: str, confidence, delivery: dict,
                 app_config: dict | None = None) -> str | None:
        app = _make_app(app_config)
        with app.app_context():
            from app.utils.whatsapp_utils import _resolve_escalation_reason
            return _resolve_escalation_reason(
                message_body=message_body,
                confidence=confidence,
                delivery=delivery,
            )

    def test_outbound_fallback_flag_takes_priority_over_keyword(self):
        """operator_review_flagged in delivery overrides keyword escalation."""
        reason = self._resolve(
            message_body="human please",
            confidence=0.9,
            delivery={"operator_review_flagged": True,
                      "operator_review_reason": "outbound_fallback_failure"},
            app_config={"ESCALATION_KEYWORDS": "human"},
        )
        self.assertEqual(reason, "outbound_fallback_failure")

    def test_outbound_fallback_flag_takes_priority_over_low_confidence(self):
        """operator_review_flagged overrides low confidence escalation."""
        reason = self._resolve(
            message_body="something",
            confidence=0.05,
            delivery={"operator_review_flagged": True,
                      "operator_review_reason": "outbound_fallback_failure"},
            app_config={"ESCALATION_CONFIDENCE_THRESHOLD": 0.35},
        )
        self.assertEqual(reason, "outbound_fallback_failure")

    def test_keyword_match_produces_escalation_keyword_reason(self):
        """Message containing configured keyword → reason='escalation_keyword'."""
        reason = self._resolve(
            message_body="I need a human agent",
            confidence=0.9,
            delivery={},
            app_config={"ESCALATION_KEYWORDS": "human,agent,escalate"},
        )
        self.assertEqual(reason, "escalation_keyword")

    def test_keyword_case_insensitive_match(self):
        """Keyword matching is case-insensitive."""
        reason = self._resolve(
            message_body="ESCALATE this issue",
            confidence=0.9,
            delivery={},
            app_config={"ESCALATION_KEYWORDS": "escalate"},
        )
        self.assertEqual(reason, "escalation_keyword")

    def test_low_confidence_below_threshold_triggers_reason(self):
        """AI confidence below configured threshold → reason='low_confidence'."""
        reason = self._resolve(
            message_body="some benign text",
            confidence=0.10,
            delivery={},
            app_config={"ESCALATION_CONFIDENCE_THRESHOLD": 0.35},
        )
        self.assertEqual(reason, "low_confidence")

    def test_confidence_at_threshold_does_not_escalate(self):
        """Confidence exactly at threshold → no escalation from confidence."""
        reason = self._resolve(
            message_body="some benign text",
            confidence=0.35,
            delivery={},
            app_config={"ESCALATION_CONFIDENCE_THRESHOLD": 0.35,
                        "ESCALATION_KEYWORDS": ""},
        )
        self.assertIsNone(reason)

    def test_no_conditions_returns_none(self):
        """No keyword, sufficient confidence, no delivery flag → None."""
        reason = self._resolve(
            message_body="hello there",
            confidence=0.9,
            delivery={},
            app_config={"ESCALATION_CONFIDENCE_THRESHOLD": 0.35,
                        "ESCALATION_KEYWORDS": ""},
        )
        self.assertIsNone(reason)


if __name__ == "__main__":
    unittest.main()
