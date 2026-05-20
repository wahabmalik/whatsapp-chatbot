"""Compliance and Sendability Control Surface  (Story 12.6).

Provides:
- Tenant-scoped consent ledger CRUD with audit trail.
- Template sendability state reader with stale/unknown-state detection.
- Quality/sendability alert indicator (no_issue | warning | action_required).
- Pre-dispatch eligibility gate used by the outbound template send path.

Design constraints:
- All reads and writes are scoped to a single tenant_id — no cross-tenant data.
- Blocked-send evidence is written to AuditLog with correlation_id and passes
  through observability.sanitize_text so credential material is never logged.
- Stale/unknown provider state always resolves to the safe default (block send).
  The system never infers sendability from missing or stale sync data.
- Eligible sends are unaffected; the gate does NOT change retry/fallback semantics
  for messages that are already in-flight (AC 12.6.7).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.models import AuditLog, ConsentLedger, StarterTemplateDraft
from app.models.base import new_uuid, utcnow
from app.services.observability import sanitize_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Sendability display states that the operator sees.
DISPLAY_STATE_APPROVED = "approved"
DISPLAY_STATE_PENDING = "pending"
DISPLAY_STATE_REJECTED = "rejected"
DISPLAY_STATE_PAUSED = "paused"
DISPLAY_STATE_STALE = "stale"
DISPLAY_STATE_UNKNOWN = "unknown"

# Internal provider states that map to each display state.
_PROVIDER_STATE_MAP: dict[str, str] = {
    "approved": DISPLAY_STATE_APPROVED,
    "active": DISPLAY_STATE_APPROVED,
    "pending_approval": DISPLAY_STATE_PENDING,
    "rejected": DISPLAY_STATE_REJECTED,
    "paused": DISPLAY_STATE_PAUSED,
    "draft": DISPLAY_STATE_PENDING,  # not yet submitted → operator must act
}

# Display states that allow sending (safe default: everything else is blocked).
SENDABLE_DISPLAY_STATES: frozenset[str] = frozenset({DISPLAY_STATE_APPROVED})

# Provider states that are eligible for staleness evaluation.
_STALE_ELIGIBLE_STATES: frozenset[str] = frozenset({"pending_approval"})

# Default threshold after which a pending state is considered stale (72 hours).
DEFAULT_STALE_THRESHOLD_SECONDS: int = 72 * 3600

# Alert levels.
ALERT_NO_ISSUE = "no_issue"
ALERT_WARNING = "warning"
ALERT_ACTION_REQUIRED = "action_required"

# Operator-facing guidance copy (plain language, no credentials).
_ALERT_GUIDANCE: dict[str, str] = {
    ALERT_NO_ISSUE: "All templates are approved and consent is in order. Sends are unblocked.",
    ALERT_WARNING: (
        "One or more templates have a pending or stale provider state. "
        "Review approval status and re-submit if needed. Sends using these templates are currently blocked."
    ),
    ALERT_ACTION_REQUIRED: (
        "One or more templates are rejected, paused, or have an unknown provider state. "
        "Action is required: check your WhatsApp Business account for policy details and re-submit "
        "corrected templates. Sends using these templates are blocked."
    ),
}

# Blocked-send reason codes (stable, used as API contract values).
REASON_CONSENT_MISSING = "consent_required"
REASON_TEMPLATE_NOT_SENDABLE = "template_not_sendable"
REASON_STALE_OR_UNKNOWN = "provider_state_stale_or_unknown"

# Operator-safe reason messages (no secrets, safe to surface in API responses).
_REASON_MESSAGES: dict[str, str] = {
    REASON_CONSENT_MISSING: (
        "This contact does not have recorded consent for outbound messaging. "
        "Grant consent before sending."
    ),
    REASON_TEMPLATE_NOT_SENDABLE: (
        "The selected template is not in an approved sendable state. "
        "Check the template's provider review status and resolve before sending."
    ),
    REASON_STALE_OR_UNKNOWN: (
        "The template's provider state is stale or unavailable. "
        "The system has applied a safe default and blocked this send. "
        "Re-sync or re-submit the template to confirm its current approval state."
    ),
}


# ---------------------------------------------------------------------------
# Consent Ledger
# ---------------------------------------------------------------------------

def get_consent_ledger(
    db,
    tenant_id: str,
    *,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Return a paginated, tenant-scoped view of consent records.

    Args:
        db: SaaS DB extension (has `.session()` factory).
        tenant_id: Scope all results to this tenant.
        search: Optional substring filter on contact_id (case-insensitive).
        limit: Maximum rows to return (clamped to 1–200).
        offset: Pagination offset.

    Returns:
        dict with keys: entries (list), total (int), limit, offset.
    """
    tenant_key = str(tenant_id or "").strip()
    if not tenant_key:
        return {"entries": [], "total": 0, "limit": limit, "offset": offset}

    limit = max(1, min(200, int(limit)))
    offset = max(0, int(offset))
    search_term = str(search or "").strip().lower()

    sess = db.session()
    try:
        query = sess.query(ConsentLedger).filter(ConsentLedger.tenant_id == tenant_key)
        if search_term:
            query = query.filter(
                ConsentLedger.contact_id.ilike(f"%{search_term}%")
            )
        total = query.count()
        rows = query.order_by(ConsentLedger.updated_at.desc()).limit(limit).offset(offset).all()
        entries = [_serialize_consent_entry(row) for row in rows]
        return {"entries": entries, "total": total, "limit": limit, "offset": offset}
    finally:
        sess.close()


def upsert_consent_record(
    db,
    *,
    tenant_id: str,
    contact_id: str,
    status: str,
    source: str | None,
    actor_id: str | None,
    correlation_id: str,
) -> dict[str, Any]:
    """Create or update a consent record and write an audit entry.

    Valid status values: granted | required | revoked.

    Returns:
        Serialized consent entry dict.

    Raises:
        ValueError: if status is not a recognized value.
    """
    tenant_key = str(tenant_id or "").strip()
    contact_key = str(contact_id or "").strip()
    normalized_status = str(status or "").strip().lower()
    normalized_source = sanitize_text(str(source or "").strip())
    actor = str(actor_id or "operator")

    if normalized_status not in {"granted", "required", "revoked"}:
        raise ValueError(f"Invalid consent status: {normalized_status!r}. Expected granted, required, or revoked.")
    if not tenant_key or not contact_key:
        raise ValueError("tenant_id and contact_id are required.")

    sess = db.session()
    try:
        row = (
            sess.query(ConsentLedger)
            .filter(
                ConsentLedger.tenant_id == tenant_key,
                ConsentLedger.contact_id == contact_key,
            )
            .one_or_none()
        )
        old_status = row.status if row is not None else None

        if row is None:
            row = ConsentLedger(
                tenant_id=tenant_key,
                contact_id=contact_key,
                status=normalized_status,
                source=normalized_source or None,
            )
            sess.add(row)
            action = "compliance.consent_granted" if normalized_status == "granted" else "compliance.consent_recorded"
        else:
            row.status = normalized_status
            row.source = normalized_source or row.source
            action = "compliance.consent_updated"

        sess.flush()
        serialized = _serialize_consent_entry(row)

        sess.add(
            AuditLog(
                tenant_id=tenant_key,
                actor_id=actor,
                actor_type="operator",
                action=action,
                payload=json.dumps(
                    {
                        "contact_id": contact_key,
                        "old_status": old_status,
                        "new_status": normalized_status,
                        "source": normalized_source or None,
                        "correlation_id": correlation_id,
                    },
                    ensure_ascii=True,
                ),
            )
        )
        sess.commit()

        logger.info(
            "CONSENT_RECORD_%s tenant_id=%s contact_id_hash=%s status=%s correlation_id=%s",
            action.upper().replace(".", "_"),
            tenant_key,
            _hash_contact(contact_key),
            normalized_status,
            correlation_id,
        )
        return serialized
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def _hash_contact(contact_id: str) -> str:
    """Return a short hash of the contact ID for log-safe references."""
    import hashlib
    return hashlib.sha1(contact_id.encode("utf-8")).hexdigest()[:12]


def _serialize_consent_entry(row: ConsentLedger) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "contact_id": row.contact_id,
        "status": row.status,
        "source": row.source,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# ---------------------------------------------------------------------------
# Template Sendability
# ---------------------------------------------------------------------------

def map_provider_state_to_display(
    provider_state: str | None,
    *,
    updated_at: datetime | None = None,
    stale_threshold_seconds: int | None = None,
) -> tuple[str, bool]:
    """Map an internal provider_state to a display state and stale flag.

    The "stale" flag is True when the provider state has been in a
    transitional state (e.g. pending_approval) longer than the threshold,
    implying the sync data may be outdated.

    Safe default: unmapped/unknown states resolve to DISPLAY_STATE_UNKNOWN,
    which is treated as non-sendable.

    Returns:
        (display_state, is_stale) tuple.
    """
    raw = str(provider_state or "").strip().lower()
    display = _PROVIDER_STATE_MAP.get(raw, DISPLAY_STATE_UNKNOWN)

    is_stale = False
    if raw in _STALE_ELIGIBLE_STATES and updated_at is not None:
        threshold = int(stale_threshold_seconds or DEFAULT_STALE_THRESHOLD_SECONDS)
        now = datetime.now(timezone.utc)
        updated_aware = updated_at if updated_at.tzinfo is not None else updated_at.replace(tzinfo=timezone.utc)
        age_seconds = (now - updated_aware).total_seconds()
        if age_seconds > threshold:
            display = DISPLAY_STATE_STALE
            is_stale = True

    return display, is_stale


def get_template_sendability_states(
    db,
    tenant_id: str,
    *,
    stale_threshold_seconds: int | None = None,
) -> list[dict[str, Any]]:
    """Return sendability state for every tenant template draft.

    Each entry includes:
      - workflow_slug, title, category_label
      - provider_state (raw)
      - display_state (approved | pending | rejected | paused | stale | unknown)
      - is_stale (bool)
      - is_sendable (bool) — True only for display_state == "approved"
      - last_updated (ISO timestamp or None)

    Stale/unknown states are surfaced explicitly; the system never pretends
    a template is sendable when the state is unavailable.
    """
    tenant_key = str(tenant_id or "").strip()
    if not tenant_key:
        return []

    sess = db.session()
    try:
        rows = (
            sess.query(StarterTemplateDraft)
            .filter(StarterTemplateDraft.tenant_id == tenant_key)
            .order_by(StarterTemplateDraft.created_at.asc())
            .all()
        )
        result = []
        for row in rows:
            display_state, is_stale = map_provider_state_to_display(
                row.provider_state,
                updated_at=row.updated_at,
                stale_threshold_seconds=stale_threshold_seconds,
            )
            result.append(
                {
                    "workflow_slug": row.workflow_slug,
                    "title": row.title,
                    "category_label": row.category_label,
                    "provider_state": row.provider_state,
                    "display_state": display_state,
                    "is_stale": is_stale,
                    "is_sendable": display_state in SENDABLE_DISPLAY_STATES,
                    "consent_state": row.consent_state,
                    "sendability_state": row.sendability_state,
                    "last_updated": row.updated_at.isoformat() if row.updated_at else None,
                    "last_submission_at": row.last_submission_at.isoformat() if row.last_submission_at else None,
                }
            )
        return result
    finally:
        sess.close()


def evaluate_sendability_alert(template_states: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute the quality/sendability alert level across all template states.

    Alert levels (AC 12.6.3):
      no_issue       — all templates are approved or there are no templates
      warning        — at least one template is pending or stale
      action_required — at least one template is rejected, paused, or unknown

    Returns:
        dict with keys: level (str), guidance (str), details (dict).
    """
    if not template_states:
        return {
            "level": ALERT_NO_ISSUE,
            "guidance": _ALERT_GUIDANCE[ALERT_NO_ISSUE],
            "details": {"total": 0, "sendable": 0, "blocked": 0},
        }

    sendable_count = sum(1 for t in template_states if t.get("is_sendable"))
    stale_count = sum(1 for t in template_states if t.get("is_stale"))
    pending_count = sum(1 for t in template_states if t.get("display_state") == DISPLAY_STATE_PENDING)
    action_states = {DISPLAY_STATE_REJECTED, DISPLAY_STATE_PAUSED, DISPLAY_STATE_UNKNOWN}
    action_required_count = sum(1 for t in template_states if t.get("display_state") in action_states)
    total = len(template_states)

    if action_required_count > 0:
        level = ALERT_ACTION_REQUIRED
    elif stale_count > 0 or pending_count > 0:
        level = ALERT_WARNING
    else:
        level = ALERT_NO_ISSUE

    return {
        "level": level,
        "guidance": _ALERT_GUIDANCE[level],
        "details": {
            "total": total,
            "sendable": sendable_count,
            "blocked": total - sendable_count,
            "pending": pending_count,
            "stale": stale_count,
            "action_required": action_required_count,
        },
    }


# ---------------------------------------------------------------------------
# Pre-dispatch eligibility gate
# ---------------------------------------------------------------------------

def check_dispatch_eligibility(
    *,
    consent_status: str | None,
    provider_state: str | None,
    updated_at: datetime | None = None,
    stale_threshold_seconds: int | None = None,
    correlation_id: str = "n/a",
) -> dict[str, Any]:
    """Gate function that determines whether a template dispatch is allowed.

    Called before the outbound send path commits a template activation.
    Returns a structured eligibility result with a stable reason_code that
    the caller can use for audit logging and operator-facing messaging.

    Evaluation order (stops at first blocked condition):
      1. Missing/revoked consent → REASON_CONSENT_MISSING
      2. Stale or unknown provider state → REASON_STALE_OR_UNKNOWN
      3. Non-sendable display state → REASON_TEMPLATE_NOT_SENDABLE

    AC 12.6.7: This gate only covers pre-dispatch eligibility. It does NOT
    affect retry/fallback behavior for in-flight sends that already passed
    the gate.

    Returns:
        dict with keys:
            eligible (bool), reason_code (str|None), reason_message (str|None),
            display_state (str), is_stale (bool), correlation_id (str).
    """
    normalized_consent = str(consent_status or "").strip().lower()
    display_state, is_stale = map_provider_state_to_display(
        provider_state,
        updated_at=updated_at,
        stale_threshold_seconds=stale_threshold_seconds,
    )

    if normalized_consent != "granted":
        return _blocked(REASON_CONSENT_MISSING, display_state, is_stale, correlation_id)

    if is_stale or display_state == DISPLAY_STATE_UNKNOWN:
        return _blocked(REASON_STALE_OR_UNKNOWN, display_state, is_stale, correlation_id)

    if display_state not in SENDABLE_DISPLAY_STATES:
        return _blocked(REASON_TEMPLATE_NOT_SENDABLE, display_state, is_stale, correlation_id)

    return {
        "eligible": True,
        "reason_code": None,
        "reason_message": None,
        "display_state": display_state,
        "is_stale": is_stale,
        "correlation_id": correlation_id,
    }


def _blocked(
    reason_code: str,
    display_state: str,
    is_stale: bool,
    correlation_id: str,
) -> dict[str, Any]:
    return {
        "eligible": False,
        "reason_code": reason_code,
        "reason_message": _REASON_MESSAGES[reason_code],
        "display_state": display_state,
        "is_stale": is_stale,
        "correlation_id": correlation_id,
    }


def record_blocked_dispatch(
    sess,
    *,
    tenant_id: str,
    workflow_slug: str,
    reason_code: str,
    actor_id: str | None,
    correlation_id: str,
    display_state: str,
    is_stale: bool,
) -> None:
    """Write an audit log entry for a blocked dispatch attempt.

    The payload is sanitized before persistence (AC 12.6.5: no secret leakage).
    """
    payload = json.dumps(
        {
            "workflow_slug": workflow_slug,
            "reason_code": reason_code,
            "display_state": display_state,
            "is_stale": is_stale,
            "correlation_id": correlation_id,
        },
        ensure_ascii=True,
    )
    sess.add(
        AuditLog(
            tenant_id=str(tenant_id or ""),
            actor_id=str(actor_id or "operator"),
            actor_type="operator",
            action="compliance.dispatch_blocked",
            payload=sanitize_text(payload),
        )
    )
    logger.warning(
        "COMPLIANCE_DISPATCH_BLOCKED tenant_id=%s workflow_slug=%s reason=%s display_state=%s is_stale=%s correlation_id=%s",
        tenant_id,
        workflow_slug,
        reason_code,
        display_state,
        is_stale,
        correlation_id,
    )
