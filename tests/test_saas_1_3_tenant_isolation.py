from __future__ import annotations

import os
from datetime import timedelta, timezone

import pytest

from app.models.base import utcnow


_BASE_ENV = {
    "WHATSAPP_PROVIDER": "meta",
    "ACCESS_TOKEN": "token",
    "YOUR_PHONE_NUMBER": "15551234567",
    "APP_ID": "123456789",
    "APP_SECRET": "supersecret",
    "RECIPIENT_WAID": "15551234567",
    "VERSION": "v18.0",
    "PHONE_NUMBER_ID": "1234567890",
    "VERIFY_TOKEN": "verify-token",
    "OPENAI_API_KEY": "sk-test",
    "FLASK_SECRET_KEY": "test-secret-key",
}


@pytest.fixture()
def saas_app(tmp_path):
    db_path = tmp_path / "saas_story_1_3.db"
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()

    env = {
        **_BASE_ENV,
        "DATABASE_URL": f"sqlite:///{db_path}",
        "SESSION_FILE_DIR": str(session_dir),
    }

    original = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    try:
        from app import create_app

        app = create_app()
        app.config.update(TESTING=True)
        yield app
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture()
def client(saas_app):
    return saas_app.test_client()


def _csrf_headers(client, token: str) -> dict[str, str]:
    with client.session_transaction() as flask_session:
        flask_session["_csrf_token"] = token
    return {"X-CSRFToken": token}


def _signup(client, email: str, password: str = "StrongPass123!") -> None:
    response = client.post(
        "/auth/signup",
        data={"email": email, "password": password},
        headers=_csrf_headers(client, f"csrf-{email}"),
    )
    assert response.status_code == 302


def _logout(client) -> None:
    client.post("/auth/logout", headers=_csrf_headers(client, "csrf-logout"))


def _login(client, email: str, password: str = "StrongPass123!") -> None:
    response = client.post(
        "/auth/login",
        data={"email": email, "password": password},
        headers=_csrf_headers(client, f"csrf-login-{email}"),
    )
    assert response.status_code == 302


def _tenant_id_for_email(app, email: str) -> str:
    from app.models import User

    session = app.extensions["saas_db"].session()
    try:
        user = session.query(User).filter(User.email == email).one()
        return user.tenant_id
    finally:
        session.close()


def _seed_tenant_b_records(app, tenant_b: str) -> None:
    from app.models import BotConfig, ConnectionState, Subscription, UsageCounter

    session = app.extensions["saas_db"].session()
    try:
        config = session.query(BotConfig).filter(BotConfig.tenant_id == tenant_b).one()
        config.business_name = "Tenant B Co"
        config.ai_persona_prompt = "Tenant B persona"

        usage = session.query(UsageCounter).filter(UsageCounter.tenant_id == tenant_b).one()
        usage.conversations_used = 7
        usage.is_blocked = False

        connection = session.query(ConnectionState).filter(ConnectionState.tenant_id == tenant_b).one()
        connection.status = "connected"
        connection.evolution_instance = "tenant-b-instance"

        subscription = Subscription(
            tenant_id=tenant_b,
            stripe_customer_id="cus_b",
            stripe_subscription_id="sub_b",
            plan_key="starter",
            status="active",
            conversation_limit=2000,
            current_period_start=utcnow() - timedelta(days=1),
            current_period_end=utcnow() + timedelta(days=29),
        )
        session.add(subscription)
        session.commit()
    finally:
        session.close()


def test_repository_contract_denies_unscoped_tenant_context(saas_app):
    from app.repositories import BotConfigRepository

    with pytest.raises(ValueError, match="tenant_id is required"):
        BotConfigRepository(saas_app.extensions["saas_db"].session(), tenant_id=None)

    with pytest.raises(ValueError, match="tenant_id is required"):
        BotConfigRepository(saas_app.extensions["saas_db"].session(), tenant_id="   ")


def test_cross_tenant_repositories_do_not_read_or_modify_other_tenant_data(saas_app, client):
    from app.models import BotConfig, ConnectionState, Subscription, UsageCounter
    from app.repositories import (
        BotConfigRepository,
        ConnectionStateRepository,
        SubscriptionRepository,
        UsageCounterRepository,
    )

    _signup(client, "tenant-a@example.com")
    _logout(client)
    _signup(client, "tenant-b@example.com")

    tenant_a = _tenant_id_for_email(saas_app, "tenant-a@example.com")
    tenant_b = _tenant_id_for_email(saas_app, "tenant-b@example.com")

    _seed_tenant_b_records(saas_app, tenant_b)

    session = saas_app.extensions["saas_db"].session()
    try:
        a_bot_repo = BotConfigRepository(session, tenant_a)
        a_sub_repo = SubscriptionRepository(session, tenant_a)
        a_usage_repo = UsageCounterRepository(session, tenant_a)
        a_conn_repo = ConnectionStateRepository(session, tenant_a)

        b_config = session.query(BotConfig).filter(BotConfig.tenant_id == tenant_b).one()
        b_subscription = session.query(Subscription).filter(Subscription.tenant_id == tenant_b).one()
        b_usage = session.query(UsageCounter).filter(UsageCounter.tenant_id == tenant_b).one()
        b_connection = session.query(ConnectionState).filter(ConnectionState.tenant_id == tenant_b).one()

        assert a_bot_repo.get() is not None
        assert a_sub_repo.get() is None
        assert a_usage_repo.get() is not None
        assert a_conn_repo.get() is not None

        a_bot_repo.update(business_name="Tenant A Only")
        a_usage_repo.update_block_state(is_blocked=True)
        a_conn_repo.update_connection(status="disconnected", evolution_instance="tenant-a-instance")

        session.refresh(b_config)
        session.refresh(b_usage)
        session.refresh(b_connection)
        assert b_config.business_name == "Tenant B Co"
        assert b_usage.conversations_used == 7
        assert b_connection.evolution_instance == "tenant-b-instance"

        assert a_sub_repo.delete() == 0
        session.refresh(b_subscription)
        assert b_subscription.tenant_id == tenant_b
    finally:
        session.close()


def test_billing_plans_explicit_cross_tenant_request_is_denied(saas_app, client):
    _signup(client, "tenant-a@example.com")
    _logout(client)
    _signup(client, "tenant-b@example.com")
    _logout(client)

    _login(client, "tenant-a@example.com")

    tenant_b = _tenant_id_for_email(saas_app, "tenant-b@example.com")

    denied = client.get(f"/billing/plans?tenant_id={tenant_b}")
    assert denied.status_code == 404

    allowed = client.get("/billing/plans")
    assert allowed.status_code == 200
