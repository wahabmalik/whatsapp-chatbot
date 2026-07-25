"""Operator CRM dual-sheet routes and template contracts."""

from __future__ import annotations

import unittest

from app import create_app


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
            }
        )
        self.client = self.app.test_client()

    def _operator(self):
        with self.client.session_transaction() as session:
            session["dashboard_role"] = "operator"

    def test_leads_sheet_renders_pipeline_and_empty_copy_contract(self):
        self._operator()
        response = self.client.get("/leads")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Leads Sheet", body)
        self.assertIn("Download Leads CSV", body)
        self.assertIn("Discover", body)
        self.assertIn("Follow-up only", body)
        self.assertIn("Sheet 1", body)

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
        self.assertIn("Download Sales CSV", body)
        self.assertIn("Build what they want", body)
        self.assertIn("Sheet 2", body)

    def test_channels_lists_supported_platforms(self):
        self._operator()
        response = self.client.get("/channels")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        for label in ("WhatsApp", "Telegram", "Instagram", "Discord", "Slack", "Email"):
            self.assertIn(label, body)

    def test_overview_has_crm_hero_and_sheet_ctas(self):
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

    def test_setup_includes_lead_gen_controls(self):
        self._operator()
        response = self.client.get("/setup")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Lead generation", body)
        self.assertIn("Service offering", body)
        self.assertIn("CRM export", body)


if __name__ == "__main__":
    unittest.main()
