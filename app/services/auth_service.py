from __future__ import annotations

import hashlib
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from typing import Callable

import bcrypt

from app.models import BotConfig, ConnectionState, Tenant, UsageCounter, User
from app.models.base import utcnow


AUTH_SESSION_USER_KEY = "auth_user_id"
AUTH_SESSION_TENANT_KEY = "auth_tenant_id"
AUTH_SESSION_ROLE_KEY = "auth_user_role"
PASSWORD_RESET_TOKEN_TTL_MINUTES = 30


class AuthError(Exception):
    status_code = 400
    error_code = "AUTH_ERROR"
    message = "Authentication error."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        if message is not None:
            self.message = message


class ValidationError(AuthError):
    status_code = 422
    error_code = "VALIDATION_ERROR"
    message = "Submitted credentials are invalid."


class EmailTakenError(AuthError):
    status_code = 409
    error_code = "EMAIL_TAKEN"
    message = "An account with that email already exists."


class InvalidCredentialsError(AuthError):
    status_code = 401
    error_code = "INVALID_CREDENTIALS"
    message = "Email or password is incorrect."


class AccountDisabledError(AuthError):
    status_code = 403
    error_code = "ACCOUNT_DISABLED"
    message = "Account is disabled."


class InvalidResetTokenError(AuthError):
    status_code = 400
    error_code = "INVALID_TOKEN"
    message = "Password reset token is invalid."


class ResetTokenExpiredError(AuthError):
    status_code = 400
    error_code = "TOKEN_EXPIRED"
    message = "Password reset token has expired."


@dataclass(frozen=True)
class AuthIdentity:
    user_id: str
    tenant_id: str


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_signup_payload(email: str, password: str) -> tuple[str, str]:
    normalized_email = normalize_email(email)
    if not normalized_email or "@" not in normalized_email:
        raise ValidationError("A valid email address is required.")
    if not _is_strong_password(password):
        raise ValidationError(
            "Password must be at least 12 characters and include upper, lower, digit, and symbol."
        )
    return normalized_email, password


def _is_strong_password(password: str) -> bool:
    candidate = password or ""
    return (
        len(candidate) >= 12
        and re.search(r"[a-z]", candidate) is not None
        and re.search(r"[A-Z]", candidate) is not None
        and re.search(r"\d", candidate) is not None
        and re.search(r"[^A-Za-z0-9]", candidate) is not None
    )


def hash_password(password: str) -> str:
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_account(db, email: str, password: str) -> AuthIdentity:
    normalized_email, validated_password = validate_signup_payload(email, password)
    session = db.session()
    try:
        if session.query(User).filter(User.email == normalized_email).one_or_none() is not None:
            raise EmailTakenError()

        tenant = Tenant(name=_derive_tenant_name(normalized_email))
        session.add(tenant)
        session.flush()

        user = User(
            tenant_id=tenant.id,
            email=normalized_email,
            password_hash=hash_password(validated_password),
            is_admin=True,
        )
        session.add(user)
        session.add(BotConfig(tenant_id=tenant.id))
        session.add(
            UsageCounter(
                tenant_id=tenant.id,
                period_start=utcnow(),
                conversations_used=0,
                is_blocked=False,
            )
        )
        session.add(ConnectionState(tenant_id=tenant.id, status="disconnected"))
        session.flush()
        session.commit()

        return AuthIdentity(user_id=user.id, tenant_id=tenant.id)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def authenticate_account(db, email: str, password: str) -> AuthIdentity:
    normalized_email = normalize_email(email)
    session = db.session()
    try:
        user = session.query(User).filter(User.email == normalized_email).one_or_none()
        if user is None or not verify_password(password or "", user.password_hash):
            raise InvalidCredentialsError()

        tenant = session.query(Tenant).filter(Tenant.id == user.tenant_id).one_or_none()
        if tenant is None:
            raise InvalidCredentialsError()
        if not tenant.is_active:
            raise AccountDisabledError(tenant.disabled_reason or None)

        return AuthIdentity(user_id=user.id, tenant_id=user.tenant_id)
    finally:
        session.close()


def login_session(flask_session, identity: AuthIdentity) -> None:
    flask_session.clear()  # prevent session fixation: regenerate session state on privilege escalation
    flask_session[AUTH_SESSION_USER_KEY] = identity.user_id
    flask_session[AUTH_SESSION_TENANT_KEY] = identity.tenant_id


def logout_session(flask_session) -> None:
    flask_session.pop(AUTH_SESSION_USER_KEY, None)
    flask_session.pop(AUTH_SESSION_TENANT_KEY, None)


def current_identity(flask_session) -> AuthIdentity | None:
    user_id = flask_session.get(AUTH_SESSION_USER_KEY)
    tenant_id = flask_session.get(AUTH_SESSION_TENANT_KEY)
    if not user_id or not tenant_id:
        return None
    return AuthIdentity(user_id=user_id, tenant_id=tenant_id)


def _derive_tenant_name(email: str) -> str:
    local_part = email.split("@", 1)[0].strip()
    slug = re.sub(r"[^a-zA-Z0-9]+", " ", local_part).strip()
    return slug.title() or "Workspace"


def request_password_reset(
    db,
    email: str,
    send_reset_email: Callable[[str, str], None],
    *,
    ttl_minutes: int = PASSWORD_RESET_TOKEN_TTL_MINUTES,
) -> None:
    normalized_email = normalize_email(email)
    if not normalized_email or "@" not in normalized_email:
        return

    session = db.session()
    user_email: str | None = None
    reset_token: str | None = None
    try:
        user = session.query(User).filter(User.email == normalized_email).one_or_none()
        if user is None:
            return

        reset_token = secrets.token_urlsafe(48)
        user.reset_token = _hash_reset_token(reset_token)
        user.reset_token_expires = utcnow() + timedelta(minutes=max(ttl_minutes, 1))
        user_email = user.email
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    if user_email is None or reset_token is None:
        return

    try:
        send_reset_email(user_email, reset_token)
    except Exception as exc:  # noqa: BLE001
        logging.warning(
            "PASSWORD_RESET_EMAIL_DISPATCH_FAILED reason=%s",
            exc,
        )


def reset_password_with_token(db, token: str, password: str) -> None:
    if not token or not token.strip():
        raise InvalidResetTokenError()
    if not _is_strong_password(password):
        raise ValidationError(
            "Password must be at least 12 characters and include upper, lower, digit, and symbol."
        )

    token_hash = _hash_reset_token(token)
    now = _coerce_utc(utcnow())

    session = db.session()
    try:
        user = session.query(User).filter(User.reset_token == token_hash).one_or_none()
        if user is None:
            raise InvalidResetTokenError()

        expires_at = _coerce_utc(user.reset_token_expires)
        if expires_at is None or expires_at <= now:
            user.reset_token = None
            user.reset_token_expires = None
            session.commit()
            raise ResetTokenExpiredError()

        user.password_hash = hash_password(password)
        user.reset_token = None
        user.reset_token_expires = None
        session.commit()
    except AuthError:
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)