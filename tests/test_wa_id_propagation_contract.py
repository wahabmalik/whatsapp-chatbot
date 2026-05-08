"""
Story 7.7 — wa_id End-to-End Propagation Contract Test

Verifies that the wa_id extracted from an inbound message by normalize_inbound_message()
propagates correctly as the `to` field in the outbound WhatsApp API call payload.
"""
import json
import os
import unittest
from unittest.mock import MagicMock, patch


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
    "FLASK_SECRET_KEY": "test-secret-key",
}


def _meta_text_payload(wa_id="15559876543", name="Propagation Test", body="ping"):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [
                                {"wa_id": wa_id, "profile": {"name": name}}
                            ],
                            "messages": [
                                {
                                    "id": "wamid.propagation001",
                                    "type": "text",
                                    "text": {"body": body},
                                    "timestamp": "1700000001",
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


class WaIdPropagationContractTests(unittest.TestCase):
    """
    Contract: wa_id from inbound normalization must equal the `to` field
    in the outbound WhatsApp API request payload.
    """

    def _make_app(self, extra_config=None):
        from app import create_app

        env = dict(_BASE_ENV)
        if extra_config:
            env.update(extra_config)
        with patch.dict(os.environ, env, clear=False):
            app = create_app()
        return app

    def _fake_ok_response(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.text = '{"messages":[{"id":"wamid.out001"}]}'
        return mock_resp

    def test_outbound_to_field_matches_inbound_wa_id_meta(self):
        """For a Meta inbound payload, `to` in the outbound call equals the contact wa_id."""
        inbound_wa_id = "15559876543"
        payload = _meta_text_payload(wa_id=inbound_wa_id, body="hello")

        captured = {}

        def _capture_send(data, timeout):
            captured["data"] = json.loads(data) if isinstance(data, str) else data
            return self._fake_ok_response()

        app = self._make_app()
        with app.app_context():
            with patch("app.utils.whatsapp_utils._send_request", side_effect=_capture_send):
                with patch(
                    "app.utils.whatsapp_utils._default_ai_provider",
                    return_value="pong",
                ):
                    from app.utils.whatsapp_utils import process_whatsapp_message

                    process_whatsapp_message(payload, request_id="test-propagation")

        self.assertIn("data", captured, "No outbound send call was captured")
        self.assertEqual(
            captured["data"].get("to"),
            inbound_wa_id,
            f"Expected outbound `to` == {inbound_wa_id!r}, got {captured['data'].get('to')!r}",
        )

    def test_outbound_to_field_matches_inbound_wa_id_different_number(self):
        """Outbound `to` must track whatever wa_id arrives inbound, not a hardcoded value."""
        inbound_wa_id = "447911123456"
        payload = _meta_text_payload(wa_id=inbound_wa_id, body="hi there")

        captured = {}

        def _capture_send(data, timeout):
            captured["data"] = json.loads(data) if isinstance(data, str) else data
            return self._fake_ok_response()

        app = self._make_app()
        with app.app_context():
            with patch("app.utils.whatsapp_utils._send_request", side_effect=_capture_send):
                with patch(
                    "app.utils.whatsapp_utils._default_ai_provider",
                    return_value="reply",
                ):
                    from app.utils.whatsapp_utils import process_whatsapp_message

                    process_whatsapp_message(payload, request_id="test-propagation-2")

        self.assertIn("data", captured)
        self.assertEqual(captured["data"].get("to"), inbound_wa_id)

    def test_process_result_from_field_matches_inbound_wa_id(self):
        """`from` key in process_whatsapp_message result equals the inbound wa_id."""
        inbound_wa_id = "15559876543"
        payload = _meta_text_payload(wa_id=inbound_wa_id)

        def _ok_send(data, timeout):
            return self._fake_ok_response()

        app = self._make_app()
        with app.app_context():
            with patch("app.utils.whatsapp_utils._send_request", side_effect=_ok_send):
                with patch(
                    "app.utils.whatsapp_utils._default_ai_provider",
                    return_value="ack",
                ):
                    from app.utils.whatsapp_utils import process_whatsapp_message

                    result = process_whatsapp_message(payload, request_id="test-from")

        self.assertEqual(result.get("from"), inbound_wa_id)


if __name__ == "__main__":
    unittest.main()
