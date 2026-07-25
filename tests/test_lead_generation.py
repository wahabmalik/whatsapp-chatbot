from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.lead_generation import (
    STAGE_BUILD_REQUEST,
    STAGE_CLOSED_WON,
    STAGE_FOLLOW_UP,
    detect_lead_intent,
    detect_sales_signals,
    extract_lead_fields,
    is_final_lead,
    is_lead_qualified,
    list_leads,
    mark_lead_stage,
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


def test_detect_sales_signals_for_follow_up_close_and_build():
    assert detect_sales_signals("please follow up tomorrow")["follow_up"] is True
    assert detect_sales_signals("let's proceed and start the project")["closed_won"] is True
    assert detect_sales_signals("can you build this custom software for me")["build_request"] is True


def test_pipeline_moves_to_final_closed_sale(tmp_path: Path):
    store = tmp_path / "leads.jsonl"
    app = MagicMock()
    app.config = {
        "LEAD_GEN_ENABLED": True,
        "LEAD_GEN_EXPORT_TO_CRM": False,
        "LEAD_STORE_PATH": str(store),
        "LEAD_STORE_MAX_LINES": 1000,
    }

    process_inbound_for_leads(
        app,
        message_text="I need a website. Reach me at client@example.com",
        user_id="user-close",
        channel="whatsapp",
        profile_name="Client",
    )
    final = process_inbound_for_leads(
        app,
        message_text="Let's proceed. Start the project.",
        user_id="user-close",
        channel="whatsapp",
        profile_name="Client",
    )

    assert final is not None
    assert final["stage"] == STAGE_CLOSED_WON
    assert final["outcome"] == "closed_sale"
    assert is_final_lead(final) is True


def test_pipeline_moves_to_build_request_final(tmp_path: Path):
    store = tmp_path / "leads.jsonl"
    app = MagicMock()
    app.config = {
        "LEAD_GEN_ENABLED": True,
        "LEAD_GEN_EXPORT_TO_CRM": False,
        "LEAD_STORE_PATH": str(store),
        "LEAD_STORE_MAX_LINES": 1000,
    }

    lead = process_inbound_for_leads(
        app,
        message_text="Please build me an app. My email is build@example.com",
        user_id="user-build",
        channel="discord",
        profile_name="Builder",
    )

    assert lead is not None
    assert lead["stage"] == STAGE_BUILD_REQUEST
    assert lead["outcome"] == "build_what_they_want"
    finals = list_leads(app, final_only=True)
    assert len(finals) == 1
    assert finals[0]["user_id"] == "user-build"


def test_follow_up_stage_detected(tmp_path: Path):
    store = tmp_path / "leads.jsonl"
    app = MagicMock()
    app.config = {
        "LEAD_GEN_ENABLED": True,
        "LEAD_GEN_EXPORT_TO_CRM": False,
        "LEAD_STORE_PATH": str(store),
        "LEAD_STORE_MAX_LINES": 1000,
    }

    lead = process_inbound_for_leads(
        app,
        message_text="I want pricing. Follow up tomorrow please.",
        user_id="user-fu",
        channel="slack",
        profile_name="Sam",
    )
    assert lead is not None
    assert lead["stage"] == STAGE_FOLLOW_UP
    assert list_leads(app, follow_up_only=True)[0]["user_id"] == "user-fu"


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


def test_mark_lead_stage_operator_override(tmp_path: Path):
    store = tmp_path / "leads.jsonl"
    app = MagicMock()
    app.config = {
        "LEAD_GEN_ENABLED": True,
        "LEAD_STORE_PATH": str(store),
        "LEAD_STORE_MAX_LINES": 1000,
        "LEAD_GEN_EXPORT_TO_CRM": False,
    }
    upsert_lead(app, user_id="u9", channel="telegram", fields={"email": "u9@example.com", "interest": "bot"})
    lead = mark_lead_stage(app, user_id="u9", channel="telegram", stage="closed_won")
    assert lead is not None
    assert lead["stage"] == STAGE_CLOSED_WON
    assert lead["is_final"] is True


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
                "need_summary": "web app",
                "interest": "web app",
                "channel": "whatsapp",
                "stage": "closed_won",
                "outcome": "closed_sale",
                "qualified": True,
                "is_final": True,
                "message_count": 3,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "finalized_at": "2026-01-01T00:00:00+00:00",
                "last_message": "Need a web app",
            }
        ]
    )
    assert rows[0][0] == "lead_id"
    assert rows[1][1] == "Sam"
    assert rows[1][2] == "sam@example.com"
    assert rows[1][7] == "closed_won"
    assert rows[1][8] == "closed_sale"
