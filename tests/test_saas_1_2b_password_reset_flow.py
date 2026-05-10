from __future__ import annotations

import hashlib
import os
from datetime import timedelta, timezone
from unittest.mock import patch

import bcrypt
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
def auth_app(tmp_path):
    db_path = tmp_path / "saas_auth_reset.db"
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
        app.extensions["password_reset_outbox"] = []

        def dispatch(email: str, token: str, reset_url: str) -> None:
            app.extensions["password_reset_outbox"].append(
                {"email": email, "token": token, "reset_url": reset_url}
            )

        app.config["AUTH_PASSWORD_RESET_DISPATCH"] = dispatch
        yield app


@pytest.fixture()
def client(auth_app):
    return auth_app.test_client()


def _csrf_headers(client, token: str = "auth-csrf-token") -> dict[str, str]:
    with client.session_transaction() as session:
        session["_csrf_token"] = token
    return {"X-CSRFToken": token}


def _signup(client) -> None:
    response = client.post(
        "/auth/signup",
        data={"email": "owner@example.com", "password": "StrongPass123!"},
        headers=_csrf_headers(client, "signup-token"),
    )
    assert response.status_code == 302


def _get_user(app):
    from app.models import User

    db = app.extensions["saas_db"]
    session = db.session()
    try:
        return session.query(User).one()
    finally:
        session.close()


def test_forgot_password_existing_user_sets_single_use_token_and_dispatches(auth_app, client):
    _signup(client)

    response = client.post(
        "/auth/forgot-password",
        data={"email": "owner@example.com"},
        headers=_csrf_headers(client, "forgot-token"),
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["data"]["message"] == "Reset email sent if account exists"

    outbox = auth_app.extensions["password_reset_outbox"]
    assert len(outbox) == 1
    sent = outbox[0]
    assert sent["email"] == "owner@example.com"
    assert sent["token"] in sent["reset_url"]

    user = _get_user(auth_app)
    assert user.reset_token
    assert user.reset_token == hashlib.sha256(sent["token"].encode("utf-8")).hexdigest()
    assert user.reset_token_expires is not None
    expires_at = user.reset_token_expires
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    assert expires_at > utcnow() + timedelta(minutes=20)


def test_forgot_password_unknown_email_still_returns_200_without_dispatch(auth_app, client):
    response = client.post(
        "/auth/forgot-password",
        data={"email": "missing@example.com"},
        headers=_csrf_headers(client, "forgot-unknown"),
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert auth_app.extensions["password_reset_outbox"] == []


def test_forgot_password_dispatch_failure_is_hidden_from_user(auth_app, client):
    _signup(client)

    def raise_dispatch(_email: str, _token: str, _reset_url: str) -> None:
        raise RuntimeError("smtp outage")

    auth_app.config["AUTH_PASSWORD_RESET_DISPATCH"] = raise_dispatch

    response = client.post(
        "/auth/forgot-password",
        data={"email": "owner@example.com"},
        headers=_csrf_headers(client, "forgot-fail"),
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True

    user = _get_user(auth_app)
    assert user.reset_token is not None
    assert user.reset_token_expires is not None


def test_reset_password_success_updates_hash_and_invalidates_token(auth_app, client):
    _signup(client)

    forgot = client.post(
        "/auth/forgot-password",
        data={"email": "owner@example.com"},
        headers=_csrf_headers(client, "forgot-valid"),
    )
    assert forgot.status_code == 200

    token = auth_app.extensions["password_reset_outbox"][0]["token"]

    reset = client.post(
        "/auth/reset-password",
        data={"token": token, "password": "NewStrongPass456!"},
        headers=_csrf_headers(client, "reset-valid"),
    )

    assert reset.status_code == 200
    payload = reset.get_json()
    assert payload["ok"] is True
    assert payload["data"]["redirect"].endswith("/auth/login")

    user = _get_user(auth_app)
    assert user.reset_token is None
    assert user.reset_token_expires is None
    assert bcrypt.checkpw("NewStrongPass456!".encode("utf-8"), user.password_hash.encode("utf-8"))

    old_login = client.post(
        "/auth/login",
        data={"email": "owner@example.com", "password": "StrongPass123!"},
        headers=_csrf_headers(client, "login-old"),
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/auth/login",
        data={"email": "owner@example.com", "password": "NewStrongPass456!"},
        headers=_csrf_headers(client, "login-new"),
    )
    assert new_login.status_code == 302


def test_reset_password_token_is_single_use(auth_app, client):
    _signup(client)

    forgot = client.post(
        "/auth/forgot-password",
        data={"email": "owner@example.com"},
        headers=_csrf_headers(client, "forgot-single-use"),
    )
    assert forgot.status_code == 200

    token = auth_app.extensions["password_reset_outbox"][0]["token"]

    first = client.post(
        "/auth/reset-password",
        data={"token": token, "password": "SingleUsePass123!"},
        headers=_csrf_headers(client, "reset-first"),
    )
    assert first.status_code == 200

    second = client.post(
        "/auth/reset-password",
        data={"token": token, "password": "AnotherPass123!"},
        headers=_csrf_headers(client, "reset-second"),
    )
    assert second.status_code == 400
    payload = second.get_json()
    assert payload["error_code"] == "INVALID_TOKEN"


def test_reset_password_rejects_expired_token(auth_app, client):
    _signup(client)

    forgot = client.post(
        "/auth/forgot-password",
        data={"email": "owner@example.com"},
        headers=_csrf_headers(client, "forgot-expired"),
    )
    assert forgot.status_code == 200

    token = auth_app.extensions["password_reset_outbox"][0]["token"]

    from app.models import User

    db = auth_app.extensions["saas_db"]
    session = db.session()
    try:
        user = session.query(User).one()
        user.reset_token_expires = utcnow() - timedelta(minutes=1)
        session.commit()
    finally:
        session.close()

    reset = client.post(
        "/auth/reset-password",
        data={"token": token, "password": "ExpiredPass123!"},
        headers=_csrf_headers(client, "reset-expired"),
    )

    assert reset.status_code == 400
    payload = reset.get_json()
    assert payload["error_code"] == "TOKEN_EXPIRED"

    user = _get_user(auth_app)
    assert user.reset_token is None
    assert user.reset_token_expires is None


def test_reset_password_rejects_weak_password(auth_app, client):
    _signup(client)

    forgot = client.post(
        "/auth/forgot-password",
        data={"email": "owner@example.com"},
        headers=_csrf_headers(client, "forgot-weak-pass"),
    )
    assert forgot.status_code == 200

    token = auth_app.extensions["password_reset_outbox"][0]["token"]

    reset = client.post(
        "/auth/reset-password",
        data={"token": token, "password": "weak"},
        headers=_csrf_headers(client, "reset-weak-pass"),
    )

    assert reset.status_code == 422
    payload = reset.get_json()
    assert payload["error_code"] == "VALIDATION_ERROR"

    user = _get_user(auth_app)
    assert user.reset_token is not None
    assert user.reset_token_expires is not None
