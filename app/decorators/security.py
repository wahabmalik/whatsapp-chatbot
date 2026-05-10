from functools import wraps
from flask import current_app, jsonify, request, has_app_context
import logging
import hashlib
import hmac
import time
from app.services.expiring_store import ExpiringKeyStore, create_expiring_store
from app.services.observability import CORRELATION_ID_HEADER, ensure_correlation_id
from app.config import PROVIDER_META, normalize_provider


_FALLBACK_REPLAY_STORE = ExpiringKeyStore(window_seconds=300)


def _forbidden_response(message: str, reason: str, request_id: str):
    return (
        jsonify(
            {
                "status": "error",
                "message": message,
                "reason": reason,
                "correlation_id": request_id,
            }
        ),
        403,
    )


def validate_signature(payload, signature):
    """
    Validate the incoming payload's signature against our expected signature
    """
    # Use the App Secret to hash the payload
    app_secret = str(current_app.config.get("APP_SECRET", ""))
    if not app_secret:
        return False

    expected_signature = hmac.new(
        bytes(app_secret, "latin-1"),
        msg=payload.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()

    # Check if the signature matches
    return hmac.compare_digest(expected_signature, signature)


def _is_timestamp_valid(timestamp_header: str) -> bool:
    if not timestamp_header:
        return True

    try:
        header_timestamp = int(timestamp_header)
    except ValueError:
        return False

    skew_limit = int(current_app.config.get("SIGNATURE_MAX_SKEW_SECONDS", 300))
    return abs(int(time.time()) - header_timestamp) <= skew_limit


def _check_and_store_replay(signature: str, timestamp_header: str) -> bool:
    if timestamp_header:
        replay_key = f"{signature}:{timestamp_header}"
    else:
        replay_key = signature

    return not _get_replay_store().seen_recently(replay_key)


def _get_replay_store() -> ExpiringKeyStore:
    if not has_app_context():
        return _FALLBACK_REPLAY_STORE

    return create_expiring_store(
        app=current_app,
        extension_key="signature_replay_store",
        namespace="signature_replay",
        window_seconds=int(current_app.config.get("SIGNATURE_REPLAY_WINDOW_SECONDS", 300)),
    )


def _parse_signature_header() -> str:
    header_value = request.headers.get("X-Hub-Signature-256", "")
    if not header_value.startswith("sha256="):
        return ""
    return header_value[7:]


def clear_signature_replay_cache() -> None:
    _FALLBACK_REPLAY_STORE.clear()
    if has_app_context() and "signature_replay_store" in current_app.extensions:
        current_app.extensions["signature_replay_store"].clear()


def _enforce_meta_webhook_verification(request_id: str):
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    expected_token = str(current_app.config.get("VERIFY_TOKEN", ""))

    if mode and token:
        if mode == "subscribe" and hmac.compare_digest(token, expected_token):
            logging.info("WEBHOOK_VERIFIED request_id=%s", request_id)
            return challenge, 200

        logging.info("VERIFICATION_FAILED reason=token_mismatch request_id=%s", request_id)
        return _forbidden_response("Verification failed", "token_mismatch", request_id)

    logging.info("VERIFICATION_FAILED reason=missing_params request_id=%s", request_id)
    return _forbidden_response("Missing parameters", "missing_params", request_id)


def _enforce_evolution_webhook_signature(request_id: str):
    secret = str(current_app.config.get("EVOLUTION_WEBHOOK_SECRET", "")).strip()
    if not secret:
        return None

    header_name = str(
        current_app.config.get("EVOLUTION_WEBHOOK_SECRET_HEADER", "apikey")
    ).strip() or "apikey"
    provided = request.headers.get(header_name, "").strip()
    if hmac.compare_digest(provided, secret):
        return None

    logging.info(
        "Webhook secret verification failed provider=evolution request_id=%s",
        request_id,
    )
    return _forbidden_response(
        "Invalid webhook secret",
        "invalid_webhook_secret",
        request_id,
    )


def _enforce_meta_webhook_signature(request_id: str):
    signature = _parse_signature_header()
    if not signature:
        logging.info(
            "Signature verification failed: missing or malformed signature request_id=%s",
            request_id,
        )
        return _forbidden_response(
            "Invalid signature",
            "missing_or_malformed_signature",
            request_id,
        )

    timestamp_header = request.headers.get("X-Hub-Signature-Timestamp", "").strip()
    if not _is_timestamp_valid(timestamp_header):
        logging.info(
            "Signature verification failed: invalid timestamp request_id=%s",
            request_id,
        )
        return _forbidden_response(
            "Invalid signature timestamp",
            "invalid_signature_timestamp",
            request_id,
        )

    if not _check_and_store_replay(signature, timestamp_header):
        logging.info(
            "Signature verification failed: replay detected request_id=%s",
            request_id,
        )
        return _forbidden_response(
            "Duplicate signature",
            "duplicate_signature",
            request_id,
        )

    if not validate_signature(request.data.decode("utf-8"), signature):
        logging.info("Signature verification failed request_id=%s", request_id)
        return _forbidden_response("Invalid signature", "invalid_signature", request_id)

    return None


def enforce_inbound_webhook_request():
    """Apply provider-aware webhook authentication before route handlers run."""
    request_id = ensure_correlation_id(request.headers.get(CORRELATION_ID_HEADER))
    provider = normalize_provider(current_app.config.get("WHATSAPP_PROVIDER"))

    if request.method == "GET":
        if provider != PROVIDER_META:
            logging.info("WEBHOOK_READY provider=evolution request_id=%s", request_id)
            return jsonify({"status": "ok", "provider": provider}), 200
        return _enforce_meta_webhook_verification(request_id)

    if request.method == "POST":
        if provider != PROVIDER_META:
            return _enforce_evolution_webhook_signature(request_id)
        return _enforce_meta_webhook_signature(request_id)

    return None


def signature_required(f):
    """
    Decorator to ensure that the incoming requests to our webhook are valid and signed with the correct signature.
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        result = enforce_inbound_webhook_request()
        if result is not None:
            return result
        return f(*args, **kwargs)

    return decorated_function


def require_role(*allowed_roles):
    """
    Decorator to enforce role-based access control.
    
    Usage::
        @require_role('customer')
        def dashboard():
            ...
            
        @require_role('admin')
        def admin_panel():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            from flask import session, redirect, url_for
            
            user_role = session.get("auth_user_role")
            if user_role not in allowed_roles:
                return redirect(url_for("auth.login")), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator
