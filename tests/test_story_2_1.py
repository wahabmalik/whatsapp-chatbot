"""
Tests for Story 2.1: Inbound Normalization and Idempotency

Covers:
- normalize_inbound_message() for Meta payloads (text, status update, non-text)
- normalize_inbound_message() for Evolution payloads (text, fromMe, non-text)
- Duplicate suppression via create_expiring_store() / _is_duplicate_message()
- Store factory backend selection: memory, sqlite, sqlite-fallback-to-memory
- Store close() lifecycle compatibility
"""
import os
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


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------

def _meta_text_payload(
    wa_id="15551234567",
    name="Test User",
    msg_id="wamid.test001",
    body="Hello",
    timestamp="1700000000",
):
    entry_value = {
        "contacts": [{"wa_id": wa_id, "profile": {"name": name}}],
        "messages": [
            {
                "id": msg_id,
                "type": "text",
                "text": {"body": body},
                "timestamp": timestamp,
            }
        ],
    }
    return {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": entry_value}]}],
    }


def _meta_status_payload():
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [
                                {"id": "wamid.status001", "status": "delivered"}
                            ]
                        }
                    }
                ]
            }
        ],
    }


def _meta_non_text_payload(msg_type="image"):
    entry_value = {
        "contacts": [{"wa_id": "15551234567", "profile": {"name": "Test"}}],
        "messages": [
            {
                "id": "wamid.img001",
                "type": msg_type,
                "image": {"id": "img001"},
                "timestamp": "1700000000",
            }
        ],
    }
    return {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": entry_value}]}],
    }


def _evolution_text_payload(
    wa_id="5511987654321@s.whatsapp.net",
    msg_id="evo-msg-001",
    text="Hello from Evolution",
    name="Evo User",
):
    return {
        "key": {"remoteJid": wa_id, "id": msg_id, "fromMe": False},
        "message": {"conversation": text},
        "pushName": name,
        "messageTimestamp": "1700000000",
    }


def _evolution_from_me_payload():
    return {
        "key": {
            "remoteJid": "5511987654321@s.whatsapp.net",
            "id": "evo-out-001",
            "fromMe": True,
        },
        "message": {"conversation": "bot reply"},
    }


def _evolution_non_text_payload():
    return {
        "key": {
            "remoteJid": "5511987654321@s.whatsapp.net",
            "id": "evo-img-001",
            "fromMe": False,
        },
        "message": {"imageMessage": {"url": "https://example.com/img.jpg"}},
        "messageTimestamp": "1700000000",
    }


def _instagram_text_payload(
    sender_id="17841400008460056",
    recipient_id="17841499999999999",
    msg_id="ig-mid-001",
    body="Hello from Instagram",
    timestamp="1700000002",
):
    return {
        "object": "instagram",
        "entry": [
            {
                "id": recipient_id,
                "time": int(timestamp),
                "messaging": [
                    {
                        "sender": {"id": sender_id},
                        "recipient": {"id": recipient_id},
                        "timestamp": int(timestamp),
                        "message": {"mid": msg_id, "text": body},
                    }
                ],
            }
        ],
    }


def _instagram_non_text_payload():
    return {
        "object": "instagram",
        "entry": [
            {
                "id": "17841499999999999",
                "messaging": [
                    {
                        "sender": {"id": "17841400008460056"},
                        "recipient": {"id": "17841499999999999"},
                        "timestamp": 1700000002,
                        "message": {
                            "mid": "ig-mid-image-001",
                            "attachments": [{"type": "image"}],
                        },
                    }
                ],
            }
        ],
    }


def _messenger_text_payload(
    sender_id="1234567890123456",
    recipient_id="9876543210987654",
    msg_id="m-mid-001",
    body="Hello from Messenger",
    timestamp="1700000003",
):
    return {
        "object": "page",
        "entry": [
            {
                "id": recipient_id,
                "time": int(timestamp),
                "messaging": [
                    {
                        "sender": {"id": sender_id},
                        "recipient": {"id": recipient_id},
                        "timestamp": int(timestamp),
                        "message": {"mid": msg_id, "text": body},
                    }
                ],
            }
        ],
    }


def _messenger_non_text_payload():
    return {
        "object": "page",
        "entry": [
            {
                "id": "9876543210987654",
                "messaging": [
                    {
                        "sender": {"id": "1234567890123456"},
                        "recipient": {"id": "9876543210987654"},
                        "timestamp": 1700000003,
                        "message": {
                            "mid": "m-mid-image-001",
                            "attachments": [{"type": "image"}],
                        },
                    }
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# Meta inbound normalization
# ---------------------------------------------------------------------------

class MetaInboundNormalizationTests(unittest.TestCase):
    """normalize_inbound_message() for Meta WhatsApp payloads (AC1, AC2)."""

    def setUp(self):
        self._env = patch.dict(os.environ, _BASE_ENV, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_text_message_produces_canonical_fields(self):
        """AC1: text message maps to user_id, message_text, timestamp, message_id."""
        from app.utils.whatsapp_utils import normalize_inbound_message

        payload = _meta_text_payload(
            wa_id="15551234567", msg_id="wamid.001", body="Hi there", timestamp="1700000001"
        )
        result = normalize_inbound_message(payload)
        self.assertIsNotNone(result)
        self.assertEqual(result["user_id"], "15551234567")
        self.assertEqual(result["message_text"], "Hi there")
        self.assertEqual(result["message_id"], "wamid.001")
        self.assertEqual(result["event_id"], "msg:meta:wamid.001")
        self.assertEqual(result["dedupe_key"], result["event_id"])
        self.assertEqual(result["timestamp"], "1700000001")
        self.assertFalse(result["unsupported"])
        self.assertFalse(result["status_update"])

    def test_missing_message_id_uses_fingerprint_event_id(self):
        """AC1: message without message_id still gets deterministic dedupe identifiers."""
        from app.utils.whatsapp_utils import normalize_inbound_message

        payload = _meta_text_payload(body="hello there", timestamp="1700000009")
        payload["entry"][0]["changes"][0]["value"]["messages"][0].pop("id", None)

        result = normalize_inbound_message(payload)
        self.assertIsNotNone(result)
        self.assertTrue(str(result["event_id"]).startswith("fp:meta:"))
        self.assertEqual(result["dedupe_key"], result["event_id"])

    def test_missing_message_id_payload_variants_produce_distinct_fingerprint_ids(self):
        """Distinct no-ID payload variants should not collapse onto one dedupe key."""
        from app.utils.whatsapp_utils import normalize_inbound_message

        payload_a = _meta_text_payload(body="hello there", timestamp="1700000009")
        payload_a["entry"][0]["changes"][0]["value"]["messages"][0].pop("id", None)
        payload_a["entry"][0]["changes"][0]["value"]["messages"][0]["context"] = {"id": "ctx-a"}

        payload_b = _meta_text_payload(body="hello there", timestamp="1700000009")
        payload_b["entry"][0]["changes"][0]["value"]["messages"][0].pop("id", None)
        payload_b["entry"][0]["changes"][0]["value"]["messages"][0]["context"] = {"id": "ctx-b"}

        result_a = normalize_inbound_message(payload_a)
        result_b = normalize_inbound_message(payload_b)

        self.assertIsNotNone(result_a)
        self.assertIsNotNone(result_b)
        self.assertNotEqual(result_a["event_id"], result_b["event_id"])

    def test_backward_compatible_aliases_present(self):
        """AC1: wa_id and text aliases are present for existing callers."""
        from app.utils.whatsapp_utils import normalize_inbound_message

        result = normalize_inbound_message(_meta_text_payload(wa_id="15551234567", body="Hello"))
        self.assertEqual(result["wa_id"], result["user_id"])
        self.assertEqual(result["text"], result["message_text"])

    def test_status_update_returns_status_update_flag(self):
        """AC2: Meta status update payload returns status_update=True."""
        from app.utils.whatsapp_utils import normalize_inbound_message

        result = normalize_inbound_message(_meta_status_payload())
        self.assertIsNotNone(result)
        self.assertTrue(result.get("status_update"))

    def test_image_message_returns_unsupported(self):
        """AC2: non-text message type returns unsupported=True, not a crash."""
        from app.utils.whatsapp_utils import normalize_inbound_message

        result = normalize_inbound_message(_meta_non_text_payload("image"))
        self.assertIsNotNone(result)
        self.assertTrue(result["unsupported"])
        self.assertEqual(result["unsupported_reason"], "non_text_message")

    def test_audio_message_returns_unsupported(self):
        """AC2: audio message type returns unsupported."""
        from app.utils.whatsapp_utils import normalize_inbound_message

        result = normalize_inbound_message(_meta_non_text_payload("audio"))
        self.assertIsNotNone(result)
        self.assertTrue(result["unsupported"])

    def test_none_body_returns_none(self):
        """AC2: None payload returns None without raising."""
        from app.utils.whatsapp_utils import normalize_inbound_message

        self.assertIsNone(normalize_inbound_message(None))

    def test_empty_dict_returns_none(self):
        """AC2: empty dict payload returns None without raising."""
        from app.utils.whatsapp_utils import normalize_inbound_message

        self.assertIsNone(normalize_inbound_message({}))

    def test_missing_contacts_returns_none(self):
        """AC2: payload without contacts does not crash, returns None."""
        from app.utils.whatsapp_utils import normalize_inbound_message

        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "id": "x",
                                        "type": "text",
                                        "text": {"body": "Hi"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ],
        }
        result = normalize_inbound_message(payload)
        self.assertIsNone(result)

    def test_whitespace_only_body_returns_unsupported(self):
        """AC2: message with whitespace-only text body returns unsupported."""
        from app.utils.whatsapp_utils import normalize_inbound_message

        payload = _meta_text_payload(body="   ")
        result = normalize_inbound_message(payload)
        self.assertIsNotNone(result)
        self.assertTrue(result["unsupported"])

    def test_missing_timestamp_uses_safe_fallback(self):
        """AC1: missing timestamp does not crash; a fallback value is returned."""
        from app.utils.whatsapp_utils import normalize_inbound_message

        payload = _meta_text_payload(body="Hello")
        payload["entry"][0]["changes"][0]["value"]["messages"][0].pop("timestamp", None)
        result = normalize_inbound_message(payload)
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.get("timestamp"))


class InstagramInboundNormalizationTests(unittest.TestCase):
    """normalize_inbound_message() for Instagram Meta payloads."""

    def setUp(self):
        self._env = patch.dict(os.environ, _BASE_ENV, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_text_message_produces_canonical_fields(self):
        from app.utils.whatsapp_utils import normalize_inbound_message

        result = normalize_inbound_message(
            _instagram_text_payload(sender_id="17841400008460056", body="Hi from IG")
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["provider"], "meta")
        self.assertEqual(result["channel"], "instagram")
        self.assertEqual(result["user_id"], "17841400008460056")
        self.assertEqual(result["message_text"], "Hi from IG")
        self.assertEqual(result["recipient_id"], "17841400008460056")
        self.assertEqual(result["instagram_recipient_id"], "17841400008460056")
        self.assertEqual(result["message_id"], "ig-mid-001")
        self.assertFalse(result["unsupported"])
        self.assertFalse(result["status_update"])

    def test_echo_payload_returns_status_update(self):
        from app.utils.whatsapp_utils import normalize_inbound_message

        payload = _instagram_text_payload()
        payload["entry"][0]["messaging"][0]["message"]["is_echo"] = True

        result = normalize_inbound_message(payload)

        self.assertIsNotNone(result)
        self.assertTrue(result["status_update"])
        self.assertEqual(result["channel"], "instagram")

    def test_non_text_payload_returns_unsupported(self):
        from app.utils.whatsapp_utils import normalize_inbound_message

        result = normalize_inbound_message(_instagram_non_text_payload())

        self.assertIsNotNone(result)
        self.assertTrue(result["unsupported"])
        self.assertEqual(result["unsupported_reason"], "non_text_message")


class MessengerInboundNormalizationTests(unittest.TestCase):
    """normalize_inbound_message() for Facebook Messenger Meta payloads."""

    def setUp(self):
        self._env = patch.dict(os.environ, _BASE_ENV, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_text_message_produces_canonical_fields(self):
        from app.utils.whatsapp_utils import normalize_inbound_message

        result = normalize_inbound_message(
            _messenger_text_payload(sender_id="1234567890123456", body="Hi from Messenger")
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["provider"], "meta")
        self.assertEqual(result["channel"], "messenger")
        self.assertEqual(result["user_id"], "1234567890123456")
        self.assertEqual(result["message_text"], "Hi from Messenger")
        self.assertEqual(result["recipient_id"], "1234567890123456")
        self.assertEqual(result["messenger_recipient_id"], "1234567890123456")
        self.assertEqual(result["message_id"], "m-mid-001")
        self.assertFalse(result["unsupported"])
        self.assertFalse(result["status_update"])

    def test_echo_payload_returns_status_update(self):
        from app.utils.whatsapp_utils import normalize_inbound_message

        payload = _messenger_text_payload()
        payload["entry"][0]["messaging"][0]["message"]["is_echo"] = True

        result = normalize_inbound_message(payload)

        self.assertIsNotNone(result)
        self.assertTrue(result["status_update"])
        self.assertEqual(result["channel"], "messenger")

    def test_non_text_payload_returns_unsupported(self):
        from app.utils.whatsapp_utils import normalize_inbound_message

        result = normalize_inbound_message(_messenger_non_text_payload())

        self.assertIsNotNone(result)
        self.assertTrue(result["unsupported"])
        self.assertEqual(result["unsupported_reason"], "non_text_message")


# ---------------------------------------------------------------------------
# Evolution inbound normalization
# ---------------------------------------------------------------------------

class EvolutionInboundNormalizationTests(unittest.TestCase):
    """normalize_inbound_message() for Evolution API payloads (AC1, AC2)."""

    def setUp(self):
        self._env = patch.dict(
            os.environ, {**_BASE_ENV, "WHATSAPP_PROVIDER": "evolution"}, clear=False
        )
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_text_conversation_produces_canonical_fields(self):
        """AC1: Evolution text message maps to user_id, message_text, message_id."""
        from app.utils.whatsapp_utils import normalize_inbound_message

        payload = _evolution_text_payload(
            wa_id="5511987654321@s.whatsapp.net",
            msg_id="evo-001",
            text="Hello Evo",
            name="Evo User",
        )
        result = normalize_inbound_message(payload)
        self.assertIsNotNone(result)
        self.assertEqual(result["message_text"], "Hello Evo")
        self.assertEqual(result["message_id"], "evo-001")
        self.assertEqual(result["event_id"], "msg:evolution:evo-001")
        self.assertEqual(result["dedupe_key"], result["event_id"])
        self.assertFalse(result["unsupported"])
        self.assertFalse(result["status_update"])

    def test_from_me_payload_returns_status_update(self):
        """AC2: fromMe=True is treated as outbound, not inbound user message."""
        from app.utils.whatsapp_utils import normalize_inbound_message

        result = normalize_inbound_message(_evolution_from_me_payload())
        self.assertIsNotNone(result)
        self.assertTrue(result.get("status_update"))

    def test_non_text_evolution_returns_unsupported(self):
        """AC2: Evolution image message returns unsupported."""
        from app.utils.whatsapp_utils import normalize_inbound_message

        result = normalize_inbound_message(_evolution_non_text_payload())
        self.assertIsNotNone(result)
        self.assertTrue(result["unsupported"])
        self.assertEqual(result["unsupported_reason"], "non_text_message")

    def test_extended_text_message_is_supported(self):
        """AC1: extendedTextMessage format is recognized and extracted."""
        from app.utils.whatsapp_utils import normalize_inbound_message

        payload = {
            "key": {
                "remoteJid": "5511987654321@s.whatsapp.net",
                "id": "evo-ext-001",
                "fromMe": False,
            },
            "message": {"extendedTextMessage": {"text": "Extended hello"}},
            "pushName": "Evo User",
            "messageTimestamp": "1700000001",
        }
        result = normalize_inbound_message(payload)
        self.assertIsNotNone(result)
        self.assertEqual(result["message_text"], "Extended hello")

    def test_wa_id_stripped_of_jid_suffix(self):
        """AC1: JID suffix (@s.whatsapp.net) is stripped from user_id."""
        from app.utils.whatsapp_utils import normalize_inbound_message

        payload = _evolution_text_payload(wa_id="5511987654321@s.whatsapp.net")
        result = normalize_inbound_message(payload)
        self.assertIsNotNone(result)
        self.assertNotIn("@", result["user_id"])


# ---------------------------------------------------------------------------
# Duplicate suppression
# ---------------------------------------------------------------------------

class DuplicateSuppressionTests(unittest.TestCase):
    """AC3: duplicate suppression via create_expiring_store() seam."""

    def setUp(self):
        self._env = patch.dict(os.environ, _BASE_ENV, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def _make_app(self):
        from app import create_app
        return create_app()

    def test_first_occurrence_of_message_id_is_not_duplicate(self):
        """AC3: first time a message_id is seen, not marked duplicate."""
        from app.services.expiring_store import ExpiringKeyStore

        store = ExpiringKeyStore(window_seconds=300)
        self.assertFalse(store.seen_recently("wamid-new-001"))

    def test_second_occurrence_of_same_id_is_duplicate(self):
        """AC3: repeated message_id within the window is suppressed."""
        from app.services.expiring_store import ExpiringKeyStore

        store = ExpiringKeyStore(window_seconds=300)
        store.seen_recently("wamid-dup-001")
        self.assertTrue(store.seen_recently("wamid-dup-001"))

    def test_different_message_ids_are_not_duplicates(self):
        """AC3: distinct message IDs are each processed once."""
        from app.services.expiring_store import ExpiringKeyStore

        store = ExpiringKeyStore(window_seconds=300)
        self.assertFalse(store.seen_recently("wamid-a"))
        self.assertFalse(store.seen_recently("wamid-b"))

    def test_empty_message_id_is_not_deduplicated(self):
        """AC3: missing/empty message_id short-circuits before duplicate check."""
        app = self._make_app()
        with app.app_context():
            from app.views import _is_duplicate_message

            self.assertFalse(_is_duplicate_message(None))
            self.assertFalse(_is_duplicate_message(""))

    def test_clear_resets_duplicate_tracking(self):
        """AC3: clear() allows a previously seen ID to be processed again."""
        from app.services.expiring_store import ExpiringKeyStore

        store = ExpiringKeyStore(window_seconds=300)
        store.seen_recently("wamid-clr-001")
        store.clear()
        self.assertFalse(store.seen_recently("wamid-clr-001"))

    def test_expired_entry_is_not_flagged_as_duplicate(self):
        """AC3: entries older than the window are purged and not flagged."""
        from app.services.expiring_store import ExpiringKeyStore

        # Use a mock clock to simulate time passage.
        clock = [0.0]
        store = ExpiringKeyStore(window_seconds=10, now_fn=lambda: clock[0])
        store.seen_recently("wamid-expire-001")
        clock[0] = 15.0  # advance past window
        self.assertFalse(store.seen_recently("wamid-expire-001"))


# ---------------------------------------------------------------------------
# Store factory backend selection and lifecycle
# ---------------------------------------------------------------------------

class StoreFactoryTests(unittest.TestCase):
    """AC4, AC5: create_expiring_store() backend selection, fallback, and close()."""

    def setUp(self):
        self._env = patch.dict(os.environ, _BASE_ENV, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def _make_app(self, extra_config=None):
        from app import create_app

        app = create_app()
        if extra_config:
            app.config.update(extra_config)
        return app

    def test_default_backend_creates_memory_store(self):
        """AC4: no STATE_STORE_BACKEND → ExpiringKeyStore (in-memory)."""
        from app.services.expiring_store import ExpiringKeyStore, create_expiring_store

        app = self._make_app()
        with app.app_context():
            store = create_expiring_store(
                app=app,
                extension_key="test_mem_001",
                namespace="test",
                window_seconds=60,
            )
        self.assertIsInstance(store, ExpiringKeyStore)

    def test_sqlite_backend_creates_sqlite_store(self):
        """AC4: STATE_STORE_BACKEND=sqlite → SQLiteExpiringKeyStore."""
        import tempfile
        import os as _os
        from app.services.expiring_store import SQLiteExpiringKeyStore, create_expiring_store

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _os.path.join(tmpdir, "test.db")
            app = self._make_app(
                {
                    "STATE_STORE_BACKEND": "sqlite",
                    "STATE_STORE_SQLITE_PATH": db_path,
                }
            )
            with app.app_context():
                store = create_expiring_store(
                    app=app,
                    extension_key="test_sqlite_001",
                    namespace="test",
                    window_seconds=60,
                )
            self.assertIsInstance(store, SQLiteExpiringKeyStore)
            store.close()

    def test_sqlite_bad_path_falls_back_to_memory(self):
        """AC4: sqlite init on invalid path + FALLBACK_TO_MEMORY=True → in-memory.

        Uses an existing regular file as the parent-directory component of the
        db path, which SQLite cannot open on any platform regardless of whether
        the directory exists.
        """
        import tempfile

        from app.services.expiring_store import ExpiringKeyStore, create_expiring_store

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            # tmp.name is a real file; treating it as a directory must always fail
            bad_path = os.path.join(tmp.name, "runtime_state.db")

        app = self._make_app(
            {
                "STATE_STORE_BACKEND": "sqlite",
                "STATE_STORE_SQLITE_PATH": bad_path,
                "STATE_STORE_FALLBACK_TO_MEMORY": True,
            }
        )
        with app.app_context():
            store = create_expiring_store(
                app=app,
                extension_key="test_fallback_001",
                namespace="test",
                window_seconds=60,
            )
        self.assertIsInstance(store, ExpiringKeyStore)

    def test_same_extension_key_returns_same_instance(self):
        """AC4: create_expiring_store is idempotent for the same extension_key."""
        from app.services.expiring_store import create_expiring_store

        app = self._make_app()
        with app.app_context():
            store1 = create_expiring_store(
                app=app, extension_key="shared_key", namespace="ns", window_seconds=60
            )
            store2 = create_expiring_store(
                app=app, extension_key="shared_key", namespace="ns", window_seconds=60
            )
        self.assertIs(store1, store2)

    def test_memory_store_close_is_a_no_op(self):
        """AC5: ExpiringKeyStore.close() completes without raising."""
        from app.services.expiring_store import ExpiringKeyStore

        store = ExpiringKeyStore(window_seconds=60)
        store.close()  # Must not raise

    def test_sqlite_store_close_releases_connection(self):
        """AC5: SQLiteExpiringKeyStore.close() is safe to call multiple times."""
        import tempfile
        import os as _os
        from app.services.expiring_store import SQLiteExpiringKeyStore

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _os.path.join(tmpdir, "lifecycle.db")
            store = SQLiteExpiringKeyStore(
                db_path=db_path, namespace="test", window_seconds=60
            )
            store.close()
            store.close()  # Second call must not raise


if __name__ == "__main__":
    unittest.main()
