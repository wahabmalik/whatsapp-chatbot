from __future__ import annotations

import os
from unittest.mock import patch

import bcrypt
import pytest


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
def auth_app(tmp_path):
    db_path = tmp_path / "saas_auth.db"
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()

    env = {
        **_BASE_ENV,
        "DATABASE_URL": f"sqlite:///{db_path}",
        "SESSION_FILE_DIR": str(session_dir),
    }

    with patch.dict(os.environ, env, clear=True), patch("app.config.load_dotenv", return_value=None):
        from app import create_app

        app = create_app()
        app.config.update(TESTING=True)
        yield app


@pytest.fixture()
def client(auth_app):
    return auth_app.test_client()


def _csrf_headers(client, token: str = "auth-csrf-token") -> dict[str, str]:
    with client.session_transaction() as session:
        session["_csrf_token"] = token
    return {"X-CSRFToken": token}


def _session_values(client):
    with client.session_transaction() as session:
        return dict(session)


def _load_user_records(app):
    from app.models import BotConfig, ConnectionState, Tenant, UsageCounter, User

    db = app.extensions["saas_db"]
    session = db.session()
    try:
        return {
            "tenants": session.query(Tenant).all(),
            "users": session.query(User).all(),
            "bot_configs": session.query(BotConfig).all(),
            "usage_counters": session.query(UsageCounter).all(),
            "connection_states": session.query(ConnectionState).all(),
        }
    finally:
        session.close()


def test_signup_creates_tenant_and_user_atomically_and_logs_user_in(auth_app, client):
    response = client.post(
        "/auth/signup",
        data={"email": "owner@example.com", "password": "StrongPass123!"},
        headers=_csrf_headers(client),
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/billing/plans")

    data = _load_user_records(auth_app)
    assert len(data["tenants"]) == 1
    assert len(data["users"]) == 1
    assert len(data["bot_configs"]) == 1
    assert len(data["usage_counters"]) == 1
    assert len(data["connection_states"]) == 1

    user = data["users"][0]
    assert user.email == "owner@example.com"
    assert user.password_hash != "StrongPass123!"
    assert bcrypt.checkpw("StrongPass123!".encode("utf-8"), user.password_hash.encode("utf-8"))

    session_values = _session_values(client)
    assert session_values.get("auth_user_id") == user.id
    assert session_values.get("auth_tenant_id") == user.tenant_id


def test_signup_rejects_duplicate_email(auth_app, client):
    first = client.post(
        "/auth/signup",
        data={"email": "owner@example.com", "password": "StrongPass123!"},
        headers=_csrf_headers(client, "signup-first"),
    )
    assert first.status_code == 302

    second = client.post(
        "/auth/signup",
        data={"email": "owner@example.com", "password": "StrongPass456!"},
        headers=_csrf_headers(client, "signup-second"),
    )

    assert second.status_code == 409
    payload = second.get_json()
    assert payload["ok"] is False
    assert payload["error_code"] == "EMAIL_TAKEN"


def test_signup_rejects_weak_password_with_validation_error(client):
    response = client.post(
        "/auth/signup",
        data={"email": "owner@example.com", "password": "weak"},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 422
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_code"] == "VALIDATION_ERROR"


def test_login_creates_authenticated_session(auth_app, client):
    signup = client.post(
        "/auth/signup",
        data={"email": "owner@example.com", "password": "StrongPass123!"},
        headers=_csrf_headers(client, "signup-token"),
    )
    assert signup.status_code == 302

    client.post("/auth/logout", headers=_csrf_headers(client, "logout-token"))

    response = client.post(
        "/auth/login",
        data={"email": "owner@example.com", "password": "StrongPass123!"},
        headers=_csrf_headers(client, "login-token"),
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith(("/", "/billing/plans", "/admin/customers", "/dashboard"))

    session_values = _session_values(client)
    assert session_values.get("auth_user_id")
    assert session_values.get("auth_tenant_id")
    assert session_values.get("auth_user_role") in {"admin", "customer"}


def test_login_rejects_invalid_credentials(client):
    response = client.post(
        "/auth/login",
        data={"email": "missing@example.com", "password": "WrongPass123!"},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 401
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_code"] == "INVALID_CREDENTIALS"


def test_login_rejects_disabled_account(auth_app, client):
    signup = client.post(
        "/auth/signup",
        data={"email": "owner@example.com", "password": "StrongPass123!"},
        headers=_csrf_headers(client, "signup-token"),
    )
    assert signup.status_code == 302

    from app.models import Tenant

    db = auth_app.extensions["saas_db"]
    session = db.session()
    try:
        tenant = session.query(Tenant).one()
        tenant.is_active = False
        session.commit()
    finally:
        session.close()

    client.post("/auth/logout", headers=_csrf_headers(client, "logout-token"))

    response = client.post(
        "/auth/login",
        data={"email": "owner@example.com", "password": "StrongPass123!"},
        headers=_csrf_headers(client, "login-token"),
    )

    assert response.status_code == 403
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_code"] == "ACCOUNT_DISABLED"


def test_login_with_orphaned_tenant_fails_with_invalid_credentials(auth_app, client):
    signup = client.post(
        "/auth/signup",
        data={"email": "owner@example.com", "password": "StrongPass123!"},
        headers=_csrf_headers(client, "signup-orphan-tenant"),
    )
    assert signup.status_code == 302

    from app.models import User

    db = auth_app.extensions["saas_db"]
    session = db.session()
    try:
        user = session.query(User).filter(User.email == "owner@example.com").one()
        user.tenant_id = "00000000-0000-0000-0000-000000000000"
        session.commit()
    finally:
        session.close()

    client.post("/auth/logout", headers=_csrf_headers(client, "logout-orphan-tenant"))

    response = client.post(
        "/auth/login",
        data={"email": "owner@example.com", "password": "StrongPass123!"},
        headers=_csrf_headers(client, "login-orphan-tenant"),
    )

    assert response.status_code == 401
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_code"] == "INVALID_CREDENTIALS"


def test_logout_invalidates_session_and_protected_page_redirects_to_login(client):
    signup = client.post(
        "/auth/signup",
        data={"email": "owner@example.com", "password": "StrongPass123!"},
        headers=_csrf_headers(client, "signup-token"),
    )
    assert signup.status_code == 302

    protected_before = client.get("/billing/plans", follow_redirects=False)
    assert protected_before.status_code in (200, 302)
    if protected_before.status_code == 302:
        assert "/auth/login" not in protected_before.headers["Location"]

    logout = client.post("/auth/logout", headers=_csrf_headers(client, "logout-token"), follow_redirects=False)
    assert logout.status_code == 302
    assert logout.headers["Location"].endswith("/auth/login")

    session_values = _session_values(client)
    assert "auth_user_id" not in session_values
    assert "auth_tenant_id" not in session_values

    protected_after = client.get("/billing/plans", follow_redirects=False)
    assert protected_after.status_code == 302
    assert "/auth/login" in protected_after.headers["Location"]


def test_dashboard_topbar_shows_user_email_and_logout_when_authenticated(client):
    signup = client.post(
        "/auth/signup",
        data={"email": "owner@example.com", "password": "StrongPass123!"},
        headers=_csrf_headers(client, "signup-dashboard-topbar"),
    )
    assert signup.status_code == 302

    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "owner@example.com" in body
    assert 'action="/auth/logout"' in body
    assert 'name="csrf_token"' in body


def test_dashboard_topbar_shows_login_link_when_anonymous(client):
    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'href="/auth/login"' in body
    assert "Log in" in body
    assert 'action="/auth/logout"' not in body


@pytest.mark.parametrize("route,data", [
    ("/auth/signup", {"email": "owner@example.com", "password": "StrongPass123!"}),
    ("/auth/login", {"email": "owner@example.com", "password": "StrongPass123!"}),
    ("/auth/logout", {}),
    ("/auth/forgot-password", {"email": "owner@example.com"}),
    ("/auth/reset-password", {"token": "any-token", "password": "StrongPass123!"}),
])
def test_auth_post_routes_require_csrf_with_400(route, data, client):
    response = client.post(route, data=data)

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_code"] == "CSRF_INVALID"


def test_login_session_clears_pre_auth_session_data(auth_app, client):
    with client.session_transaction() as session:
        session["pre_auth_marker"] = "should-be-cleared"

    response = client.post(
        "/auth/signup",
        data={"email": "owner@example.com", "password": "StrongPass123!"},
        headers=_csrf_headers(client, "signup-session-clear"),
        follow_redirects=False,
    )

    assert response.status_code == 302
    session_values = _session_values(client)
    assert "pre_auth_marker" not in session_values
    assert session_values.get("auth_user_id")
    assert session_values.get("auth_tenant_id")


def test_login_with_next_param_uses_safe_relative_target(auth_app, client):
    signup = client.post(
        "/auth/signup",
        data={"email": "owner@example.com", "password": "StrongPass123!"},
        headers=_csrf_headers(client, "signup-next-target"),
    )
    assert signup.status_code == 302

    client.post("/auth/logout", headers=_csrf_headers(client, "logout-next-target"))

    response = client.post(
        "/auth/login?next=/onboarding",
        data={"email": "owner@example.com", "password": "StrongPass123!"},
        headers=_csrf_headers(client, "login-next-target"),
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/onboarding")


def test_login_with_next_auth_login_does_not_loop_back_to_signin(auth_app, client):
    signup = client.post(
        "/auth/signup",
        data={"email": "owner@example.com", "password": "StrongPass123!"},
        headers=_csrf_headers(client, "signup-no-loop-target"),
    )
    assert signup.status_code == 302

    client.post("/auth/logout", headers=_csrf_headers(client, "logout-no-loop-target"))

    response = client.post(
        "/auth/login?next=/auth/login",
        data={"email": "owner@example.com", "password": "StrongPass123!"},
        headers=_csrf_headers(client, "login-no-loop-target"),
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/billing/plans")


def test_login_with_next_auth_logout_does_not_loop_or_logout_immediately(auth_app, client):
    signup = client.post(
        "/auth/signup",
        data={"email": "owner@example.com", "password": "StrongPass123!"},
        headers=_csrf_headers(client, "signup-no-logout-loop-target"),
    )
    assert signup.status_code == 302

    client.post("/auth/logout", headers=_csrf_headers(client, "logout-no-logout-loop-target"))

    response = client.post(
        "/auth/login?next=/auth/logout",
        data={"email": "owner@example.com", "password": "StrongPass123!"},
        headers=_csrf_headers(client, "login-no-logout-loop-target"),
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/billing/plans")


def test_login_with_next_auth_signup_does_not_loop_back_to_signup(auth_app, client):
    signup = client.post(
        "/auth/signup",
        data={"email": "owner@example.com", "password": "StrongPass123!"},
        headers=_csrf_headers(client, "signup-no-signup-loop-target"),
    )
    assert signup.status_code == 302

    client.post("/auth/logout", headers=_csrf_headers(client, "logout-no-signup-loop-target"))

    response = client.post(
        "/auth/login?next=/auth/signup",
        data={"email": "owner@example.com", "password": "StrongPass123!"},
        headers=_csrf_headers(client, "login-no-signup-loop-target"),
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/billing/plans")


def test_login_with_next_auth_signup_trailing_slash_does_not_loop(auth_app, client):
    signup = client.post(
        "/auth/signup",
        data={"email": "owner@example.com", "password": "StrongPass123!"},
        headers=_csrf_headers(client, "signup-no-signup-slash-loop-target"),
    )
    assert signup.status_code == 302

    client.post("/auth/logout", headers=_csrf_headers(client, "logout-no-signup-slash-loop-target"))

    response = client.post(
        "/auth/login?next=/auth/signup/",
        data={"email": "owner@example.com", "password": "StrongPass123!"},
        headers=_csrf_headers(client, "login-no-signup-slash-loop-target"),
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/billing/plans")


def test_login_and_signup_pages_redirect_authenticated_user_to_post_login_target(client):
    signup = client.post(
        "/auth/signup",
        data={"email": "owner@example.com", "password": "StrongPass123!"},
        headers=_csrf_headers(client, "signup-auth-redirect"),
        follow_redirects=False,
    )
    assert signup.status_code == 302

    login_page = client.get("/auth/login", follow_redirects=False)
    signup_page = client.get("/auth/signup", follow_redirects=False)

    assert login_page.status_code == 302
    assert login_page.headers["Location"].endswith("/billing/plans")
    assert signup_page.status_code == 302
    assert signup_page.headers["Location"].endswith("/billing/plans")


@pytest.mark.parametrize(
    "route,data",
    [
        ("/auth/signup", {"email": "owner@example.com", "password": "StrongPass123!"}),
        ("/auth/login", {"email": "owner@example.com", "password": "StrongPass123!"}),
        ("/auth/forgot-password", {"email": "owner@example.com"}),
        ("/auth/reset-password", {"token": "any-token", "password": "StrongPass123!"}),
    ],
)
def test_auth_post_routes_return_503_when_saas_db_unavailable(auth_app, client, route, data):
    class _UnavailableDB:
        is_ready = False

    auth_app.extensions["saas_db"] = _UnavailableDB()

    response = client.post(route, data=data, headers=_csrf_headers(client, f"db-down-{route}"))

    assert response.status_code == 503
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_code"] == "SAAS_UNAVAILABLE"
