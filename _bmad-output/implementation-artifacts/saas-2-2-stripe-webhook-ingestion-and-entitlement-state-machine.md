---
story_id: "saas-2.2"
story_key: "saas-2-2-stripe-webhook-ingestion-and-entitlement-state-machine"
status: "done"
epic: saas-2
story: "2"
sprint_status_file: _bmad-output/implementation-artifacts/sprint-status-saas-v1.yaml
created: "2026-05-05"
updated: "2026-05-05"
depends_on:
  - saas-2-1-plan-selection-ui-and-stripe-checkout-flow
---

# Story saas-2.2: Stripe Webhook Ingestion and Entitlement State Machine

## User Story

As the billing engine,
I want Stripe lifecycle webhook events ingested idempotently and projected into the entitlement state,
so that subscription changes take effect reliably without manual intervention and without duplicate processing.

## Acceptance Criteria

1. Given a Stripe webhook event is received at the Flask webhook endpoint, when the webhook
	signature is verified using the Stripe signing secret, then the raw event is stored append-only
	in billing_events keyed on Stripe event ID and subsequent delivery of the same event ID is a no-op.

2. For checkout.session.completed, invoice.paid, customer.subscription.updated,
	customer.subscription.deleted, and invoice.payment_failed events, the subscriptions record for the
	affected tenant is updated using the entitlement state mapping:
	active|trialing -> entitled, past_due|unpaid -> blocked path, canceled -> disabled.

3. Entitlement transitions are recorded in audit_log with actor_type=stripe_webhook and include
	event metadata (event_id, event_type, from_status, to_status).

4. Failed webhook signature verification returns 400; valid events with no handler return 200
	and are logged as unhandled.

5. ENF-01 is preserved: only webhook-confirmed active/trialing status allows bot activation;
	pending_webhook from Story 2.1 remains non-entitled.

## Tasks / Subtasks

- [x] Add billing event ledger model with idempotency key on stripe_event_id (AC: 1)
- [x] Implement Stripe webhook verification helper and ingestion pipeline in billing_service.py (AC: 1, 4)
- [x] Implement supported event dispatch and subscription status transitions for 5 Stripe event types (AC: 2)
- [x] Write audit_log entries for webhook-driven subscription transitions (AC: 3)
- [x] Wire unauthenticated webhook route POST /billing/webhook/stripe in views_auth.py (AC: 1, 4)
- [x] Add STRIPE_WEBHOOK_SECRET config key (AC: 1)
- [x] Add tests test_saas_2_2_stripe_webhook_ingestion_and_entitlement_state_machine.py (AC: 1-5)
- [x] Run targeted Story 2.2 tests and fix regressions

## Dev Notes

- Story source: _bmad-output/planning-artifacts/epics-saas-v1.md section Story 2.2.
- Predecessor dependency: saas-2.1 creates subscriptions rows in pending_webhook.
- This story intentionally upgrades status only from Stripe webhook-confirmed events.
- The webhook endpoint is server-to-server and therefore auth/CSRF exempt by design.
- billing_events is append-only and idempotent by unique stripe_event_id.
- audit_log entries use actor_type="stripe_webhook" and action="subscription.transition".

## Dev Agent Record

### Agent Model Used

GPT-5.3-Codex (Amelia)

### Debug Log

- 2026-05-05: Created story artifact and implemented service/model/route changes for Stripe webhook ingestion.
- 2026-05-05: Added billing_events model and subscription transition logic with audit logging.
- 2026-05-05: Added webhook route POST /billing/webhook/stripe and STRIPE_WEBHOOK_SECRET config support.
- 2026-05-05: Added and validated Story 2.2 pytest suite.

### Completion Notes

- billing_service.py now provides construct_stripe_event and ingest_webhook_event with event-id idempotency.
- Supported Stripe events update subscriptions deterministically and preserve ENF-01 entitlement gate.
- Duplicate webhook deliveries are no-ops by stripe_event_id uniqueness in billing_events.
- Invalid signatures are rejected with 400; unhandled events return 200 and are ledgered.

## File List

- _bmad-output/implementation-artifacts/saas-2-2-stripe-webhook-ingestion-and-entitlement-state-machine.md
- _bmad-output/implementation-artifacts/sprint-status-saas-v1.yaml
- app/models/__init__.py
- app/services/billing_service.py
- app/views_auth.py
- app/config.py
- tests/test_saas_2_2_stripe_webhook_ingestion_and_entitlement_state_machine.py

### Change Log

- 2026-05-05: Story created and implemented to done.
