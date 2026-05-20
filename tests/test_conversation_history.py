from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.models import ConversationMessage, ConversationSummary, Tenant
from app.saas_db import SaaSDatabase
from app.services.conversation_history import record_conversation_exchange
from app.views_dashboard import ROLE_OPERATOR, SESSION_ROLE_KEY


CONVERSATION_SEARCH_MAX_DATASET = 10000
CONVERSATION_SEARCH_MAX_SECONDS = 2.0


@pytest.fixture
def client():
    app = create_app(config_name="testing")
    app.config["DATABASE_URL"] = "sqlite:///:memory:"

    saas_db = SaaSDatabase()
    saas_db.init_app(app)
    app.extensions["saas_db"] = saas_db
    saas_db.create_tables()

    with app.test_client() as client:
        with app.app_context():
            yield client


def _db_session(client):
    saas_db = client.application.extensions["saas_db"]
    return saas_db.session()


def _ensure_tenant(db_session, tenant_id: str):
    row = db_session.query(Tenant).filter(Tenant.id == tenant_id).one_or_none()
    if row is None:
        db_session.add(Tenant(id=tenant_id, name=f"tenant-{tenant_id}"))


def _set_operator_role(client):
    with client.session_transaction() as sess:
        sess[SESSION_ROLE_KEY] = ROLE_OPERATOR


def test_list_conversations_supports_filters_and_pagination(client):
    _set_operator_role(client)

    sess = _db_session(client)
    try:
        _ensure_tenant(sess, "tenant-a")
        _ensure_tenant(sess, "tenant-b")
        base = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)

        sess.add_all(
            [
                ConversationSummary(
                    id="conv-a1",
                    tenant_id="tenant-a",
                    conversation_key="conv-a1",
                    wa_id="1111111111",
                    message_count=3,
                    escalation_flag=False,
                    latest_timestamp=base,
                ),
                ConversationSummary(
                    id="conv-a2",
                    tenant_id="tenant-a",
                    conversation_key="conv-a2",
                    wa_id="2222222222",
                    message_count=2,
                    escalation_flag=True,
                    latest_timestamp=base + timedelta(days=1),
                ),
                ConversationSummary(
                    id="conv-b1",
                    tenant_id="tenant-b",
                    conversation_key="conv-b1",
                    wa_id="1111111111",
                    message_count=7,
                    escalation_flag=False,
                    latest_timestamp=base + timedelta(days=1),
                ),
            ]
        )
        sess.commit()
    finally:
        sess.close()

    with patch(
        "app.views_dashboard.current_identity",
        return_value=SimpleNamespace(tenant_id="tenant-a", user_id="op-1"),
    ):
        response = client.get(
            "/api/conversations?wa_id=2222222222&start_date=2026-05-16&end_date=2026-05-16&page=1&per_page=10"
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["total"] == 1
    assert payload["page"] == 1
    assert payload["per_page"] == 10
    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == "conv-a2"


def test_get_conversation_detail_is_chronological_and_tenant_scoped(client):
    _set_operator_role(client)

    sess = _db_session(client)
    try:
        _ensure_tenant(sess, "tenant-a")
        convo = ConversationSummary(
            id="conv-a1",
            tenant_id="tenant-a",
            conversation_key="conv-a1",
            wa_id="1111111111",
            message_count=2,
            escalation_flag=False,
            latest_timestamp=datetime(2026, 5, 15, 12, 30, tzinfo=timezone.utc),
        )
        sess.add(convo)
        sess.add_all(
            [
                ConversationMessage(
                    id="msg-2",
                    tenant_id="tenant-a",
                    conversation_summary_id="conv-a1",
                    conversation_key="conv-a1",
                    wa_id="1111111111",
                    sender="assistant",
                    text_body="Reply",
                    timestamp=datetime(2026, 5, 15, 12, 30, tzinfo=timezone.utc),
                    delivery_status="delivered",
                ),
                ConversationMessage(
                    id="msg-1",
                    tenant_id="tenant-a",
                    conversation_summary_id="conv-a1",
                    conversation_key="conv-a1",
                    wa_id="1111111111",
                    sender="user",
                    text_body="Hi",
                    timestamp=datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc),
                    delivery_status="received",
                ),
            ]
        )
        sess.commit()
    finally:
        sess.close()

    with patch(
        "app.views_dashboard.current_identity",
        return_value=SimpleNamespace(tenant_id="tenant-a", user_id="op-1"),
    ):
        response = client.get("/api/conversations/conv-a1")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["conversation"]["id"] == "conv-a1"
    assert [row["id"] for row in payload["conversation"]["messages"]] == ["msg-1", "msg-2"]

    with patch(
        "app.views_dashboard.current_identity",
        return_value=SimpleNamespace(tenant_id="tenant-b", user_id="op-2"),
    ):
        forbidden_tenant = client.get("/api/conversations/conv-a1")
    assert forbidden_tenant.status_code == 404


def test_conversations_api_requires_operator_role(client):
    with patch(
        "app.views_dashboard.current_identity",
        return_value=SimpleNamespace(tenant_id="tenant-a", user_id="op-1"),
    ):
        response = client.get("/api/conversations")
    assert response.status_code == 403
    payload = response.get_json()
    assert payload["ok"] is False


def test_conversations_api_requires_authenticated_identity(client):
    _set_operator_role(client)
    with patch("app.views_dashboard.current_identity", return_value=None):
        response = client.get("/api/conversations")
    assert response.status_code == 401
    payload = response.get_json()
    assert payload["ok"] is False


def test_conversation_endpoints_are_read_only(client):
    _set_operator_role(client)
    with patch(
        "app.views_dashboard.current_identity",
        return_value=SimpleNamespace(tenant_id="tenant-a", user_id="op-1"),
    ):
        post_response = client.post("/api/conversations")
        delete_response = client.delete("/api/conversations/conv-a1")

    assert post_response.status_code == 405
    assert delete_response.status_code == 405


def test_record_conversation_exchange_persists_inbound_and_outbound_messages(client):
    sess = _db_session(client)
    try:
        _ensure_tenant(sess, "tenant-a")
        sess.commit()
    finally:
        sess.close()

    persisted = record_conversation_exchange(
        client.application,
        tenant_id="tenant-a",
        wa_id="1234567890",
        conversation_id="conv-seed-1",
        correlation_id="corr-1",
        inbound_text="Need status update",
        outbound_text="Your order is on the way",
        outbound_status="delivered",
        escalation_flag=False,
    )
    assert persisted is True

    sess = _db_session(client)
    try:
        summary = (
            sess.query(ConversationSummary)
            .filter(
                ConversationSummary.tenant_id == "tenant-a",
                ConversationSummary.conversation_key == "conv-seed-1",
            )
            .one()
        )
        messages = (
            sess.query(ConversationMessage)
            .filter(ConversationMessage.conversation_summary_id == summary.id)
            .order_by(ConversationMessage.timestamp.asc())
            .all()
        )
        assert summary.message_count == 2
        assert [row.sender for row in messages] == ["user", "assistant"]
    finally:
        sess.close()


def test_list_conversations_search_meets_ac_12_2_3_threshold(client):
    _set_operator_role(client)
    target_index = 999
    target_wa_id = str(1000000000 + target_index)
    sess = _db_session(client)
    try:
        _ensure_tenant(sess, "tenant-a")
        base = datetime(2026, 5, 15, tzinfo=timezone.utc)
        rows = []
        for index in range(CONVERSATION_SEARCH_MAX_DATASET):
            rows.append(
                ConversationSummary(
                    id=f"conv-{index}",
                    tenant_id="tenant-a",
                    conversation_key=f"conv-{index}",
                    wa_id=str(1000000000 + index),
                    message_count=2,
                    escalation_flag=False,
                    latest_timestamp=base + timedelta(minutes=index),
                )
            )
        sess.bulk_save_objects(rows)
        sess.commit()
    finally:
        sess.close()

    with patch(
        "app.views_dashboard.current_identity",
        return_value=SimpleNamespace(tenant_id="tenant-a", user_id="op-1"),
    ):
        start = time.perf_counter()
        response = client.get(
            f"/api/conversations?wa_id={target_wa_id}&start_date=2026-05-15&end_date=2026-05-16&page=1&per_page=50"
        )
        elapsed = time.perf_counter() - start

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["total"] == 1
    assert payload["items"][0]["wa_id"] == target_wa_id
    assert elapsed <= CONVERSATION_SEARCH_MAX_SECONDS