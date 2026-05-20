from __future__ import annotations

import copy
import hashlib
import json
import logging
from pathlib import Path
from decimal import Decimal, InvalidOperation
from typing import Any

from app.models import AuditLog, StarterTemplateDraft
from app.models.base import utcnow
from app.services.observability import get_correlation_id

logger = logging.getLogger(__name__)

STARTER_PACK_KEY = "india_d2c_starter_pack"
STARTER_PACK_LABEL = "India D2C starter pack"
STARTER_PACK_COHORT_SLICE = "sprint3-conditional"
CATEGORY_EXPLAINER_URL = "https://developers.facebook.com/docs/whatsapp/pricing"
ALLOWED_PROVIDER_STATES_FOR_SEND = {"approved", "active"}
INDIA_PRICE_TABLE_SCOPE = "india_only"
INDIA_PRICE_TABLE_VERSION = "v1"
DEFAULT_ESTIMATE_CURRENCY = "INR"

_STARTER_CATALOGUE: tuple[dict[str, str], ...] = (
    {
        "workflow_slug": "abandoned_cart_reminder",
        "title": "Abandoned Cart Follow-up",
        "body": "Hi {{customer_name}}, your cart is waiting. Complete checkout today and reply here if you need help.",
        "category_label": "MARKETING",
    },
    {
        "workflow_slug": "order_status_update",
        "title": "Order Status Update",
        "body": "Hi {{customer_name}}, order {{order_id}} is now {{order_status}}. Reply to this message for support.",
        "category_label": "UTILITY",
    },
    {
        "workflow_slug": "cod_confirmation",
        "title": "Cash on Delivery Confirmation",
        "body": "Hi {{customer_name}}, please confirm Cash on Delivery for order {{order_id}} by replying YES.",
        "category_label": "UTILITY",
    },
    {
        "workflow_slug": "support_triage",
        "title": "Support Triage",
        "body": "Hi {{customer_name}}, we received your request. Share your order ID and issue summary so we can help faster.",
        "category_label": "UTILITY",
    },
)


def get_starter_pack_catalogue() -> list[dict[str, str]]:
    return [copy.deepcopy(item) for item in _STARTER_CATALOGUE]


def is_starter_pack_enabled_for_tenant(app, tenant_id: str) -> bool:
    enabled = bool(app.config.get("INDIA_D2C_STARTER_PACK_ENABLED", False))
    if not enabled:
        return False

    normalized_tenant = str(tenant_id or "").strip().lower()
    if not normalized_tenant:
        return False

    allowlist = set(app.config.get("INDIA_D2C_STARTER_PACK_COHORT_TENANTS", []))
    if normalized_tenant in allowlist:
        return True

    percent = int(app.config.get("INDIA_D2C_STARTER_PACK_COHORT_PERCENT", 0))
    if percent <= 0:
        return False
    if percent >= 100:
        return True

    digest = hashlib.sha256(normalized_tenant.encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % 100
    return bucket < percent


def list_tenant_starter_drafts(db, tenant_id: str) -> list[dict[str, Any]]:
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
        return [_serialize_draft(row) for row in rows]
    finally:
        sess.close()


def enable_starter_pack(
    db,
    app,
    *,
    tenant_id: str,
    actor_id: str | None,
    source: str,
    replace_existing: bool,
) -> dict[str, Any]:
    tenant_key = str(tenant_id or "").strip()
    actor = str(actor_id or "operator")
    correlation_id = get_correlation_id() or "n/a"

    created: list[dict[str, Any]] = []
    reused: list[dict[str, Any]] = []
    replaced: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    sess = db.session()
    try:
        for item in _STARTER_CATALOGUE:
            slug = item["workflow_slug"]
            try:
                row = (
                    sess.query(StarterTemplateDraft)
                    .filter(
                        StarterTemplateDraft.tenant_id == tenant_key,
                        StarterTemplateDraft.workflow_slug == slug,
                    )
                    .one_or_none()
                )

                if row is not None and not replace_existing:
                    reused.append(_serialize_draft(row))
                    _append_audit(
                        sess,
                        tenant_id=tenant_key,
                        actor_id=actor,
                        action="starter_pack.draft_reused",
                        payload={
                            "pack_key": STARTER_PACK_KEY,
                            "source": source,
                            "workflow_slug": slug,
                            "category_label": row.category_label,
                        },
                    )
                    _record_starter_pack_telemetry(
                        app,
                        {
                            "event_type": "starter_pack.draft_reused",
                            "tenant_id": tenant_key,
                            "pack_enabled": True,
                            "workflow_slug": slug,
                            "category_label": row.category_label,
                            "draft_created_at": _iso_or_none(row.created_at),
                            "outcome": "reused",
                            "source": source,
                            "correlation_id": correlation_id,
                        },
                    )
                    sess.commit()
                    continue

                if row is None:
                    row = StarterTemplateDraft(
                        tenant_id=tenant_key,
                        workflow_slug=slug,
                        title=item["title"],
                        body=item["body"],
                        category_label=item["category_label"],
                        draft_status="draft",
                        provider_state="draft",
                        consent_state="required",
                        sendability_state="blocked",
                    )
                    sess.add(row)
                    outcome = "created"
                    action = "starter_pack.draft_created"
                else:
                    row.title = item["title"]
                    row.body = item["body"]
                    row.category_label = item["category_label"]
                    row.draft_status = "draft"
                    row.provider_state = "draft"
                    row.sendability_state = "blocked"
                    row.last_submission_outcome = None
                    row.last_submission_at = None
                    outcome = "replaced"
                    action = "starter_pack.draft_replaced"

                sess.flush()
                serialized = _serialize_draft(row)
                _append_audit(
                    sess,
                    tenant_id=tenant_key,
                    actor_id=actor,
                    action=action,
                    payload={
                        "pack_key": STARTER_PACK_KEY,
                        "source": source,
                        "workflow_slug": slug,
                        "category_label": row.category_label,
                        "draft_created_at": serialized.get("created_at"),
                    },
                )
                _record_starter_pack_telemetry(
                    app,
                    {
                        "event_type": action,
                        "tenant_id": tenant_key,
                        "pack_enabled": True,
                        "workflow_slug": slug,
                        "category_label": row.category_label,
                        "draft_created_at": serialized.get("created_at"),
                        "outcome": outcome,
                        "source": source,
                        "correlation_id": correlation_id,
                    },
                )
                sess.commit()

                if outcome == "created":
                    created.append(serialized)
                else:
                    replaced.append(serialized)
            except Exception as exc:  # noqa: BLE001
                sess.rollback()
                logger.exception(
                    "STARTER_PACK_DRAFT_CREATE_FAILED tenant_id=%s workflow_slug=%s source=%s correlation_id=%s",
                    tenant_key,
                    slug,
                    source,
                    correlation_id,
                )
                failures.append(
                    {
                        "workflow_slug": slug,
                        "message": "Draft creation failed. Retry this workflow from the starter-pack panel.",
                        "error": str(exc),
                    }
                )
                _record_starter_pack_telemetry(
                    app,
                    {
                        "event_type": "starter_pack.draft_failed",
                        "tenant_id": tenant_key,
                        "pack_enabled": True,
                        "workflow_slug": slug,
                        "category_label": item["category_label"],
                        "draft_created_at": None,
                        "outcome": "failed",
                        "source": source,
                        "correlation_id": correlation_id,
                    },
                )

        _append_audit(
            sess,
            tenant_id=tenant_key,
            actor_id=actor,
            action="starter_pack.enable",
            payload={
                "pack_key": STARTER_PACK_KEY,
                "source": source,
                "replace_existing": bool(replace_existing),
                "created_count": len(created),
                "reused_count": len(reused),
                "replaced_count": len(replaced),
                "failed_count": len(failures),
                "correlation_id": correlation_id,
            },
        )
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()

    return {
        "pack_key": STARTER_PACK_KEY,
        "pack_label": STARTER_PACK_LABEL,
        "created": created,
        "reused": reused,
        "replaced": replaced,
        "failures": failures,
        "summary": {
            "created": len(created),
            "reused": len(reused),
            "replaced": len(replaced),
            "failed": len(failures),
        },
        "correlation_id": correlation_id,
    }


def update_tenant_starter_draft(
    db,
    *,
    tenant_id: str,
    workflow_slug: str,
    title: str,
    body: str,
    category_label: str,
) -> dict[str, Any] | None:
    sess = db.session()
    try:
        row = (
            sess.query(StarterTemplateDraft)
            .filter(
                StarterTemplateDraft.tenant_id == str(tenant_id or "").strip(),
                StarterTemplateDraft.workflow_slug == str(workflow_slug or "").strip(),
            )
            .one_or_none()
        )
        if row is None:
            return None

        row.title = str(title or "").strip()
        row.body = str(body or "").strip()
        row.category_label = str(category_label or "").strip().upper()
        sess.commit()
        sess.refresh(row)
        return _serialize_draft(row)
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def submit_starter_draft(
    db,
    app,
    *,
    tenant_id: str,
    workflow_slug: str,
    actor_id: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    draft, blocked_reason, _estimate = _transition_draft_state(
        db,
        app,
        tenant_id=tenant_id,
        workflow_slug=workflow_slug,
        actor_id=actor_id,
        target_action="submit",
    )
    return draft, blocked_reason


def activate_starter_draft(
    db,
    app,
    *,
    tenant_id: str,
    workflow_slug: str,
    actor_id: str | None,
    recipient_count: Any,
    preview_only: bool,
    operator_confirmed: bool,
) -> tuple[dict[str, Any] | None, str | None, dict[str, Any] | None]:
    return _transition_draft_state(
        db,
        app,
        tenant_id=tenant_id,
        workflow_slug=workflow_slug,
        actor_id=actor_id,
        target_action="activate",
        recipient_count=recipient_count,
        preview_only=preview_only,
        operator_confirmed=operator_confirmed,
    )


def _transition_draft_state(
    db,
    app,
    *,
    tenant_id: str,
    workflow_slug: str,
    actor_id: str | None,
    target_action: str,
    recipient_count: Any = None,
    preview_only: bool = False,
    operator_confirmed: bool = False,
) -> tuple[dict[str, Any] | None, str | None, dict[str, Any] | None]:
    tenant_key = str(tenant_id or "").strip()
    slug = str(workflow_slug or "").strip()
    actor = str(actor_id or "operator")
    correlation_id = get_correlation_id() or "n/a"

    sess = db.session()
    try:
        row = (
            sess.query(StarterTemplateDraft)
            .filter(
                StarterTemplateDraft.tenant_id == tenant_key,
                StarterTemplateDraft.workflow_slug == slug,
            )
            .one_or_none()
        )
        if row is None:
            return None, "not_found", None

        reason: str | None = None
        outcome = "blocked"
        estimate_payload: dict[str, Any] | None = None

        if target_action == "submit":
            if row.consent_state != "granted":
                reason = "consent_required"
            elif row.provider_state not in {"draft", "rejected"}:
                reason = "already_submitted"
            else:
                row.provider_state = "pending_approval"
                row.draft_status = "submitted"
                row.last_submission_outcome = "submitted"
                row.last_submission_at = utcnow()
                outcome = "submitted"
        else:
            estimate_payload, estimate_error = _build_cost_estimate(
                app,
                category_label=row.category_label,
                recipient_count=recipient_count,
                correlation_id=correlation_id,
            )
            if estimate_error is not None:
                reason = "estimation_failed"
                outcome = "blocked"
            elif row.consent_state != "granted":
                reason = "consent_required"
            elif row.provider_state not in ALLOWED_PROVIDER_STATES_FOR_SEND:
                reason = "approval_required"
            elif row.sendability_state != "ready":
                reason = "sendability_blocked"
            elif preview_only:
                outcome = "preview"
            elif bool(estimate_payload.get("threshold_exceeded")) and not operator_confirmed:
                reason = "cost_confirmation_required"
                outcome = "blocked"
            else:
                row.draft_status = "active"
                row.last_submission_outcome = "activated"
                row.last_submission_at = utcnow()
                outcome = "activated"

        if estimate_payload is not None:
            estimate_payload["operator_confirmation_decision"] = _operator_confirmation_decision(
                preview_only=preview_only,
                operator_confirmed=operator_confirmed,
                threshold_exceeded=bool(estimate_payload.get("threshold_exceeded")),
                blocked_reason=reason,
            )
        elif target_action == "activate":
            estimate_payload = {
                "price_table_scope": INDIA_PRICE_TABLE_SCOPE,
                "price_table_version": INDIA_PRICE_TABLE_VERSION,
                "country_code": str(app.config.get("INDIA_MESSAGE_COST_COUNTRY", "IN") or "IN").strip().upper(),
                "currency": DEFAULT_ESTIMATE_CURRENCY,
                "inputs": {
                    "template_category": str(row.category_label or "").strip().upper(),
                    "recipient_count": None,
                },
                "projected_spend_paisa": None,
                "threshold_paisa": int(app.config.get("INDIA_MESSAGE_COST_WARNING_THRESHOLD_PAISA", 0) or 0),
                "threshold_exceeded": False,
                "estimation_error": estimate_error if 'estimate_error' in locals() else None,
                "operator_confirmation_decision": _operator_confirmation_decision(
                    preview_only=preview_only,
                    operator_confirmed=operator_confirmed,
                    threshold_exceeded=False,
                    blocked_reason=reason,
                ),
            }

        _append_audit(
            sess,
            tenant_id=tenant_key,
            actor_id=actor,
            action=f"starter_pack.{target_action}",
            payload={
                "pack_key": STARTER_PACK_KEY,
                "workflow_slug": slug,
                "category_label": row.category_label,
                "outcome": outcome,
                "blocked_reason": reason,
                "correlation_id": correlation_id,
                "recipient_count": estimate_payload.get("inputs", {}).get("recipient_count") if estimate_payload else None,
                "projected_spend_paisa": estimate_payload.get("projected_spend_paisa") if estimate_payload else None,
                "threshold_paisa": estimate_payload.get("threshold_paisa") if estimate_payload else None,
                "threshold_exceeded": estimate_payload.get("threshold_exceeded") if estimate_payload else None,
                "operator_confirmation_decision": estimate_payload.get("operator_confirmation_decision") if estimate_payload else None,
                "price_table_scope": estimate_payload.get("price_table_scope") if estimate_payload else None,
                "country_code": estimate_payload.get("country_code") if estimate_payload else None,
                "estimation_error": estimate_payload.get("estimation_error") if estimate_payload else None,
            },
        )
        _record_starter_pack_telemetry(
            app,
            {
                "event_type": f"starter_pack.{target_action}",
                "tenant_id": tenant_key,
                "pack_enabled": True,
                "workflow_slug": slug,
                "category_label": row.category_label,
                "draft_created_at": _iso_or_none(row.created_at),
                "outcome": outcome,
                "blocked_reason": reason,
                "correlation_id": correlation_id,
                "recipient_count": estimate_payload.get("inputs", {}).get("recipient_count") if estimate_payload else None,
                "projected_spend_paisa": estimate_payload.get("projected_spend_paisa") if estimate_payload else None,
                "threshold_paisa": estimate_payload.get("threshold_paisa") if estimate_payload else None,
                "threshold_exceeded": estimate_payload.get("threshold_exceeded") if estimate_payload else None,
                "operator_confirmation_decision": estimate_payload.get("operator_confirmation_decision") if estimate_payload else None,
                "price_table_scope": estimate_payload.get("price_table_scope") if estimate_payload else None,
                "country_code": estimate_payload.get("country_code") if estimate_payload else None,
                "estimation_error": estimate_payload.get("estimation_error") if estimate_payload else None,
            },
        )

        sess.commit()
        sess.refresh(row)
        return _serialize_draft(row), reason, estimate_payload
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def _build_cost_estimate(
    app,
    *,
    category_label: str,
    recipient_count: Any,
    correlation_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    normalized_country = str(app.config.get("INDIA_MESSAGE_COST_COUNTRY", "IN") or "IN").strip().upper()
    normalized_category = str(category_label or "").strip().upper()
    count, count_error = _parse_recipient_count(recipient_count)
    if count_error is not None:
        return None, count_error
    if normalized_country != "IN":
        return None, "Cost estimation is limited to India-only pricing configuration."

    price_table = {
        "MARKETING": int(app.config.get("INDIA_MESSAGE_COST_MARKETING_PAISA", 0) or 0),
        "UTILITY": int(app.config.get("INDIA_MESSAGE_COST_UTILITY_PAISA", 0) or 0),
        "AUTHENTICATION": int(app.config.get("INDIA_MESSAGE_COST_AUTHENTICATION_PAISA", 0) or 0),
    }
    unit_price = price_table.get(normalized_category)
    if unit_price is None or unit_price <= 0:
        return None, "Cost estimation requires a supported India template category and price table entry."

    projected_spend_paisa = unit_price * count
    threshold_paisa = int(app.config.get("INDIA_MESSAGE_COST_WARNING_THRESHOLD_PAISA", 0) or 0)
    return {
        "price_table_scope": INDIA_PRICE_TABLE_SCOPE,
        "price_table_version": INDIA_PRICE_TABLE_VERSION,
        "country_code": normalized_country,
        "currency": DEFAULT_ESTIMATE_CURRENCY,
        "inputs": {
            "template_category": normalized_category,
            "recipient_count": count,
        },
        "unit_price_paisa": unit_price,
        "projected_spend_paisa": projected_spend_paisa,
        "projected_spend_inr": _format_inr(projected_spend_paisa),
        "threshold_paisa": threshold_paisa,
        "threshold_inr": _format_inr(threshold_paisa),
        "threshold_exceeded": projected_spend_paisa > threshold_paisa,
        "estimation_error": None,
        "correlation_id": correlation_id,
    }, None


def _parse_recipient_count(value: Any) -> tuple[int | None, str | None]:
    text = str(value or "").strip()
    if not text:
        return None, "Recipient count is required before send confirmation."
    try:
        parsed = int(Decimal(text))
    except (InvalidOperation, ValueError):
        return None, "Recipient count must be a positive integer."
    if parsed <= 0:
        return None, "Recipient count must be a positive integer."
    return parsed, None


def _format_inr(value_paisa: int) -> str:
    return f"{Decimal(value_paisa) / Decimal(100):.2f}"


def _operator_confirmation_decision(
    *,
    preview_only: bool,
    operator_confirmed: bool,
    threshold_exceeded: bool,
    blocked_reason: str | None,
) -> str:
    if blocked_reason == "estimation_failed":
        return "estimation_failed"
    if preview_only:
        return "previewed"
    if threshold_exceeded and operator_confirmed:
        return "confirmed"
    if threshold_exceeded:
        return "required"
    return "not_required"


def _append_audit(sess, *, tenant_id: str, actor_id: str, action: str, payload: dict[str, Any]) -> None:
    sess.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_type="operator",
            action=action,
            payload=json.dumps(payload, ensure_ascii=True),
        )
    )


def _record_starter_pack_telemetry(app, payload: dict[str, Any]) -> None:
    store_path = Path(str(app.config.get("STARTER_PACK_TELEMETRY_PATH", "data/starter_pack_telemetry.jsonl")))
    store_path.parent.mkdir(parents=True, exist_ok=True)

    line = json.dumps(payload, ensure_ascii=True)
    with store_path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _serialize_draft(row: StarterTemplateDraft) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "workflow_slug": row.workflow_slug,
        "title": row.title,
        "body": row.body,
        "category_label": row.category_label,
        "draft_status": row.draft_status,
        "provider_state": row.provider_state,
        "consent_state": row.consent_state,
        "sendability_state": row.sendability_state,
        "last_submission_outcome": row.last_submission_outcome,
        "last_submission_at": _iso_or_none(row.last_submission_at),
        "created_at": _iso_or_none(row.created_at),
        "updated_at": _iso_or_none(row.updated_at),
    }
