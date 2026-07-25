from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.lead_generation import (
    detect_lead_intent,
    extract_lead_fields,
    is_lead_qualified,
    list_leads,
    process_inbound_for_leads,
    upsert_lead,
)


def test_detect_lead_intent_keywords():
    assert detect_lead_intent("I want a pricing quote") is True
    assert detect_lead_intent("hello there") is False


def test_extract_lead_fields_from_message():
    fields = extract_lead_fields(
        "Hi, my name is Ada Lovelace. Email me at ada@example.com or +1 555-123-4567. "
        "I'm interested in the pro plan.",
        profile_name="Ada",
    )
    assert fields["name"] == "Ada Lovelace"
    assert fields["email"] == "ada@example.com"
    assert "555" in fields["phone"]
    assert "pro plan" in fields["interest"].lower()


def test_is_lead_qualified_requires_contact_and_signal():
    assert is_lead_qualified({"email": "a@b.com", "interest": "demo"}) is True
    assert is_lead_qualified({"email": "a@b.com"}) is False
    assert is_lead_qualified({"interest": "demo"}) is False


def test_process_inbound_for_leads_persists_and_exports(tmp_path: Path):
    store = tmp_path / "leads.jsonl"
    app = MagicMock()
    app.config = {
        "LEAD_GEN_ENABLED": True,
        "LEAD_GEN_EXPORT_TO_CRM": True,
        "LEAD_STORE_PATH": str(store),
        "LEAD_STORE_MAX_LINES": 1000,
        "CRM_EXPORT_ENABLED": True,
        "CRM_EXPORT_WEBHOOK_URL": "https://crm.example.com/hook",
        "CRM_EXPORT_API_KEY": "secret",
        "CRM_EXPORT_TIMEOUT_SECONDS": 5.0,
    }

    with patch("app.services.lead_generation.export_analytics_event_to_crm", return_value=True) as export_mock:
        lead = process_inbound_for_leads(
            app,
            message_text="I want pricing. Reach me at lead@example.com",
            user_id="user-1",
            channel="whatsapp",
            profile_name="Sam",
            request_id="req-1",
        )

    assert lead is not None
    assert lead["qualified"] is True
    assert lead["email"] == "lead@example.com"
    assert export_mock.called
    assert store.exists()
    saved = [json.loads(line) for line in store.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert saved[0]["email"] == "lead@example.com"


def test_list_leads_returns_newest_first(tmp_path: Path):
    store = tmp_path / "leads.jsonl"
    app = MagicMock()
    app.config = {
        "LEAD_GEN_ENABLED": True,
        "LEAD_STORE_PATH": str(store),
        "LEAD_STORE_MAX_LINES": 1000,
        "LEAD_GEN_EXPORT_TO_CRM": False,
    }

    upsert_lead(app, user_id="u1", channel="discord", fields={"email": "one@example.com", "interest": "a"})
    upsert_lead(app, user_id="u2", channel="slack", fields={"email": "two@example.com", "interest": "b"})

    leads = list_leads(app, limit=10)
    assert len(leads) == 2
    assert leads[0]["user_id"] == "u2"


def test_process_inbound_disabled_returns_none(tmp_path: Path):
    app = MagicMock()
    app.config = {
        "LEAD_GEN_ENABLED": False,
        "LEAD_STORE_PATH": str(tmp_path / "leads.jsonl"),
    }
    assert process_inbound_for_leads(
        app,
        message_text="I want pricing. Reach me at lead@example.com",
        user_id="user-1",
        channel="email",
    ) is None


def test_leads_to_csv_rows_includes_header_and_values():
    from app.services.lead_generation import leads_to_csv_rows

    rows = leads_to_csv_rows(
        [
            {
                "lead_id": "whatsapp:1",
                "name": "Sam",
                "email": "sam@example.com",
                "phone": "",
                "interest": "web app",
                "channel": "whatsapp",
                "qualified": True,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "last_message": "Need a web app",
            }
        ]
    )
    assert rows[0][0] == "lead_id"
    assert rows[1][1] == "Sam"
    assert rows[1][2] == "sam@example.com"
    assert rows[1][6] == "yes"
