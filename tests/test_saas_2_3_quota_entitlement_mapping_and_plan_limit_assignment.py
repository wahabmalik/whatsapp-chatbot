"""
tests/test_saas_2_3_quota_entitlement_mapping_and_plan_limit_assignment.py

Story saas-2.3: Quota Entitlement Mapping and Plan Limit Assignment

Acceptance criteria covered:
  AC-1: ensure_usage_counter creates a usage_counters row with conversations_used=0
        on first activation; idempotent on repeat calls (no mid-cycle wipe).
  AC-2: period_start is taken from subscriptions.current_period_start and is NOT
        altered by subsequent plan changes.
  AC-3: PLAN_QUOTA_MAP in quota_service is the single source of truth:
        starter→2000, pro→5000, business→15000.
  AC-4: Plan changes update conversation_limit immediately; conversations_used and
        period_start are preserved.  ENF-11: upgrade clears is_blocked when
        new_limit > conversations_used.
  AC-5: Every quota lifecycle transition (init, plan_change) writes an audit_log entry.
  AC-6: Integration — checkout.session.completed webhook initialises usage_counters;
        customer.subscription.updated applies plan change and ENF-11 end-to-end.
"""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Stub the `stripe` module so billing_service imports safely without a real key
# ---------------------------------------------------------------------------
_stripe_mock = MagicMock()
sys.modules.setdefault("stripe", _stripe_mock)

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.saas_db import SaaSDatabase  # noqa: E402
from app.models import AuditLog, Subscription, Tenant, UsageCounter  # noqa: E402
from app.models.base import utcnow  # noqa: E402
from app.services.quota_service import (  # noqa: E402
    PLAN_QUOTA_MAP,
    apply_plan_change,
    ensure_usage_counter,
    get_quota_for_plan,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    """In-memory SQLite SaaSDatabase wired for unit tests."""
    saas_db = SaaSDatabase()
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    saas_db._engine = engine
    saas_db._Session = sessionmaker(bind=engine)
    saas_db.create_tables()
    yield saas_db
    saas_db.close()


@pytest.fixture()
def sess(db):
    """Open a single session for a test; rolls back on teardown."""
    s = db.session()
    yield s
    s.rollback()
    s.close()


def _make_tenant(sess, tenant_id: str = "tenant-abc") -> Tenant:
    t = Tenant(id=tenant_id, name="Test Tenant", is_active=True)
    sess.add(t)
    sess.flush()
    return t


def _make_subscription(
    sess,
    tenant_id: str,
    plan_key: str = "starter",
    status: str = "active",
) -> Subscription:
    now = utcnow()
    sub = Subscription(
        tenant_id=tenant_id,
        stripe_customer_id="cus_test",
        stripe_subscription_id="sub_test_" + plan_key,
        plan_key=plan_key,
        status=status,
        conversation_limit=PLAN_QUOTA_MAP[plan_key],
        current_period_start=now,
        current_period_end=now,
    )
    sess.add(sub)
    sess.flush()
    return sub


# ===========================================================================
# AC-3: PLAN_QUOTA_MAP values
# ===========================================================================


class TestPlanQuotaMap:
    def test_starter_limit(self):
        assert PLAN_QUOTA_MAP["starter"] == 2000

    def test_pro_limit(self):
        assert PLAN_QUOTA_MAP["pro"] == 5000

    def test_business_limit(self):
        assert PLAN_QUOTA_MAP["business"] == 15000

    def test_get_quota_for_plan_starter(self):
        assert get_quota_for_plan("starter") == 2000

    def test_get_quota_for_plan_pro(self):
        assert get_quota_for_plan("pro") == 5000

    def test_get_quota_for_plan_business(self):
        assert get_quota_for_plan("business") == 15000

    def test_get_quota_for_unknown_plan_raises(self):
        with pytest.raises(KeyError):
            get_quota_for_plan("enterprise")

    def test_no_extra_plans(self):
        assert set(PLAN_QUOTA_MAP.keys()) == {"starter", "pro", "business"}


# ===========================================================================
# AC-1: ensure_usage_counter — first creation
# ===========================================================================


class TestEnsureUsageCounterInit:
    def test_creates_row_with_zero_used(self, sess):
        """AC-1: Row is created with conversations_used=0 and is_blocked=False."""
        t = _make_tenant(sess)
        now = utcnow()
        counter = ensure_usage_counter(sess, t.id, now)
        assert counter.tenant_id == t.id
        assert counter.conversations_used == 0
        assert counter.is_blocked is False

    def test_period_start_matches_argument(self, sess):
        """AC-2: period_start is set from the supplied datetime."""
        t = _make_tenant(sess)
        period = utcnow()
        counter = ensure_usage_counter(sess, t.id, period)
        assert counter.period_start == period

    def test_row_persisted_after_flush(self, sess):
        """AC-1: Row is visible in the session after flush."""
        t = _make_tenant(sess)
        ensure_usage_counter(sess, t.id, utcnow())
        sess.commit()
        loaded = sess.query(UsageCounter).filter(UsageCounter.tenant_id == t.id).first()
        assert loaded is not None
        assert loaded.conversations_used == 0

    def test_writes_audit_log_on_init(self, sess):
        """AC-5: An audit_log entry with action=quota.init is written on first creation."""
        t = _make_tenant(sess)
        ensure_usage_counter(sess, t.id, utcnow())
        sess.commit()
        entry = (
            sess.query(AuditLog)
            .filter(AuditLog.tenant_id == t.id, AuditLog.action == "quota.init")
            .first()
        )
        assert entry is not None
        assert entry.actor_type == "system"
        payload = json.loads(entry.payload)
        assert payload["conversations_used"] == 0
        assert payload["is_blocked"] is False


# ===========================================================================
# AC-1: ensure_usage_counter — idempotency (no mid-cycle wipe)
# ===========================================================================


class TestEnsureUsageCounterIdempotency:
    def test_returns_existing_row_unchanged(self, sess):
        """AC-1: Calling ensure_usage_counter twice does not reset the existing row."""
        t = _make_tenant(sess)
        period = utcnow()
        counter = ensure_usage_counter(sess, t.id, period)

        # Simulate some usage
        counter.conversations_used = 42
        counter.is_blocked = True
        sess.flush()

        # Call again — must return the same row untouched
        same_counter = ensure_usage_counter(sess, t.id, period)
        assert same_counter.conversations_used == 42
        assert same_counter.is_blocked is True

    def test_no_duplicate_audit_log_on_idempotent_call(self, sess):
        """AC-5: A second ensure_usage_counter does NOT add another audit.init entry."""
        t = _make_tenant(sess)
        ensure_usage_counter(sess, t.id, utcnow())
        ensure_usage_counter(sess, t.id, utcnow())
        sess.commit()
        count = (
            sess.query(AuditLog)
            .filter(AuditLog.tenant_id == t.id, AuditLog.action == "quota.init")
            .count()
        )
        assert count == 1


# ===========================================================================
# AC-4: apply_plan_change — basic propagation
# ===========================================================================


class TestApplyPlanChangeBasic:
    def test_plan_change_does_not_reset_conversations_used(self, sess):
        """AC-4: conversations_used is preserved across a plan change."""
        t = _make_tenant(sess)
        ensure_usage_counter(sess, t.id, utcnow())
        counter = sess.query(UsageCounter).filter(UsageCounter.tenant_id == t.id).first()
        counter.conversations_used = 1500
        sess.flush()

        apply_plan_change(sess, tenant_id=t.id, new_plan_key="pro", new_limit=5000)

        reloaded = sess.query(UsageCounter).filter(UsageCounter.tenant_id == t.id).first()
        assert reloaded.conversations_used == 1500

    def test_plan_change_does_not_reset_period_start(self, sess):
        """AC-2 / AC-4: period_start is preserved across a plan change."""
        t = _make_tenant(sess)
        period = utcnow()
        ensure_usage_counter(sess, t.id, period)

        apply_plan_change(sess, tenant_id=t.id, new_plan_key="pro", new_limit=5000)

        reloaded = sess.query(UsageCounter).filter(UsageCounter.tenant_id == t.id).first()
        # SQLite strips tzinfo on round-trip; compare naive values only
        stored = reloaded.period_start.replace(tzinfo=None) if reloaded.period_start.tzinfo else reloaded.period_start
        expected = period.replace(tzinfo=None) if period.tzinfo else period
        assert stored == expected

    def test_writes_audit_log_on_plan_change(self, sess):
        """AC-5: An audit_log entry with action=quota.plan_change is written."""
        t = _make_tenant(sess)
        ensure_usage_counter(sess, t.id, utcnow())

        apply_plan_change(sess, tenant_id=t.id, new_plan_key="pro", new_limit=5000)
        sess.commit()

        entry = (
            sess.query(AuditLog)
            .filter(AuditLog.tenant_id == t.id, AuditLog.action == "quota.plan_change")
            .first()
        )
        assert entry is not None
        assert entry.actor_type == "system"
        payload = json.loads(entry.payload)
        assert payload["new_plan_key"] == "pro"
        assert payload["new_limit"] == 5000

    def test_no_counter_returns_no_counter_action(self, sess):
        """apply_plan_change returns {'action': 'no_counter'} when no row exists."""
        t = _make_tenant(sess)
        result = apply_plan_change(sess, tenant_id=t.id, new_plan_key="pro", new_limit=5000)
        assert result == {"action": "no_counter"}


# ===========================================================================
# AC-4 / ENF-11: plan upgrade clears is_blocked
# ===========================================================================


class TestENF11PlanUpgradeClearsBlocked:
    def test_upgrade_clears_is_blocked_when_new_limit_exceeds_used(self, sess):
        """ENF-11: Upgrade unblocks tenant when new_limit > conversations_used."""
        t = _make_tenant(sess)
        ensure_usage_counter(sess, t.id, utcnow())
        counter = sess.query(UsageCounter).filter(UsageCounter.tenant_id == t.id).first()
        counter.conversations_used = 1999   # hit starter limit
        counter.is_blocked = True
        sess.flush()

        result = apply_plan_change(
            sess, tenant_id=t.id, new_plan_key="pro", new_limit=5000
        )

        reloaded = sess.query(UsageCounter).filter(UsageCounter.tenant_id == t.id).first()
        assert reloaded.is_blocked is False
        assert result == {"action": "plan_change_applied", "unblocked": True}

    def test_upgrade_audit_records_unblocked_true(self, sess):
        """ENF-11: audit_log payload records unblocked=True."""
        t = _make_tenant(sess)
        ensure_usage_counter(sess, t.id, utcnow())
        counter = sess.query(UsageCounter).filter(UsageCounter.tenant_id == t.id).first()
        counter.conversations_used = 2000
        counter.is_blocked = True
        sess.flush()

        apply_plan_change(sess, tenant_id=t.id, new_plan_key="business", new_limit=15000)
        sess.commit()

        entry = (
            sess.query(AuditLog)
            .filter(AuditLog.tenant_id == t.id, AuditLog.action == "quota.plan_change")
            .first()
        )
        payload = json.loads(entry.payload)
        assert payload["unblocked"] is True
        assert payload["was_blocked"] is True

    def test_upgrade_does_not_clear_block_when_limit_equals_used(self, sess):
        """ENF-11: is_blocked NOT cleared when new_limit == conversations_used (not strictly greater)."""
        t = _make_tenant(sess)
        ensure_usage_counter(sess, t.id, utcnow())
        counter = sess.query(UsageCounter).filter(UsageCounter.tenant_id == t.id).first()
        counter.conversations_used = 5000   # exactly at pro limit
        counter.is_blocked = True
        sess.flush()

        result = apply_plan_change(
            sess, tenant_id=t.id, new_plan_key="pro", new_limit=5000
        )

        reloaded = sess.query(UsageCounter).filter(UsageCounter.tenant_id == t.id).first()
        assert reloaded.is_blocked is True
        assert result["unblocked"] is False

    def test_upgrade_does_not_clear_block_when_limit_less_than_used(self, sess):
        """ENF-11: is_blocked NOT cleared when new_limit < conversations_used."""
        t = _make_tenant(sess)
        ensure_usage_counter(sess, t.id, utcnow())
        counter = sess.query(UsageCounter).filter(UsageCounter.tenant_id == t.id).first()
        counter.conversations_used = 5500   # exceeded pro limit
        counter.is_blocked = True
        sess.flush()

        result = apply_plan_change(
            sess, tenant_id=t.id, new_plan_key="pro", new_limit=5000
        )

        reloaded = sess.query(UsageCounter).filter(UsageCounter.tenant_id == t.id).first()
        assert reloaded.is_blocked is True
        assert result["unblocked"] is False


# ===========================================================================
# AC-4: Downgrade — does not modify conversations_used or unblock
# ===========================================================================


class TestPlanDowngrade:
    def test_downgrade_does_not_unblock(self, sess):
        """AC-4: Downgrade leaves is_blocked=False as-is (not blocked before downgrade)."""
        t = _make_tenant(sess)
        ensure_usage_counter(sess, t.id, utcnow())
        counter = sess.query(UsageCounter).filter(UsageCounter.tenant_id == t.id).first()
        counter.conversations_used = 1000  # below new lower limit
        counter.is_blocked = False
        sess.flush()

        apply_plan_change(
            sess, tenant_id=t.id, new_plan_key="starter", new_limit=2000
        )

        reloaded = sess.query(UsageCounter).filter(UsageCounter.tenant_id == t.id).first()
        assert reloaded.is_blocked is False
        assert reloaded.conversations_used == 1000

    def test_downgrade_preserves_conversations_used_above_new_limit(self, sess):
        """AC-4: Downgrade does not wipe conversations_used even if it exceeds new limit."""
        t = _make_tenant(sess)
        ensure_usage_counter(sess, t.id, utcnow())
        counter = sess.query(UsageCounter).filter(UsageCounter.tenant_id == t.id).first()
        counter.conversations_used = 4800  # would exceed starter limit after downgrade
        counter.is_blocked = False
        sess.flush()

        apply_plan_change(
            sess, tenant_id=t.id, new_plan_key="starter", new_limit=2000
        )

        reloaded = sess.query(UsageCounter).filter(UsageCounter.tenant_id == t.id).first()
        assert reloaded.conversations_used == 4800


# ===========================================================================
# AC-6: Integration — billing_service webhook calls quota functions
# ===========================================================================


class TestWebhookIntegration:
    """End-to-end: ingest_webhook_event triggers quota init / plan change."""

    def _make_event(self, event_type: str, **data_obj_kwargs) -> dict:
        """Build a minimal dict-style Stripe event."""
        return {
            "id": "evt_test_" + event_type.replace(".", "_"),
            "type": event_type,
            "data": {
                "object": {
                    "id": "sub_test_001",
                    "subscription": "sub_test_001",
                    "customer": "cus_test_001",
                    "status": "active",
                    "metadata": {
                        "plan_key": "starter",
                        "tenant_id": "tenant-int-001",
                    },
                    "current_period_start": 1700000000,
                    "current_period_end": 1702592000,
                    **data_obj_kwargs,
                }
            },
        }

    @pytest.fixture()
    def int_db(self, tmp_path):
        """SaaSDatabase for integration tests; uses a temp SQLite file to allow
        multiple sessions accessing the same data (needed for cross-session reads)."""
        saas_db = SaaSDatabase()
        db_path = tmp_path / "int_saas.db"
        engine = create_engine(
            f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
        )
        saas_db._engine = engine
        saas_db._Session = sessionmaker(bind=engine)
        saas_db.create_tables()

        # Pre-create tenant for integration tests
        s = saas_db.session()
        try:
            tenant = Tenant(id="tenant-int-001", name="Int Tenant", is_active=True)
            s.add(tenant)
            s.commit()
        finally:
            s.close()

        yield saas_db
        saas_db.close()

    def test_checkout_completed_initialises_usage_counter(self, int_db):
        """AC-6: checkout.session.completed triggers ensure_usage_counter."""
        from app.services.billing_service import ingest_webhook_event

        event = self._make_event(
            "checkout.session.completed",
            status="complete",
            metadata={"plan_key": "starter", "tenant_id": "tenant-int-001"},
        )
        result = ingest_webhook_event(int_db, event, b"{}")
        assert result["status"] == "processed"

        s = int_db.session()
        try:
            counter = (
                s.query(UsageCounter)
                .filter(UsageCounter.tenant_id == "tenant-int-001")
                .first()
            )
            assert counter is not None
            assert counter.conversations_used == 0
            assert counter.is_blocked is False
        finally:
            s.close()

    def test_checkout_completed_writes_quota_init_audit(self, int_db):
        """AC-5/6: audit_log contains quota.init entry after checkout.session.completed."""
        from app.services.billing_service import ingest_webhook_event

        event = self._make_event(
            "checkout.session.completed_auditcheck",
        )
        # Use a distinct event id
        event["id"] = "evt_audit_checkout_001"
        event["type"] = "checkout.session.completed"
        ingest_webhook_event(int_db, event, b"{}")

        s = int_db.session()
        try:
            entry = (
                s.query(AuditLog)
                .filter(
                    AuditLog.tenant_id == "tenant-int-001",
                    AuditLog.action == "quota.init",
                )
                .first()
            )
            assert entry is not None
        finally:
            s.close()

    def test_checkout_completed_idempotent_no_counter_reset(self, int_db):
        """AC-1/6: Duplicate checkout event does not reset existing usage_counters."""
        from app.services.billing_service import ingest_webhook_event

        # First activation
        event1 = self._make_event("checkout.session.completed")
        event1["id"] = "evt_checkout_idem_001"
        ingest_webhook_event(int_db, event1, b"{}")

        # Simulate usage
        s = int_db.session()
        try:
            counter = (
                s.query(UsageCounter)
                .filter(UsageCounter.tenant_id == "tenant-int-001")
                .first()
            )
            counter.conversations_used = 100
            s.commit()
        finally:
            s.close()

        # Second checkout event (different evt id — not a duplicate at billing level)
        event2 = self._make_event("checkout.session.completed")
        event2["id"] = "evt_checkout_idem_002"
        ingest_webhook_event(int_db, event2, b"{}")

        s = int_db.session()
        try:
            counter = (
                s.query(UsageCounter)
                .filter(UsageCounter.tenant_id == "tenant-int-001")
                .first()
            )
            # conversations_used must NOT be reset
            assert counter.conversations_used == 100
        finally:
            s.close()

    def test_subscription_updated_applies_plan_change_enf11(self, int_db):
        """AC-4/6/ENF-11: customer.subscription.updated triggers apply_plan_change and unblocks."""
        from app.services.billing_service import ingest_webhook_event

        # First, activate subscription via checkout event
        checkout_event = self._make_event("checkout.session.completed")
        checkout_event["id"] = "evt_enf11_checkout"
        ingest_webhook_event(int_db, checkout_event, b"{}")

        # Block the tenant (simulate limit reached)
        s = int_db.session()
        try:
            counter = (
                s.query(UsageCounter)
                .filter(UsageCounter.tenant_id == "tenant-int-001")
                .first()
            )
            counter.conversations_used = 1999
            counter.is_blocked = True
            s.commit()
        finally:
            s.close()

        # Plan upgrade via webhook
        upgrade_event = {
            "id": "evt_enf11_upgrade",
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_test_001",
                    "subscription": "sub_test_001",
                    "customer": "cus_test_001",
                    "status": "active",
                    "metadata": {
                        "plan_key": "pro",
                        "tenant_id": "tenant-int-001",
                    },
                    "current_period_start": 1700000000,
                    "current_period_end": 1702592000,
                }
            },
        }
        result = ingest_webhook_event(int_db, upgrade_event, b"{}")
        assert result["status"] == "processed"

        s = int_db.session()
        try:
            counter = (
                s.query(UsageCounter)
                .filter(UsageCounter.tenant_id == "tenant-int-001")
                .first()
            )
            # ENF-11: should be unblocked now
            assert counter.is_blocked is False
            # usage must be preserved
            assert counter.conversations_used == 1999
        finally:
            s.close()

    def test_subscription_updated_plan_change_preserves_period_start(self, int_db):
        """AC-2/6: Plan change does not alter period_start in usage_counters."""
        from app.services.billing_service import ingest_webhook_event

        # Activate
        checkout_event = self._make_event("checkout.session.completed")
        checkout_event["id"] = "evt_period_checkout"
        ingest_webhook_event(int_db, checkout_event, b"{}")

        s = int_db.session()
        try:
            original_period = (
                s.query(UsageCounter)
                .filter(UsageCounter.tenant_id == "tenant-int-001")
                .first()
                .period_start
            )
        finally:
            s.close()

        # Upgrade
        upgrade_event = {
            "id": "evt_period_upgrade",
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_test_001",
                    "subscription": "sub_test_001",
                    "customer": "cus_test_001",
                    "status": "active",
                    "metadata": {"plan_key": "business", "tenant_id": "tenant-int-001"},
                    "current_period_start": 1700000000,
                    "current_period_end": 1702592000,
                }
            },
        }
        ingest_webhook_event(int_db, upgrade_event, b"{}")

        s = int_db.session()
        try:
            counter = (
                s.query(UsageCounter)
                .filter(UsageCounter.tenant_id == "tenant-int-001")
                .first()
            )
            assert counter.period_start == original_period
        finally:
            s.close()
