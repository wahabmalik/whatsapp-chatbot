---
story_id: "saas-2.3"
story_key: "saas-2-3-quota-entitlement-mapping-and-plan-limit-assignment"
status: "done"
epic: saas-2
story: "3"
sprint_status_file: _bmad-output/implementation-artifacts/sprint-status-saas-v1.yaml
created: "2026-05-05"
updated: "2026-05-05"
depends_on:
  - saas-2-2-stripe-webhook-ingestion-and-entitlement-state-machine
---

# Story saas-2.3: Quota Entitlement Mapping and Plan Limit Assignment

## User Story

As the usage enforcement system,
I want the active subscription to automatically map to a monthly conversation quota,
so that the enforcement layer always knows how many conversations a tenant is allowed
this billing period without hardcoding limits in application logic.

## Acceptance Criteria

1. Given a tenant transitions to `active` entitlement state (via `checkout.session.completed`
   or `invoice.paid` webhook), when quota initialisation runs, then a `usage_counters` row is
   created for that tenant with `conversations_used = 0` if it does not already exist; an
   existing row is left unchanged (idempotency — no mid-cycle wipe).

2. The `usage_counters.period_start` is set to `subscriptions.current_period_start` on
   first initialisation and is NOT altered by subsequent plan changes.

3. `subscriptions.conversation_limit` is set from the plan catalogue:
   `starter` → 2 000, `pro` → 5 000, `business` → 15 000. This mapping lives in
   `app/services/quota_service.py:PLAN_QUOTA_MAP` — never hardcoded in caller logic.

4. When a plan change occurs (via `customer.subscription.updated`):
   - `subscriptions.conversation_limit` is updated immediately (no billing-period boundary required).
   - `usage_counters.conversations_used` and `usage_counters.period_start` are **not** touched.
   - ENF-11: if `new_limit > conversations_used` **and** `is_blocked = TRUE`, `is_blocked` is
     cleared atomically in the same DB flush.

5. Every quota lifecycle transition (counter init and plan change) writes an `audit_log`
   entry with `actor_type = "system"` and the relevant payload.

6. All transitions (checkout activation, invoice.paid, plan upgrade, plan downgrade) are
   exercised by the pytest suite and pass green.

## Tasks / Subtasks

- [x] Create `app/services/quota_service.py` with PLAN_QUOTA_MAP, `ensure_usage_counter`, and
      `apply_plan_change` (AC: 1, 2, 3, 4, 5)
- [x] In `billing_service._apply_subscription_transition`: call `ensure_usage_counter` after
      `checkout.session.completed` and `invoice.paid` transitions (AC: 1, 2)
- [x] In `billing_service._apply_subscription_transition`: call `apply_plan_change` after
      `customer.subscription.updated` modifies `plan_key` / `conversation_limit` (AC: 4, 5)
- [x] Add `tests/test_saas_2_3_quota_entitlement_mapping_and_plan_limit_assignment.py` covering
      all ACs including mid-cycle change and ENF-11 (AC: 1–6)
- [x] Run targeted Story 2.3 tests and fix regressions

## Dev Notes

### Source Mapping
- Story source: `_bmad-output/planning-artifacts/epics-saas-v1.md` §Story 2.3.
- Architecture references: `architecture-whatsapp-ai-bot-saas-v1.md` §4 (schema), §8 (ENF rules).
- Predecessor: saas-2.2 provides the Stripe webhook ingestion pipeline
  (`billing_service.ingest_webhook_event` and `_apply_subscription_transition`).

### Existing Code Patterns
- `app/services/billing_service.py` contains `CONVERSATION_LIMITS` dict (same values as
  PLAN_QUOTA_MAP; keep billing_service using its own dict for backward-compat; quota_service
  is the new canonical source for quota-specific logic).
- `app/models/__init__.py` — `UsageCounter` (tenant_id PK, period_start, conversations_used,
  is_blocked, updated_at), `AuditLog`, `Subscription` models are already defined.
- `SaaSDatabase.session()` returns a raw SQLAlchemy `Session`; callers manage lifecycle.
  `db.session()` is the pattern used throughout (see billing_service.py).
- The session passed into `_apply_subscription_transition` is already inside a transaction
  managed by `ingest_webhook_event`; quota functions receive the **same** `sess` and call
  `sess.flush()` — **not** `sess.commit()` — to stay within the outer transaction.

### ENF Rules Applied
- ENF-11: plan upgrade clears `is_blocked` if `new_limit > conversations_used` — implemented
  in `apply_plan_change`.
- ENF-06: `usage_counters` update and audit entry must be flushed in the same transaction as
  the subscription update — achieved by passing `sess` through.

### Key Design Decisions
- `ensure_usage_counter` is idempotent: if the row exists, return it unchanged. This handles
  duplicate webhook delivery (covered by billing_events idempotency in Story 2.2 first, but
  quota init must be safe regardless).
- Plan downgrade (new_limit ≤ conversations_used): `conversation_limit` is lowered, but
  `is_blocked` is NOT cleared (ENF-11 only fires on upgrade; blocking logic for downgrade
  is the enforcement layer's responsibility in a future story).
- `apply_plan_change` is called only when `plan_key` changes in the `customer.subscription.updated`
  handler — guarded by `if plan_key in CONVERSATION_LIMITS`.
- Do NOT call `apply_plan_change` from `checkout.session.completed` — that path calls
  `ensure_usage_counter` which already handles first-time init.

### Test Fixture Pattern
Follow `test_saas_1_1_schema_and_tenant_model.py`:
- Use `SaaSDatabase` with `sqlite:///:memory:` and direct `db._engine` / `db._Session` injection.
- Create Tenant + Subscription rows in test fixtures.
- Call quota_service functions directly (unit tests) AND via `ingest_webhook_event` mock
  (integration tests).

## Dev Agent Record

### Agent Model Used
Claude Sonnet 4.6 (Amelia)

### Debug Log
- 2026-05-05: Story file created (bmad-create-story).
- 2026-05-05: Implementation complete; 29/29 tests green.

### Completion Notes
- 2026-05-05: All 29 tests pass green (29/29). quota_service.py implemented with PLAN_QUOTA_MAP,
  ensure_usage_counter, and apply_plan_change. billing_service updated to call quota functions.
  Fixed one test assertion (SQLite tz-naive round-trip) — implementation correct throughout.

## File List
- _bmad-output/implementation-artifacts/saas-2-3-quota-entitlement-mapping-and-plan-limit-assignment.md
- _bmad-output/implementation-artifacts/sprint-status-saas-v1.yaml
- app/services/quota_service.py  (new)
- app/services/billing_service.py  (modified)
- tests/test_saas_2_3_quota_entitlement_mapping_and_plan_limit_assignment.py  (new)

### Change Log
- 2026-05-05: Story file created (bmad-create-story).
