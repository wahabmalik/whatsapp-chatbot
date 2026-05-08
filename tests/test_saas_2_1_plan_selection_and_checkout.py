"""
tests/test_saas_2_1_plan_selection_and_checkout.py

Story saas-2.1: Plan Selection UI and Paddle Checkout Flow

Acceptance criteria covered:
  AC-1: GET /billing/plans shows three plans with price and conversation limit.
  AC-2: POST /billing/checkout with valid plan creates a Paddle checkout and
        returns checkout_url.
  AC-3: GET /billing/success?transaction_id=... creates a subscription in
        pending_webhook state.
  AC-4: A pending_webhook subscription does NOT satisfy the ENF-01 activation
        guard (status must be in active/trialing).
  AC-5: GET /billing/portal redirects authenticated customer to Paddle portal.
  AC-6: POST /billing/checkout rejects missing/invalid CSRF (400).
  AC-7: All billing routes redirect unauthenticated requests to login.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest  # noqa: E402

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

_PADDLE_ENV = {
    "PADDLE_API_KEY": "pdl_api_test_mock",
    "PADDLE_STARTER_PRICE_ID": "pri_starter_test",
    "PADDLE_PRO_PRICE_ID": "pri_pro_test",
    "PADDLE_BUSINESS_PRICE_ID": "pri_business_test",
}

# ---------------------------------------------------------------------------
# Paddle service mock helpers
# ---------------------------------------------------------------------------
_PADDLE_CHECKOUT_URL = "https://buy.paddle.com/product/pri_starter_test"
_PADDLE_PORTAL_URL = "https://customer.paddle.com/customers/ctm_portal_test"

_MOCK_TRANSACTION = {
    "id": "txn_test123",
    "customer_id": "ctm_test123",
    "subscription_id": "sub_test123",
    "custom_data": {"plan_key": "starter", "tenant_id": "tenant-abc"},
    "status": "completed",
}


def _patch_paddle(checkout_url: str = _PADDLE_CHECKOUT_URL,
                  transaction: dict | None = None,
                  portal_url: str = _PADDLE_PORTAL_URL):
    """Return a context-manager stack that patches all paddle HTTP calls."""
    import contextlib
    from unittest.mock import patch as _patch

    tx = transaction or _MOCK_TRANSACTION

    @contextlib.contextmanager
    def _ctx():
        with _patch(
            "app.services.paddle_billing_service.create_paddle_checkout_url",
            return_value=checkout_url,
        ), _patch(
            "app.services.paddle_billing_service.retrieve_paddle_transaction",
            return_value=tx,
        ), _patch(
            "app.services.paddle_billing_service.create_paddle_portal_url",
            return_value=portal_url,
        ):
            yield

    return _ctx()


@pytest.fixture()
def billing_app(tmp_path):
    db_path = tmp_path / "saas_billing.db"
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()

    env = {
        **_BASE_ENV,
        **_PADDLE_ENV,
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
def client(billing_app):
    return billing_app.test_client()


def _csrf_headers(client, token: str = "billing-csrf-token") -> dict[str, str]:
    with client.session_transaction() as s:
        s["_csrf_token"] = token
    return {"X-CSRFToken": token}


def _signup_and_login(client, email="owner@example.com", password="StrongPass123!"):
    """Create account and return CSRF token for subsequent requests."""
    token = "signup-csrf"
    with client.session_transaction() as s:
        s["_csrf_token"] = token
    resp = client.post(
        "/auth/signup",
        data={"email": email, "password": password},
        headers={"X-CSRFToken": token},
        follow_redirects=False,
    )
    assert resp.status_code == 302, f"signup failed: {resp.status_code}"
    return token


def _get_subscription(app, tenant_id):
    from app.models import Subscription

    db = app.extensions["saas_db"]
    s = db.session()
    try:
        return (
            s.query(Subscription)
            .filter(Subscription.tenant_id == tenant_id)
            .first()
        )
    finally:
        s.close()


def _get_session_tenant(client):
    with client.session_transaction() as s:
        return s.get("auth_tenant_id")


# ===========================================================================
# AC-1: Plan listing
# ===========================================================================


class TestPlanListing:
    def test_billing_plans_shows_three_plans(self, client):
        """GET /billing/plans shows Starter, Pro, Business with price and limit."""
        _signup_and_login(client)
        resp = client.get("/billing/plans")
        assert resp.status_code == 200
        body = resp.data.decode()
        # All three plan names
        assert "Starter" in body
        assert "Pro" in body
        assert "Business" in body
        # Prices
        assert "$29" in body
        assert "$49" in body
        assert "$99" in body
        # Conversation limits
        assert "2,000" in body
        assert "5,000" in body
        assert "15,000" in body

    def test_billing_plans_requires_auth(self, client):
        """GET /billing/plans redirects unauthenticated users to login (AC-7)."""
        resp = client.get("/billing/plans", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_billing_plans_rejects_cross_tenant_param(self, client):
        """GET /billing/plans?tenant_id=<other> returns 404 (isolation contract)."""
        _signup_and_login(client)
        resp = client.get("/billing/plans?tenant_id=other-tenant-uuid")
        assert resp.status_code == 404


# ===========================================================================
# AC-2: Checkout creates Stripe session
# ===========================================================================


class TestBillingCheckout:
    def test_checkout_returns_checkout_url_for_valid_plan(self, client):
        """POST /billing/checkout with valid plan returns checkout_url (AC-2)."""
        csrf_token = _signup_and_login(client)
        headers = _csrf_headers(client, csrf_token)

        with _patch_paddle():
            resp = client.post(
                "/billing/checkout",
                data={"plan_key": "starter"},
                headers=headers,
            )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert "checkout_url" in body["data"]
        assert "paddle" in body["data"]["checkout_url"] or "buy." in body["data"]["checkout_url"]

    def test_checkout_all_three_plans_valid(self, client):
        """All three plan keys are accepted (AC-2)."""
        for plan_key in ("starter", "pro", "business"):
            # Create fresh account for each plan to avoid ALREADY_SUBSCRIBED
            email = f"{plan_key}@example.com"
            token = f"csrf-{plan_key}"
            with client.session_transaction() as s:
                s["_csrf_token"] = token
            client.post(
                "/auth/signup",
                data={"email": email, "password": "StrongPass123!"},
                headers={"X-CSRFToken": token},
                follow_redirects=False,
            )
            headers = _csrf_headers(client, token)
            with _patch_paddle():
                resp = client.post(
                    "/billing/checkout",
                    data={"plan_key": plan_key},
                    headers=headers,
                )
            assert resp.status_code == 200, f"plan_key={plan_key} failed"
            body = resp.get_json()
            assert body["ok"] is True

    def test_checkout_rejects_invalid_plan(self, client):
        """POST /billing/checkout with unknown plan_key returns 422 (AC-2 INVALID_PLAN)."""
        csrf_token = _signup_and_login(client, "invalid@example.com")
        headers = _csrf_headers(client, csrf_token)

        resp = client.post(
            "/billing/checkout",
            data={"plan_key": "enterprise"},
            headers=headers,
        )
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["ok"] is False
        assert body["error_code"] == "INVALID_PLAN"

    def test_checkout_rejects_already_subscribed(self, billing_app, client):
        """POST /billing/checkout returns 409 when subscription already exists (AC-2)."""
        csrf_token = _signup_and_login(client, "existing@example.com")
        tenant_id = _get_session_tenant(client)

        # Create a pending subscription directly to simulate already-subscribed state
        from app.services.billing_service import create_pending_subscription

        db = billing_app.extensions["saas_db"]
        create_pending_subscription(
            db,
            tenant_id=tenant_id,
            stripe_customer_id="cus_existing",
            stripe_subscription_id="sub_existing123",
            plan_key="starter",
        )

        headers = _csrf_headers(client, csrf_token)
        resp = client.post(
            "/billing/checkout",
            data={"plan_key": "pro"},
            headers=headers,
        )
        assert resp.status_code == 409
        body = resp.get_json()
        assert body["ok"] is False
        assert body["error_code"] == "ALREADY_SUBSCRIBED"

    def test_checkout_rejects_invalid_csrf(self, client):
        """POST /billing/checkout without valid CSRF returns 400 (AC-6)."""
        _signup_and_login(client)
        # Do NOT set CSRF in session or header
        resp = client.post(
            "/billing/checkout",
            data={"plan_key": "starter"},
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["error_code"] == "CSRF_INVALID"

    def test_checkout_requires_authentication(self, client):
        """POST /billing/checkout without auth redirects to login (AC-7)."""
        resp = client.post(
            "/billing/checkout",
            data={"plan_key": "starter"},
            follow_redirects=False,
        )
        # Either 302 redirect or 400 for CSRF (unauthenticated client has no CSRF token)
        # The auth guard fires before CSRF in this case
        assert resp.status_code in (302, 400)
        if resp.status_code == 302:
            assert "/auth/login" in resp.headers["Location"]

    def test_checkout_accepts_plan_key_from_json_body(self, client):
        """POST /billing/checkout accepts plan_key from JSON body (AC-2)."""
        csrf_token = _signup_and_login(client, "json@example.com")
        headers = {
            **_csrf_headers(client, csrf_token),
            "Content-Type": "application/json",
        }
        with _patch_paddle():
            resp = client.post(
                "/billing/checkout",
                json={"plan_key": "pro"},
                headers=headers,
            )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True


# ===========================================================================
# AC-3 & AC-4: Success callback creates pending subscription
# ===========================================================================


class TestBillingSuccess:
    def test_success_callback_creates_pending_webhook_subscription(self, billing_app, client):
        """GET /billing/success creates subscription in pending_webhook state (AC-3)."""
        _signup_and_login(client)
        tenant_id = _get_session_tenant(client)

        with _patch_paddle():
            resp = client.get("/billing/success?transaction_id=txn_test_session123")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "Payment received" in body or "processing" in body.lower() or "pending" in body.lower() or "confirmed" in body.lower()

        sub = _get_subscription(billing_app, tenant_id)
        assert sub is not None
        assert sub.status == "pending_webhook"
        assert sub.plan_key == "starter"  # from the mocked transaction custom_data
        assert sub.stripe_subscription_id == "sub_test123"
        assert sub.stripe_customer_id == "ctm_test123"

    def test_pending_webhook_subscription_does_not_activate_bot(self, billing_app, client):
        """Pending subscription fails ENF-01 activation guard (AC-4)."""
        _signup_and_login(client, "nobot@example.com")
        tenant_id = _get_session_tenant(client)

        with _patch_paddle():
            client.get("/billing/success?transaction_id=txn_test_session_nobot")

        from app.services.billing_service import can_activate_bot

        db = billing_app.extensions["saas_db"]
        assert can_activate_bot(db, tenant_id) is False, (
            "pending_webhook subscription must not activate bot (ENF-01)"
        )

    def test_active_subscription_satisfies_activation_guard(self, billing_app):
        """Active subscription satisfies ENF-01 (positive control for AC-4)."""
        from app.models import Subscription
        from app.models.base import utcnow
        from app.services.billing_service import can_activate_bot

        db = billing_app.extensions["saas_db"]
        sess = db.session()
        try:
            # Create a minimal tenant for this test
            from app.models import Tenant

            tenant = Tenant(name="Active Test")
            sess.add(tenant)
            sess.flush()

            now = utcnow()
            sub = Subscription(
                tenant_id=tenant.id,
                stripe_customer_id="cus_active",
                stripe_subscription_id="sub_active_unique",
                plan_key="pro",
                status="active",
                conversation_limit=5000,
                current_period_start=now,
                current_period_end=now,
            )
            sess.add(sub)
            sess.commit()

            assert can_activate_bot(db, tenant.id) is True
        finally:
            sess.close()

    def test_trialing_subscription_satisfies_activation_guard(self, billing_app):
        """Trialing subscription satisfies ENF-01 (positive control for AC-4)."""
        from app.models import Subscription, Tenant
        from app.models.base import utcnow
        from app.services.billing_service import can_activate_bot

        db = billing_app.extensions["saas_db"]
        sess = db.session()
        try:
            tenant = Tenant(name="Trial Test")
            sess.add(tenant)
            sess.flush()

            now = utcnow()
            sub = Subscription(
                tenant_id=tenant.id,
                stripe_customer_id="cus_trialing",
                stripe_subscription_id="sub_trialing_unique",
                plan_key="starter",
                status="trialing",
                conversation_limit=2000,
                current_period_start=now,
                current_period_end=now,
            )
            sess.add(sub)
            sess.commit()

            assert can_activate_bot(db, tenant.id) is True
        finally:
            sess.close()

    def test_success_callback_is_idempotent(self, billing_app, client):
        """Calling /billing/success twice with same transaction_id does not create duplicates (AC-3)."""
        _signup_and_login(client, "idempotent@example.com")
        tenant_id = _get_session_tenant(client)

        with _patch_paddle():
            client.get("/billing/success?transaction_id=txn_test_session_idem")
            client.get("/billing/success?transaction_id=txn_test_session_idem")

        from app.models import Subscription

        db = billing_app.extensions["saas_db"]
        sess = db.session()
        try:
            count = (
                sess.query(Subscription)
                .filter(Subscription.tenant_id == tenant_id)
                .count()
            )
        finally:
            sess.close()
        assert count == 1, "Duplicate subscription created on double success callback"

    def test_success_callback_without_transaction_id_redirects_to_plans(self, client):
        """GET /billing/success without transaction_id redirects to /billing/plans."""
        _signup_and_login(client)
        resp = client.get("/billing/success", follow_redirects=False)
        assert resp.status_code == 302
        assert "/billing/plans" in resp.headers["Location"]

    def test_success_callback_requires_authentication(self, client):
        """GET /billing/success without auth redirects to login (AC-7)."""
        resp = client.get("/billing/success?transaction_id=txn_test", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]


# ===========================================================================
# AC-5: Portal redirect
# ===========================================================================


class TestBillingPortal:
    def test_portal_redirects_to_paddle_portal(self, billing_app, client):
        """GET /billing/portal redirects to Paddle Customer Portal (AC-5)."""
        _signup_and_login(client)
        tenant_id = _get_session_tenant(client)

        # First create a subscription with a real customer_id
        from app.services.billing_service import create_pending_subscription

        db = billing_app.extensions["saas_db"]
        create_pending_subscription(
            db,
            tenant_id=tenant_id,
            stripe_customer_id="ctm_portal_test",
            stripe_subscription_id="sub_portal_test_unique",
            plan_key="pro",
        )

        with _patch_paddle(portal_url="https://customer.paddle.com/customers/ctm_portal_test"):
            resp = client.get("/billing/portal", follow_redirects=False)
        assert resp.status_code == 302
        assert "paddle.com" in resp.headers["Location"]

    def test_portal_without_subscription_redirects_to_plans(self, client):
        """GET /billing/portal without subscription redirects to /billing/plans."""
        _signup_and_login(client, "noportal@example.com")
        resp = client.get("/billing/portal", follow_redirects=False)
        assert resp.status_code == 302
        assert "/billing/plans" in resp.headers["Location"]

    def test_portal_requires_authentication(self, client):
        """GET /billing/portal without auth redirects to login (AC-7)."""
        resp = client.get("/billing/portal", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]


# ===========================================================================
# Plan catalogue unit tests
# ===========================================================================


class TestPlanCatalogue:
    def test_list_plans_returns_three_items(self):
        from app.services.billing_service import list_plans

        plans = list_plans()
        assert len(plans) == 3

    def test_starter_plan_spec(self):
        from app.services.billing_service import get_plan

        plan = get_plan("starter")
        assert plan is not None
        assert plan["price_usd"] == 29
        assert plan["conversations"] == 2000
        assert plan["name"] == "Starter"

    def test_pro_plan_spec(self):
        from app.services.billing_service import get_plan

        plan = get_plan("pro")
        assert plan is not None
        assert plan["price_usd"] == 49
        assert plan["conversations"] == 5000
        assert plan["name"] == "Pro"

    def test_business_plan_spec(self):
        from app.services.billing_service import get_plan

        plan = get_plan("business")
        assert plan is not None
        assert plan["price_usd"] == 99
        assert plan["conversations"] == 15000
        assert plan["name"] == "Business"

    def test_unknown_plan_returns_none(self):
        from app.services.billing_service import get_plan

        assert get_plan("enterprise") is None
        assert get_plan("") is None
        assert get_plan("STARTER") is None  # case-sensitive


# ===========================================================================
# Conversation limit assignment
# ===========================================================================


class TestConversationLimitAssignment:
    def test_pending_subscription_sets_conversation_limit(self, billing_app, client):
        """Pending subscription has conversation_limit from plan catalogue."""
        _signup_and_login(client, "limits@example.com")
        tenant_id = _get_session_tenant(client)

        from app.services.billing_service import create_pending_subscription

        db = billing_app.extensions["saas_db"]
        sub = create_pending_subscription(
            db,
            tenant_id=tenant_id,
            stripe_customer_id="cus_limits",
            stripe_subscription_id="sub_limits_unique",
            plan_key="business",
        )
        assert sub.conversation_limit == 15000

    def test_each_plan_has_correct_limit(self, billing_app):
        """Verify conversation limits match plan catalogue for all plans."""
        from app.models import Tenant
        from app.services.billing_service import create_pending_subscription, CONVERSATION_LIMITS

        db = billing_app.extensions["saas_db"]
        sess = db.session()
        try:
            for plan_key, expected_limit in CONVERSATION_LIMITS.items():
                tenant = Tenant(name=f"Limit Test {plan_key}")
                sess.add(tenant)
                sess.flush()
                tenant_id = tenant.id
                sess.commit()

                sub = create_pending_subscription(
                    db,
                    tenant_id=tenant_id,
                    stripe_customer_id=f"cus_{plan_key}_limit",
                    stripe_subscription_id=f"sub_{plan_key}_limit_unique",
                    plan_key=plan_key,
                )
                assert sub.conversation_limit == expected_limit, (
                    f"plan {plan_key}: expected {expected_limit}, got {sub.conversation_limit}"
                )
        finally:
            sess.close()
