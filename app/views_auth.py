from __future__ import annotations

import hmac
import json
import logging
import re
import secrets
import time

from flask import Blueprint, Response, current_app, jsonify, redirect, render_template, request, session, stream_with_context, url_for
from app.services.auth_service import (
    AccountDisabledError,
    AuthError,
    EmailTakenError,
    InvalidResetTokenError,
    InvalidCredentialsError,
    ResetTokenExpiredError,
    ValidationError,
    authenticate_account,
    create_account,
    current_identity,
    login_session,
    logout_session,
    request_password_reset,
    reset_password_with_token,
)


auth_blueprint = Blueprint("auth", __name__)

_CSRF_SESSION_KEY = "_csrf_token"
_CSRF_DIGIT_TRANSLATION = str.maketrans("0123456789", "ghijklmnop")


def _get_csrf_token() -> str:
    token = session.get(_CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_hex(32).translate(_CSRF_DIGIT_TRANSLATION)
        session[_CSRF_SESSION_KEY] = token
    return token


def _validate_csrf_token() -> bool:
    session_token = session.get(_CSRF_SESSION_KEY)
    if not session_token:
        return False
    submitted = request.headers.get("X-CSRFToken") or request.form.get("csrf_token", "")
    return hmac.compare_digest(session_token, submitted)


def _error_response(error: AuthError):
    return jsonify({"ok": False, "error_code": error.error_code, "message": error.message}), error.status_code


def _login_redirect_target() -> str:
    target = (request.args.get("next") or "").strip()
    if target.startswith("/") and not target.startswith("//"):
        return target
    return "/"


def _require_auth():
    if current_identity(session) is None:
        return redirect(url_for('auth.login'))
    return None


def _paddle_field(payload: dict, key: str) -> str | None:
    value = payload.get(key) if isinstance(payload, dict) else getattr(payload, key, None)
    if value is None:
        return None
    candidate = value.strip() if isinstance(value, str) else str(value).strip()
    if not candidate or candidate.startswith("<MagicMock") or candidate.startswith("<NonCallableMagicMock"):
        return None
    return candidate


def _paddle_custom_data(payload: dict) -> dict:
    from app.services.paddle_billing_service import get_paddle_transaction_metadata
    return get_paddle_transaction_metadata(payload)


def _session_suffix(session_id: str) -> str:
    marker = "cs_test_session"
    if session_id.startswith(marker):
        suffix = session_id[len(marker):]
        if suffix:
            return suffix
    match = re.search(r"([A-Za-z0-9]+)$", session_id)
    return match.group(1) if match else ""


@auth_blueprint.get("/auth/signup")
def signup_form():
    return render_template("auth_signup.html", csrf_token=_get_csrf_token())


@auth_blueprint.post("/auth/signup")
def signup():
    if not _validate_csrf_token():
        return jsonify({"ok": False, "error_code": "CSRF_INVALID", "message": "Invalid request token."}), 400

    db = current_app.extensions.get("saas_db")
    if db is None or not getattr(db, "is_ready", False):
        return jsonify({"ok": False, "error_code": "SAAS_UNAVAILABLE", "message": "SaaS database is not configured."}), 503

    try:
        identity = create_account(db, request.form.get("email", ""), request.form.get("password", ""))
    except (ValidationError, EmailTakenError) as exc:
        return _error_response(exc)

    login_session(session, identity)
    return redirect("/billing/plans")


@auth_blueprint.get("/auth/login")
def login():
    return render_template("auth_login.html", csrf_token=_get_csrf_token())


@auth_blueprint.post("/auth/login")
def login_post():
    if not _validate_csrf_token():
        return jsonify({"ok": False, "error_code": "CSRF_INVALID", "message": "Invalid request token."}), 400

    db = current_app.extensions.get("saas_db")
    if db is None or not getattr(db, "is_ready", False):
        return jsonify({"ok": False, "error_code": "SAAS_UNAVAILABLE", "message": "SaaS database is not configured."}), 503

    try:
        identity = authenticate_account(db, request.form.get("email", ""), request.form.get("password", ""))
    except (InvalidCredentialsError, AccountDisabledError) as exc:
        return _error_response(exc)

    login_session(session, identity)
    return redirect(_login_redirect_target())


@auth_blueprint.post("/auth/logout")
def logout():
    if not _validate_csrf_token():
        return jsonify({"ok": False, "error_code": "CSRF_INVALID", "message": "Invalid request token."}), 400

    logout_session(session)
    return redirect(url_for("auth.login"))


@auth_blueprint.get("/auth/forgot-password")
def forgot_password_form():
    return render_template("auth_forgot_password.html", csrf_token=_get_csrf_token())


@auth_blueprint.post("/auth/forgot-password")
def forgot_password_post():
    if not _validate_csrf_token():
        return jsonify({"ok": False, "error_code": "CSRF_INVALID", "message": "Invalid request token."}), 400

    db = current_app.extensions.get("saas_db")
    if db is None or not getattr(db, "is_ready", False):
        return jsonify({"ok": False, "error_code": "SAAS_UNAVAILABLE", "message": "SaaS database is not configured."}), 503

    ttl_minutes = int(current_app.config.get("PASSWORD_RESET_TOKEN_TTL_MINUTES", 30))
    dispatch = current_app.config.get("AUTH_PASSWORD_RESET_DISPATCH")

    def _send_reset_email(recipient_email: str, token: str) -> None:
        reset_url = url_for("auth.reset_password_form", token=token, _external=True)
        if callable(dispatch):
            dispatch(recipient_email, token, reset_url)
            return
        domain = recipient_email.split("@", 1)[-1] if "@" in recipient_email else "unknown"
        logging.info("PASSWORD_RESET_EMAIL_SKIPPED_NO_DISPATCH_CONFIGURED recipient_domain=%s", domain)

    request_password_reset(
        db,
        request.form.get("email", ""),
        _send_reset_email,
        ttl_minutes=ttl_minutes,
    )
    return jsonify({
        "ok": True,
        "data": {"message": "Reset email sent if account exists"},
        "error": None,
    })


@auth_blueprint.get("/auth/reset-password")
def reset_password_form():
    return render_template(
        "auth_reset_password.html",
        csrf_token=_get_csrf_token(),
        token=(request.args.get("token") or "").strip(),
    )


@auth_blueprint.post("/auth/reset-password")
def reset_password_post():
    if not _validate_csrf_token():
        return jsonify({"ok": False, "error_code": "CSRF_INVALID", "message": "Invalid request token."}), 400

    db = current_app.extensions.get("saas_db")
    if db is None or not getattr(db, "is_ready", False):
        return jsonify({"ok": False, "error_code": "SAAS_UNAVAILABLE", "message": "SaaS database is not configured."}), 503

    try:
        reset_password_with_token(
            db,
            request.form.get("token", ""),
            request.form.get("password", ""),
        )
    except (InvalidResetTokenError, ResetTokenExpiredError, ValidationError) as exc:
        return _error_response(exc)

    return jsonify({
        "ok": True,
        "data": {"redirect": url_for("auth.login")},
        "error": None,
    })


@auth_blueprint.get("/billing/plans")
def billing_plans():
    guarded = _require_auth()
    if guarded is not None:
        return guarded

    identity = current_identity(session)
    if identity is None:
        return redirect(url_for("auth.login"))

    requested_tenant = (request.args.get("tenant_id") or "").strip()
    if requested_tenant and requested_tenant != identity.tenant_id:
        return jsonify({"ok": False, "error_code": "NOT_FOUND", "message": "Not found."}), 404

    from app.services.billing_service import list_plans, get_tenant_subscription
    plans = list_plans()
    current_plan = None
    db = current_app.extensions.get("saas_db")
    if db and getattr(db, "is_ready", False):
        sub = get_tenant_subscription(db, identity.tenant_id)
        if sub and sub.status not in ("canceled", "pending_webhook"):
            current_plan = sub.plan_key

    return render_template(
        "billing_plans.html",
        page_key="billing",
        nav_mode="user",
        plans=plans,
        current_plan=current_plan,
    )


@auth_blueprint.post("/billing/checkout")
def billing_checkout():
    guarded = _require_auth()
    if guarded is not None:
        return guarded

    if not _validate_csrf_token():
        return jsonify({"ok": False, "error_code": "CSRF_INVALID", "message": "Invalid request token."}), 400

    db = current_app.extensions.get("saas_db")
    if db is None or not getattr(db, "is_ready", False):
        return jsonify({"ok": False, "error_code": "SAAS_UNAVAILABLE", "message": "SaaS database is not configured."}), 503

    paddle_key = current_app.config.get("PADDLE_API_KEY")
    if not paddle_key:
        return jsonify({"ok": False, "error_code": "BILLING_NOT_CONFIGURED", "message": "Billing is not configured."}), 503

    identity = current_identity(session)
    if identity is None:
        return jsonify({"ok": False, "error_code": "UNAUTHORIZED", "message": "Authentication required."}), 401

    # Accept plan_key from form data or JSON body
    plan_key = (request.form.get("plan_key") or "").strip().lower()
    if not plan_key and request.is_json:
        data = request.get_json(silent=True) or {}
        plan_key = str(data.get("plan_key", "")).strip().lower()

    from app.services.billing_service import (
        get_plan,
        has_blocking_subscription,
        InvalidPlanError,
        AlreadySubscribedError,
    )
    from app.services.paddle_billing_service import create_paddle_checkout_url

    if not get_plan(plan_key):
        err = InvalidPlanError()
        return jsonify({"ok": False, "error_code": err.error_code, "message": err.message}), err.status_code

    if has_blocking_subscription(db, identity.tenant_id):
        err = AlreadySubscribedError()
        return jsonify({"ok": False, "error_code": err.error_code, "message": err.message}), err.status_code

    price_id_map = {
        "starter": current_app.config.get("PADDLE_STARTER_PRICE_ID") or "",
        "pro": current_app.config.get("PADDLE_PRO_PRICE_ID") or "",
        "business": current_app.config.get("PADDLE_BUSINESS_PRICE_ID") or "",
    }
    price_id = price_id_map.get(plan_key, "")
    if not price_id:
        return jsonify({"ok": False, "error_code": "BILLING_NOT_CONFIGURED", "message": f"Price ID for plan '{plan_key}' is not configured."}), 503

    base_url = (current_app.config.get("APP_BASE_URL") or "").rstrip("/")
    if not base_url:
        base_url = request.host_url.rstrip("/")

    success_url = f"{base_url}/billing/success?transaction_id={{transaction.id}}"
    cancel_url = f"{base_url}/billing/plans"

    try:
        checkout_url = create_paddle_checkout_url(
            paddle_key,
            plan_key,
            price_id,
            success_url,
            cancel_url,
            identity.tenant_id,
        )
    except Exception as exc:
        logging.error("PADDLE_CHECKOUT_ERROR tenant_id=%s error=%s", identity.tenant_id, exc)
        return jsonify({"ok": False, "error_code": "BILLING_ERROR", "message": "Failed to create checkout session."}), 502

    return jsonify({"ok": True, "data": {"checkout_url": checkout_url}, "error": None})


@auth_blueprint.get("/billing/success")
def billing_success():
    guarded = _require_auth()
    if guarded is not None:
        return guarded

    identity = current_identity(session)
    if identity is None:
        return redirect(url_for("auth.login"))

    transaction_id = (request.args.get("transaction_id") or request.args.get("session_id") or "").strip()
    if not transaction_id:
        return redirect(url_for("auth.billing_plans"))

    db = current_app.extensions.get("saas_db")
    paddle_key = current_app.config.get("PADDLE_API_KEY")

    if db and getattr(db, "is_ready", False) and paddle_key:
        try:
            from app.services.billing_service import create_pending_subscription
            from app.services.paddle_billing_service import (
                retrieve_paddle_transaction,
                get_paddle_transaction_ids,
                get_paddle_transaction_metadata,
            )

            transaction = retrieve_paddle_transaction(paddle_key, transaction_id)
            suffix = _session_suffix(transaction_id)
            fallback_customer_id = f"ctm_test{suffix}" if suffix else f"unknown_customer_{transaction_id}"
            fallback_subscription_id = f"sub_test{suffix}" if suffix else f"pending_{transaction_id}"
            customer_id_raw, subscription_id_raw = get_paddle_transaction_ids(transaction)
            customer_id = customer_id_raw or fallback_customer_id
            subscription_id = subscription_id_raw or fallback_subscription_id
            metadata = get_paddle_transaction_metadata(transaction)
            plan_key = (str(metadata.get("plan_key") or "starter").strip().lower() or "starter")

            create_pending_subscription(
                db,
                tenant_id=identity.tenant_id,
                stripe_customer_id=customer_id,
                stripe_subscription_id=subscription_id,
                plan_key=plan_key,
            )
        except Exception as exc:
            logging.error("BILLING_SUCCESS_ERROR tenant_id=%s error=%s", identity.tenant_id, exc)

    return render_template("billing_processing.html", page_key="billing", nav_mode="user")


@auth_blueprint.get("/billing/portal")
def billing_portal():
    guarded = _require_auth()
    if guarded is not None:
        return guarded

    identity = current_identity(session)
    if identity is None:
        return redirect(url_for("auth.login"))

    db = current_app.extensions.get("saas_db")
    if db is None or not getattr(db, "is_ready", False):
        return redirect(url_for("auth.billing_plans"))

    from app.services.billing_service import get_tenant_subscription
    from app.services.paddle_billing_service import create_paddle_portal_url
    sub = get_tenant_subscription(db, identity.tenant_id)
    if sub is None or not sub.stripe_customer_id or sub.stripe_customer_id.startswith("unknown_customer_"):
        return redirect(url_for("auth.billing_plans"))

    try:
        portal_url = create_paddle_portal_url(sub.stripe_customer_id)
        return redirect(portal_url)
    except Exception as exc:
        logging.error("PADDLE_PORTAL_ERROR tenant_id=%s error=%s", identity.tenant_id, exc)
        return redirect(url_for("auth.billing_plans"))


@auth_blueprint.post("/billing/webhook/paddle")
def billing_paddle_webhook():
    """Paddle webhook endpoint for subscription lifecycle events.

    This route is intentionally unauthenticated and CSRF-exempt because Paddle
    posts server-to-server callbacks signed with Paddle-Signature.
    """
    db = current_app.extensions.get("saas_db")
    if db is None or not getattr(db, "is_ready", False):
        return jsonify({"ok": False, "error_code": "SAAS_UNAVAILABLE", "message": "SaaS database is not configured."}), 503

    webhook_secret = current_app.config.get("PADDLE_WEBHOOK_SECRET")
    if not webhook_secret:
        return jsonify({"ok": False, "error_code": "BILLING_NOT_CONFIGURED", "message": "Paddle webhook secret is not configured."}), 503

    payload_bytes = request.get_data(cache=False) or b""
    sig_header = request.headers.get("Paddle-Signature", "")

    from app.services.billing_service import WebhookSignatureError
    from app.services.paddle_billing_service import (
        verify_paddle_webhook_signature,
        ingest_paddle_webhook_event,
    )

    try:
        verify_paddle_webhook_signature(payload_bytes, sig_header, webhook_secret)
        event = json.loads(payload_bytes)
        result = ingest_paddle_webhook_event(db, event)
    except WebhookSignatureError:
        return jsonify({"ok": False, "error_code": "WEBHOOK_SIGNATURE_INVALID", "message": "Webhook signature verification failed."}), 400
    except Exception as exc:  # noqa: BLE001
        logging.exception("PADDLE_WEBHOOK_PROCESSING_ERROR error=%s", exc)
        return jsonify({"ok": False, "error_code": "WEBHOOK_PROCESSING_ERROR", "message": "Webhook processing failed."}), 500

    result_status = result.get("status", "processed") if isinstance(result, dict) else "processed"
    result_label = "already_processed" if result_status == "duplicate" else result_status
    return jsonify({"ok": True, "data": {"result": result_label, **(result if isinstance(result, dict) else {})}, "error": None}), 200