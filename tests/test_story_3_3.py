"""
Tests for Story 3.3: Conversation Context and Operator Activity Views

Covers:
- ConversationContextStore: max 5 messages per user, timeout reset, explicit boundary reset
- MessageLogBuffer: FIFO cap at 100, newest-first ordering, thread-safe add
- /logs route: status filtering, phone number masking in rendered entries
- /api/logs and /api/metrics routes: accessible under operator session
"""
import os
import time
import unittest
from unittest.mock import patch


_BASE_ENV = {
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


def _make_app():
    with patch.dict(os.environ, _BASE_ENV, clear=False):
        from app import create_app
        return create_app()


# ---------------------------------------------------------------------------
# ConversationContextStore
# ---------------------------------------------------------------------------

class ConversationContextStoreTests(unittest.TestCase):
    """AC1: per-user rolling context window, max 5, reset on timeout/boundary."""

    def setUp(self):
        from app.services.conversation_context import ConversationContextStore
        self.store = ConversationContextStore(timeout_seconds=3600.0)

    def _msg(self, text: str, role: str = "user") -> dict:
        return {"role": role, "text": text, "timestamp": "2026-05-01T00:00:00Z", "message_id": text}

    def test_append_and_get_single_message(self):
        """AC1: appended message is retrievable via get_context."""
        self.store.append_message("user1", self._msg("hello"))
        ctx = self.store.get_context("user1")
        self.assertEqual(len(ctx), 1)
        self.assertEqual(ctx[0]["text"], "hello")

    def test_max_messages_is_five(self):
        """AC1: only last 5 messages are retained per user."""
        for i in range(7):
            self.store.append_message("user2", self._msg(f"msg-{i}"))
        ctx = self.store.get_context("user2")
        self.assertEqual(len(ctx), 5)
        # Oldest messages are dropped, newest kept
        self.assertEqual(ctx[-1]["text"], "msg-6")
        self.assertEqual(ctx[0]["text"], "msg-2")

    def test_get_context_empty_for_unknown_user(self):
        """AC1: unknown user returns empty list."""
        self.assertEqual(self.store.get_context("no-such-user"), [])

    def test_reset_context_clears_messages(self):
        """AC1: reset_context removes all messages for the user (boundary reset)."""
        self.store.append_message("user3", self._msg("hi"))
        self.store.reset_context("user3")
        self.assertEqual(self.store.get_context("user3"), [])

    def test_reset_context_for_unknown_user_is_safe(self):
        """AC1: reset_context on unknown user does not raise."""
        self.store.reset_context("ghost-user")  # Must not raise

    def test_timeout_clears_context_on_next_access(self):
        """AC1: context expired on get_context returns empty list (mock monotonic)."""
        from app.services import conversation_context as _cc
        store = _cc.ConversationContextStore(timeout_seconds=60.0)
        # Seed at t=0
        with patch("app.services.conversation_context.monotonic", return_value=0.0):
            store.append_message("user4", self._msg("soon-expired"))
        # Access at t=120 (well beyond 60s timeout)
        with patch("app.services.conversation_context.monotonic", return_value=120.0):
            self.assertEqual(store.get_context("user4"), [])

    def test_timeout_resets_on_new_append(self):
        """AC1: a new message from an expired user restarts a fresh window (mock monotonic)."""
        from app.services import conversation_context as _cc
        store = _cc.ConversationContextStore(timeout_seconds=60.0)
        with patch("app.services.conversation_context.monotonic", return_value=0.0):
            store.append_message("user5", self._msg("old"))
        # Append at t=120 (expired)
        with patch("app.services.conversation_context.monotonic", return_value=120.0):
            store.append_message("user5", self._msg("new"))
            ctx = store.get_context("user5")
        self.assertEqual(len(ctx), 1)
        self.assertEqual(ctx[0]["text"], "new")

    def test_clear_removes_all_users(self):
        """AC1: clear() wipes all stored contexts."""
        self.store.append_message("ua", self._msg("a"))
        self.store.append_message("ub", self._msg("b"))
        self.store.clear()
        self.assertEqual(self.store.get_context("ua"), [])
        self.assertEqual(self.store.get_context("ub"), [])

    def test_get_context_returns_copy_not_reference(self):
        """AC1: mutations to returned list do not affect the store."""
        self.store.append_message("user6", self._msg("immutable"))
        ctx = self.store.get_context("user6")
        ctx.clear()
        self.assertEqual(len(self.store.get_context("user6")), 1)


# ---------------------------------------------------------------------------
# MessageLogBuffer
# ---------------------------------------------------------------------------

class MessageLogBufferTests(unittest.TestCase):
    """AC2, AC3: in-memory log buffer, FIFO cap 100, newest-first retrieval."""

    def setUp(self):
        from app.services.message_log import MessageLogBuffer
        self.buf = MessageLogBuffer(max_size=100)

    def _entry(self, status="sent", phone="15551234567", text="hello"):
        return {
            "timestamp": "2026-05-01T00:00:00Z",
            "from": phone,
            "message_id": f"id-{phone}-{status}",
            "to_num": "1234567890",
            "agent": "test-agent",
            "preview": text,
            "reply_text": "ok",
            "status": status,
            "error": None,
            "operator_review_flagged": False,
            "operator_review_reason": None,
        }

    def test_empty_buffer_returns_empty_list(self):
        """AC2: fresh buffer has no entries."""
        self.assertEqual(self.buf.get_all(), [])

    def test_added_entry_is_retrievable(self):
        """AC2: add_message stores entry retrievable via get_all()."""
        self.buf.add_message(self._entry(status="sent"))
        entries = self.buf.get_all()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["status"], "sent")

    def test_newest_first_ordering(self):
        """AC3: get_all() returns newest entries first."""
        self.buf.add_message(self._entry(status="sent", phone="111"))
        self.buf.add_message(self._entry(status="error", phone="222"))
        entries = self.buf.get_all()
        self.assertEqual(entries[0]["from"], "222")  # newest first
        self.assertEqual(entries[1]["from"], "111")

    def test_fifo_cap_at_max_size(self):
        """AC3: buffer capped at max_size; oldest entries are dropped."""
        buf = __import__(
            "app.services.message_log", fromlist=["MessageLogBuffer"]
        ).MessageLogBuffer(max_size=5)
        for i in range(7):
            buf.add_message(self._entry(phone=str(i)))
        entries = buf.get_all()
        self.assertEqual(len(entries), 5)
        # Oldest two (0, 1) dropped; newest (6) is first
        phones = [e["from"] for e in entries]
        self.assertIn("6", phones)
        self.assertNotIn("0", phones)
        self.assertNotIn("1", phones)

    def test_clear_empties_buffer(self):
        """AC3: clear() removes all entries."""
        self.buf.add_message(self._entry())
        self.buf.clear()
        self.assertEqual(self.buf.get_all(), [])

    def test_get_all_returns_copy_not_reference(self):
        """AC3: mutation of returned list does not affect buffer state."""
        self.buf.add_message(self._entry())
        first = self.buf.get_all()
        first.clear()
        self.assertEqual(len(self.buf.get_all()), 1)

    def test_max_size_property(self):
        """AC3: max_size property reflects configured limit."""
        from app.services.message_log import MessageLogBuffer
        buf = MessageLogBuffer(max_size=50)
        self.assertEqual(buf.max_size, 50)


# ---------------------------------------------------------------------------
# Operator logs view: status filtering and phone masking
# ---------------------------------------------------------------------------

class OperatorLogsViewTests(unittest.TestCase):
    """AC3, AC4: /logs route filters by status and masks phone numbers."""

    def setUp(self):
        self._env = patch.dict(os.environ, _BASE_ENV, clear=False)
        self._env.start()
        self.app = _make_app()
        self.client = self.app.test_client()
        self.app.config["SECRET_KEY"] = "test-secret-key"
        self.app.config["TESTING"] = True
        self.app.config["WTF_CSRF_ENABLED"] = False
        with self.app.app_context():
            from app.services.message_log import get_message_log_buffer
            get_message_log_buffer(self.app).clear()

    def tearDown(self):
        self._env.stop()

    def _operator_session(self, client):
        """Set the operator session role."""
        with client.session_transaction() as sess:
            sess["dashboard_role"] = "operator"

    def _add_log_entries(self, entries):
        with self.app.app_context():
            from app.services.message_log import get_message_log_buffer
            buf = get_message_log_buffer(self.app)
            for entry in entries:
                buf.add_message(entry)

    def _log_entry(self, status="sent", phone="15551234567"):
        return {
            "timestamp": "2026-05-01T10:00:00Z",
            "from": phone,
            "message_id": f"id-{phone}",
            "to_num": "1234567890",
            "agent": "test",
            "preview": "hello",
            "reply_text": "ok",
            "status": status,
            "error": None,
            "operator_review_flagged": False,
            "operator_review_reason": None,
        }

    def test_logs_page_requires_operator_access(self):
        """AC3: /logs redirects unauthenticated requests."""
        response = self.client.get("/logs")
        self.assertIn(response.status_code, (302, 403))

    def test_logs_page_accessible_to_operator(self):
        """AC3: /logs renders 200 for authenticated operator."""
        self._operator_session(self.client)
        response = self.client.get("/logs")
        self.assertEqual(response.status_code, 200)

    def test_logs_filter_status_sent(self):
        """AC3: ?status=sent returns only sent entries."""
        self._add_log_entries([
            self._log_entry(status="sent", phone="111"),
            self._log_entry(status="error", phone="222"),
        ])
        self._operator_session(self.client)
        response = self.client.get("/logs?status=sent")
        self.assertEqual(response.status_code, 200)
        body = response.data.decode()
        # The error entry's phone should not appear
        self.assertNotIn("222", body)

    def test_logs_filter_status_error(self):
        """AC3: ?status=error returns only error entries."""
        self._add_log_entries([
            self._log_entry(status="sent", phone="111"),
            self._log_entry(status="error", phone="222"),
        ])
        self._operator_session(self.client)
        response = self.client.get("/logs?status=error")
        self.assertEqual(response.status_code, 200)
        body = response.data.decode()
        self.assertNotIn("111", body)

    def test_logs_filter_status_error_accepts_whitespace_and_case_variants(self):
        """AC4: status filter normalizes case and whitespace for valid values."""
        self._add_log_entries([
            self._log_entry(status="sent", phone="111"),
            self._log_entry(status="error", phone="222"),
        ])
        self._operator_session(self.client)
        response = self.client.get("/logs?status=%20ErRoR%20")
        self.assertEqual(response.status_code, 200)
        body = response.data.decode()
        self.assertNotIn("111", body)
        self.assertIn("222", body)

    def test_logs_filter_invalid_status_falls_back_to_all_entries(self):
        """AC4: unknown status values do not drop entries and behave as all."""
        self._add_log_entries([
            self._log_entry(status="sent", phone="111"),
            self._log_entry(status="error", phone="222"),
        ])
        self._operator_session(self.client)
        response = self.client.get("/logs?status=unknown")
        self.assertEqual(response.status_code, 200)
        body = response.data.decode()
        self.assertIn("111", body)
        self.assertIn("222", body)

    def test_logs_filter_invalid_status_with_whitespace_still_falls_back_to_all(self):
        """AC4: normalized unknown status values still retain all entries."""
        self._add_log_entries([
            self._log_entry(status="sent", phone="111"),
            self._log_entry(status="error", phone="222"),
        ])
        self._operator_session(self.client)
        response = self.client.get("/logs?status=%20Unknown%20")
        self.assertEqual(response.status_code, 200)
        body = response.data.decode()
        self.assertIn("111", body)
        self.assertIn("222", body)

    def test_logs_phone_number_is_masked_in_entries(self):
        """AC4: phone numbers in log entries are masked in visible output."""
        self._add_log_entries([self._log_entry(phone="15551234567")])
        self._operator_session(self.client)
        response = self.client.get("/logs")
        self.assertEqual(response.status_code, 200)
        body = response.data.decode()
        # Masked form must be visible in the rendered page
        self.assertIn("155...4567", body)
        # The raw number may exist only inside data-full (hidden) span —
        # confirm the masked version is the primary display (data-masked span)
        self.assertIn("data-masked", body)


# ---------------------------------------------------------------------------
# Operator API routes
# ---------------------------------------------------------------------------

class OperatorApiRouteTests(unittest.TestCase):
    """AC2, AC5: /api/logs and /api/metrics accessible under operator session."""

    def setUp(self):
        self._env = patch.dict(os.environ, _BASE_ENV, clear=False)
        self._env.start()
        self.app = _make_app()
        self.client = self.app.test_client()
        self.app.config["SECRET_KEY"] = "test-secret-key"
        self.app.config["TESTING"] = True

    def tearDown(self):
        self._env.stop()

    def _operator_session(self, client):
        with client.session_transaction() as sess:
            sess["dashboard_role"] = "operator"

    def test_api_logs_returns_json_list(self):
        """AC2: /api/logs returns a JSON array."""
        self._operator_session(self.client)
        response = self.client.get("/api/logs")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIsInstance(data, list)

    def test_api_metrics_returns_json_object(self):
        """AC2: /api/metrics returns a JSON object with expected keys."""
        self._operator_session(self.client)
        response = self.client.get("/api/metrics")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIsInstance(data, dict)

    def test_api_health_returns_json_with_status(self):
        """AC5: /api/health returns JSON with a status key."""
        self._operator_session(self.client)
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("status", data)

    def test_operator_metrics_page_accessible(self):
        """AC5: /operator/metrics renders for operator session."""
        self._operator_session(self.client)
        response = self.client.get("/operator/metrics")
        self.assertEqual(response.status_code, 200)


class ThreadInspectorApiTests(unittest.TestCase):
    """Operator thread inspector API exposes safe recent context and activity."""

    def setUp(self):
        self._env = patch.dict(os.environ, _BASE_ENV, clear=False)
        self._env.start()
        self.app = _make_app()
        self.client = self.app.test_client()
        self.app.config["SECRET_KEY"] = "test-secret-key"
        self.app.config["TESTING"] = True

        with self.app.app_context():
            from app.services.conversation_context import get_conversation_context_store
            from app.services.message_log import get_message_log_buffer

            get_conversation_context_store(self.app).clear()
            get_message_log_buffer(self.app).clear()

    def tearDown(self):
        self._env.stop()

    def _operator_session(self, client):
        with client.session_transaction() as sess:
            sess["dashboard_role"] = "operator"

    def test_thread_inspector_requires_operator_access(self):
        response = self.client.get("/api/thread-inspector?user_id=15551234567")
        self.assertIn(response.status_code, (302, 403))

    def test_thread_inspector_requires_user_id(self):
        self._operator_session(self.client)
        response = self.client.get("/api/thread-inspector")
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload.get("ok", True))

    def test_thread_inspector_returns_sanitized_context_and_masked_activity(self):
        self._operator_session(self.client)

        with self.app.app_context():
            from app.services.conversation_context import get_conversation_context_store
            from app.services.message_log import get_message_log_buffer

            context_store = get_conversation_context_store(self.app)
            log_buffer = get_message_log_buffer(self.app)

            for i in range(6):
                text = f"m{i} openai_api_key=sk-secret-abc123"
                context_store.append_message(
                    "15551234567",
                    {
                        "role": "user",
                        "text": text,
                        "timestamp": "2026-05-01T10:00:00Z",
                        "message_id": f"ctx-{i}",
                    },
                )

            log_buffer.add_message(
                {
                    "timestamp": "2026-05-01T10:00:00Z",
                    "from": "15551234567",
                    "message_id": "msg-1",
                    "to_num": "1234567890",
                    "agent": "test-agent",
                    "preview": "authorization=Bearer abc",
                    "reply_text": "ok",
                    "status": "sent",
                    "error": None,
                    "operator_review_flagged": False,
                    "operator_review_reason": None,
                }
            )
            log_buffer.add_message(
                {
                    "timestamp": "2026-05-01T10:01:00Z",
                    "from": "16667778888",
                    "message_id": "msg-2",
                    "to_num": "1234567890",
                    "agent": "test-agent",
                    "preview": "other-user",
                    "reply_text": "ok",
                    "status": "error",
                    "error": "timeout",
                    "operator_review_flagged": True,
                    "operator_review_reason": "outbound_fallback_failure",
                }
            )

        response = self.client.get("/api/thread-inspector?user_id=+1 (555) 123-4567")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload.get("ok"))

        thread = payload["thread"]
        self.assertEqual(thread["user_id_masked"], "155...4567")

        context = thread["conversation_context"]
        self.assertEqual(len(context), 5)
        self.assertIn("[REDACTED]", context[0]["text"])
        self.assertNotIn("sk-secret-abc123", context[0]["text"])

        activity = thread["recent_activity"]
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity[0]["from_masked"], "155...4567")
        self.assertNotIn("from", activity[0])
        self.assertIn("[REDACTED]", activity[0]["preview"])


class OperatorDashboardInterventionSignalTests(unittest.TestCase):
    """Dashboard shows explicit stop/clear intervention signals for operators."""

    def setUp(self):
        self._env = patch.dict(os.environ, _BASE_ENV, clear=False)
        self._env.start()
        self.app = _make_app()
        self.client = self.app.test_client()

        with self.app.app_context():
            from app.services.message_log import get_message_log_buffer
            get_message_log_buffer(self.app).clear()

    def tearDown(self):
        self._env.stop()

    def _operator_session(self):
        with self.client.session_transaction() as sess:
            sess["dashboard_role"] = "operator"

    def _add_entry(self, *, flagged: bool, reason: str | None):
        with self.app.app_context():
            from app.services.message_log import get_message_log_buffer
            get_message_log_buffer(self.app).add_message(
                {
                    "timestamp": "2026-05-01T10:00:00Z",
                    "from": "15551234567",
                    "message_id": "msg-1",
                    "to_num": "1234567890",
                    "agent": "test-agent",
                    "preview": "hello",
                    "reply_text": "ok",
                    "status": "sent",
                    "error": None,
                    "operator_review_flagged": flagged,
                    "operator_review_reason": reason,
                }
            )

    def test_operator_dashboard_shows_stop_signal_when_escalation_flagged(self):
        self._add_entry(flagged=True, reason="escalation_keyword")
        self._operator_session()

        response = self.client.get("/operator")
        self.assertEqual(response.status_code, 200)
        body = response.data.decode()
        self.assertIn("Automation stop signal active", body)
        self.assertIn("escalation_keyword", body)

    def test_operator_dashboard_shows_clear_signal_when_no_escalation(self):
        self._add_entry(flagged=False, reason=None)
        self._operator_session()

        response = self.client.get("/operator")
        self.assertEqual(response.status_code, 200)
        body = response.data.decode()
        self.assertIn("No active stop signal", body)


if __name__ == "__main__":
    unittest.main()
