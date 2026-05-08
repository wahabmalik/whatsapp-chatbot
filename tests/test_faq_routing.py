import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from app.services import agent_registry
from app.utils.whatsapp_utils import process_whatsapp_message


class FaqRoutingTests(unittest.TestCase):
    def _inbound_body(self, wa_id: str, text: str) -> dict:
        return {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "contacts": [
                                    {
                                        "wa_id": wa_id,
                                        "profile": {"name": "Test User"},
                                    }
                                ],
                                "messages": [
                                    {
                                        "id": "wamid-1",
                                        "text": {"body": text},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ],
        }

    def _write_faq_file(self, payload: dict) -> str:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        faq_path = Path(temp_dir.name) / "user_faqs.json"
        faq_path.write_text(json.dumps(payload), encoding="utf-8")
        return str(faq_path)

    def _build_app(self, faq_path: str) -> Flask:
        app = Flask(__name__)
        app.config.update(
            {
                "ACCESS_TOKEN": "token",
                "VERSION": "v18.0",
                "PHONE_NUMBER_ID": "1234567890",
                "FAQ_STORE_PATH": faq_path,
            }
        )
        return app

    def test_user_specific_faq_answer_short_circuits_agent_generation(self):
        faq_path = self._write_faq_file(
            {
                "default": [
                    {
                        "questions": ["what are your hours"],
                        "answer": "Default support hours are 9 to 6.",
                    }
                ],
                "users": {
                    "15551230001": [
                        {
                            "questions": ["what are your hours"],
                            "answer": "Your dedicated support line is available 24/7.",
                        }
                    ]
                },
            }
        )
        app = self._build_app(faq_path)

        with app.app_context():
            with patch("app.utils.whatsapp_utils.get_selected_agent", return_value={"name": "Ops"}):
                with patch(
                    "app.utils.whatsapp_utils.send_message",
                    return_value={"status": "sent", "error": None},
                ) as mock_send:
                    with patch("app.utils.whatsapp_utils.generate_response") as mock_generate:
                        delivery = process_whatsapp_message(
                            self._inbound_body("15551230001", "What are your hours?"),
                            request_id="req-faq-1",
                        )

        self.assertEqual(delivery["response_source"], "faq")
        self.assertEqual(
            delivery["reply_text"],
            "Your dedicated support line is available 24/7.",
        )
        mock_generate.assert_not_called()

        outbound = json.loads(mock_send.call_args.args[0])
        self.assertEqual(outbound["text"]["body"], "Your dedicated support line is available 24/7.")

    def test_unique_question_falls_back_to_agent_generation(self):
        faq_path = self._write_faq_file(
            {
                "default": [
                    {
                        "questions": ["refund policy"],
                        "answer": "Refunds are available within 30 days.",
                    }
                ]
            }
        )
        app = self._build_app(faq_path)

        with app.app_context():
            with patch("app.utils.whatsapp_utils.get_selected_agent", return_value={"name": "Ops"}):
                with patch(
                    "app.utils.whatsapp_utils.send_message",
                    return_value={"status": "sent", "error": None},
                ):
                    with patch(
                        "app.utils.whatsapp_utils.generate_response",
                        return_value="[Ops] I WILL HELP WITH THAT UNIQUE QUESTION",
                    ) as mock_generate:
                        delivery = process_whatsapp_message(
                            self._inbound_body("15551230001", "Can I switch my delivery address now?"),
                            request_id="req-faq-2",
                        )

        self.assertEqual(delivery["response_source"], "agent")
        self.assertEqual(delivery["reply_text"], "[Ops] I WILL HELP WITH THAT UNIQUE QUESTION")
        mock_generate.assert_called_once()

    def test_agent_switch_applies_to_next_inbound_message(self):
        faq_path = self._write_faq_file({"default": []})
        app = self._build_app(faq_path)

        with app.app_context():
            with patch(
                "app.utils.whatsapp_utils.get_selected_agent",
                side_effect=[
                    {"name": "Nia"},
                    {"name": "Nia"},
                    {"name": "Amelia"},
                    {"name": "Amelia"},
                ],
            ):
                with patch(
                    "app.utils.whatsapp_utils.send_message",
                    return_value={"status": "sent", "error": None},
                ):
                    first = process_whatsapp_message(
                        self._inbound_body("15551230001", "first message"),
                        request_id="req-agent-switch-1",
                    )
                    second = process_whatsapp_message(
                        self._inbound_body("15551230001", "second message"),
                        request_id="req-agent-switch-2",
                    )

        self.assertEqual(first["reply_text"], "[Nia] FIRST MESSAGE")
        self.assertEqual(second["reply_text"], "[Amelia] SECOND MESSAGE")

    def test_agent_switch_applies_on_next_message_with_persisted_selection(self):
        faq_path = self._write_faq_file({"default": []})
        app = self._build_app(faq_path)

        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        selection_file = Path(temp_dir.name) / "data" / "agent_selection.json"

        original_selection_file = agent_registry.SELECTION_FILE
        agent_registry.SELECTION_FILE = selection_file
        self.addCleanup(setattr, agent_registry, "SELECTION_FILE", original_selection_file)

        available_agents = [
            {"code": "nia", "name": "Nia"},
            {"code": "amelia", "name": "Amelia"},
        ]

        with app.app_context():
            with patch("app.services.agent_registry.list_bmad_agents", return_value=available_agents):
                agent_registry.set_selected_agent_code("nia")
                with patch(
                    "app.utils.whatsapp_utils.send_message",
                    return_value={"status": "sent", "error": None},
                ):
                    first = process_whatsapp_message(
                        self._inbound_body("15551230001", "first message"),
                        request_id="req-runtime-switch-1",
                    )

                    agent_registry.set_selected_agent_code("amelia")
                    second = process_whatsapp_message(
                        self._inbound_body("15551230001", "second message"),
                        request_id="req-runtime-switch-2",
                    )

        self.assertEqual(first["reply_text"], "[Nia] FIRST MESSAGE")
        self.assertEqual(second["reply_text"], "[Amelia] SECOND MESSAGE")


if __name__ == "__main__":
    unittest.main()
