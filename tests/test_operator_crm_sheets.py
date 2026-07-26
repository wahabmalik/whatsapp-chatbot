"""Operator CRM dual-sheet routes and functionality-aligned UI contracts."""

from __future__ import annotations

import unittest

from app import create_app
from app.services.operator_crm import build_channel_status, channel_is_configured


class OperatorCrmSheetTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(
            {
                "TESTING": True,
                "OPENAI_API_KEY": "openai-key",
                "ACCESS_TOKEN": "test-token",
                "APP_ID": "test-app",
                "APP_SECRET": "test-secret",
                "RECIPIENT_WAID": "10000000000",
                "VERSION": "v18.0",
                "PHONE_NUMBER_ID": "123",
                "VERIFY_TOKEN": "verify",
                "OUTBOUND_CHANNEL": "whatsapp",
                "CRM_EXPORT_ENABLED": False,
            }
        )
        self.client = self.app.test_client()

    def _operator(self):
        with self.client.session_transaction() as session:
            session["dashboard_role"] = "operator"

    def test_leads_sheet_renders_pipeline_and_demo_honesty(self):
        self._operator()
        response = self.client.get("/leads")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Leads Sheet", body)
        self.assertIn("Download sample CSV", body)
        self.assertIn("Discover", body)
        self.assertIn("Follow-up only", body)
        self.assertIn("Sheet 1", body)
        self.assertIn("Sample data", body)
        self.assertIn("View conversations", body)

    def test_leads_follow_up_filter(self):
        self._operator()
        response = self.client.get("/leads?filter=follow-up")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Follow-up", body)
        self.assertNotIn("Proposal looks good", body)

    def test_sales_sheet_renders_closed_book(self):
        self._operator()
        response = self.client.get("/sales")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Sales Sheet", body)
        self.assertIn("Download sample CSV", body)
        self.assertIn("Build what they want", body)
        self.assertIn("Sheet 2", body)
        self.assertIn("Sample data", body)

    def test_channels_lists_supported_and_coming_soon(self):
        self._operator()
        response = self.client.get("/channels")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        for label in ("WhatsApp", "Telegram", "Instagram", "Discord", "Slack", "Email"):
            self.assertIn(label, body)
        self.assertIn("Coming soon", body)
        self.assertIn("Configured", body)
        self.assertIn("Active outbound", body)
        self.assertTrue(("Connect" in body) or ("Configure" in body))

    def test_channel_status_uses_real_config(self):
        rows = build_channel_status(
            self.app.config,
            setup_url="/setup",
            onboarding_url="/onboarding",
        )
        whatsapp = next(row for row in rows if row["id"] == "whatsapp")
        telegram = next(row for row in rows if row["id"] == "telegram")
        discord = next(row for row in rows if row["id"] == "discord")
        self.assertEqual(whatsapp["status"], "active_outbound")
        self.assertEqual(telegram["status"], "not_connected")
        self.assertEqual(discord["status"], "coming_soon")
        self.assertTrue(channel_is_configured("whatsapp", self.app.config))
        self.assertFalse(channel_is_configured("telegram", self.app.config))

    def test_overview_has_crm_hero_without_agency_leftover(self):
        self._operator()
        response = self.client.get("/operator")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Built to close.", body)
        self.assertIn("Generate leads. Close deals.", body)
        self.assertIn("Closar", body)
        self.assertIn("Open Leads Sheet", body)
        self.assertIn("Open Sales Sheet", body)
        self.assertIn("Notification Center", body)
        self.assertIn("Sample CRM preview", body)
        self.assertIn("Conversations", body)
        self.assertIn("Messages processed", body)
        self.assertIn("Internal errors", body)
        self.assertNotIn("ELITE DIGITAL AGENCY", body)
        self.assertNotIn("Book a Free Consultation", body)

    def test_setup_is_read_only_for_lead_gen_and_keeps_webhook_checklist(self):
        self._operator()
        response = self.client.get("/setup")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Lead generation UI", body)
        self.assertIn("CRM export", body)
        self.assertIn("Read-only until persistence ships", body)
        self.assertIn("Channel &amp; webhook checklist", body)
        self.assertNotIn("Save lead gen settings", body)
        self.assertNotIn("data-leadgen-form", body)

    def test_billing_processing_mentions_stripe(self):
        from pathlib import Path

        html = Path("app/templates/billing_processing.html").read_text(encoding="utf-8")
        self.assertIn("Stripe", html)
        self.assertNotIn("Paddle", html)


if __name__ == "__main__":
    unittest.main()
