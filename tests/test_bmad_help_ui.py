"""BMAD Help catalog UI contracts."""

from __future__ import annotations

import unittest

from app import create_app
from app.services.bmad_help import load_bmad_help_catalog


class BmadHelpUiTests(unittest.TestCase):
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
        with self.client.session_transaction() as session:
            session["dashboard_role"] = "operator"

    def test_catalog_loads_bmad_help_entry(self):
        catalog = load_bmad_help_catalog()
        self.assertTrue(catalog["available"])
        skills = {row["skill"] for row in catalog["entries"]}
        self.assertIn("bmad-help", skills)
        self.assertIn("bmad-create-prd", skills)
        codes = {row["menu_code"] for row in catalog["entries"]}
        self.assertIn("BH", codes)
        self.assertIn("CP", codes)

    def test_bmad_help_page_renders(self):
        response = self.client.get("/bmad-help")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("BMAD Help", body)
        self.assertIn("bmad-help", body)
        self.assertIn("Recommended next", body)
        self.assertIn("/bmad-help", body)

    def test_agents_page_links_to_bmad_help(self):
        response = self.client.get("/agents")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Open BMAD Help", body)
        self.assertIn("/bmad-help", body)


if __name__ == "__main__":
    unittest.main()
