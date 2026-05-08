from __future__ import annotations

import json
import logging
import re
import time
import hashlib
from datetime import datetime, timezone

import requests
from flask import current_app

from app.config import PROVIDER_EVOLUTION, PROVIDER_META, normalize_provider
from app.services.agent_registry import get_selected_agent
from app.services.channel_interface import get_outbound_channel
from app.services.conversation_analytics import emit_analytics_event
from app.services.escalation_queue import append_review_artifact
from app.services.faq_store import find_faq_answer
from app.services.message_log import get_message_log_buffer
from app.services.metrics import Timer, get_metrics_collector
from app.services.outbound_delivery import get_background_delivery_service

# from app.services.openai_service import generate_response


def log_http_response(response, request_id: str | None = None):
    logging.info("Status=%s request_id=%s", response.status_code, request_id)
    logging.info(
        "Content-type=%s request_id=%s",
        response.headers.get("content-type"),
        request_id,
    )
    logging.info("Body=%s request_id=%s", response.text, request_id)


def get_text_message_input(recipient, text):
    return json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
    )


def _active_provider() -> str:
    return normalize_provider(current_app.config.get("WHATSAPP_PROVIDER"))


def _normalize_wa_id(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    raw = raw.split("@")[0]
    raw = raw.split(":")[0]
    return re.sub(r"\D", "", raw)


def _extract_evolution_text(message: dict | None) -> str | None:
    if not isinstance(message, dict):
        return None

    if isinstance(message.get("conversation"), str):
        return message["conversation"]

    extended = message.get("extendedTextMessage")
    if isinstance(extended, dict) and isinstance(extended.get("text"), str):
        return extended["text"]

    return None


def _safe_timestamp(value) -> str:
    raw = str(value or "").strip()
    if raw:
        return raw
    # Deterministic fallback for malformed/missing timestamps.
    return "0"


def _stable_payload_hash(value) -> str:
    try:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError):
        canonical = repr(value)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:20]


def _unsupported_inbound(provider: str, reason: str, *, message_id: str | None = None) -> dict:
    dedupe_key = _build_inbound_dedupe_key(
        provider=provider,
        message_id=message_id,
        user_id="",
        message_text="",
        timestamp=_safe_timestamp(None),
        extra_components={"reason": reason},
    )
    return {
        "provider": provider,
        "status_update": False,
        "unsupported": True,
        "unsupported_reason": reason,
        "message_id": message_id,
        "event_id": dedupe_key,
        "dedupe_key": dedupe_key,
        "user_id": "",
        "message_text": "",
        "timestamp": _safe_timestamp(None),
        # Backward-compatible aliases for existing callers.
        "wa_id": "",
        "text": "",
        "name": "Unknown",
    }


def normalize_inbound_message(body: dict | None) -> dict | None:
    if not isinstance(body, dict):
        return None

    entry = body.get("entry")
    if isinstance(entry, list) and entry and isinstance(entry[0], dict):
        changes = entry[0].get("changes")
        if not isinstance(changes, list) or not changes or not isinstance(changes[0], dict):
            return None
        value = changes[0].get("value")
        if not isinstance(value, dict):
            return None

        if value.get("statuses"):
            return {"provider": PROVIDER_META, "status_update": True}

        contacts = value.get("contacts") or []
        messages = value.get("messages") or []
        if not contacts or not messages:
            return None

        contact = contacts[0] or {}
        message = messages[0] or {}
        message_id = message.get("id")
        message_type = str(message.get("type") or "").strip().lower()
        if message_type and message_type != "text":
            return _unsupported_inbound(PROVIDER_META, "non_text_message", message_id=message_id)

        text_body = ((message.get("text") or {}).get("body") or "").strip()
        if not text_body:
            return _unsupported_inbound(PROVIDER_META, "non_text_message", message_id=message_id)

        user_id = _normalize_wa_id(contact.get("wa_id"))
        if not user_id:
            return None

        name = ((contact.get("profile") or {}).get("name") or "Unknown").strip() or "Unknown"
        timestamp = _safe_timestamp(message.get("timestamp"))
        dedupe_key = _build_inbound_dedupe_key(
            provider=PROVIDER_META,
            message_id=message_id,
            user_id=user_id,
            message_text=text_body,
            timestamp=timestamp,
            extra_components={
                "contact": {
                    "wa_id": contact.get("wa_id"),
                    "name": name,
                },
                "message": message,
            },
        )

        return {
            "provider": PROVIDER_META,
            "status_update": False,
            "unsupported": False,
            "unsupported_reason": None,
            "message_id": message_id,
            "event_id": dedupe_key,
            "dedupe_key": dedupe_key,
            "user_id": user_id,
            "message_text": text_body,
            "timestamp": timestamp,
            # Backward-compatible aliases for existing callers.
            "wa_id": user_id,
            "name": name,
            "text": text_body,
        }

    payload = body.get("data") if isinstance(body.get("data"), dict) else body
    key = payload.get("key") if isinstance(payload, dict) else None
    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(key, dict) or not isinstance(message, dict):
        return None

    if key.get("fromMe"):
        return {"provider": PROVIDER_EVOLUTION, "status_update": True}

    message_id = key.get("id")
    # Evolution payloads where message has media keys (without text forms) are unsupported.
    text_like = isinstance(message.get("conversation"), str) or isinstance(
        (message.get("extendedTextMessage") or {}).get("text"),
        str,
    )
    if not text_like:
        return _unsupported_inbound(PROVIDER_EVOLUTION, "non_text_message", message_id=message_id)

    text_body = (_extract_evolution_text(message) or "").strip()
    wa_id = _normalize_wa_id(key.get("remoteJid"))
    if not text_body or not wa_id:
        return None

    name = str(
        payload.get("pushName")
        or payload.get("senderName")
        or payload.get("pushname")
        or "Unknown"
    ).strip() or "Unknown"

    timestamp = _safe_timestamp(
        payload.get("messageTimestamp")
        or payload.get("timestamp")
        or key.get("timestamp")
    )
    dedupe_key = _build_inbound_dedupe_key(
        provider=PROVIDER_EVOLUTION,
        message_id=message_id,
        user_id=wa_id,
        message_text=text_body,
        timestamp=timestamp,
        extra_components={
            "key": key,
            "message": message,
            "name": name,
        },
    )

    return {
        "provider": PROVIDER_EVOLUTION,
        "status_update": False,
        "unsupported": False,
        "unsupported_reason": None,
        "message_id": message_id,
        "event_id": dedupe_key,
        "dedupe_key": dedupe_key,
        "user_id": wa_id,
        "message_text": text_body,
        "timestamp": timestamp,
        # Backward-compatible aliases for existing callers.
        "wa_id": wa_id,
        "name": name,
        "text": text_body,
    }


def _build_inbound_dedupe_key(
    *,
    provider: str,
    message_id: str | None,
    user_id: str,
    message_text: str,
    timestamp: str,
    extra_components=None,
) -> str:
    provider_key = str(provider or "unknown").strip().lower() or "unknown"
    message_id_key = str(message_id or "").strip()
    if message_id_key:
        return f"msg:{provider_key}:{message_id_key}"

    user_key = str(user_id or "").strip()
    timestamp_key = str(timestamp or "0").strip() or "0"
    normalized_text = " ".join(str(message_text or "").strip().split()).lower()
    text_digest = hashlib.sha1(normalized_text.encode("utf-8")).hexdigest()[:20]
    payload_digest = _stable_payload_hash(extra_components or {})
    return f"fp:{provider_key}:{user_key}:{timestamp_key}:{text_digest}:{payload_digest}"


def _meta_send_request(data, headers, timeout: int):
    version = _required_config_value("VERSION")
    phone_number_id = _required_config_value("PHONE_NUMBER_ID")
    url = f"https://graph.facebook.com/{version}/{phone_number_id}/messages"
    return requests.post(url, data=data, headers=headers, timeout=timeout)


def _evolution_send_request(data, headers, timeout: int, *, evolution_instance_name: str | None = None):
    payload = json.loads(data) if isinstance(data, str) else dict(data or {})
    recipient = _normalize_wa_id(payload.get("to") or current_app.config.get("RECIPIENT_WAID"))
    text = str(((payload.get("text") or {}).get("body") or "")).strip()
    evolution_payload = {
        "number": recipient,
        "text": text,
        "linkPreview": bool(((payload.get("text") or {}).get("preview_url") or False)),
    }
    base_url = _required_config_value("EVOLUTION_API_URL").rstrip("/")
    instance_name = str(evolution_instance_name or "").strip() or _required_config_value("EVOLUTION_INSTANCE_NAME")
    url = (
        base_url
        + f"/message/sendText/{instance_name}"
    )
    return requests.post(url, json=evolution_payload, headers=headers, timeout=timeout)


def _required_config_value(name: str) -> str:
    value = str(current_app.config.get(name, "")).strip()
    if not value:
        raise ValueError(f"Missing required configuration: {name}")
    return value


def _send_timeout_seconds() -> float:
    return float(current_app.config.get("WHATSAPP_SEND_TIMEOUT_SECONDS", 10.0))


def _send_request(data, timeout: int, *, evolution_instance_name: str | None = None):
    provider = _active_provider()
    headers = {"Content-type": "application/json"}
    if provider == PROVIDER_META:
        headers["Authorization"] = f"Bearer {_required_config_value('ACCESS_TOKEN')}"
        return _meta_send_request(data, headers, timeout)

    headers["apikey"] = str(current_app.config.get("EVOLUTION_API_KEY", ""))
    return _evolution_send_request(
        data,
        headers,
        timeout,
        evolution_instance_name=evolution_instance_name,
    )


def generate_response(response):
    # Keep this deterministic stub but include selected BMAD agent identity.
    agent = get_selected_agent()
    agent_name = agent["name"] if agent else "Bot"
    return f"[{agent_name}] {response.upper()}"


def _build_agent_reply(message_body: str, wa_id: str, name: str) -> dict:
    return {
        "reply_text": generate_response(message_body),
        "confidence": None,
        "source": "agent",
    }


def _parse_escalation_keywords(configured_keywords) -> set[str]:
    if isinstance(configured_keywords, str):
        return {part.strip().lower() for part in configured_keywords.split(",") if part.strip()}
    if isinstance(configured_keywords, (list, tuple, set)):
        return {str(part).strip().lower() for part in configured_keywords if str(part).strip()}
    return set()


def _contains_escalation_keyword(message_body: str, configured_keywords) -> bool:
    text = message_body.lower()
    for keyword in _parse_escalation_keywords(configured_keywords):
        pattern = re.compile(rf"(?<!\w){re.escape(keyword)}(?!\w)")
        if pattern.search(text):
            return True
    return False


def _resolve_escalation_reason(*, message_body: str, confidence: float | None, delivery: dict) -> str | None:
    if delivery.get("operator_review_flagged"):
        return str(delivery.get("operator_review_reason") or "outbound_fallback_failure")

    if _contains_escalation_keyword(message_body, current_app.config.get("ESCALATION_KEYWORDS", ())):
        return "escalation_keyword"

    if isinstance(confidence, (float, int)):
        threshold = float(current_app.config.get("ESCALATION_CONFIDENCE_THRESHOLD", 0.35))
        if float(confidence) < threshold:
            return "low_confidence"

    return None


def _default_ai_provider(
    message_text: str,
    wa_id: str,
    name: str,
    agent_context: dict | None = None,
) -> str:
    use_openai = bool(current_app.config.get("USE_OPENAI_SERVICE", False))
    if use_openai:
        if not str(current_app.config.get("OPENAI_ASSISTANT_ID", "")).strip():
            logging.warning(
                "USE_OPENAI_SERVICE is enabled but OPENAI_ASSISTANT_ID is missing; using deterministic fallback"
            )
            return generate_response(message_text)
        from app.services.openai_service import generate_response as openai_generate_response

        return openai_generate_response(message_text, wa_id, name, agent_context)
    return generate_response(message_text)


def _generate_reply_result(*, message_text: str, wa_id: str, name: str, agent_context, request_id: str | None, metrics):
    from app.services.openai_service import generate_reply_result

    return generate_reply_result(
        message_text=message_text,
        wa_id=wa_id,
        name=name,
        agent_context=agent_context,
        request_id=request_id,
        provider=_default_ai_provider,
        metrics=metrics,
    )


def _safe_observe_send_duration(metrics, duration_seconds: float, request_id: str | None) -> None:
    try:
        metrics.observe_duration("whatsapp.send_duration", duration_seconds)
    except Exception as exc:
        logging.warning(
            "Skipping whatsapp send duration metric request_id=%s reason=%s",
            request_id,
            exc,
        )


def _retry_backoff_schedule() -> tuple[int, ...]:
    return (1, 2, 4)


def _try_send_once(
    data,
    request_id: str,
    *,
    attempt: int,
    send_timeout: float,
    metrics,
    evolution_instance_name: str | None = None,
):
    attempt_timer = Timer()
    try:
        metrics.increment("whatsapp.send_attempt")
        logging.info(
            "Sending WhatsApp message attempt=%s request_id=%s",
            attempt + 1,
            request_id,
        )
        send_kwargs = {"timeout": send_timeout}
        if evolution_instance_name is not None:
            send_kwargs["evolution_instance_name"] = evolution_instance_name
        response = _send_request(data, **send_kwargs)
        response.raise_for_status()
        log_http_response(response, request_id=request_id)
        metrics.increment("whatsapp.send_success")
        metrics.observe_duration("whatsapp.send_attempt_duration", attempt_timer.elapsed())
        return {
            "ok": True,
            "status": "sent",
            "response_status": response.status_code,
            "fallback_sent": False,
            "operator_review_flagged": False,
            "operator_review_reason": None,
            "attempts": attempt + 1,
        }
    except requests.Timeout:
        metrics.increment("whatsapp.send_error")
        metrics.observe_duration("whatsapp.send_attempt_duration", attempt_timer.elapsed())
        logging.error(
            "Timeout occurred while sending message attempt=%s request_id=%s",
            attempt + 1,
            request_id,
        )
    except requests.RequestException as exc:
        metrics.increment("whatsapp.send_error")
        metrics.observe_duration("whatsapp.send_attempt_duration", attempt_timer.elapsed())
        logging.error(
            "Request failed due to: %s attempt=%s request_id=%s",
            exc,
            attempt + 1,
            request_id,
        )
    except (ValueError, KeyError, TypeError) as exc:
        metrics.increment("whatsapp.send_error")
        metrics.observe_duration("whatsapp.send_attempt_duration", attempt_timer.elapsed())
        logging.error(
            "Configuration or data error during send attempt=%s request_id=%s: %s",
            attempt + 1,
            request_id,
            exc,
        )
    return None


def _fallback_text_with_reference(request_id: str) -> str:
    fallback_text = str(
        current_app.config.get(
            "OUTBOUND_FALLBACK_TEXT",
            "We're experiencing delays right now. A human agent will follow up shortly.",
        )
    ).strip()
    if not fallback_text:
        raise ValueError("OUTBOUND_FALLBACK_TEXT cannot be empty")
    if request_id in fallback_text:
        return fallback_text
    return f"{fallback_text} Reference: {request_id}."


def _send_fallback(
    data,
    request_id: str,
    *,
    send_timeout: float,
    metrics,
    evolution_instance_name: str | None = None,
):
    fallback_sent = False
    fallback_error = None
    try:
        payload = json.loads(data) if isinstance(data, str) else {}
        recipient = payload.get("to") or current_app.config.get("RECIPIENT_WAID")
        if not recipient or not str(recipient).strip():
            raise ValueError(f"Cannot send fallback: recipient is empty (data={data})")

        fallback_data = get_text_message_input(recipient, _fallback_text_with_reference(request_id))
        fallback_attempts = int(current_app.config.get("WHATSAPP_FALLBACK_MAX_RETRIES", 2))
        for fallback_attempt in range(fallback_attempts):
            attempt_timer = Timer()
            metrics.increment("whatsapp.send_attempt")
            try:
                send_kwargs = {"timeout": send_timeout}
                if evolution_instance_name is not None:
                    send_kwargs["evolution_instance_name"] = evolution_instance_name
                response = _send_request(fallback_data, **send_kwargs)
                response.raise_for_status()
                log_http_response(response, request_id=request_id)
                metrics.observe_duration("whatsapp.send_attempt_duration", attempt_timer.elapsed())
                fallback_sent = True
                metrics.increment("whatsapp.fallback_sent")
                logging.error(
                    "Primary outbound delivery failed after retries; fallback sent request_id=%s status_code=%s fallback_attempt=%s",
                    request_id,
                    response.status_code,
                    fallback_attempt + 1,
                )
                break
            except (requests.Timeout, requests.RequestException, ValueError, TypeError, KeyError, AttributeError) as exc:
                fallback_error = str(exc)
                metrics.increment("whatsapp.send_error")
                metrics.increment("whatsapp.fallback_failed")
                metrics.observe_duration("whatsapp.send_attempt_duration", attempt_timer.elapsed())
                logging.error(
                    "Primary outbound delivery failed after retries; fallback attempt failed request_id=%s attempt=%s/%s error=%s",
                    request_id,
                    fallback_attempt + 1,
                    fallback_attempts,
                    exc,
                )
    except (ValueError, TypeError, requests.RequestException, KeyError, AttributeError, RuntimeError) as exc:
        fallback_error = str(exc)
        metrics.increment("whatsapp.fallback_failed")
        logging.error(
            "Primary outbound delivery failed after retries; fallback send failed: %s request_id=%s",
            exc,
            request_id,
        )

    error_message = "Failed to send message"
    if fallback_error:
        error_message = f"Failed to send message and fallback failed: {fallback_error}"

    return {
        "ok": False,
        "status": "fallback_sent" if fallback_sent else "error",
        "error": error_message,
        "fallback_sent": fallback_sent,
        "response_status": None,
        "operator_review_flagged": True,
        "operator_review_reason": "outbound_fallback_failure",
        "attempts": len(_retry_backoff_schedule()) + 1,
    }


def _complete_send_message(
    data,
    request_id: str,
    *,
    start_attempt: int = 0,
    initial_elapsed: float = 0.0,
    initial_backoff_seconds: float = 0.0,
    evolution_instance_name: str | None = None,
):
    timer = Timer()
    metrics = get_metrics_collector(current_app)
    retry_backoff = _retry_backoff_schedule()
    max_retries = len(retry_backoff)
    send_timeout = _send_timeout_seconds()

    if initial_backoff_seconds > 0:
        time.sleep(initial_backoff_seconds)

    for attempt in range(start_attempt, max_retries + 1):
        result = _try_send_once(
            data,
            request_id,
            attempt=attempt,
            send_timeout=send_timeout,
            metrics=metrics,
            evolution_instance_name=evolution_instance_name,
        )
        if result is not None:
            _safe_observe_send_duration(metrics, initial_elapsed + timer.elapsed(), request_id)
            return result

        if attempt < max_retries:
            time.sleep(retry_backoff[attempt])

    result = _send_fallback(
        data,
        request_id,
        send_timeout=send_timeout,
        metrics=metrics,
        evolution_instance_name=evolution_instance_name,
    )
    _safe_observe_send_duration(metrics, initial_elapsed + timer.elapsed(), request_id)
    return result


def _background_log_context(delivery_context: dict | None, result: dict, request_id: str) -> dict | None:
    if not delivery_context:
        return None
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "correlation_id": request_id,
        "from": delivery_context.get("wa_id"),
        "message_id": delivery_context.get("message_id"),
        "to_num": delivery_context.get("to_num"),
        "agent": delivery_context.get("agent") or "Unknown",
        "preview": delivery_context.get("input_text"),
        "reply_text": delivery_context.get("reply_text"),
        "status": result.get("status", "error"),
        "error": result.get("error"),
        "operator_review_flagged": bool(result.get("operator_review_flagged")),
        "operator_review_reason": result.get("operator_review_reason"),
        "review_artifact_queued": bool(result.get("review_artifact_queued")),
        "review_artifact_error": result.get("review_artifact_error"),
    }


def _complete_deferred_delivery(app, data, request_id: str, delivery_context: dict | None = None, initial_elapsed: float = 0.0):
    # THREAD CONTEXT PROPAGATION REQUIREMENT (Architecture Note):
    # Any new background path that dispatches work outside the request thread MUST:
    #   1. Accept `request_id` (correlation ID) as an explicit argument — never read it from
    #      thread-local storage (set_correlation_id is thread-local and will be empty in a new thread).
    #   2. Call `set_correlation_id(request_id)` at the start of execution inside the new thread/context.
    #   3. Call `clear_correlation_id()` in a `finally` block to prevent ID leakage to unrelated requests.
    # This function serves as the reference implementation of this convention.
    from app.services.health_check import set_last_error
    from app.services.observability import clear_correlation_id, set_correlation_id

    with app.app_context():
        set_correlation_id(request_id)
        try:
            result = dict(_complete_send_message(
                data,
                request_id,
                start_attempt=1,
                initial_elapsed=initial_elapsed,
                initial_backoff_seconds=_retry_backoff_schedule()[0],
                evolution_instance_name=(delivery_context or {}).get("evolution_instance"),
            ))

            review_artifact_queued = False
            review_artifact_error = None
            if result.get("operator_review_flagged") and delivery_context:
                review_artifact_queued, review_artifact_error = append_review_artifact(
                    app,
                    correlation_id=request_id,
                    reason=str(result.get("operator_review_reason") or "outbound_fallback_failure"),
                    wa_id=str(delivery_context.get("wa_id") or ""),
                    message_id=delivery_context.get("message_id"),
                )
                if review_artifact_error is not None:
                    logging.warning(
                        "Deferred escalation artifact write failed request_id=%s reason=%s error=%s",
                        request_id,
                        result.get("operator_review_reason") or "outbound_fallback_failure",
                        review_artifact_error,
                    )

            result["review_artifact_queued"] = review_artifact_queued
            result["review_artifact_error"] = review_artifact_error

            emit_analytics_event(
                app,
                stage="outbound_outcome",
                correlation_id=request_id,
                user_id=(delivery_context or {}).get("wa_id"),
                conversation_id=(delivery_context or {}).get("message_id"),
                outcome_status=str(result.get("status") or "error"),
                details={
                    "deferred": True,
                    "operator_review_flagged": bool(result.get("operator_review_flagged")),
                    "operator_review_reason": result.get("operator_review_reason"),
                    "review_artifact_queued": review_artifact_queued,
                },
            )

            log_entry = _background_log_context(delivery_context, result, request_id)
            if log_entry is not None:
                get_message_log_buffer(app).add_message(log_entry)

            if result.get("status") == "error":
                set_last_error(app, result.get("error"))
            else:
                set_last_error(app, None)
            return result
        finally:
            clear_correlation_id()


def send_message(data, request_id: str | None = None, delivery_context: dict | None = None):
    from app.services.observability import ensure_correlation_id

    request_id = request_id or ensure_correlation_id(None)
    timer = Timer()
    metrics = get_metrics_collector(current_app)
    send_timeout = _send_timeout_seconds()
    evolution_instance_name = (delivery_context or {}).get("evolution_instance")
    immediate_result = _try_send_once(
        data,
        request_id,
        attempt=0,
        send_timeout=send_timeout,
        metrics=metrics,
        evolution_instance_name=evolution_instance_name,
    )
    if immediate_result is not None:
        _safe_observe_send_duration(metrics, timer.elapsed(), request_id)
        return immediate_result

    if bool(current_app.config.get("WHATSAPP_DEFER_RETRIES", False)):
        try:
            get_background_delivery_service(current_app._get_current_object()).submit(
                _complete_deferred_delivery,
                current_app._get_current_object(),
                data,
                request_id,
                delivery_context,
                timer.elapsed(),
            )
            return {
                "ok": False,
                "status": "retrying",
                "error": None,
                "fallback_sent": False,
                "response_status": None,
                "operator_review_flagged": False,
                "operator_review_reason": None,
                "attempts": 1,
                "deferred": True,
            }
        except Exception as exc:
            logging.warning(
                "Deferred delivery enqueue failed; continuing synchronously request_id=%s error=%s",
                request_id,
                exc,
            )

    return _complete_send_message(
        data,
        request_id,
        start_attempt=1,
        initial_elapsed=timer.elapsed(),
        initial_backoff_seconds=_retry_backoff_schedule()[0],
        evolution_instance_name=evolution_instance_name,
    )


def process_text_for_whatsapp(text):
    # Remove brackets
    pattern = r"\【.*?\】"
    # Substitute the pattern with an empty string
    text = re.sub(pattern, "", text).strip()

    # Pattern to find double asterisks including the word(s) in between
    pattern = r"\*\*(.*?)\*\*"

    # Replacement pattern with single asterisks
    replacement = r"*\1*"

    # Substitute occurrences of the pattern with the replacement
    whatsapp_style_text = re.sub(pattern, replacement, text)

    return whatsapp_style_text


def process_whatsapp_message(body, request_id: str | None = None, inbound_message: dict | None = None):
    from app.services.observability import ensure_correlation_id

    request_id = request_id or ensure_correlation_id(None)
    inbound = inbound_message or normalize_inbound_message(body)
    if not inbound or inbound.get("status_update") or inbound.get("unsupported"):
        raise ValueError("No inbound message payload found")

    wa_id = str(inbound.get("user_id") or inbound.get("wa_id") or "")
    name = str(inbound.get("name") or "Unknown")
    agent = get_selected_agent()

    message_id = inbound.get("message_id")
    message_body = str(inbound.get("message_text") or inbound.get("text") or "").strip()
    evolution_instance = str(inbound.get("evolution_instance") or "").strip() or None
    if not wa_id or not message_body:
        raise ValueError("No inbound message payload found")

    faq_answer = find_faq_answer(current_app, wa_id, message_body)
    response_source = "agent"
    ai_result = None
    if faq_answer:
        response = faq_answer
        response_source = "faq"
        emit_analytics_event(
            current_app,
            stage="ai_outcome",
            correlation_id=request_id,
            user_id=wa_id,
            conversation_id=message_id,
            outcome_status="faq_hit",
            details={"source": response_source},
        )
    else:
        ai_result = _generate_reply_result(
            message_text=message_body,
            wa_id=wa_id,
            name=name,
            agent_context=agent,
            request_id=request_id,
            metrics=get_metrics_collector(current_app),
        )
        if ai_result.get("ok"):
            response = ai_result.get("reply_text") or ""
            emit_analytics_event(
                current_app,
                stage="ai_outcome",
                correlation_id=request_id,
                user_id=wa_id,
                conversation_id=message_id,
                outcome_status=str(ai_result.get("status") or "success"),
                details={
                    "source": response_source,
                    "confidence": ai_result.get("confidence"),
                },
            )
        else:
            response = current_app.config.get(
                "AI_FAILURE_FALLBACK_TEXT",
                "I'm having trouble answering right now. Please try again in a moment.",
            )
            response_source = "ai_fallback"
            emit_analytics_event(
                current_app,
                stage="ai_outcome",
                correlation_id=request_id,
                user_id=wa_id,
                conversation_id=message_id,
                outcome_status="fallback",
                details={
                    "source": response_source,
                    "ai_status": ai_result.get("status"),
                    "ai_error_code": ai_result.get("error_code"),
                },
            )

    agent_name = agent["name"] if agent else "Unknown"
    logging.info(
        "Processed inbound WhatsApp message wa_id=%s profile_name=%s request_id=%s source=%s",
        wa_id,
        name,
        request_id,
        response_source,
    )

    # OpenAI Integration
    # response = generate_response(message_body, wa_id, name)
    # response = process_text_for_whatsapp(response)

    data = get_text_message_input(wa_id, response)
    delivery = get_outbound_channel(current_app).send(
        data,
        request_id=request_id,
        delivery_context={
            "wa_id": wa_id,
            "message_id": message_id,
            "to_num": wa_id,
            "agent": agent_name,
            "input_text": message_body,
            "reply_text": response,
            "evolution_instance": evolution_instance,
        },
    )
    escalation_reason = _resolve_escalation_reason(
        message_body=message_body,
        confidence=(ai_result or {}).get("confidence"),
        delivery=delivery,
    )
    operator_review_flagged = bool(escalation_reason)
    emit_analytics_event(
        current_app,
        stage="escalation_flag",
        correlation_id=request_id,
        user_id=wa_id,
        conversation_id=message_id,
        outcome_status="flagged" if operator_review_flagged else "clear",
        details={
            "reason": escalation_reason,
            "delivery_status": delivery.get("status"),
        },
    )
    review_artifact_queued = False
    review_artifact_error = None
    if operator_review_flagged:
        review_artifact_queued, review_artifact_error = append_review_artifact(
            current_app,
            correlation_id=request_id,
            reason=str(escalation_reason),
            wa_id=wa_id,
            message_id=message_id,
        )
        if review_artifact_error is not None:
            logging.warning(
                "Escalation artifact write failed request_id=%s reason=%s error=%s",
                request_id,
                escalation_reason,
                review_artifact_error,
            )

    error = delivery.get("error")
    if ai_result and not ai_result.get("ok") and not error:
        error = f"ai_{ai_result.get('status')}:{ai_result.get('error_code')}"

    emit_analytics_event(
        current_app,
        stage="outbound_outcome",
        correlation_id=request_id,
        user_id=wa_id,
        conversation_id=message_id,
        outcome_status=str(delivery.get("status", "error")),
        details={
            "deferred": bool(delivery.get("deferred")),
            "operator_review_flagged": operator_review_flagged,
            "operator_review_reason": escalation_reason,
        },
    )

    return {
        "from": wa_id,
        "name": name,
        "message_id": message_id,
        "agent": agent_name,
        "input_text": message_body,
        "reply_text": response,
        "response_source": response_source,
        "operator_review_flagged": operator_review_flagged,
        "operator_review_reason": escalation_reason,
        "review_artifact_queued": review_artifact_queued,
        "review_artifact_error": review_artifact_error,
        "ai_status": ai_result.get("status") if ai_result else None,
        "confidence": ai_result.get("confidence") if ai_result else None,
        "ai_error_code": ai_result.get("error_code") if ai_result else None,
        "ai_metadata": ai_result.get("metadata") if ai_result else None,
        "status": delivery.get("status", "error"),
        "error": error,
        "evolution_instance": evolution_instance,
    }


def is_valid_whatsapp_message(body):
    """
    Check if the incoming webhook event has a valid WhatsApp message structure.
    """
    inbound = normalize_inbound_message(body)
    return bool(inbound and not inbound.get("status_update") and not inbound.get("unsupported"))
