from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.services.observability import sanitize_text


logger = logging.getLogger(__name__)


def _utc(value: datetime | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_conversation_key(conversation_id: str | None, wa_id: str) -> str:
    candidate = str(conversation_id or "").strip()
    if candidate:
        return candidate
    return f"wa:{wa_id}"


def _clean_message_body(value: str | None) -> str:
    sanitized = sanitize_text(str(value or "")).strip()
    if len(sanitized) > 4000:
        return sanitized[:4000]
    return sanitized


def _record_message(
    session,
    *,
    tenant_id: str,
    wa_id: str,
    conversation_key: str,
    sender: str,
    text_body: str | None,
    timestamp: datetime,
    delivery_status: str,
    correlation_id: str | None,
    escalation_flag: bool,
) -> None:
    from app.models import ConversationMessage, ConversationSummary

    summary = (
        session.query(ConversationSummary)
        .filter(
            ConversationSummary.tenant_id == tenant_id,
            ConversationSummary.conversation_key == conversation_key,
        )
        .one_or_none()
    )
    if summary is None:
        summary = ConversationSummary(
            tenant_id=tenant_id,
            wa_id=wa_id,
            conversation_key=conversation_key,
            latest_timestamp=timestamp,
            message_count=0,
            escalation_flag=False,
        )
        session.add(summary)

    summary.wa_id = wa_id
    summary.latest_timestamp = max(_utc(summary.latest_timestamp), timestamp)
    summary.message_count = int(summary.message_count or 0) + 1
    summary.escalation_flag = bool(summary.escalation_flag) or bool(escalation_flag)

    session.add(
        ConversationMessage(
            tenant_id=tenant_id,
            conversation_summary=summary,
            conversation_key=conversation_key,
            wa_id=wa_id,
            sender=str(sender or "unknown")[:255],
            text_body=_clean_message_body(text_body),
            timestamp=timestamp,
            delivery_status=str(delivery_status or "unknown")[:50],
            correlation_id=(str(correlation_id).strip()[:128] if correlation_id else None),
        )
    )


def record_conversation_exchange(
    app,
    *,
    tenant_id: str | None,
    wa_id: str | None,
    conversation_id: str | None,
    correlation_id: str | None,
    inbound_text: str | None,
    outbound_text: str | None,
    outbound_status: str,
    escalation_flag: bool,
    inbound_timestamp: datetime | None = None,
    outbound_timestamp: datetime | None = None,
) -> bool:
    """Persist tenant-scoped read-model rows for the conversation history viewer."""
    normalized_tenant = str(tenant_id or "").strip()
    normalized_wa_id = str(wa_id or "").strip()
    if not normalized_tenant or not normalized_wa_id:
        return False

    db = app.extensions.get("saas_db")
    if db is None or not getattr(db, "is_ready", False):
        return False

    conversation_key = _normalize_conversation_key(conversation_id, normalized_wa_id)
    inbound_at = _utc(inbound_timestamp)
    outbound_at = _utc(outbound_timestamp)

    sess = db.session()
    try:
        _record_message(
            sess,
            tenant_id=normalized_tenant,
            wa_id=normalized_wa_id,
            conversation_key=conversation_key,
            sender="user",
            text_body=inbound_text,
            timestamp=inbound_at,
            delivery_status="received",
            correlation_id=correlation_id,
            escalation_flag=escalation_flag,
        )
        _record_message(
            sess,
            tenant_id=normalized_tenant,
            wa_id=normalized_wa_id,
            conversation_key=conversation_key,
            sender="assistant",
            text_body=outbound_text,
            timestamp=outbound_at,
            delivery_status=outbound_status,
            correlation_id=correlation_id,
            escalation_flag=escalation_flag,
        )
        sess.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        sess.rollback()
        logger.warning(
            "CONVERSATION_HISTORY_PERSIST_FAILED tenant_id=%s wa_id=%s conversation_key=%s error=%s",
            normalized_tenant,
            normalized_wa_id,
            conversation_key,
            exc,
        )
        return False
    finally:
        sess.close()
