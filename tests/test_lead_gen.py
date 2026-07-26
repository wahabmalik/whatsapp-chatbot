from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.models import Lead, Tenant
from app.saas_db import SaaSDatabase
from app.services.lead_gen import (
    LeadGenValidationError,
    export_leads_csv,
    list_leads,
    normalize_usernames,
    scrape_and_store,
)
from app.views_dashboard import ROLE_OPERATOR, SESSION_ROLE_KEY


@pytest.fixture
def client():
    app = create_app(config_name="testing")
    app.config["DATABASE_URL"] = "sqlite:///:memory:"
    app.config["SCOUT_DELAY_MIN"] = 0
    app.config["SCOUT_DELAY_MAX"] = 0

    saas_db = SaaSDatabase()
    saas_db.init_app(app)
    app.extensions["saas_db"] = saas_db
    saas_db.create_tables()

    with app.test_client() as client:
        with app.app_context():
            yield client


def _db_session(client):
    return client.application.extensions["saas_db"].session()


def _ensure_tenant(db_session, tenant_id: str):
    row = db_session.query(Tenant).filter(Tenant.id == tenant_id).one_or_none()
    if row is None:
        db_session.add(Tenant(id=tenant_id, name=f"tenant-{tenant_id}"))
        db_session.commit()


def _set_operator_role(client):
    with client.session_transaction() as sess:
        sess[SESSION_ROLE_KEY] = ROLE_OPERATOR
        sess["_csrf_token"] = "test-csrf-token"


def test_normalize_usernames_strips_and_dedupes():
    assert normalize_usernames("@Alice\nalice\nbob, @Bob") == ["Alice", "bob"]


def test_scrape_and_store_persists_enriched_lead(client):
    db = client.application.extensions["saas_db"]
    sess = _db_session(client)
    try:
        _ensure_tenant(sess, "tenant-a")
    finally:
        sess.close()

    profile = {
        "username": "creator1",
        "full_name": "Creator One",
        "bio": "hello",
        "follower_count": 1200,
        "following_count": 10,
        "website": "https://example.com",
        "email": "",
        "phone": "",
        "platform": "instagram",
        "profile_url": "https://www.instagram.com/creator1/",
    }
    enriched = {
        **profile,
        "email": "creator1@example.com",
        "email_score": 80,
        "email_source": "bio",
        "email_verified": True,
        "lead_score": 72,
    }

    with patch("app.services.lead_gen.scrape_instagram", return_value=profile) as mocked_scrape, patch(
        "app.services.lead_gen.LeadEnricher"
    ) as mocked_enricher_cls, patch("app.services.lead_gen.random_delay"):
        mocked_enricher_cls.return_value.enrich_lead.return_value = enriched
        result = scrape_and_store(
            db,
            "tenant-a",
            "instagram",
            ["creator1"],
            enrich=True,
            app=client.application,
        )

    mocked_scrape.assert_called_once_with("creator1")
    assert result["stored"] == 1
    assert result["leads"][0]["email"] == "creator1@example.com"

    sess = _db_session(client)
    try:
        row = sess.query(Lead).filter(Lead.tenant_id == "tenant-a").one()
        assert row.username == "creator1"
        assert row.email == "creator1@example.com"
        assert row.lead_score == 72
        assert row.email_verified is True
    finally:
        sess.close()


def test_scrape_and_store_upserts_same_username(client):
    db = client.application.extensions["saas_db"]
    sess = _db_session(client)
    try:
        _ensure_tenant(sess, "tenant-a")
    finally:
        sess.close()

    first = {
        "username": "creator1",
        "full_name": "Old Name",
        "bio": "v1",
        "follower_count": 1,
        "platform": "github",
        "profile_url": "https://github.com/creator1",
        "email": "old@example.com",
    }
    second = {
        "username": "creator1",
        "full_name": "New Name",
        "bio": "v2",
        "follower_count": 99,
        "platform": "github",
        "profile_url": "https://github.com/creator1",
        "email": "new@example.com",
        "lead_score": 55,
    }

    with patch("app.services.lead_gen.scrape_github", side_effect=[first, second]), patch(
        "app.services.lead_gen.random_delay"
    ):
        scrape_and_store(db, "tenant-a", "github", ["creator1"], enrich=False, app=client.application)
        scrape_and_store(db, "tenant-a", "github", ["creator1"], enrich=False, app=client.application)

    sess = _db_session(client)
    try:
        rows = sess.query(Lead).filter(Lead.tenant_id == "tenant-a").all()
        assert len(rows) == 1
        assert rows[0].full_name == "New Name"
        assert rows[0].email == "new@example.com"
        assert rows[0].follower_count == 99
    finally:
        sess.close()


def test_list_and_export_are_tenant_scoped(client):
    db = client.application.extensions["saas_db"]
    sess = _db_session(client)
    try:
        _ensure_tenant(sess, "tenant-a")
        _ensure_tenant(sess, "tenant-b")
        sess.add_all(
            [
                Lead(
                    tenant_id="tenant-a",
                    platform="tiktok",
                    username="a1",
                    email="a1@example.com",
                    lead_score=40,
                ),
                Lead(
                    tenant_id="tenant-b",
                    platform="tiktok",
                    username="b1",
                    email="b1@example.com",
                    lead_score=90,
                ),
            ]
        )
        sess.commit()
    finally:
        sess.close()

    listed = list_leads(db, "tenant-a", platform="tiktok")
    assert listed["total"] == 1
    assert listed["items"][0]["username"] == "a1"

    csv_text = export_leads_csv(db, "tenant-a")
    assert "a1@example.com" in csv_text
    assert "b1@example.com" not in csv_text


def test_scrape_rejects_too_many_usernames(client):
    db = client.application.extensions["saas_db"]
    with pytest.raises(LeadGenValidationError):
        scrape_and_store(
            db,
            "tenant-a",
            "instagram",
            [f"user{i}" for i in range(11)],
            enrich=False,
            app=client.application,
        )


def test_leads_api_scrape_and_list(client):
    _set_operator_role(client)
    sess = _db_session(client)
    try:
        _ensure_tenant(sess, "tenant-a")
    finally:
        sess.close()

    profile = {
        "username": "creator1",
        "full_name": "Creator One",
        "bio": "bio",
        "follower_count": 10,
        "platform": "instagram",
        "profile_url": "https://www.instagram.com/creator1/",
        "email": "creator1@example.com",
        "lead_score": 61,
    }

    with patch(
        "app.lead_gen.routes.current_identity",
        return_value=SimpleNamespace(tenant_id="tenant-a", user_id="op-1"),
    ), patch("app.services.lead_gen.scrape_instagram", return_value=profile), patch(
        "app.services.lead_gen.random_delay"
    ):
        scrape_response = client.post(
            "/api/leads/scrape",
            json={"platform": "instagram", "usernames": "creator1", "enrich": False},
            headers={"X-CSRFToken": "test-csrf-token"},
        )
        list_response = client.get("/api/leads")

    assert scrape_response.status_code == 200
    scrape_payload = scrape_response.get_json()
    assert scrape_payload["ok"] is True
    assert scrape_payload["stored"] == 1

    assert list_response.status_code == 200
    list_payload = list_response.get_json()
    assert list_payload["ok"] is True
    assert list_payload["total"] == 1
    assert list_payload["items"][0]["username"] == "creator1"


def test_leads_page_requires_operator(client):
    response = client.get("/leads")
    assert response.status_code in {302, 401, 403}


def test_required_tables_include_leads():
    db = SaaSDatabase()
    assert "leads" in db.required_tables
