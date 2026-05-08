---
story_id: "saas-2.1"
story_key: "saas-2-1-plan-selection-ui-and-stripe-checkout-flow"
status: "done"
epic: saas-2
story: "1"
sprint_status_file: _bmad-output/implementation-artifacts/sprint-status-saas-v1.yaml
created: "2026-05-05"
updated: "2026-05-05"
depends_on:
  - saas-1-3-tenant-isolation-contract-and-cross-tenant-access-denial-tests
---

# Story saas-2.1: Plan Selection UI and Stripe Checkout Flow

## User Story

As a newly registered customer,
I want to select a plan and complete payment via Stripe Checkout,
so that my subscription is activated and my bot can proceed to onboarding.

## Acceptance Criteria

1. Given a logged-in user who has not yet selected a plan, when they view the plan selection page,
   then the three v1 plans are presented with price and conversation limit clearly stated:
   Starter ($29/mo, 2 000 conversations), Pro ($49/mo, 5 000), Business ($99/mo, 15 000).

2. When the user selects a plan and clicks Subscribe, then they are redirected to Stripe Checkout
   with the correct price ID and a success/cancel callback URL that includes a session identifier.

3. When Stripe Checkout completes successfully, then the user is redirected back to the app;
   a `subscription` record is created in `pending_webhook` state; the app does not activate
   entitlements until the webhook is confirmed (Story 2.2).

4. No bot activation is possible while subscription state is not `active` or `trialing`.

5. Given a customer with an active subscription, when they click 'Manage billing', then they are
   redirected to the Stripe Customer Portal via `GET /billing/portal`.

6. CSRF protection is active on `POST /billing/checkout`; missing or invalid CSRF token returns
   400 and does not process the request.

7. All billing routes require authentication; unauthenticated requests are redirected to login.

## Tasks / Subtasks

- [x] Create `app/services/billing_service.py` with plan catalogue, Stripe session creation, and pending subscription creation (AC: 1, 2, 3)
- [x] Add Stripe config keys to `app/config.py` (STRIPE_SECRET_KEY, per-plan price IDs) (AC: 2)
- [x] Update `GET /billing/plans` to pass plan data to template (AC: 1)
- [x] Add `POST /billing/checkout` route — validate plan, check not already subscribed, create Stripe checkout session, return checkout_url (AC: 2, 6, 7)
- [x] Add `GET /billing/success` route — retrieve Stripe session, create subscription in pending_webhook state (AC: 3, 4)
- [x] Add `GET /billing/portal` route — create Stripe Customer Portal session and redirect (AC: 5, 7)
- [x] Update `app/templates/billing_plans.html` — three plan cards with price and conversation limit (UX-DR9) (AC: 1)
- [x] Create `app/templates/billing_processing.html` — processing/pending state page (AC: 3)
- [x] Add `stripe` to `requirements.txt` (AC: 2)
- [x] Write `tests/test_saas_2_1_plan_selection_and_checkout.py` covering all ACs
- [x] Run story test suite and full regression suite

## Dev Notes

- Story source: `_bmad-output/planning-artifacts/epics-saas-v1.md` §Story 2.1
- Architecture references:
  - `_bmad-output/planning-artifacts/architecture-whatsapp-ai-bot-saas-v1.md` §9 (Screen 2 API contracts)
  - Repository contract: `app/repositories/base.py`
- API Contracts (arch §9 Screen 2):
  - `GET /billing/plans` → returns plan list (rendered as HTML template with plan data)
  - `POST /billing/checkout` → `{ plan_key }` → JSON `{ ok, data: { checkout_url } }` | Errors: INVALID_PLAN (422), ALREADY_SUBSCRIBED (409), STRIPE_NOT_CONFIGURED (503)
  - `GET /billing/portal` → redirects to Stripe Customer Portal
  - `GET /billing/success?session_id=...` → creates pending subscription; shows processing page
- Canonical table: `subscriptions` — created in `pending_webhook` status after Stripe redirect
- Entitlement truth: webhook-confirmed only (Story 2.2 upgrades to `active`)
- Stripe session includes `metadata: { plan_key, tenant_id }` to enable plan_key recovery on success callback
- `stripe_subscription_id` unique constraint: idempotent upsert on `stripe_subscription_id`; old pending stubs deleted before insert
- Constraints:
  - No entitlement granted on success redirect; only webhook can set `active`
  - Stripe secret key and price IDs all optional at config level (503 if not set)
  - Preserve all existing auth/session contracts from Story 1.2a
  - CSRF guard on all state-changing billing routes
- ENF-01 relevant: subscription must reach `active` or `trialing` (Story 2.2) before bot can reply

## Dev Agent Record

### Agent Model Used

Claude Sonnet 4.6 (Amelia)

### Debug Log

- 2026-05-05: Story artifact created and sprint-status updated to in-progress.
- 2026-05-05: Implemented billing_service.py with plan catalogue, Stripe session helpers, and pending subscription creation.
- 2026-05-05: Added Stripe config keys to app/config.py.
- 2026-05-05: Updated GET /billing/plans to pass plan data; added POST /billing/checkout, GET /billing/success, GET /billing/portal routes to views_auth.py.
- 2026-05-05: Updated billing_plans.html with three plan cards (UX-DR9); created billing_processing.html.
- 2026-05-05: Added stripe to requirements.txt.
- 2026-05-05: Wrote test_saas_2_1_plan_selection_and_checkout.py with full AC coverage.

### Completion Notes

- billing_service.py implements plan catalogue (Starter/Pro/Business), Stripe checkout session creation, portal session creation, and pending subscription upsert.
- GET /billing/plans now passes plan data to the template; template renders three plan cards per UX-DR9.
- POST /billing/checkout validates CSRF, auth, plan_key, and ALREADY_SUBSCRIBED; calls Stripe API; returns JSON checkout_url.
- GET /billing/success retrieves Stripe session metadata (plan_key, customer, subscription IDs) and creates subscription in pending_webhook state.
- GET /billing/portal creates Stripe Customer Portal session and redirects.
- can_activate_bot() guard verified: pending_webhook does NOT satisfy ENF-01 (must be active/trialing).
- Stripe imported lazily inside functions — all Stripe calls are mockable without installing stripe in test env (sys.modules mock).
- 27 story tests pass; 524 total pass, 5 skipped, 0 failures.

## File List

- _bmad-output/implementation-artifacts/saas-2-1-plan-selection-ui-and-stripe-checkout-flow.md
- _bmad-output/implementation-artifacts/sprint-status-saas-v1.yaml
- requirements.txt
- app/config.py
- app/services/billing_service.py
- app/views_auth.py
- app/templates/billing_plans.html
- app/templates/billing_processing.html
- tests/test_saas_2_1_plan_selection_and_checkout.py

### Change Log

- 2026-05-05: Story created and moved to in-progress.
