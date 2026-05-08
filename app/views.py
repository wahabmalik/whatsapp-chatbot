from __future__ import annotations

import logging
from typing import Any
from datetime import datetime, timezone

from flask import (
    Blueprint,
    Response,
    request,
    jsonify,
    current_app,
    has_app_context,
)
from werkzeug.exceptions import BadRequest

from .config import (
    PROVIDER_EVOLUTION,
    PROVIDER_META,
    normalize_provider,
)
from .decorators.security import enforce_inbound_webhook_request
from .models import ConnectionState, Subscription, Tenant, UsageCounter
from .services.conversation_context import get_conversation_context_store
from .services.billing_service import can_activate_bot
from .services.expiring_store import create_expiring_store
from .services.health_check import set_last_error, get_bot_health
from .services.message_log import get_message_log_buffer
from .services.metrics import get_metrics_collector, Timer
from .services.observability import CORRELATION_ID_HEADER, ensure_correlation_id, get_correlation_id
from .services.conversation_analytics import emit_analytics_event
from .utils.whatsapp_utils import (
    normalize_inbound_message,
    process_whatsapp_message,
)

webhook_blueprint = Blueprint("webhook", __name__)


@webhook_blueprint.before_request
def enforce_webhook_access_controls():
    if request.endpoint in {"webhook.webhook_get", "webhook.webhook_post"}:
        return enforce_inbound_webhook_request()
    return None


def _outbound_target_label() -> str:
    provider = normalize_provider(current_app.config.get("WHATSAPP_PROVIDER"))
    if provider == PROVIDER_META:
        return str(current_app.config.get("PHONE_NUMBER_ID", ""))
    return str(current_app.config.get("EVOLUTION_INSTANCE_NAME", ""))


def _is_duplicate_message(message_id: str | None) -> bool:
    if not message_id:
        return False

    return _get_message_id_store().seen_recently(message_id)


def _get_message_id_store():
    return create_expiring_store(
        app=current_app,
        extension_key="message_id_store",
        namespace="webhook_message_id",
        window_seconds=int(current_app.config.get("IDEMPOTENCY_WINDOW_SECONDS", 300)),
    )


def _trim_text(value: str | None, limit: int = 200) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def clear_message_idempotency_cache() -> None:
    # Keep this helper for tests while moving storage behind an app extension seam.
    if has_app_context() and "message_id_store" in current_app.extensions:
        current_app.extensions["message_id_store"].clear()


def _error_response(message: str, status_code: int, reason: str, request_id: str):
    return (
        jsonify(
            {
                "status": "error",
                "message": message,
                "reason": reason,
                "correlation_id": request_id,
            }
        ),
        status_code,
    )


def _extract_evolution_instance_name(payload: Any) -> str:
    if isinstance(payload, dict):
        direct = payload.get("instance_name") or payload.get("instanceName") or payload.get("instance")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        for key in ("data", "event", "instance", "body"):
            nested = payload.get(key)
            found = _extract_evolution_instance_name(nested)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _extract_evolution_instance_name(item)
            if found:
                return found
    return ""


def _extract_evolution_state(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("state", "status", "connection", "connectionStatus"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
        for key in ("data", "event", "instance", "body"):
            nested = payload.get(key)
            found = _extract_evolution_state(nested)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _extract_evolution_state(item)
            if found:
                return found
    return ""


def _extract_evolution_phone(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in ("phone", "phoneNumber", "number", "wuid", "wid"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key in ("data", "event", "instance", "body"):
            nested = payload.get(key)
            found = _extract_evolution_phone(nested)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _extract_evolution_phone(item)
            if found:
                return found
    return None


def _normalize_connection_state(raw_state: str) -> str:
    value = str(raw_state or "").strip().lower()
    if value in {"open", "connected", "online", "ready"}:
        return "connected"
    if value in {"connecting", "qr", "qrcode", "pending", "in_progress"}:
        return "connecting"
    if value in {"close", "closed", "disconnected", "offline"}:
        return "disconnected"
    return ""


def _get_saas_db():
    db = current_app.extensions.get("saas_db")
    return db if getattr(db, "is_ready", False) else None


def _resolve_tenant_by_instance(db, instance_name: str) -> ConnectionState | None:
    sess = db.session()
    try:
        return (
            sess.query(ConnectionState)
            .filter(ConnectionState.evolution_instance == instance_name)
            .one_or_none()
        )
    finally:
        sess.close()


def _sync_connection_state_from_event(db, *, instance_name: str, state: str, phone_number: str | None) -> bool:
    connection = _resolve_tenant_by_instance(db, instance_name)
    if connection is None:
        return False

    normalized = _normalize_connection_state(state)
    if not normalized:
        return True

    sess = db.session()
    try:
        row = sess.query(ConnectionState).filter(ConnectionState.tenant_id == connection.tenant_id).one_or_none()
        if row is None:
            return False
        row.status = normalized
        if normalized == "connected":
            row.connected_at = datetime.now(timezone.utc)
            if phone_number:
                row.phone_number = phone_number
        elif normalized == "disconnected":
            row.connected_at = None
            row.phone_number = None
        sess.commit()
        return True
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def _is_evolution_state_event(body: dict[str, Any]) -> bool:
    event_name = str(body.get("event") or body.get("type") or "").strip().lower()
    if event_name == "instance.state.updated":
        return True
    if "instance" in event_name and "state" in event_name:
        return True
    return False


def _enforce_tenant_inbound_guards(db, tenant_id: str, request_id: str):
    sess = db.session()
    try:
        tenant = sess.query(Tenant).filter(Tenant.id == tenant_id).one_or_none()
        if tenant is None:
            logging.warning("TENANT_ROUTING_REJECT tenant_missing tenant_id=%s request_id=%s", tenant_id, request_id)
            return "tenant_missing"
        if not tenant.is_active:
            return "tenant_inactive"

        conn = sess.query(ConnectionState).filter(ConnectionState.tenant_id == tenant_id).one_or_none()
        if conn is None or str(conn.status or "").strip().lower() != "connected":
            return "connection_not_connected"

        usage = sess.query(UsageCounter).filter(UsageCounter.tenant_id == tenant_id).one_or_none()
        if usage is not None and bool(usage.is_blocked):
            return "usage_blocked"

        if not can_activate_bot(db, tenant_id):
            return "subscription_not_entitled"

        return None
    finally:
        sess.close()


def handle_message():
    """
    Handle incoming webhook events from the WhatsApp API.

    This function processes incoming WhatsApp messages and other events,
    such as delivery statuses. If the event is a valid message, it gets
    processed. If the incoming payload is not a recognized WhatsApp event,
    an error is returned.

    Every message send will trigger 4 HTTP requests to your webhook: message, sent, delivered, read.

    Returns:
        response: A tuple containing a JSON response and an HTTP status code.
    """
    timer = Timer()
    request_id = get_correlation_id() or ensure_correlation_id(request.headers.get(CORRELATION_ID_HEADER))
    metrics = get_metrics_collector(current_app)
    metrics.increment("webhook.requests_total")
    logging.info("Processing webhook event request_id=%s", request_id)
    validation_errors = current_app.extensions.get("config_validation_errors", [])
    if validation_errors:
        metrics.increment("webhook.blocked_config_invalid_total")
        metrics.observe_duration("webhook.handle_message_seconds", timer.elapsed())
        logging.warning(
            "Webhook blocked due to invalid startup configuration request_id=%s errors=%s",
            request_id,
            "; ".join(validation_errors),
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Configuration is incomplete. Complete setup before processing webhooks.",
                    "reason": "config_invalid",
                    "validation_errors": validation_errors,
                    "correlation_id": request_id,
                }
            ),
            503,
        )
    # logging.info(f"request body: {body}")

    try:
        body = request.get_json(silent=False)

        if normalize_provider(current_app.config.get("WHATSAPP_PROVIDER")) == PROVIDER_EVOLUTION:
            db = _get_saas_db()
            if db is not None and _is_evolution_state_event(body):
                instance_name = _extract_evolution_instance_name(body)
                state = _extract_evolution_state(body)
                phone_number = _extract_evolution_phone(body)

                if not instance_name:
                    logging.warning(
                        "EVOLUTION_STATE_EVENT_IGNORED reason=missing_instance_name request_id=%s",
                        request_id,
                    )
                else:
                    updated = _sync_connection_state_from_event(
                        db,
                        instance_name=instance_name,
                        state=state,
                        phone_number=phone_number,
                    )
                    if not updated:
                        logging.warning(
                            "CROSS_TENANT_ROUTING_REJECTED reason=unknown_instance_name instance_name=%s request_id=%s",
                            instance_name,
                            request_id,
                        )
                metrics.increment("webhook.status_updates_total")
                metrics.observe_duration("webhook.handle_message_seconds", timer.elapsed())
                return jsonify({"status": "ok", "handled": True}), 200

        inbound = normalize_inbound_message(body)
        if inbound and inbound.get("status_update"):
            metrics.increment("webhook.status_updates_total")
            metrics.observe_duration("webhook.handle_message_seconds", timer.elapsed())
            logging.info("Received a WhatsApp status update request_id=%s", request_id)
            return jsonify({"status": "ok"}), 200

        if inbound and inbound.get("unsupported"):
            metrics.increment("webhook.invalid_events_total")
            metrics.observe_duration("webhook.handle_message_seconds", timer.elapsed())
            logging.warning(
                "Unsupported inbound payload acknowledged request_id=%s reason=%s",
                request_id,
                inbound.get("unsupported_reason") or "unsupported_payload",
            )
            return (
                jsonify(
                    {
                        "status": "ok",
                        "handled": True,
                        "reason": inbound.get("unsupported_reason") or "unsupported_payload",
                        "correlation_id": request_id,
                    }
                ),
                200,
            )

        if inbound and not inbound.get("status_update") and not inbound.get("unsupported"):
            db = _get_saas_db()
            if (
                db is not None
                and normalize_provider(inbound.get("provider")) == PROVIDER_EVOLUTION
            ):
                instance_name = _extract_evolution_instance_name(body)
                if not instance_name:
                    metrics.increment("webhook.invalid_events_total")
                    metrics.observe_duration("webhook.handle_message_seconds", timer.elapsed())
                    logging.warning(
                        "CROSS_TENANT_ROUTING_REJECTED reason=missing_instance_name request_id=%s",
                        request_id,
                    )
                    return jsonify({"status": "ok", "handled": True, "reason": "missing_instance_name"}), 200

                connection = _resolve_tenant_by_instance(db, instance_name)
                if connection is None:
                    metrics.increment("webhook.invalid_events_total")
                    metrics.observe_duration("webhook.handle_message_seconds", timer.elapsed())
                    logging.warning(
                        "CROSS_TENANT_ROUTING_REJECTED reason=unknown_instance_name instance_name=%s request_id=%s",
                        instance_name,
                        request_id,
                    )
                    return jsonify({"status": "ok", "handled": True, "reason": "unknown_instance_name"}), 200

                guard_reason = _enforce_tenant_inbound_guards(db, connection.tenant_id, request_id)
                if guard_reason is not None:
                    metrics.increment("webhook.blocked_inactive_tenant_total")
                    metrics.observe_duration("webhook.handle_message_seconds", timer.elapsed())
                    logging.info(
                        "TENANT_INBOUND_BLOCKED tenant_id=%s reason=%s request_id=%s",
                        connection.tenant_id,
                        guard_reason,
                        request_id,
                    )
                    return jsonify({"status": "ok", "handled": True, "reason": guard_reason}), 200

                inbound["tenant_id"] = connection.tenant_id
                inbound["evolution_instance"] = instance_name

            message_id = inbound.get("message_id") if inbound else None
            dedupe_key = (
                inbound.get("dedupe_key")
                or inbound.get("event_id")
                or message_id
            ) if inbound else None
            emit_analytics_event(
                current_app,
                stage="inbound_receive",
                correlation_id=request_id,
                user_id=inbound.get("user_id") if inbound else None,
                conversation_id=message_id or dedupe_key,
                outcome_status="received",
                details={
                    "provider": inbound.get("provider") if inbound else None,
                    "status_update": bool((inbound or {}).get("status_update")),
                },
            )
            if _is_duplicate_message(dedupe_key):
                metrics.increment("webhook.duplicates_total")
                metrics.observe_duration("webhook.handle_message_seconds", timer.elapsed())
                logging.info(
                    "Duplicate webhook message skipped request_id=%s message_id=%s dedupe_key=%s",
                    request_id,
                    message_id,
                    dedupe_key,
                )
                return jsonify({"status": "ok", "duplicate": True, "correlation_id": request_id}), 200

            delivery = process_whatsapp_message(
                body,
                request_id=request_id,
                inbound_message=inbound,
            )
            log_buffer = get_message_log_buffer(current_app)
            log_buffer.add_message(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "from": delivery.get("from"),
                    "message_id": delivery.get("message_id"),
                    "to_num": delivery.get("evolution_instance") or _outbound_target_label(),
                    "agent": delivery.get("agent") or "Unknown",
                    "preview": _trim_text(delivery.get("input_text"), 80),
                    "reply_text": _trim_text(delivery.get("reply_text"), 200),
                    "status": delivery.get("status", "error"),
                    "error": _trim_text(delivery.get("error"), 200),
                    "operator_review_flagged": bool(delivery.get("operator_review_flagged")),
                    "operator_review_reason": delivery.get("operator_review_reason"),
                }
            )
            sender_id = delivery.get("from") or ""
            if sender_id:
                get_conversation_context_store(current_app).append_message(
                    sender_id,
                    {
                        "role": "user",
                        "text": _trim_text(delivery.get("input_text"), 200),
                        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "message_id": delivery.get("message_id"),
                    },
                )
            set_last_error(current_app, None)
            metrics.increment("webhook.processed_messages_total")
            metrics.observe_duration("webhook.handle_message_seconds", timer.elapsed())
            return jsonify({"status": "ok", "correlation_id": request_id}), 200
        else:
            metrics.increment("webhook.invalid_events_total")
            metrics.observe_duration("webhook.handle_message_seconds", timer.elapsed())
            # if the request is not a WhatsApp API event, return an error
            return _error_response("Not a WhatsApp API event", 404, "invalid_event", request_id)
    except BadRequest:
        metrics.increment("webhook.json_decode_errors_total")
        metrics.observe_duration("webhook.handle_message_seconds", timer.elapsed())
        logging.error("Failed to decode JSON request_id=%s", request_id)
        return _error_response("Invalid JSON provided", 400, "json_decode_error", request_id)
    except Exception as exc:  # pragma: no cover - defensive fallback
        metrics.increment("webhook.internal_errors_total")
        metrics.observe_duration("webhook.handle_message_seconds", timer.elapsed())
        set_last_error(current_app, _trim_text(str(exc), 200))
        logging.exception("Unhandled webhook processing error: %s request_id=%s", exc, request_id)
        return _error_response("Internal server error", 500, "internal_error", request_id)


@webhook_blueprint.route("/webhook", methods=["GET"])
def webhook_get():
    return jsonify({"status": "ok"}), 200


@webhook_blueprint.route("/webhook", methods=["POST"])
def webhook_post():
    return handle_message()


@webhook_blueprint.route("/health", methods=["GET"])
def health():
    return jsonify(get_bot_health(current_app)), 200


def _prometheus_text_snapshot(snapshot: dict[str, Any]) -> str:
    lines: list[str] = []

    counters = snapshot.get("counters", {}) or {}
    for key, value in sorted(counters.items()):
        metric_name = str(key).replace(".", "_")
        lines.append(f"# TYPE {metric_name} counter")
        lines.append(f"{metric_name} {int(value)}")

    lines.append("# TYPE http_inflight_requests gauge")
    lines.append(f"http_inflight_requests {int(snapshot.get('inflight', 0))}")

    lines.append("# TYPE http_errors_last_300s gauge")
    lines.append(f"http_errors_last_300s {int(snapshot.get('errors_last_300s', 0))}")

    return "\n".join(lines) + "\n"


@webhook_blueprint.route("/metrics", methods=["GET"])
def metrics():
    return jsonify(get_metrics_collector(current_app).snapshot()), 200


@webhook_blueprint.route("/metrics/prometheus", methods=["GET"])
@webhook_blueprint.route("/api/metrics/prometheus", methods=["GET"])
def metrics_prometheus():
    payload = _prometheus_text_snapshot(get_metrics_collector(current_app).snapshot())
    return Response(payload, mimetype="text/plain")


