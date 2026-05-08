---
stepsCompleted:
  - "step-01-validate-prerequisites"
  - "step-02-design-epics"
  - "step-03-create-stories"
  - "step-04-final-validation"
inputDocuments:
  - "_bmad-output/planning-artifacts/prd-whatsapp-ai-bot-saas-v1.md"
  - "_bmad-output/planning-artifacts/architecture-whatsapp-ai-bot-saas-v1.md"
  - "_bmad-output/planning-artifacts/ux-design.md"
  - "docs/operations_runbook.md"
  - "docs/release_smoke_checklist.md"
  - "docs/setup_guide.md"
workflowType: "saas-v1-epics-and-stories"
project_name: "Malixis Reply v1"
user_name: "Wahab"
date: "2026-05-04"
revision: "2 — added ENF rules, API contracts, data model refs, UX design reqs"
skillVersion: "bmad-create-epics-and-stories"
---

# Malixis Reply v1 — Epic Breakdown

## Overview

This document is the implementation-ready backlog for the Malixis Reply v1 product, derived
from `prd-whatsapp-ai-bot-saas-v1.md` and the SaaS v1 section of `architecture.md`.

It is sequenced for **low-risk, incremental delivery on the existing Flask runtime**.  
Stories carry explicit `depends-on` tags, `v1-scope` labels, and a `risk-notes` section where
relevant.

Delivery phasing follows the PRD's recommended Incremental Delivery Plan:

| Phase | Focus | Epics |
|---|---|---|
| 1 — Foundation | Multi-tenant model, auth, subscription wiring, data boundaries | Epic 1 |
| 2 — Activation | Stripe checkout, QR onboarding, connection lifecycle | Epics 2 + 3 |
| 3 — Operations | Dashboard, usage enforcement, upgrade UX | Epic 4 |
| 4 — Internal control | Admin panel, audit trail, launch hardening | Epics 5 + 6 |

---

## Requirements Inventory

### Functional Requirements

FR1: New customers can register with email and password, verify identity, log in, log out, and
request a password reset — all without technical assistance.

FR2: Every request against customer-plane data is bound to the authenticated user's `tenant_id`;
unscoped queries are disallowed by repository contract and verified by automated cross-tenant
access-denial tests.

FR3: Users select a plan (Starter / Pro / Business) and complete Stripe Checkout before the bot
is activated; the subscription status (active, past_due, canceled) is reflected in the product
in near-real-time via Stripe webhooks.

FR4: Monthly usage quotas are automatically assigned from the active subscription plan;
the billing cycle defines the metering period.

FR5: An onboarding page fetches and displays a QR code from the Evolution API; the user scans it
with WhatsApp to link their phone number; real-time connection status updates
(disconnected / connecting / connected) are shown during the flow.

FR6: Once connected, the bot transitions to a live state and begins serving AI auto-replies to
inbound WhatsApp messages routed through the tenant's Evolution API instance.

FR7: The customer dashboard displays current WhatsApp connection status, conversations used vs.
plan limit, a progress bar, remaining count, and next billing reset date; data must be ≤ 60 s stale.

FR8: Customers can configure a business name and a custom AI persona/instruction prompt; changes
persist per tenant and apply to all subsequent AI replies.

FR9: Each completed exchange (one inbound message + one successful AI reply) increments the usage
counter by 1 via an atomic, idempotent transaction.

FR10: When the plan limit is reached, the system halts AI auto-replies, updates the dashboard to
show the blocked state, and presents an upgrade CTA and next reset date.

FR11: On billing cycle reset (Stripe period renewal) or plan upgrade, the bot resumes auto-replies
automatically without operator intervention.

FR12: Inbound webhook delivery from Evolution API is idempotent; duplicate message events must
not double-count usage or trigger duplicate replies.

FR13: Internal admins can list all tenants, view per-tenant status (plan, usage, subscription
state, WhatsApp connection state), search/filter tenants, and manually disable or re-enable a
tenant; all admin actions are logged in an append-only audit trail.

FR14: Bot configuration changes (persona prompt, business name) must be reflected in AI reply
behavior on subsequent messages without requiring a redeploy.

---

### Non-Functional Requirements

NFR1: Security — tenant isolation is enforced on all reads/writes; passwords are stored using a
strong hash + salt; secrets are managed via environment variables and never logged; CSRF protection
covers all state-changing dashboard and admin routes.

NFR2: Billing integrity — usage enforcement is deterministic and auditable; idempotency keys
prevent double-counting; Stripe webhook ingestion is idempotent on event ID; entitlement state
machine is deterministic.

NFR3: Reliability — successful AI reply rate ≥ 98% while account is within quota; resilient
handling of transient Evolution API failures with retry and circuit-breaker pattern.

NFR4: Performance — dashboard page load P50 ≤ 2 s; status/usage API response P50 ≤ 500 ms.

NFR5: Observability — structured logs include `tenant_id` and correlation IDs; metrics cover
connection status, reply success/failure, usage increments, and blocked events.

NFR6: Activation — signup-to-live bot median time ≤ 10 minutes; onboarding completion rate
(signup to QR connected) ≥ 70%.

NFR7: Supportability — admin time to identify customer status ≤ 2 minutes per account.

NFR8: Deployment simplicity — v1 runs on a single-region single-process Flask deployment; no
new infrastructure beyond a relational database and Evolution API service.

NFR9: Audit trail — all admin critical actions (disable/enable, entitlement override, plan
override) are append-only logged with actor, action, target, timestamp, and request ID.

---

### Additional Requirements (Architecture)

- **Multi-tenant Option A**: Single relational database; all business entities carry `tenant_id`;
  repository APIs require `tenant_id`; unscoped access is disallowed by contract.

- **Core SaaS entities**: `tenants`, `users`, `tenant_memberships`, `tenant_settings`,
  `tenant_whatsapp_sessions`, `subscriptions`, `billing_events`, `entitlements`,
  `usage_counters`, `usage_idempotency`, `audit_logs`.

- **Evolution session-per-tenant isolation**: Each tenant has a distinct
  `instance_name` in `tenant_whatsapp_sessions`; inbound webhook routing resolves tenant
  from instance identity before message handling; outbound always resolves
  `tenant_id → instance_name` — never uses a global shared instance.

- **Stripe webhook-safe entitlements**: Raw events stored append-only in `billing_events`
  (idempotent on Stripe event ID); `entitlements` is the derived snapshot used for runtime
  enforcement; state machine: `trialing|active` → entitled; `past_due|unpaid|incomplete` →
  grace/blocked; `canceled` → disabled at termination boundary.

- **Usage metering sequence**: Pre-send guard checks entitlement + quota; if blocked, skip AI
  reply; if sent, execute atomic transaction (insert idempotency key, increment
  `usage_counters.used_count`); duplicate key = no-increment.

- **Auth**: Email/password with strong hashing; secure server-side session cookie;
  CSRF protection on all state-changing routes; short-lived signed single-use
  password-reset tokens; session carries `user_id` + `tenant_id`.

- **Admin boundary**: Customer plane is tenant-scoped only; internal admin plane has global
  tenant visibility with explicit role checks; audit log is append-only.

- **Flask app factory extension**: SaaS modules wire into the existing Flask factory pattern;
  SaaS database access is a registered extension with teardown lifecycle management.

- **Existing runtime preserved**: Evolution API adapter and OpenAI service remain untouched
  in the core webhook pipeline; SaaS layer wraps them with tenant-context resolution.

---

### PRD Success Metrics (referenced in story acceptance criteria)

| Metric ID | Area | Metric | Target | Referenced In |
|---|---|---|---|---|
| SM-1 | Activation | Signup-to-live bot median time | ≤ 10 minutes | Stories 2.1, 3.1, 6.3 |
| SM-2 | Activation | Onboarding completion rate (signup → QR connected) | ≥ 70% | Stories 3.1, 6.3 |
| SM-3 | Reliability | AI reply rate while under limit | ≥ 98% | Stories 3.2, 4.3, 6.2 |
| SM-4 | Monetization | Paid conversion from signup (first 90 days) | ≥ 20% | Stories 2.1, 6.3 |
| SM-5 | Billing Integrity | Usage-plan enforcement correctness | 100% stop at limit-hit | Stories 4.4, 6.2 |
| SM-6 | Transparency | Dashboard usage data freshness | ≤ 60 s lag | Stories 4.1, 4.3 |
| SM-7 | Supportability | Admin time to identify customer status | ≤ 2 minutes/account | Stories 5.1, 5.2 |
| SM-8 | Performance | Dashboard page load P50 | ≤ 2 s | Story 4.1 |
| SM-9 | Performance | Status/usage API response P50 | ≤ 500 ms | Story 4.1 |

---

### UX Design Requirements (from `ux-design.md`)

| UX-DR | Screen | Requirement | Covered By |
|---|---|---|---|
| UX-DR1 | Setup (`/setup`) | Redirect here if required `.env` keys missing; step indicators; cannot proceed until all keys ✓ | Story 1.1 (app-layer prerequisite) |
| UX-DR2 | Dashboard (`/`) | 3-column grid; bot status green/red dot; metrics auto-refresh every 30 s without full reload | Story 4.1 |
| UX-DR3 | Dashboard | "Bot Status" shows red + "Not running" if health check fails | Story 4.1 |
| UX-DR4 | Agent Selector (`/agents`) | Radio card layout replacing `<select>`; teal border on selected; inline toast on save | Existing feature — no SaaS story needed |
| UX-DR5 | Metrics (`/metrics`) | Counter table from `MetricsCollector.snapshot()`; duration bars; "Reset metrics" confirm dialog | Story 4.1 (existing metrics — no SaaS story) |
| UX-DR6 | Message Log (`/logs`) | Ring buffer ≤ 100 entries; phone numbers masked by default; filter by status | Existing feature — no SaaS story needed |
| UX-DR7 | Navigation | Persistent left sidebar (desktop) / bottom tab bar (mobile); active state teal `#0f766e` | Story 4.1 (dashboard shell) |
| UX-DR8 | QR Onboarding | Real-time status indicator disconnected → connecting → connected; retry affordance on Evolution failure | Story 3.1 |
| UX-DR9 | Plan Selection | Three plan cards with price and conversation limit clearly stated before Stripe redirect | Story 2.1 |
| UX-DR10 | Blocked State | Dashboard renders blocked overlay with upgrade CTA and reset date when `is_blocked: true` | Story 4.4 |

---

### FR Coverage Map

| FR | Summary | Epic | Story |
|---|---|---|---|
| FR1 | Email/password auth, login, logout, password reset | Epic 1 | Stories 1.1, 1.2a, 1.2b |
| FR2 | Tenant isolation — all customer-plane data scoped to tenant | Epic 1 | Story 1.3 |
| FR3 | Plan selection + Stripe Checkout + subscription state | Epic 2 | Stories 2.1, 2.2 |
| FR4 | Monthly quota mapping from active subscription | Epic 2 | Story 2.3 |
| FR5 | Evolution API QR fetch, display, and real-time status | Epic 3 | Story 3.1 |
| FR6 | Bot live state after QR connected; AI replies begin | Epic 3 | Story 3.2 |
| FR7 | Dashboard: connection status, usage, progress, reset date | Epic 4 | Story 4.1 |
| FR8 | Bot config: business name + persona prompt per tenant | Epic 4 | Story 4.2 |
| FR9 | Atomic idempotent usage increment per completed exchange | Epic 4 | Story 4.3 |
| FR10 | Usage limit reached: halt replies, blocked state, upgrade CTA | Epic 4 | Story 4.4 |
| FR11 | Auto-resume on billing reset or plan upgrade | Epic 4 | Story 4.5 |
| FR12 | Idempotent inbound webhook; no double-count on duplicate delivery | Epic 4 | Story 4.3 |
| FR13 | Admin panel: list/search tenants, view status, disable/enable, audit log | Epic 5 | Stories 5.1, 5.2, 5.3 |
| FR14 | Bot config changes apply to subsequent messages without redeploy | Epic 4 | Story 4.2 |

---

### Enforcement Rules Master Table (arch §8)

These rules are **absolute** — no softening permitted in implementation. Each is traced to the story that must verify it.

| Rule | Constraint | Enforced In | Story Coverage |
|---|---|---|---|
| ENF-01 | No AI reply unless `subscriptions.status IN ('active', 'trialing')` | Bot Runtime pre-send guard | Stories 2.2, 2.3, 3.2 |
| ENF-02 | No AI reply if `usage_counters.is_blocked = TRUE` | Bot Runtime pre-send guard | Stories 4.4, 6.2 |
| ENF-03 | No AI reply if `tenants.is_active = FALSE` | Bot Runtime pre-send guard | Stories 1.3, 5.3 |
| ENF-04 | No AI reply unless `connection_states.status = 'connected'` | Bot Runtime (Evolution only delivers to connected instances) | Story 3.2 |
| ENF-05 | Idempotency check before count increment | Bot Runtime — insert to `usage_events` | Story 4.3 |
| ENF-06 | Usage event INSERT and counter UPDATE in same DB transaction | Bot Runtime atomic transaction | Story 4.3 |
| ENF-07 | `is_blocked` set atomically when `used >= limit` | Bot Runtime post-increment | Stories 4.3, 4.4 |
| ENF-08 | Enforcement check executes **before** OpenAI call | Bot Runtime step sequence | Stories 4.4, 6.2 |
| ENF-09 | Failed AI generation → no count, no reply | Bot Runtime error path | Story 4.3 |
| ENF-10 | Failed send → no count | Bot Runtime error path | Story 4.3 |
| ENF-11 | Plan upgrade → unblock if new limit > current used | Billing webhook handler | Story 4.5 |
| ENF-12 | Billing period reset → set `conversations_used = 0`, `is_blocked = FALSE` | Billing webhook handler | Story 4.5 |

---

### Architecture Data Model Tables (arch §4)

| Table | Purpose | Key Stories |
|---|---|---|
| `tenants` | One row per customer workspace; `is_active` admin kill switch | 1.1, 1.3, 5.3 |
| `users` | Email/password auth; linked to tenant; `password_hash` bcrypt | 1.1, 1.2 |
| `subscriptions` | Mirrors Stripe state; `status`, `plan_key`, `conversation_limit`, billing period | 2.1, 2.2, 2.3 |
| `usage_events` | Append-only ledger per completed exchange; `idempotency_key` unique | 4.3 |
| `usage_counters` | Fast read path; `conversations_used`, `is_blocked`, `period_start` | 4.3, 4.4, 4.5 |
| `connection_states` | Evolution API link state per tenant; `evolution_instance` | 3.1, 3.2, 4.1 |
| `bot_configs` | Per-tenant persona: `business_name`, `ai_persona_prompt` | 4.2 |
| `audit_log` | Append-only admin + system event log; `actor_type`, `action`, `payload` | 5.3, 6.1 |

> **Note on naming drift:** The PRD requirements inventory uses conceptual names (`tenant_settings`, `tenant_whatsapp_sessions`, `billing_events`, `usage_idempotency`). The canonical SQL schema names above (from arch §4) supersede those names. Stories that mention the conceptual names should use the canonical names during implementation.

---

## Epic List

### Epic 1: Multi-Tenant Foundation and Authentication  *(Phase 1 — Foundation)*
Users can create an account, log in, manage their session, and operate within a secure
tenant boundary. The data model that all subsequent epics build on is established here.

**FR covered:** FR1, FR2  
**v1-scope:** Must-Have

---

### Epic 2: Subscription and Billing Wiring  *(Phase 2 — Activation)*
Users can select a plan, complete Stripe Checkout, and have their subscription status and
quota entitlements reflected in the product in near-real-time via Stripe webhooks.

**FR covered:** FR3, FR4  
**depends-on:** Epic 1  
**v1-scope:** Must-Have

---

### Epic 3: WhatsApp QR Onboarding and Connection Lifecycle  *(Phase 2 — Activation)*
Users can scan a QR code to connect their WhatsApp number and see real-time connection
status; the bot transitions to live state upon successful connection.

**FR covered:** FR5, FR6  
**depends-on:** Epics 1, 2  
**v1-scope:** Must-Have

---

### Epic 4: Dashboard, Bot Config, Usage Enforcement, and Billing Lifecycle  *(Phase 3 — Operations)*
Users have full operational visibility: dashboard with connection and usage data, the ability to
configure the bot persona, deterministic usage enforcement, upgrade prompts, and automatic
resume on plan reset or upgrade.

**FR covered:** FR7, FR8, FR9, FR10, FR11, FR12, FR14  
**depends-on:** Epics 1, 2, 3  
**v1-scope:** Must-Have

---

### Epic 5: Internal Admin Panel and Audit Trail  *(Phase 4 — Internal Control)*
Internal admins can view all tenants, diagnose their operational state, and perform controlled
disable/enable actions with a full append-only audit trail.

**FR covered:** FR13  
**depends-on:** Epics 1, 4  
**v1-scope:** Must-Have

---

### Epic 6: Launch Hardening and Readiness Gates  *(Phase 4 — Internal Control)*
All v1 acceptance gates are met: security baseline, staging validation, billing lifecycle test
coverage, and operational documentation.

**FR covered:** All NFRs  
**depends-on:** Epics 1–5  
**v1-scope:** Must-Have

---

## Epic 1: Multi-Tenant Foundation and Authentication

Establish the relational database schema for all SaaS entities, wire the Flask app factory to
support multi-tenant context, and deliver complete email/password authentication so that users
can register, log in, manage sessions, and reset passwords — all within a secure tenant boundary.

---

### Story 1.1: Database Schema Bootstrap and Tenant Model

As an engineer,  
I want the core SaaS database schema created within the Flask app factory lifecycle,  
so that all subsequent stories have a stable, tenant-aware data foundation to build on.

**v1-scope:** Must-Have  
**depends-on:** None — this is the foundation story.

**Acceptance Criteria:**

**Given** the Flask application starts up  
**When** the database migration/init step runs  
**Then** the following tables exist: `tenants`, `users`, `subscriptions`, `usage_events`,
`usage_counters`, `connection_states`, `bot_configs`, `audit_log`

> **Note:** `billing_events` are stored in `audit_log` with `actor_type='stripe_webhook'`; there is no separate `billing_events` table.

**And** every business entity table includes `tenant_id` as a non-nullable indexed column

**And** a repository base class (or equivalent abstraction) enforces that all data access
methods require a `tenant_id` parameter — unscoped queries raise an explicit error

**And** the database connection is registered as a Flask app extension with a `close()` method
so it participates in app teardown lifecycle cleanly

**And** startup validation confirms database connectivity before the app accepts traffic;
missing or unreachable database fails fast with a clear error log

**risk-notes:** Row-level tenant isolation must be verified by automated tests before Epic 2 work begins. Architecture risk R4 (cross-tenant leakage) is mitigated here.

**Technical References:**
- **Tables (arch §4):** `tenants`, `users`, `subscriptions`, `usage_events`, `usage_counters`, `connection_states`, `bot_configs`, `audit_log` — all created in this story's migration
- **ENF Rules:** ENF-03 (`tenants.is_active` kill switch must exist from the start)
- **App structure (arch §10):** `app/models/` — SQLAlchemy ORM models; `app/__init__.py` — app factory blueprint registration
- **Success Metric:** Prerequisite for SM-1 (signup-to-live ≤ 10 min)

---

### Story 1.2a: Email/Password Signup, Login, and Logout

As a new customer,  
I want to create an account, log in, and manage my session,  
so that I can access my WhatsApp bot workspace without technical assistance.

**v1-scope:** Must-Have  
**depends-on:** Story 1.1

**Acceptance Criteria:**

**Given** a visitor on the signup page  
**When** they submit a valid email and password meeting strength requirements  
**Then** a new `user` record and linked `tenant` record are created atomically; the user is logged in and redirected to the post-signup flow (plan selection)

**And** passwords are stored using a strong hash+salt algorithm (bcrypt or equivalent); plaintext passwords never appear in logs or database

**And** login with correct credentials creates a secure server-side session cookie containing `user_id` and `tenant_id`

**Given** a logged-in user  
**When** they log out  
**Then** the server-side session is invalidated; subsequent requests without re-authentication are rejected and redirected to login

**And** CSRF protection is active on all auth POST routes; failed CSRF validation returns a 400 and does not process the form action

**risk-notes:** Architecture risk R4 mitigation — tenant_id must be in session on every authenticated request; any page that accesses data without a tenant_id in session must return 403.

**Technical References:**
- **API Contracts (arch §9 Screen 1):**
  - `POST /auth/signup` → `{ email, password }` → `{ redirect: "/billing/plans" }` | Errors: EMAIL_TAKEN (409), VALIDATION_ERROR (422)
  - `POST /auth/login` → `{ email, password }` → `{ redirect: "/dashboard" }` | Errors: INVALID_CREDENTIALS (401), ACCOUNT_DISABLED (403)
- **Tables (arch §4):** `users` (`password_hash` bcrypt), `tenants`
- **App structure (arch §10):** `app/modules/auth/routes.py`, `app/modules/auth/service.py`
- **Success Metric:** SM-1 — user must reach plan selection page immediately after signup

---

### Story 1.2b: Password Reset Flow

As a customer who has forgotten their password,  
I want to request a password reset via email and use a single-use token to set a new password,  
so that I can regain access to my account without technical assistance.

**v1-scope:** Must-Have  
**depends-on:** Story 1.2a

**Acceptance Criteria:**

**Given** a user who has forgotten their password  
**When** they request a reset  
**Then** a short-lived, signed, single-use token is emailed; the token allows one password change and is invalidated after use or expiry

**And** the forgot-password endpoint always returns 200 (prevents email enumeration); token delivery failure is logged but does not surface to the user as an error

**And** using an expired or already-used token returns an error and does not allow a password change

**risk-notes:** Architecture risk R4 mitigation — password reset tokens must be short-lived and single-use; reuse of a spent token is a security violation.

**Technical References:**
- **API Contracts (arch §9 Screen 1):**
  - `POST /auth/forgot-password` → always returns 200 (prevents email enumeration)
  - `POST /auth/reset-password` → `{ token, password }` | Errors: INVALID_TOKEN (400), TOKEN_EXPIRED (400)
- **Tables (arch §4):** `users` (`reset_token`, `reset_token_expires`)
- **App structure (arch §10):** `app/modules/auth/routes.py`, `app/modules/auth/service.py`

---

### Story 1.3: Tenant-Isolation Contract and Cross-Tenant Access-Denial Tests

As a platform owner,  
I want automated tests that verify every customer-plane endpoint denies access to data from a different tenant,  
so that multi-tenant data safety is continuously verified and not reliant on code review alone.

**v1-scope:** Must-Have  
**depends-on:** Stories 1.1, 1.2a

**Acceptance Criteria:**

**Given** two tenants (tenant A and tenant B) with their own records  
**When** an authenticated request from tenant A attempts to read, update, or delete any resource owned by tenant B  
**Then** the response is 403 or 404 — never 200 with tenant B data

**And** the repository layer test suite covers at least: tenant settings, subscription state, usage counters, and WhatsApp session records for the cross-tenant case

**And** the test suite runs in CI; a failing isolation test blocks the PR from merging

**And** any endpoint that reads data uses a tenant-scoped repository call verified to have been routed through the repository abstraction (not raw SQL outside the seam)

**Technical References:**
- **Tables (arch §4):** `tenants` (`is_active`), `users` (`tenant_id`), `subscriptions`, `usage_counters`, `connection_states` — all subject to cross-tenant isolation test
- **ENF Rules:** ENF-03 (tenants.is_active must block replies — validated here for the tenant kill switch path)
- **CI gate:** Test suite must block PR merge on any isolation failure (NFR1)

---

## Epic 2: Subscription and Billing Wiring

Enable customers to select a plan, complete Stripe Checkout, and have their subscription and
quota entitlements kept current in near-real-time via Stripe webhooks — without requiring a
redeploy or manual admin step.

---

### Story 2.1: Plan Selection UI and Stripe Checkout Flow

As a newly registered customer,  
I want to select a plan and complete payment via Stripe Checkout,  
so that my subscription is activated and my bot can proceed to onboarding.

**v1-scope:** Must-Have  
**depends-on:** Story 1.3

**Acceptance Criteria:**

**Given** a logged-in user who has not yet selected a plan  
**When** they view the plan selection page  
**Then** the three v1 plans are presented with price and conversation limit clearly stated:
Starter ($29/mo, 2 000 conversations), Pro ($49/mo, 5 000), Business ($99/mo, 15 000)

**When** the user selects a plan and clicks Subscribe  
**Then** they are redirected to Stripe Checkout with the correct price ID and a success/cancel callback URL that includes a session identifier

**When** Stripe Checkout completes successfully  
**Then** the user is redirected back to the app; a `subscription` record is created in `pending_webhook` state; the app does not activate entitlements until the webhook is confirmed (see Story 2.2)

**And** no bot activation is possible while subscription state is not `active`

**Given** a customer with an active subscription  
**When** they click 'Manage billing'  
**Then** they are redirected to the Stripe Customer Portal via `GET /billing/portal`

**risk-notes:** Architecture risk R3 — entitlements must not be derived from the redirect callback alone; only the Stripe webhook event establishes truth (Story 2.2). The redirect callback shows a "processing" state, not "active", until the webhook lands.

**Technical References:**
- **API Contracts (arch §9 Screen 2):**
  - `GET /billing/plans` → returns `{ plans: [{ key, name, price_usd, conversations }], current_plan }`
  - `POST /billing/checkout` → `{ plan_key }` → `{ checkout_url }` | Errors: INVALID_PLAN (422), ALREADY_SUBSCRIBED (409)
  - `GET /billing/portal` → redirects authenticated customer to Stripe Customer Portal
- **Tables (arch §4):** `subscriptions` — created in `pending_webhook` status after Stripe redirect; `tenants`
- **App structure (arch §10):** `app/modules/billing/routes.py`, `app/modules/billing/service.py`
- **UX Design:** UX-DR9 — three plan cards with price and conversation limit clearly visible before Stripe redirect
- **Success Metric:** SM-1 (plan selection is step 2 of signup-to-live path), SM-4 (paid conversion)

---

### Story 2.2: Stripe Webhook Ingestion and Entitlement State Machine

As the billing engine,  
I want Stripe lifecycle webhook events ingested idempotently and projected into the entitlement state,  
so that subscription changes take effect reliably without manual intervention and without duplicate processing.

**v1-scope:** Must-Have  
**depends-on:** Story 2.1

**Acceptance Criteria:**

**Given** a Stripe webhook event is received at the Flask webhook endpoint  
**When** the webhook signature is verified using the Stripe signing secret  
**Then** the raw event is stored append-only in `billing_events` keyed on the Stripe event ID; subsequent delivery of the same event ID is a no-op (idempotent)

**And** for `checkout.session.completed`, `invoice.paid`, `customer.subscription.updated`, `customer.subscription.deleted`, and `invoice.payment_failed` events, the `subscriptions` record for the affected tenant is updated according to the state machine:
- `active` or `trialing` → entitled (bot can reply)
- `past_due` or `unpaid` → grace period or blocked (configurable; default blocked in v1)
- `canceled` → entitlement disabled at effective termination boundary

**And** entitlement transitions are recorded in `audit_logs` with actor=`stripe-webhook`, action, tenant_id, event_id, and timestamp

**And** failed webhook signature verification returns 400; valid events with no handler are acknowledged 200 and logged as unhandled

**risk-notes:** Architecture risk R3 mitigation. Replay of all events in the `billing_events` table must be able to reconstruct the `entitlements` state deterministically.

**Technical References:**
- **API Contract:** Stripe webhook endpoint (internal) — verified via `stripe.Webhook.construct_event()` with signing secret
- **Tables (arch §4):** `subscriptions` (derived state), `audit_log` (webhook transitions recorded with `actor_type = 'stripe_webhook'`)
- **ENF Rules:** ENF-01 — `subscriptions.status IN ('active', 'trialing')` is the entitlement truth source; ENF-11, ENF-12 triggered by this handler
- **Stripe events handled:** `checkout.session.completed`, `invoice.paid`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`
- **App structure (arch §10):** `app/modules/billing/webhook_handler.py`
- **Success Metric:** SM-5 — 100% enforcement correctness depends on correct entitlement state from this story

---

### Story 2.3: Quota Entitlement Mapping and Plan Limit Assignment

As the usage enforcement system,  
I want the active subscription to automatically map to a monthly conversation quota,  
so that the enforcement layer always knows how many conversations a tenant is allowed this period.

**v1-scope:** Must-Have  
**depends-on:** Story 2.2

**Acceptance Criteria:**

**Given** a tenant transitions to `active` entitlement state  
**When** their subscription plan is determined (Starter / Pro / Business)  
**Then** the `subscriptions` record includes `monthly_quota` set to: 2 000 (Starter), 5 000 (Pro), or 15 000 (Business)

**And** the `usage_counters` record for the current billing period is initialized to `used_count = 0` if it does not already exist

**And** plan changes (upgrade or downgrade) immediately update `monthly_quota` in `entitlements` without requiring a billing-cycle boundary

**And** the quota value exposed to the dashboard and enforcement guard always reads from `entitlements` — never hardcoded in application logic

**Technical References:**
- **Tables (arch §4):** `subscriptions` (`conversation_limit` field — set from plan_key: 2000/5000/15000), `usage_counters` (`conversations_used` reset to 0 on new period)
- **ENF Rules:** ENF-01 — quota enforcement derives from `subscriptions.conversation_limit`; ENF-02 reads `usage_counters.is_blocked`
- **Plan key mapping:** `starter` → 2 000, `pro` → 5 000, `business` → 15 000 (arch §9 Screen 2)
- **Success Metric:** SM-5 — enforcement correctness requires quota always sourced from `subscriptions.conversation_limit`

---

## Epic 3: WhatsApp QR Onboarding and Connection Lifecycle

Let customers scan a QR code to connect their WhatsApp number, see real-time connection
status throughout the flow, and have the bot automatically transition to live once connected.

---

### Story 3.1: Evolution API QR Fetch, Display, and Status Polling

As a new customer,  
I want to see a QR code and scan it with WhatsApp to link my phone number,  
so that I can complete onboarding without needing technical support.

**v1-scope:** Must-Have  
**depends-on:** Stories 2.2, 2.3 (subscription must be active before bot activation is allowed)

**Acceptance Criteria:**

**Given** a customer with an active subscription is on the onboarding page  
**When** the page loads  
**Then** a QR code is fetched from the Evolution API using the tenant's dedicated `instance_name` (resolved from `tenant_whatsapp_sessions`) and rendered immediately

**And** if the tenant does not yet have a `tenant_whatsapp_sessions` record, one is created with a new unique `instance_name` at this point

**And** the page shows real-time connection status: `disconnected` → `connecting` → `connected` using polling or websocket; status is derived from the Evolution API session state for the tenant's specific instance only — never a shared global instance

**And** the QR code refreshes automatically before it expires (Evolution API QR TTL is respected)

**And** if the Evolution API call fails, a user-facing retry affordance is shown rather than a blank screen or unhandled error

**risk-notes:** Architecture risk R1 (Evolution API instability). Retry policy on QR fetch should apply exponential backoff; if Evolution is unavailable for > configured threshold, show a clear "reconnect later" CTA rather than looping.

**Technical References:**
- **API Contracts (arch §9 Screen 3):**
  - `GET /onboarding/qr-code` → `{ qr_image: "data:image/png;base64,...", expires_in_seconds: 60 }` | Errors: EVOLUTION_UNAVAILABLE (503), NO_ACTIVE_SUBSCRIPTION (402)
  - `GET /onboarding/status-stream` (SSE) → `Content-Type: text/event-stream`; events: `{ status: "connecting" }`, `{ status: "connected", phone: "..." }`, `{ status: "error", retry_after: 5 }`
- **Tables (arch §4):** `connection_states` (`status`, `evolution_instance`, `phone_number`) — provisioned here if row doesn't exist
- **App structure (arch §10):** `app/modules/onboarding/routes.py`, `app/modules/onboarding/service.py`
- **UX Design:** UX-DR8 — real-time disconnected → connecting → connected state indicator; retry affordance on Evolution failure
- **Success Metrics:** SM-1 (QR onboarding is step 3 of signup-to-live), SM-2 (onboarding completion ≥ 70%)

---

### Story 3.2: Bot Live State Transition and Inbound Routing per Tenant

As a customer whose WhatsApp number is now connected,  
I want the bot to start auto-replying to my customers automatically,  
so that I get value from the subscription immediately without any extra configuration step.

**v1-scope:** Must-Have  
**depends-on:** Story 3.1

**Acceptance Criteria:**

**Given** a tenant's QR connection transitions to `connected` status  
**When** the connection event is received (via Evolution webhook or polling confirmation)  
**Then** `tenant_whatsapp_sessions.connection_status` is updated to `connected` and `connected_at` is recorded

**And** inbound WhatsApp messages delivered to the Flask webhook are routed to the correct tenant by resolving the Evolution `instance_name` from the request payload to `tenant_id` in `tenant_whatsapp_sessions`

**And** no inbound message from one tenant's Evolution instance can be processed under another tenant's context (cross-tenant routing is explicitly rejected with a log warning)

**And** once a tenant is `connected` and `entitled`, the bot begins serving AI auto-replies using the tenant's persona config (or a safe default if none is set yet)

**And** connection status is visible in the dashboard immediately after transition (≤ 60 s data freshness per NFR4)

**Technical References:**
- **Tables (arch §4):** `connection_states` (`status`, `connected_at`, `phone_number`, `evolution_instance`); `subscriptions` (ENF-01 check)
- **ENF Rules:**
  - ENF-03 — `tenants.is_active = FALSE` blocks all replies regardless of connection
  - ENF-04 — `connection_states.status = 'connected'` required before AI reply (implicit in Evolution delivery)
- **Inbound routing:** Evolution webhook payload `instance_name` → resolve `tenant_id` from `connection_states.evolution_instance`; cross-tenant routing mismatch = reject + log warning
- **App structure (arch §10):** `app/modules/onboarding/service.py` (state transitions); `app/views.py` (inbound webhook routing guard)
- **Success Metric:** SM-3 — ≥ 98% reply rate begins here; bot must be reliable once connected

---

## Epic 4: Dashboard, Bot Config, Usage Enforcement, and Billing Lifecycle

Give customers operational self-service: a live dashboard of connection and usage state, the
ability to configure the bot persona, deterministic usage enforcement with an upgrade prompt,
and automatic resume on billing reset or plan upgrade.

---

### Story 4.1: Customer Dashboard — Connection Status and Usage Summary

As a customer,  
I want a dashboard that shows my WhatsApp connection state and usage summary,  
so that I always know whether my bot is running and how much of my plan I have used.

**v1-scope:** Must-Have  
**depends-on:** Stories 3.2, 2.3

**Acceptance Criteria:**

**Given** a logged-in customer with an active subscription  
**When** they view the dashboard  
**Then** the following are displayed and accurate: WhatsApp connection status (connected / disconnected / connecting), conversations used this period, plan limit, progress bar, remaining count, and next billing reset date

**And** all data values are consistent with the enforcement counter (no stale display while enforcement is live)

**And** dashboard data freshness is ≤ 60 seconds (either via polling or push)

**And** the dashboard page loads in ≤ 2 seconds P50 under expected launch load (NFR4)

**And** usage and status API calls complete in ≤ 500 ms P50

**Technical References:**
- **API Contract (arch §9 Screen 4):**
  - `GET /api/dashboard/summary` → `{ connection: { status, phone }, subscription: { plan, status, conversations_limit, conversations_used, conversations_remaining, reset_date, is_blocked } }`
- **Tables (arch §4):** `connection_states` (status, phone_number), `subscriptions` (plan_key, conversation_limit, current_period_end), `usage_counters` (conversations_used, is_blocked)
- **App structure (arch §10):** `app/modules/dashboard/routes.py`, `app/modules/dashboard/service.py` (aggregates from counters + subscription + connection)
- **UX Design:** UX-DR2 (3-column grid; 30 s auto-refresh without full reload), UX-DR3 (red dot if health check fails), UX-DR7 (sidebar nav shell)
- **Success Metrics:** SM-6 (≤ 60 s freshness), SM-7 (admin ident ≤ 2 min), SM-8 (page load ≤ 2 s P50), SM-9 (API ≤ 500 ms P50)

---

### Story 4.2: Bot Configuration — Business Name and Persona Prompt

As a customer,  
I want to set my business name and a custom AI persona prompt,  
so that the bot replies sound on-brand for my business from the first message.

**v1-scope:** Must-Have  
**depends-on:** Story 1.2 (tenant context), Story 3.2 (bot is live)

**Acceptance Criteria:**

**Given** a logged-in customer on the bot configuration page  
**When** they save a business name and AI persona prompt  
**Then** the values are persisted to `bot_configs` scoped to their `tenant_id`

**And** the next inbound message processed for that tenant uses the updated persona prompt in the AI call — the change does not require a redeploy

**And** configuration values are sanitized before storage; they are never interpreted as code or injected into infrastructure commands

**And** if a tenant has no custom persona set, a safe sensible default prompt is used

**And** CSRF protection is active on the configuration save route

**Technical References:**
- **API Contracts (arch §9 Screen 5):**
  - `GET /config/bot` → `{ business_name, ai_persona_prompt }`
  - `PUT /config/bot` → `{ business_name, ai_persona_prompt }` → `{ updated_at }` | Errors: VALIDATION_ERROR (422) — `business_name` > 100 chars, `ai_persona_prompt` > 2000 chars
- **Tables (arch §4):** `bot_configs` (`tenant_id` PK, `business_name`, `ai_persona_prompt`, `updated_at`)
- **App structure (arch §10):** `app/modules/bot_config/routes.py`, `app/modules/bot_config/service.py`
- **Security:** Prompt content must be sanitised before storage and before injection into OpenAI call (OWASP injection risk)

---

### Story 4.3: Atomic Usage Metering with Idempotency

As the usage metering system,  
I want each completed AI exchange to increment the usage counter exactly once, even if the webhook is delivered multiple times,  
so that billing is accurate and disputes caused by double-counting are prevented.

**v1-scope:** Must-Have  
**depends-on:** Stories 3.2, 2.3

**Acceptance Criteria:**

**Given** a tenant's AI reply is successfully sent to the end customer  
**When** the usage increment step runs  
**Then** an idempotency key composed of `(tenant_id, inbound_message_id)` is inserted into `usage_idempotency`; if the key already exists the increment is skipped (duplicate-safe)

**And** if the idempotency key is new, `usage_counters.used_count` for the current billing period is incremented atomically (a database transaction or compare-and-set operation is used — no non-atomic read-then-write)

**And** if the inbound message was received but the AI reply failed permanently, no usage increment occurs

**And** the post-increment `used_count` is observable in the dashboard within ≤ 60 s

**risk-notes:** Architecture risk R2 (incorrect usage counting). A reconciliation smoke test that replays the same inbound message ID twice and asserts `used_count` incremented only once must be part of the test suite before this story is marked done.

**Technical References:**
- **Tables (arch §4):**
  - `usage_events` — append-only ledger; `idempotency_key = SHA256(tenant_id + message_id)` UNIQUE constraint
  - `usage_counters` — `conversations_used` (atomic increment), `is_blocked` (set atomically in same tx)
- **ENF Rules:**
  - ENF-05 — idempotency check against `usage_events.idempotency_key` before any increment
  - ENF-06 — `usage_events` INSERT + `usage_counters` UPDATE in **same** DB transaction
  - ENF-07 — `is_blocked` set atomically when `conversations_used >= conversation_limit`
  - ENF-09 — failed AI generation → no insert, no increment
  - ENF-10 — failed send (Evolution) → no insert, no increment
- **Success Metric:** SM-3 (≥ 98% reply rate), SM-5 (100% billing enforcement correctness)

---

### Story 4.4: Usage Limit Enforcement — Bot Blocking and Upgrade CTA

As the usage enforcement guard,  
I want the bot to stop sending AI replies when the plan limit is reached, and show the customer a clear upgrade path,  
so that customers understand their limit status and have a self-serve resolution.

**v1-scope:** Must-Have  
**depends-on:** Story 4.3

**Acceptance Criteria:**

**Given** a tenant's `used_count` equals or exceeds `entitlements.monthly_quota`  
**When** a new inbound message arrives  
**Then** the pre-send enforcement guard blocks AI reply generation; the message is acknowledged to Evolution API but no AI reply is produced or sent

**And** `tenant_settings.blocked` (or equivalent entitlement state) is set to `true` for that tenant

**And** the customer dashboard shows a "limit reached" state including: remaining conversations = 0, upgrade CTA linking to plan upgrade, and next billing reset date

**And** the enforcement check is deterministic: it reads `used_count` and `monthly_quota` from the database atomically before every reply attempt — it never relies on cached/stale in-memory values

**And** no reply is sent while `blocked = true`, regardless of how many messages arrive

**risk-notes:** Architecture risk R5 (limit enforcement bypass under concurrency). The enforcement read must be within the same database transaction as the idempotency-key insert to prevent race conditions at high message volume.

**Technical References:**
- **Tables (arch §4):** `usage_counters` (`conversations_used`, `is_blocked`), `subscriptions` (`conversation_limit`)
- **ENF Rules:**
  - ENF-02 — `usage_counters.is_blocked = TRUE` → no reply; checked **before** any OpenAI call
  - ENF-07 — `is_blocked` must be set atomically in the same transaction as the increment that crosses the limit
  - ENF-08 — enforcement check (ENF-02) must execute **before** the OpenAI call in the runtime sequence
- **API Contract:** `GET /api/dashboard/summary` returns `is_blocked: true`; `POST /billing/upgrade` → `{ checkout_url }` (arch §9 Screen 6)
- **UX Design:** UX-DR10 — dashboard blocked overlay with upgrade CTA and reset date
- **Success Metric:** SM-5 — 100% of limit-hit accounts stop replying

---

### Story 4.5: Billing Cycle Reset and Plan Upgrade — Auto-Resume

As a customer whose usage limit was reached,  
I want my bot to resume replying automatically when my billing cycle resets or I upgrade my plan,  
so that I don't need to contact support or manually re-enable anything.

**v1-scope:** Must-Have  
**depends-on:** Stories 2.2, 4.4

**Acceptance Criteria:**

**Given** a Stripe `invoice.paid` event is received for a new billing period  
**When** the webhook is processed  
**Then** a new `usage_counters` row is created for the new period with `used_count = 0`; the previous period's row is preserved immutably

**And** if the tenant was in `blocked` state due to limit exhaustion, the blocked state is cleared and the bot resumes serving AI replies on the next inbound message

**And** if a customer completes Stripe Checkout for a plan upgrade while in blocked state, the new `monthly_quota` is applied immediately and the blocked state is cleared upon webhook confirmation

**And** resume behavior is tested: a test that sets `used_count = monthly_quota`, simulates a billing reset webhook, and asserts that the next message receives an AI reply (not a blocked response)

**Technical References:**
- **Tables (arch §4):** `usage_counters` (`conversations_used`, `is_blocked`, `period_start`), `subscriptions` (`conversation_limit`, `current_period_start`)
- **ENF Rules:**
  - ENF-11 — plan upgrade: unblock if new `conversation_limit > conversations_used`
  - ENF-12 — billing period reset (`invoice.paid` for new period): `conversations_used = 0`, `is_blocked = FALSE`
- **App structure (arch §10):** `app/modules/billing/webhook_handler.py` — both ENF-11 and ENF-12 trigger here
- **Success Metric:** SM-5 (enforcement correctness requires correct reset); SM-3 (reliability requires auto-resume without operator intervention)

---

## Epic 5: Internal Admin Panel and Audit Trail

Give internal admins complete operational control over all customer tenants: list, search,
diagnose, disable/enable — with every action captured in an immutable audit log.

---

### Story 5.1: Admin Tenant List and Status View

As an internal admin,  
I want to see a list of all tenants with their key operational status at a glance,  
so that I can identify customers needing attention in under 2 minutes.

**v1-scope:** Must-Have  
**depends-on:** Stories 1.1, 2.2, 3.2, 4.3

**Acceptance Criteria:**

**Given** an authenticated internal admin visits the admin tenant list  
**When** the page loads  
**Then** all tenants are listed with: tenant name, plan, subscription status, WhatsApp connection status, current usage vs. quota, and account enabled/disabled state

**And** the admin route is guarded by an explicit `admin` role check; requests without the admin role return 403 and do not expose any tenant data

**And** the admin view is not accessible to regular customer sessions (tenant-plane access does not grant admin access)

**And** the page loads within the 2-minute diagnostic SLA defined in NFR7 (no more than 2 minutes for an admin to identify a specific customer's operational state)

**Technical References:**
- **API Contract (arch §9 Screen 7):**
  - `GET /admin/api/customers` → query params: `page`, `per_page`, `search`, `status`, `is_blocked`; returns paginated tenant list with `plan`, `subscription_status`, `conversations_used`, `conversations_limit`, `is_blocked`, `connection_status`, `is_active`
- **Tables (arch §4):** `tenants`, `users`, `subscriptions`, `usage_counters`, `connection_states`
- **App structure (arch §10):** `app/modules/admin/routes.py`, `app/modules/admin/service.py`
- **ENF Rules:** ENF-03 — admin reads `tenants.is_active` to show current kill-switch state
- **Success Metric:** SM-7 — admin identifies customer status in ≤ 2 minutes

---

### Story 5.2: Admin Tenant Search, Filter, and Per-Tenant Detail

As an internal admin,  
I want to search and filter tenants by status or name and drill into any tenant's full operational state,  
so that I can investigate specific customer issues quickly and with complete context.

**v1-scope:** Must-Have  
**depends-on:** Story 5.1

**Acceptance Criteria:**

**Given** an admin on the tenant list  
**When** they search by name or filter by subscription status or connection status  
**Then** the list narrows to matching tenants within one user action (no page reload required); results are accurate and complete

**Given** an admin clicks into a specific tenant  
**When** the per-tenant detail page loads  
**Then** the following are visible: tenant metadata, current plan and quota, subscription history (last 3 events), current usage, WhatsApp session status, and whether the account is currently blocked

**And** sensitive data (API keys, webhook secrets) is not displayed or logged on admin pages

**Technical References:**
- **API Contract (arch §9 Screen 8):**
  - `GET /admin/api/customers/{tenant_id}` → returns full tenant context: metadata, subscription, connection, `bot_config`, `recent_audit_log` (last 3 events)
- **Tables (arch §4):** `tenants`, `users`, `subscriptions`, `usage_counters`, `connection_states`, `bot_configs`, `audit_log`
- **Success Metric:** SM-7 — search + filter within one action; per-tenant drill-down provides full operational picture

---

### Story 5.3: Admin Disable / Enable Tenant and Audit Logging

As an internal admin,  
I want to manually disable or re-enable a customer tenant and have every such action permanently logged,  
so that I can respond to operational emergencies while maintaining a complete audit trail.

**v1-scope:** Must-Have  
**depends-on:** Stories 5.1, 5.2

**Acceptance Criteria:**

**Given** an admin on a tenant detail page  
**When** they click Disable Tenant  
**Then** a confirmation step is required before the action executes; the confirmation clearly states the tenant name and the action's effect (bot stops replying; customer cannot log in)

**When** confirmed  
**Then** the tenant is marked disabled in `tenants`; their bot stops replying immediately (enforcement guard checks `tenants.enabled`); their session is invalidated

**And** an `audit_logs` record is created with: `actor = admin_user_id`, `action = "tenant.disable"`, `target = tenant_id`, `request_id`, and `timestamp`; the record is append-only and cannot be deleted via any UI action

**And** the same pattern applies to re-enable: confirmation required, audit record created, bot resumes

**And** a test asserts that an audit record is present for every disable/enable action and that the record cannot be deleted via any API or repository method

**risk-notes:** Architecture risk R10 (admin misuse). Confirmation flows and audit logging are required before this story is done. One-click rollback of account state must be verified as part of acceptance.

**Technical References:**
- **API Contracts (arch §9 Screen 8):**
  - `POST /admin/api/customers/{tenant_id}/disable` → `{ reason }` → `{ is_active: false }` | Side effect: writes to `audit_log` **before** executing
  - `POST /admin/api/customers/{tenant_id}/enable` → `{ is_active: true }` | Side effect: writes to `audit_log` before executing
- **Tables (arch §4):**
  - `tenants` (`is_active` — the kill switch)
  - `audit_log` (`actor_id`, `actor_type = 'admin'`, `action = 'tenant.disable'/'tenant.enable'`, `tenant_id`, `payload`, `created_at`) — append-only, no DELETE path
- **ENF Rules:** ENF-03 — `tenants.is_active = FALSE` stops all AI replies; this story is the only write path for that flag via admin action
- **App structure (arch §10):** `app/modules/admin/routes.py`, `app/modules/admin/service.py`
- **Success Metric:** SM-7; NFR9 (all admin critical actions logged with actor, action, target, timestamp, request_id)

---

## Epic 6: Launch Hardening and Readiness Gates

Convert all v1 product and architecture commitments into passing automated gates, validated
staging evidence, and complete operational documentation so the team can ship with confidence.

---

### Story 6.1: Security Baseline — Tenant Isolation and Auth Tests

As a release owner,  
I want an automated security test suite covering tenant isolation, auth boundaries, and CSRF protection,  
so that critical security regressions block launch before reaching production.

**v1-scope:** Must-Have  
**depends-on:** Stories 1.3, 5.3

**Acceptance Criteria:**

**Given** the full v1 codebase  
**When** the security test suite runs  
**Then** all cross-tenant access-denial tests pass (100% pass rate = launch gate A)

**And** CSRF bypass attempts on state-changing routes return 400 without processing the action

**And** admin routes return 403 for unauthenticated or non-admin sessions

**And** password reset tokens are single-use and expire correctly; reuse of a spent token returns an error

**And** no secret, API key, or password hash appears in any log output

**Technical References:**
- **ENF Rules validated here:** ENF-01 (auth state), ENF-02 (blocked state), ENF-03 (is_active kill switch) — all tested under negative conditions
- **Tables (arch §4):** `users` (password_hash never in logs), `audit_log` (admin actions verified present)
- **Test scope:** Cross-tenant isolation tests from Story 1.3; CSRF bypass tests; admin 403 guards; password reset token single-use expiry
- **Success Metric:** All SM-* security-related gates must pass before SM-1/SM-2/SM-3 can be validated in staging

---

### Story 6.2: Usage Metering and Billing Lifecycle Automated Tests

As a release owner,  
I want automated tests covering metering correctness, idempotency, enforcement under concurrency, and billing state transitions,  
so that billing disputes and enforcement bypasses are caught before launch.

**v1-scope:** Must-Have  
**depends-on:** Stories 4.3, 4.4, 4.5, 2.2

**Acceptance Criteria:**

**Given** the metering test suite  
**When** the same inbound message ID is processed twice  
**Then** `used_count` increments by exactly 1 (idempotency verified)

**And** a concurrent-send simulation at 2× expected peak throughput produces no over-limit replies

**And** billing state machine tests confirm: `invoice.paid` → entitled; `customer.subscription.deleted` → disabled; `invoice.payment_failed` → blocked; Stripe event replayed twice = no state change on second replay

**And** enforcement guard test confirms zero AI replies while `blocked = true`

**And** auto-resume test confirms bot replies resume after billing reset webhook

**Technical References:**
- **ENF Rules validated here:** ENF-05, ENF-06, ENF-07 (idempotency + atomic metering); ENF-08 (enforcement before OpenAI); ENF-09, ENF-10 (error paths no-count); ENF-11, ENF-12 (unblock on upgrade/reset)
- **Tables (arch §4):** `usage_events` (idempotency key UNIQUE), `usage_counters` (conversations_used, is_blocked), `subscriptions` (status transitions)
- **Concurrency test:** 2× expected peak throughput; asserts zero over-limit replies
- **Billing state machine coverage:** All 5 Stripe event types handled in Story 2.2 must have replay-idempotency assertions
- **Success Metric:** SM-3 (≥ 98% reply rate), SM-5 (100% enforcement), SM-6 (≤ 60 s freshness after reset)

---

### Story 6.3: Staging End-to-End Validation and Go/No-Go Report

As a release owner,  
I want a full end-to-end staging validation run across all plans and lifecycle events,  
so that I have documented evidence of readiness before production deployment.

**v1-scope:** Must-Have  
**depends-on:** Stories 6.1, 6.2, and all Epic 1–5 stories

**Acceptance Criteria:**

**Given** staging environment with all services connected (Evolution API, Stripe test mode, OpenAI)  
**When** the end-to-end validation run executes  
**Then** the activation flow completes for all three plans (Starter, Pro, Business) within ≤ 10 minutes median

**And** the metering and enforcement flows pass under normal and edge conditions (duplicate delivery, limit hit, billing reset, plan upgrade)

**And** admin workflows are validated against a sample set of test tenants

**And** all launch gates defined in `_bmad-output/test-artifacts/launch-gates.yaml` return GO

**And** a `go-no-go-report.md` is generated at `_bmad-output/test-artifacts/` and is attached to the release review

**And** no unresolved Critical or High risks remain open at the point of production cut (PRD risk operating model gate)

**Technical References:**
- **All 8 API contract screens (arch §9):** Validated end-to-end in staging against real Evolution API, Stripe test mode, and OpenAI
- **All ENF rules (ENF-01 through ENF-12):** Evidence of passing in staging validation run documented in go/no-go report
- **All PRD Success Metrics:** SM-1 through SM-9 measured and recorded; values meeting targets are GO, any miss is documented with mitigation or NO-GO
- **Launch gates file:** `_bmad-output/test-artifacts/launch-gates.yaml`
- **Output artifact:** `_bmad-output/test-artifacts/go-no-go-report.md`

---

### Story 6.4: Operational Documentation Update for SaaS v1

As a support operations lead,  
I want the setup guide, operations runbook, and release checklist updated to cover the SaaS v1
flows,  
so that the team can deploy, monitor, and recover the multi-tenant product without relying on undocumented tribal knowledge.

**v1-scope:** Must-Have  
**depends-on:** Story 6.3

**Acceptance Criteria:**

**Given** the v1 SaaS launch  
**When** the documentation set is reviewed  
**Then** `docs/setup_guide.md` covers the SaaS-specific first-time onboarding path (signup → plan → QR → live)

**And** `docs/operations_runbook.md` covers: tenant disable/enable procedure, Evolution session reset per tenant, billing webhook replay, usage counter reconciliation, and rollback playbook for entitlement state

**And** `docs/release_smoke_checklist.md` includes SaaS-specific pre-staging, staging, and production gate items

**And** all documentation is tested by at least one team member completing the onboarding flow from the doc without prior product knowledge

**Technical References:**
- **Docs updated:** `docs/setup_guide.md`, `docs/operations_runbook.md`, `docs/release_smoke_checklist.md`
- **Runbook procedures:** tenant disable/enable (uses `POST /admin/api/customers/{tenant_id}/disable|enable`), Evolution session reset per tenant (`connection_states` table), billing webhook replay, usage counter reconciliation (`usage_events` + `usage_counters`), entitlement state rollback
- **UX Design:** UX-DR1 (setup checklist flow documented), UX-DR2 – UX-DR10 (dashboard and onboarding flows described)

---

## Deferred to Post-v1

The following items are explicitly out of scope for v1 launch and should not be added to any sprint
until the v1 go/no-go gate has passed:

| Item | Rationale | Source |
|---|---|---|
| In-app notification center for billing/usage alerts | P1 in PRD | PRD P1 requirements |
| Conversation history viewer in dashboard | P1 in PRD | PRD P1 requirements |
| Daily usage trend analytics (week/month views) | P1 in PRD | PRD P1 requirements |
| Self-serve phone reconnection troubleshooting assistant | P1 in PRD | PRD P1 requirements |
| Team seats and RBAC | P2 in PRD | PRD P2 requirements |
| API access for enterprise customers | P2 in PRD | PRD P2 requirements |
| Add-on / overage billing model | P2 in PRD | PRD P2 requirements |
| Multi-channel support (SMS, Messenger, etc.) | Non-goal v1 | PRD Non-Goals |
| White-label / multi-branding | Non-goal v1 | PRD Non-Goals |
| Meta WhatsApp Business API integration | Non-goal v1 | PRD Non-Goals |
| Complex AI orchestration, tool calling, memory UI | Non-goal v1 | PRD Non-Goals |
| Schema-per-tenant or database-per-tenant isolation | Architecture Phase 2/3 | Architecture migration path |
| Prometheus metrics export | Architecture accepted constraint | Architecture constraints |
| Background async billing reconciliation workers | Architecture Phase 2 | Architecture migration path |

---

## Story Dependency Graph

```
Story 1.1  (DB schema + tenant model)
  └─> Story 1.2a  (auth: signup, login, logout, CSRF)
        ├─> Story 1.2b  (password reset flow)
        └─> Story 1.3  (tenant-isolation contract + cross-tenant tests)
              └─> Story 2.1  (plan selection + Stripe Checkout)
                    └─> Story 2.2  (Stripe webhook ingestion + entitlement state machine)
                          └─> Story 2.3  (quota entitlement mapping)
                                └─> Story 3.1  (Evolution QR fetch + status polling)
                                      └─> Story 3.2  (bot live state + inbound routing per tenant)
                                            ├─> Story 4.1  (dashboard: connection + usage)
                                            ├─> Story 4.2  (bot config: persona + business name)
                                            └─> Story 4.3  (atomic usage metering + idempotency)
                                                  └─> Story 4.4  (limit enforcement + upgrade CTA)
                                                        └─> Story 4.5  (billing reset + auto-resume)
                                                              └─> Story 5.1  (admin tenant list)
                                                                    └─> Story 5.2  (admin search + detail)
                                                                          └─> Story 5.3  (admin disable/enable + audit)
                                                                                └─> Story 6.1  (security baseline tests)
                                                                                      └─> Story 6.2  (metering + billing lifecycle tests)
                                                                                            └─> Story 6.3  (staging E2E + go/no-go)
                                                                                                  └─> Story 6.4  (SaaS v1 ops docs update)
```

---

## Risk Cross-Reference

| PRD Risk | Mitigated by Stories | Notes |
|---|---|---|
| R1 Evolution API instability | 3.1, 3.2 | Retry + reconnect CTA in Story 3.1 |
| R2 Incorrect usage counting | 4.3, 6.2 | Idempotency key + atomic increment + smoke test |
| R3 Stripe webhook / entitlement drift | 2.2, 2.3, 6.2 | Idempotent event ingestion + state machine tests |
| R4 Multi-tenant data leakage | 1.1, 1.3, 6.1 | Repository scoping + automated isolation tests |
| R5 Limit enforcement bypass under concurrency | 4.3, 4.4, 6.2 | Atomic enforcement read + concurrency stress test |
| R6 AI cost pressure | 4.4 | Hard cap via enforcement guard |
| R7 AI provider outage | 3.2 | Existing Flask runtime retry/fallback (unchanged) |
| R8 Abuse / spam | 4.4 | Per-tenant rate enforcement; future hardening post-v1 |
| R9 Onboarding drop-off | 3.1 | QR retry affordance + status hints |
| R10 Admin misuse / accidental suspension | 5.3 | Confirmation flow + audit log + one-click rollback |

---

---

## ENF Coverage Validation

All 12 enforcement rules are traced to at least one story's acceptance criteria and one test story in Epic 6:

| Rule | Story Implementation | Test Coverage |
|---|---|---|
| ENF-01 | Stories 2.2, 2.3 (subscription state) | Story 6.2 (billing state machine tests) |
| ENF-02 | Story 4.4 (blocked guard) | Story 6.2 (enforcement guard test) |
| ENF-03 | Stories 1.3, 5.3 (tenant active flag) | Story 6.1 (security baseline tests) |
| ENF-04 | Story 3.2 (connection routing) | Story 6.2 (implicit via bot reply tests) |
| ENF-05 | Story 4.3 (idempotency key) | Story 6.2 (idempotency test) |
| ENF-06 | Story 4.3 (atomic transaction) | Story 6.2 (concurrent-send simulation) |
| ENF-07 | Story 4.3 + 4.4 (atomic is_blocked set) | Story 6.2 (concurrent-send simulation) |
| ENF-08 | Story 4.4 (enforcement before OpenAI) | Story 6.2 (zero replies while blocked) |
| ENF-09 | Story 4.3 (AI failure = no count) | Story 6.2 (error path assertion) |
| ENF-10 | Story 4.3 (send failure = no count) | Story 6.2 (error path assertion) |
| ENF-11 | Story 4.5 (upgrade unblock) | Story 6.2 (auto-resume test) |
| ENF-12 | Story 4.5 (period reset) | Story 6.2 (auto-resume test) |

---

*Document status: Implementation-ready (Revision 2). All stories carry explicit ENF rule references,
API contract endpoints, data model table names (arch §4 canonical names), and success metric
alignments. Produced by BMAD bmad-create-epics-and-stories workflow — Date: 2026-05-04.*
