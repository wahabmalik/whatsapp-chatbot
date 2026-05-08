"""app/services/quota_service.py

Story saas-2.3: Quota Entitlement Mapping and Plan Limit Assignment

Responsibilities:
  - Maintain the single source of truth for plan → quota mapping.
  - Initialise usage_counters for a tenant on first subscription activation.
  - Apply quota changes on plan upgrade/downgrade and enforce ENF-11.
  - Write audit_log entries for every quota lifecycle transition.

ENF rules enforced here:
  ENF-11: Plan upgrade clears is_blocked if new_limit > current conversations_used.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from app.models import AuditLog, UsageCounter
from app.models.base import utcnow

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Plan quota map — single source of truth (arch §9, ENF-01/ENF-02)
# Starter: 2 000 / Pro: 5 000 / Business: 15 000 conversations/month
# ---------------------------------------------------------------------------

PLAN_QUOTA_MAP: dict[str, int] = {
    "starter": 2000,
    "pro": 5000,
    "business": 15000,
}


def get_quota_for_plan(plan_key: str) -> int:
    """Return the monthly conversation limit for *plan_key*.

    Raises ``KeyError`` if the plan_key is not in the catalogue.
    """
    return PLAN_QUOTA_MAP[plan_key]


# ---------------------------------------------------------------------------
# Usage counter lifecycle
# ---------------------------------------------------------------------------


def ensure_usage_counter(
    sess,
    tenant_id: str,
    period_start: datetime,
    *,
    actor_id: str = "system",
) -> UsageCounter:
    """Initialise a ``usage_counters`` row for *tenant_id* if one does not exist.

    Idempotent: if a row is already present it is returned unchanged —
    ``conversations_used`` and ``period_start`` are **never** touched by this
    function (no mid-cycle counter wipe).

    An ``audit_log`` entry with ``action = "quota.init"`` is written only on
    first creation.

    The caller is responsible for the enclosing transaction; this function
    calls ``sess.flush()`` but not ``sess.commit()``.
    """
    counter = (
        sess.query(UsageCounter)
        .filter(UsageCounter.tenant_id == tenant_id)
        .first()
    )
    if counter is not None:
        logger.debug(
            "QUOTA_COUNTER_EXISTS tenant_id=%s conversations_used=%d",
            tenant_id,
            counter.conversations_used,
        )
        return counter

    counter = UsageCounter(
        tenant_id=tenant_id,
        period_start=period_start,
        conversations_used=0,
        is_blocked=False,
    )
    sess.add(counter)

    sess.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_type="system",
            action="quota.init",
            payload=json.dumps(
                {
                    "period_start": period_start.isoformat() if hasattr(period_start, "isoformat") else str(period_start),
                    "conversations_used": 0,
                    "is_blocked": False,
                }
            ),
        )
    )

    sess.flush()
    logger.info(
        "QUOTA_COUNTER_INIT tenant_id=%s period_start=%s",
        tenant_id,
        period_start,
    )
    return counter


def apply_plan_change(
    sess,
    *,
    tenant_id: str,
    new_plan_key: str,
    new_limit: int,
    actor_id: str = "system",
) -> dict:
    """Apply a plan change to ``usage_counters`` and enforce ENF-11.

    ENF-11: If ``new_limit > conversations_used`` and ``is_blocked = TRUE``,
    ``is_blocked`` is cleared atomically in the same flush.

    ``conversations_used`` and ``period_start`` are **not** modified — the
    billing period is preserved across plan changes.

    If no ``usage_counters`` row exists (tenant not yet activated), a log
    warning is emitted and ``{"action": "no_counter"}`` is returned; the row
    will be created by ``ensure_usage_counter`` when the tenant activates.

    An ``audit_log`` entry with ``action = "quota.plan_change"`` is written.

    Returns a dict describing the outcome.
    """
    counter = (
        sess.query(UsageCounter)
        .filter(UsageCounter.tenant_id == tenant_id)
        .first()
    )
    if counter is None:
        logger.warning(
            "QUOTA_PLAN_CHANGE_NO_COUNTER tenant_id=%s new_plan=%s — "
            "counter will be created on activation",
            tenant_id,
            new_plan_key,
        )
        return {"action": "no_counter"}

    was_blocked = counter.is_blocked
    unblocked = False

    # ENF-11: plan upgrade clears is_blocked when new limit exceeds current usage
    if new_limit > counter.conversations_used and counter.is_blocked:
        counter.is_blocked = False
        unblocked = True

    counter.updated_at = utcnow()

    sess.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_type="system",
            action="quota.plan_change",
            payload=json.dumps(
                {
                    "new_plan_key": new_plan_key,
                    "new_limit": new_limit,
                    "conversations_used": counter.conversations_used,
                    "was_blocked": was_blocked,
                    "unblocked": unblocked,
                }
            ),
        )
    )

    sess.flush()
    logger.info(
        "QUOTA_PLAN_CHANGE tenant_id=%s plan=%s new_limit=%d was_blocked=%s unblocked=%s",
        tenant_id,
        new_plan_key,
        new_limit,
        was_blocked,
        unblocked,
    )
    return {"action": "plan_change_applied", "unblocked": unblocked}
