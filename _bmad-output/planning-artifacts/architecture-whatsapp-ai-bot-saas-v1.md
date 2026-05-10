---
stepsCompleted: ["step-01-init", "step-02-context", "step-03-starter", "step-04-decisions", "step-05-patterns", "step-06-structure", "step-07-validation", "step-08-complete"]
inputDocuments:
  - prd-whatsapp-ai-bot-saas-v1.md
workflowType: "architecture"
date: "2026-05-04"
author: "Winston (Architect)"
status: "Approved — Ready for Epic/Story Breakdown"
---

# Architecture: Malixis Reply v1

**Author:** Winston (Architect)  
**Date:** 2026-05-04  
**Status:** Approved — Ready for Epic/Story Breakdown  
**Input:** `prd-whatsapp-ai-bot-saas-v1.md`

---

## Table of Contents

1. [Context and Quality Attributes](#1-context-and-quality-attributes)
2. [System Overview](#2-system-overview)
3. [Architecture Decision Record](#3-architecture-decision-record)
4. [Data Model and Tenant Isolation](#4-data-model-and-tenant-isolation)
5. [Component Design](#5-component-design)
6. [Billing and Usage Metering Flow](#6-billing-and-usage-metering-flow)
7. [Connection State Flow](#7-connection-state-flow)
8. [Enforcement Rules](#8-enforcement-rules)
9. [API Contracts (8 Key Screens)](#9-api-contracts-8-key-screens)
10. [Project Structure](#10-project-structure)
11. [Implementation Patterns and Consistency Rules](#11-implementation-patterns-and-consistency-rules)
12. [Risks, Tradeoffs, and Rollout Phases](#12-risks-tradeoffs-and-rollout-phases)

---

## 1. Context and Quality Attributes

### Context

The existing Python/Flask bot handles AI response generation and Evolution API integration. v1 SaaS wraps a **multi-tenant management layer** around the existing bot runtime — adding auth, subscription billing, QR onboarding, usage governance, and an internal admin panel. No rewrite of the core bot pipeline is required.

### Constraints

| Constraint | Detail |
|---|---|
| Language/Framework | Python 3.11+ / Flask (existing codebase — no replatform) |
| Database | PostgreSQL (single instance, row-level tenant isolation) |
| External Services | Stripe (billing), Evolution API (WhatsApp), OpenAI GPT-4o mini (AI) |
| Deployment | Single-server / gunicorn + nginx (v1 scope — no Kubernetes) |
| Team | Solo or small team; complexity ceiling must stay low |
| OS | Linux server (gunicorn supported; Windows dev environment noted) |

### Quality Attributes (Priority Order)

| Attribute | Target | Rationale |
|---|---|---|
| **Tenant Isolation** | Zero cross-tenant data leakage | Critical — multi-tenant SaaS risk |
| **Billing Integrity** | 100% enforcement correctness | Core monetization trust |
| **Reliability** | ≥ 98% successful AI reply rate (under limit) | Primary product promise |
| **Performance** | Dashboard ≤ 2s p50; API ≤ 500ms p50 | UX quality bar |
| **Security** | OWASP Top 10 covered | Regulatory & trust baseline |
| **Operability** | Admin diagnosis ≤ 2 min per account | Support efficiency |
| **Simplicity** | Monolith-first; extract only when justified | Team size constraint |

---

## 2. System Overview

### Architecture Style: Modular Monolith

**Decision:** Single Flask application with clearly bounded modules, deployed as one process under gunicorn.

**Rationale:**
- Team size and v1 scope do not justify microservices operational overhead.
- Existing codebase is Flask — preserving runtime reduces risk.
- Module boundaries are defined explicitly to allow future extraction without rewrite.
- Multi-tenancy is achieved through data isolation, not service isolation.

### High-Level Component Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                          CLIENT LAYER                                │
│  Browser (SaaS Dashboard)          WhatsApp User (Customer's phone)  │
└───────────────┬──────────────────────────────────────┬───────────────┘
                │ HTTPS                                │ WhatsApp
                ▼                                      ▼
┌──────────────────────────┐          ┌──────────────────────────────┐
│     nginx (reverse proxy)│          │     Evolution API            │
│     TLS termination      │          │     (WhatsApp session mgr)   │
└────────────┬─────────────┘          └──────────────┬───────────────┘
             │                                        │ Webhook (POST)
             ▼                                        │
┌────────────────────────────────────────────────────▼──────────────┐
│                      Flask Application (gunicorn)                  │
│                                                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│  │  Auth Module │  │  Billing     │  │  Admin Module          │  │
│  │  (sessions,  │  │  Module      │  │  (customer ops,        │  │
│  │   accounts)  │  │  (Stripe,    │  │   audit log)           │  │
│  └──────────────┘  │   plans,     │  └────────────────────────┘  │
│                    │   usage)     │                               │
│  ┌──────────────┐  └──────────────┘  ┌────────────────────────┐  │
│  │  Onboarding  │                    │  Bot Config Module     │  │
│  │  Module      │  ┌──────────────┐  │  (persona, business    │  │
│  │  (QR, conn   │  │  Dashboard   │  │   name, instructions)  │  │
│  │   status)    │  │  Module      │  └────────────────────────┘  │
│  └──────────────┘  │  (usage,     │                               │
│                    │   limits)    │  ┌────────────────────────┐  │
│  ┌──────────────┐  └──────────────┘  │  Webhook / Bot         │  │
│  │  Tenant      │                    │  Runtime Module        │  │
│  │  Context     │◄───────────────────│  (message handling,    │  │
│  │  Middleware  │                    │   AI reply, metering)  │  │
│  └──────────────┘                    └────────────────────────┘  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │                   Shared Services Layer                      │ │
│  │  TenantGuard | UsageCounter | EntitlementService |           │ │
│  │  StripeClient | EvolutionClient | AuditLog | Observability   │ │
│  └──────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────┘
             │                          │               │
             ▼                          ▼               ▼
    ┌─────────────────┐     ┌────────────────┐  ┌────────────┐
    │   PostgreSQL     │     │   Stripe API   │  │ OpenAI API │
    │   (primary DB)   │     │   (billing)    │  │ (GPT-4o m) │
    └─────────────────┘     └────────────────┘  └────────────┘
```

---

## 3. Architecture Decision Record

### ADR-001: Modular Monolith over Microservices

| | |
|---|---|
| **Status** | Accepted |
| **Decision** | Deploy as a single gunicorn-managed Flask process with logically bounded modules |
| **Rationale** | Team size, existing codebase investment, v1 scope, and deployment simplicity all favor monolith. Module boundaries are contract-defined for future extraction. |
| **Tradeoff** | Horizontal scaling is per-process, not per-service. Accepted for v1 traffic volumes. |

### ADR-002: PostgreSQL as Single Source of Truth

| | |
|---|---|
| **Status** | Accepted |
| **Decision** | PostgreSQL with `tenant_id` foreign key on all tenant-scoped tables. No separate per-tenant databases. |
| **Rationale** | Simpler ops. Row-level isolation enforced by service layer (not DB-level row security for simplicity). Migration path to RLS available if needed. |
| **Tradeoff** | Requires strict discipline on all queries. Compensated by `TenantGuard` wrapper and CI tests. |

### ADR-003: Stripe as Billing System of Record

| | |
|---|---|
| **Status** | Accepted |
| **Decision** | Stripe manages subscription lifecycle. Local DB mirrors entitlement state for performance. Stripe webhooks drive state transitions. |
| **Rationale** | Stripe is the authoritative source. Local cache avoids Stripe API call on every request. |
| **Tradeoff** | State can drift on webhook failure. Mitigated by webhook retry policy, signature verification, and periodic Stripe API reconciliation job. |

### ADR-004: Atomic Usage Counting with Idempotency

| | |
|---|---|
| **Status** | Accepted |
| **Decision** | Usage counter incremented via atomic `UPDATE ... WHERE idempotency_key NOT IN processed` pattern. Idempotency key = SHA256 of (tenant_id + message_id). |
| **Rationale** | Prevents double-counting on Evolution API webhook replay. Satisfies R2 from PRD risk register. |
| **Tradeoff** | Requires idempotency_key index on usage_events table. Accepted. |

### ADR-005: Server-Sent Events for Real-Time Connection Status

| | |
|---|---|
| **Status** | Accepted |
| **Decision** | SSE endpoint streams Evolution API connection state to dashboard. No WebSocket dependency. |
| **Rationale** | SSE is simpler to implement in Flask than WebSockets, sufficient for one-directional status push, no extra infrastructure. |
| **Tradeoff** | One persistent HTTP connection per open dashboard tab. Acceptable at v1 scale. |

### ADR-006: Flask-Login + Server-Side Sessions with Multi-Role Support

| | |
|---|---|
| **Status** | Accepted |
| **Decision** | Flask-Login with server-side session storage (PostgreSQL-backed via flask-session). Session carries user_id, tenant_id, and role ('customer' or 'admin'). |
| **Rationale** | Existing Flask codebase. Avoids JWT complexity. Multi-role support allows single app to serve both customer and admin dashboards. |
| **Tradeoff** | Session store becomes a dependency. Mitigated by PostgreSQL reuse (no new infra). |
| **Role Routing** | On login, role determined by checking if user is in admin_users list. Customer → /dashboard. Admin → /admin/customers. |
| **Implementation** | Decorators: `@require_role('customer')` on customer routes, `@require_role('admin')` on admin routes. |

### ADR-007: Enforcement Check is Pre-Generation, Not Post

| | |
|---|---|
| **Status** | Accepted |
| **Decision** | Quota check runs before calling OpenAI. If blocked, skip generation and return blocked-path response. |
| **Rationale** | Prevents incurring AI cost for over-limit tenants. Enforcement is deterministic and auditable (R5). |
| **Tradeoff** | Race condition window at exact limit boundary. Mitigated by atomic counter compare-and-decrement. |

### ADR-008: Stripe Checkout Redirect (v1) with Embedded Path (P1)

| | |
|---|---|
| **Status** | Accepted for v1 (redirect); P1 review for embedded |
| **v1 Decision** | POST /billing/checkout with plan_key returns checkout_url to Stripe hosted page. Browser redirects user. |
| **v1 Rationale** | Stripe-hosted checkout is PCI-compliant out-of-box. No payment data touches Flask app. Simpler initial implementation. |
| **P1 Path** | Embed Stripe Payment Element in-page using Stripe JS for reduced friction. |
| **Webhook Handler** | POST /webhooks/stripe verifies signature, processes invoice.payment_succeeded, creates/updates subscription and entitlements. Idempotent on event ID. |
| **Reconciliation** | Daily cron validates local subscription state matches Stripe. Any drift triggers audit alert. |

---

## 4. Data Model and Tenant Isolation

### Core Schema

```sql
-- ─────────────────────────────────────────────
-- TENANTS (one per customer account)
-- ─────────────────────────────────────────────
CREATE TABLE tenants (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,     -- admin kill switch
    disabled_reason     TEXT
);

-- ─────────────────────────────────────────────
-- USERS (email/password auth, linked to tenant)
-- ─────────────────────────────────────────────
CREATE TABLE users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id),
    email               TEXT NOT NULL UNIQUE,
    password_hash       TEXT NOT NULL,                    -- bcrypt
    reset_token         TEXT,
    reset_token_expires TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at       TIMESTAMPTZ
);
CREATE INDEX idx_users_tenant ON users(tenant_id);

-- ─────────────────────────────────────────────
-- SUBSCRIPTIONS (mirrors Stripe state)
-- ─────────────────────────────────────────────
CREATE TABLE subscriptions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               UUID NOT NULL REFERENCES tenants(id) UNIQUE,
    stripe_customer_id      TEXT NOT NULL,
    stripe_subscription_id  TEXT NOT NULL UNIQUE,
    plan_key                TEXT NOT NULL,               -- 'starter'|'pro'|'business'
    status                  TEXT NOT NULL,               -- 'active'|'past_due'|'canceled'|'trialing'
    conversation_limit      INTEGER NOT NULL,            -- 2000|5000|15000
    current_period_start    TIMESTAMPTZ NOT NULL,
    current_period_end      TIMESTAMPTZ NOT NULL,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_subscriptions_tenant ON subscriptions(tenant_id);

-- ─────────────────────────────────────────────
-- USAGE LEDGER (one row per completed exchange)
-- ─────────────────────────────────────────────
CREATE TABLE usage_events (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id),
    idempotency_key     TEXT NOT NULL UNIQUE,            -- SHA256(tenant_id+message_id)
    billing_period_start TIMESTAMPTZ NOT NULL,           -- period snapshot for grouping
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_usage_tenant_period ON usage_events(tenant_id, billing_period_start);

-- ─────────────────────────────────────────────
-- USAGE COUNTERS (fast read path, derived cache)
-- ─────────────────────────────────────────────
CREATE TABLE usage_counters (
    tenant_id           UUID PRIMARY KEY REFERENCES tenants(id),
    period_start        TIMESTAMPTZ NOT NULL,
    conversations_used  INTEGER NOT NULL DEFAULT 0,
    is_blocked          BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- CONNECTION STATE (Evolution API link state)
-- ─────────────────────────────────────────────
CREATE TABLE connection_states (
    tenant_id           UUID PRIMARY KEY REFERENCES tenants(id),
    status              TEXT NOT NULL DEFAULT 'disconnected', -- 'disconnected'|'connecting'|'connected'
    phone_number        TEXT,
    evolution_instance  TEXT,                            -- Evolution API instance name
    connected_at        TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- BOT CONFIGURATION (per-tenant persona)
-- ─────────────────────────────────────────────
CREATE TABLE bot_configs (
    tenant_id           UUID PRIMARY KEY REFERENCES tenants(id),
    business_name       TEXT NOT NULL DEFAULT '',
    ai_persona_prompt   TEXT NOT NULL DEFAULT '',
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- AUDIT LOG (admin actions + critical events)
-- ─────────────────────────────────────────────
CREATE TABLE audit_log (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id            UUID,                            -- admin user_id or NULL for system
    actor_type          TEXT NOT NULL,                   -- 'admin'|'system'|'stripe_webhook'
    tenant_id           UUID REFERENCES tenants(id),
    action              TEXT NOT NULL,                   -- 'tenant.disable'|'subscription.updated' etc.
    payload             JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_audit_tenant ON audit_log(tenant_id, created_at DESC);
CREATE INDEX idx_audit_actor ON audit_log(actor_id, created_at DESC);
```

### Tenant Isolation Enforcement

**Rule:** Every service-layer read or write on a tenant-scoped table MUST pass through `TenantGuard`. No direct ORM queries on tenant-scoped tables from views or routes.

```python
# app/services/tenant_guard.py
class TenantGuard:
    """Enforces tenant_id scoping on all data access.
    MUST be used for all reads/writes on tenant-scoped tables.
    """

    def __init__(self, db, tenant_id: str):
        self._db = db
        self._tenant_id = tenant_id

    def query(self, model, **filters):
        """Returns query pre-scoped to current tenant."""
        return (
            self._db.session.query(model)
            .filter(model.tenant_id == self._tenant_id, **filters)
        )

    def get_or_404(self, model):
        row = self.query(model).first()
        if not row:
            abort(404)
        return row
```

**CI enforcement:** A test fixture asserts that no ORM query on tenant-scoped tables bypasses `TenantGuard`. This is the primary guard against R4 (tenant data leakage).

### Admin Isolation

- Admin routes prefixed `/admin/` and protected by `@admin_required` decorator.
- Admins can query across tenants — this is intentional and explicit.
- All admin actions are written to `audit_log` before executing the change.
- Admin user accounts are stored in `users` with a separate `is_admin` flag; they are NOT linked to a customer tenant.

---

## 5. Component Design

### 5.1 Auth Module

**Responsibility:** User registration, login, logout, password reset.  
**Pattern:** Flask-Login + bcrypt. Server-side sessions in PostgreSQL.

**Key behaviors:**
- On signup: create `tenants` row → create `users` row → create `bot_configs` row (defaults) → create `usage_counters` row → create `connection_states` row (all in one transaction).
- Password reset: generate cryptographically random token, store hash + expiry, email link, invalidate on use.
- Sessions expire after 30 days of inactivity.

### 5.2 Billing Module

**Responsibility:** Plan display, Stripe Checkout session creation, webhook processing, entitlement state management.

**Stripe Checkout Flow:**
```
User selects plan → POST /billing/checkout?plan=pro
→ Create Stripe Checkout Session (mode=subscription)
→ Redirect to Stripe hosted page
→ On success → Stripe sends webhook: checkout.session.completed
→ Webhook handler creates/updates subscriptions row
→ Redirect to /onboarding
```

**Webhook Events Handled:**

| Event | Action |
|---|---|
| `checkout.session.completed` | Insert/update `subscriptions`, set status=active |
| `customer.subscription.updated` | Update plan_key, limit, period dates, status |
| `customer.subscription.deleted` | Set status=canceled, set `is_blocked=true` on counter |
| `invoice.payment_failed` | Set status=past_due |
| `invoice.payment_succeeded` | Reset usage counter (if period_start changed), set status=active |

**Idempotency:** Each webhook handler checks if the event has already been processed via `stripe_event_id` dedup (stored in `audit_log` with actor_type='stripe_webhook').

### 5.3 Onboarding Module

**Responsibility:** Evolution API QR code retrieval, real-time connection status stream.

**QR Flow:**
```
GET /onboarding → renders onboarding page
→ JS fetches GET /onboarding/qr-code → returns {qr_image: base64}
→ Evolution API creates instance, generates QR
→ SSE stream: GET /onboarding/status-stream
   → polling Evolution API instance status every 3s
   → yields: data: {"status": "connecting"}
   → yields: data: {"status": "connected", "phone": "+447..."}
→ On connected: update connection_states, redirect to dashboard
```

**Error handling:** If Evolution API is unreachable, return `{"status": "error", "retry_after": 5}`. Circuit breaker opens after 3 consecutive failures.

### 5.4 Dashboard Module

**Responsibility:** Aggregate and display connection state, usage, limits, reset date.

**Data sources for dashboard API response:**
- `connection_states` → WhatsApp status
- `usage_counters` → conversations_used, is_blocked
- `subscriptions` → conversation_limit, current_period_end (reset date), plan_key, status

**Refresh strategy:** Dashboard page polls `GET /api/dashboard/summary` every 30 seconds. No server-push needed for dashboard (SSE is only for the onboarding QR flow).

### 5.5 Bot Config Module

**Responsibility:** Read/write `bot_configs` for the current tenant.

**Key behavior:**
- `business_name` and `ai_persona_prompt` are read by the Bot Runtime on every inbound message (no cache — ensures config updates are live immediately).
- Validation: `business_name` max 100 chars; `ai_persona_prompt` max 2000 chars.

### 5.6 Bot Runtime / Webhook Module

**Responsibility:** Receive Evolution API inbound webhook, enforce quota, generate AI reply, send reply, increment usage counter.

**Critical processing sequence (must not be reordered):**

```
1. Validate webhook signature (Evolution API secret)
2. Extract tenant from Evolution instance name → look up tenant_id
3. Load tenant active/blocked state (usage_counters + subscriptions JOIN)
4. ENFORCEMENT CHECK:
   IF tenant.is_blocked OR sub.status NOT IN ('active','trialing'):
       → log blocked event
       → return 200 (do not reply to customer)
       → EXIT
5. Idempotency: compute key = SHA256(tenant_id + message_id)
   IF key already exists in usage_events: return 200 (duplicate)
6. Load bot_config (business_name + ai_persona_prompt)
7. Generate AI reply (OpenAI call, timeout=15s, retry×1)
   IF AI call fails permanently → log, return 200 without reply (do not count)
8. Send reply via Evolution API
   IF send fails → log, return 200 (reply not delivered — do not count)
9. INSERT usage_events (idempotency_key) — atomic
10. UPDATE usage_counters SET conversations_used = conversations_used + 1
    WHERE tenant_id = ? AND period_start = ?
11. IF conversations_used >= conversation_limit:
    UPDATE usage_counters SET is_blocked = TRUE
12. Return 200
```

**Why this order matters:** Step 4 (enforcement) runs before AI generation (step 7) to avoid incurring cost. Step 9 (insert idempotency) runs before step 10 (counter update) with a DB transaction wrapping steps 9+10+11 to ensure atomicity.

### 5.7 Admin Module

**Responsibility:** Customer list, search/filter, customer detail view, enable/disable tenant.

**Key behaviors:**
- All routes: `@admin_required` decorator (checks `user.is_admin`).
- Customer list: paginated query across all tenants (TenantGuard is NOT used here — admins are cross-tenant by design).
- Disable tenant: sets `tenants.is_active = FALSE`. Bot Runtime checks this flag at step 3.
- All state changes: write to `audit_log` BEFORE executing the change.

### 5.8 Shared Services

| Service | Responsibility |
|---|---|
| `TenantGuard` | Scoped DB access for all tenant-scoped reads/writes |
| `EntitlementService` | Single function: `get_entitlement(tenant_id)` → returns `{active, blocked, limit, used, plan}` |
| `UsageCounter` | Atomic increment + block detection |
| `StripeClient` | Thin wrapper over `stripe` SDK — sets API key from config, handles retries |
| `EvolutionClient` | Thin wrapper over Evolution API HTTP calls — circuit breaker + retry |
| `AuditLog` | `log(actor_id, actor_type, tenant_id, action, payload)` — write-only |
| `Observability` | Structured logging (tenant_id + correlation_id on every log line) |

---

## 6. Billing and Usage Metering Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                   BILLING LIFECYCLE                             │
│                                                                 │
│  New User ──► Plan Select ──► Stripe Checkout                  │
│                                    │                           │
│                          checkout.session.completed            │
│                                    │                           │
│                          ┌─────────▼──────────┐               │
│                          │ subscriptions row   │               │
│                          │ status: active      │               │
│                          │ limit: 2000/5000... │               │
│                          │ period: [start,end] │               │
│                          └─────────┬──────────┘               │
│                                    │                           │
│                          usage_counters reset to 0             │
│                                    │                           │
│  ─────────────── EACH EXCHANGE ─────────────────────           │
│                                    │                           │
│  Inbound message ──► Enforcement check                         │
│       │                  ├── blocked? → STOP                   │
│       │                  └── active? → continue                │
│       ▼                                                        │
│  AI generation + send reply                                    │
│       │                                                        │
│       ▼                                                        │
│  INSERT usage_events (idempotency_key)                         │
│  UPDATE usage_counters +1                                      │
│  IF used >= limit → SET is_blocked=TRUE                        │
│                                                                │
│  ─────────────── BILLING CYCLE RESET ──────────────────        │
│                                                                │
│  invoice.payment_succeeded (new period)                        │
│       │                                                        │
│       ▼                                                        │
│  IF period_start changed:                                      │
│    UPDATE usage_counters SET used=0, is_blocked=FALSE          │
│    UPDATE subscriptions SET period dates                       │
│                                                                │
│  ─────────────── PLAN UPGRADE ─────────────────────────        │
│                                                                │
│  customer.subscription.updated (new plan)                      │
│       │                                                        │
│       ▼                                                        │
│  UPDATE subscriptions SET plan_key, limit                      │
│  IF new_limit > used: SET is_blocked=FALSE                     │
│                                                                │
└─────────────────────────────────────────────────────────────────┘
```

### Metering Reconciliation Job

A daily cron job (`app/jobs/usage_reconciliation.py`) that:
1. For each active tenant, counts `usage_events` rows for the current period.
2. Compares against `usage_counters.conversations_used`.
3. If delta > 0.5%, writes alert to `audit_log` with action `'metering.reconciliation.mismatch'`.
4. Does NOT auto-correct (manual review required to prevent masking bugs).

---

## 7. Connection State Flow

```
State machine per tenant (stored in connection_states.status):

  ┌─────────────────┐
  │   disconnected  │◄──────────────────────────────┐
  └────────┬────────┘                               │
           │ User visits /onboarding                │
           │ QR fetched from Evolution API          │
           ▼                                        │
  ┌─────────────────┐                               │
  │   connecting    │ (QR displayed)                │
  └────────┬────────┘                               │
           │ User scans QR                          │
           │ Evolution fires instance.state.updated │
           ▼                                        │
  ┌─────────────────┐                               │
  │    connected    │──── Evolution API drops ──────┘
  └─────────────────┘     (webhook: instance.state.updated
                           status=disconnected)
```

**State transitions are driven by Evolution API webhooks only.** The SSE stream polls the local DB (`connection_states`) — it does not poll Evolution API directly per request.

**Connection webhooks handled:**

| Webhook Event | New State | Side Effect |
|---|---|---|
| `instance.state.updated` → `open` | `connected` | Record `phone_number`, set `connected_at` |
| `instance.state.updated` → `close` | `disconnected` | Clear `phone_number` |
| `instance.state.updated` → `connecting` | `connecting` | — |

**Reconnect path:** If state becomes `disconnected` while a subscription is active, dashboard shows a reconnect CTA. User returns to `/onboarding`. A new QR is fetched (Evolution API re-generates for the same instance).

---

## 8. Enforcement Rules

These rules are absolute and must not be softened in implementation:

| Rule ID | Rule | Where Enforced |
|---|---|---|
| ENF-01 | No AI reply unless `subscriptions.status IN ('active', 'trialing')` | Bot Runtime step 4 |
| ENF-02 | No AI reply if `usage_counters.is_blocked = TRUE` | Bot Runtime step 4 |
| ENF-03 | No AI reply if `tenants.is_active = FALSE` | Bot Runtime step 3 |
| ENF-04 | No AI reply unless `connection_states.status = 'connected'` | Bot Runtime step 3 (implicit — Evolution only delivers to connected instances) |
| ENF-05 | Idempotency check before count increment | Bot Runtime step 5 |
| ENF-06 | Usage event INSERT and counter UPDATE in same DB transaction | Bot Runtime steps 9-11 |
| ENF-07 | `is_blocked` set atomically when `used >= limit` | Bot Runtime step 11 |
| ENF-08 | Enforcement check (step 4) executes before OpenAI call (step 7) | Bot Runtime sequence |
| ENF-09 | Failed AI generation → no count, no reply | Bot Runtime step 7 |
| ENF-10 | Failed send → no count | Bot Runtime step 8 |
| ENF-11 | Plan upgrade → unblock if new limit > current used | Billing webhook handler |
| ENF-12 | Billing period reset → set used=0, is_blocked=FALSE | Billing webhook handler |

---

## 9. API Contracts (8 Key Screens)

All API responses follow this envelope:

```json
{
  "ok": true,
  "data": { ... },
  "error": null
}
```

Error shape:
```json
{
  "ok": false,
  "data": null,
  "error": { "code": "LIMIT_EXCEEDED", "message": "Human-readable message" }
}
```

---

### Screen 1: Signup / Login

**POST /auth/signup**
```json
Request:  { "email": "string", "password": "string" }
Response: { "ok": true, "data": { "redirect": "/billing/plans" } }
Errors:   EMAIL_TAKEN (409), VALIDATION_ERROR (422)
```

**POST /auth/login**
```json
Request:  { "email": "string", "password": "string" }
Response: { "ok": true, "data": { "redirect": "/dashboard" } }
Errors:   INVALID_CREDENTIALS (401), ACCOUNT_DISABLED (403)
```

**POST /auth/forgot-password**
```json
Request:  { "email": "string" }
Response: { "ok": true, "data": { "message": "Reset email sent if account exists" } }
Notes:    Always returns 200 (prevents email enumeration)
```

**POST /auth/reset-password**
```json
Request:  { "token": "string", "password": "string" }
Response: { "ok": true, "data": { "redirect": "/auth/login" } }
Errors:   INVALID_TOKEN (400), TOKEN_EXPIRED (400)
```

---

### Screen 2: Plan Selection

**GET /billing/plans**
```json
Response: {
  "ok": true,
  "data": {
    "plans": [
      { "key": "starter", "name": "Starter", "price_usd": 29, "conversations": 2000 },
      { "key": "pro",     "name": "Pro",     "price_usd": 49, "conversations": 5000 },
      { "key": "business","name": "Business","price_usd": 99, "conversations": 15000 }
    ],
    "current_plan": null
  }
}
```

**POST /billing/checkout**
```json
Request:  { "plan_key": "pro" }
Response: { "ok": true, "data": { "checkout_url": "https://checkout.stripe.com/..." } }
Errors:   INVALID_PLAN (422), ALREADY_SUBSCRIBED (409)
```

**GET /billing/portal** (for existing subscribers to manage billing)
```json
Response: { "ok": true, "data": { "portal_url": "https://billing.stripe.com/..." } }
```

---

### Screen 3: QR Onboarding

**GET /onboarding/qr-code**
```json
Response: {
  "ok": true,
  "data": {
    "qr_image": "data:image/png;base64,...",
    "expires_in_seconds": 60
  }
}
Errors:   EVOLUTION_UNAVAILABLE (503), NO_ACTIVE_SUBSCRIPTION (402)
```

**GET /onboarding/status-stream** (SSE)
```
Content-Type: text/event-stream

data: {"status": "connecting"}

data: {"status": "connected", "phone": "+447700900000"}

data: {"status": "error", "retry_after": 5}
```

---

### Screen 4: Dashboard

**GET /api/dashboard/summary**
```json
Response: {
  "ok": true,
  "data": {
    "connection": {
      "status": "connected",           // "disconnected"|"connecting"|"connected"
      "phone": "+447700900000"
    },
    "subscription": {
      "plan": "pro",
      "status": "active",              // "active"|"past_due"|"canceled"
      "conversations_limit": 5000,
      "conversations_used": 1243,
      "conversations_remaining": 3757,
      "reset_date": "2026-06-03T00:00:00Z",
      "is_blocked": false
    }
  }
}
```

---

### Screen 5: Bot Configuration

**GET /config/bot**
```json
Response: {
  "ok": true,
  "data": {
    "business_name": "Acme Repairs",
    "ai_persona_prompt": "You are a helpful assistant for Acme Repairs..."
  }
}
```

**PUT /config/bot**
```json
Request: {
  "business_name": "Acme Repairs",
  "ai_persona_prompt": "You are a helpful assistant for Acme Repairs..."
}
Response: { "ok": true, "data": { "updated_at": "2026-05-04T10:30:00Z" } }
Errors:   VALIDATION_ERROR (422)  // business_name > 100 chars, prompt > 2000 chars
```

---

### Screen 6: Limit Hit State (surfaced on dashboard)

No dedicated endpoint — the dashboard summary `GET /api/dashboard/summary` returns `is_blocked: true` when the limit is hit. The UI renders the blocked state based on this field.

**POST /billing/upgrade** (triggered by upgrade CTA on blocked dashboard)
```json
Request:  { "plan_key": "business" }
Response: { "ok": true, "data": { "checkout_url": "https://checkout.stripe.com/..." } }
```

---

### Screen 7: Admin — Customer List

**GET /admin/api/customers**
```
Query params: page (default 1), per_page (default 25), search (email/phone), 
              status (active|past_due|canceled), is_blocked (true|false)
```
```json
Response: {
  "ok": true,
  "data": {
    "customers": [
      {
        "tenant_id": "uuid",
        "email": "owner@example.com",
        "plan": "pro",
        "subscription_status": "active",
        "conversations_used": 1243,
        "conversations_limit": 5000,
        "is_blocked": false,
        "connection_status": "connected",
        "is_active": true,
        "created_at": "2026-04-01T09:00:00Z"
      }
    ],
    "total": 47,
    "page": 1,
    "per_page": 25
  }
}
```

---

### Screen 8: Admin — Customer Detail

**GET /admin/api/customers/{tenant_id}**
```json
Response: {
  "ok": true,
  "data": {
    "tenant": { "id": "uuid", "is_active": true, "created_at": "..." },
    "user": { "email": "...", "last_login_at": "..." },
    "subscription": { "plan": "pro", "status": "active", "limit": 5000, "used": 1243, "reset_date": "..." },
    "connection": { "status": "connected", "phone": "...", "connected_at": "..." },
    "bot_config": { "business_name": "...", "ai_persona_prompt": "..." },
    "recent_audit_log": [
      { "action": "tenant.disable", "actor_type": "admin", "created_at": "..." }
    ]
  }
}
```

**POST /admin/api/customers/{tenant_id}/disable**
```json
Request:  { "reason": "Abuse investigation" }
Response: { "ok": true, "data": { "is_active": false } }
Side effect: writes to audit_log before executing
```

**POST /admin/api/customers/{tenant_id}/enable**
```json
Response: { "ok": true, "data": { "is_active": true } }
Side effect: writes to audit_log before executing
```

---

## 10. Project Structure

### Directory Layout

The SaaS management layer is layered on top of the existing Flask app. The existing `app/services/` bot pipeline is preserved. New modules are added alongside.

```
python-whatsapp-bot/
├── app/
│   ├── __init__.py                    # App factory — registers all blueprints
│   ├── config.py                      # Config classes (base, dev, prod)
│   │
│   ├── models/                        # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── tenant.py                  # Tenant
│   │   ├── user.py                    # User
│   │   ├── subscription.py            # Subscription
│   │   ├── usage_event.py             # UsageEvent
│   │   ├── usage_counter.py           # UsageCounter
│   │   ├── connection_state.py        # ConnectionState
│   │   ├── bot_config.py              # BotConfig
│   │   └── audit_log.py              # AuditLog
│   │
│   ├── modules/                       # Feature modules (new SaaS layer)
│   │   ├── auth/
│   │   │   ├── __init__.py
│   │   │   ├── routes.py              # /auth/* routes
│   │   │   └── service.py             # signup, login, password reset logic
│   │   ├── billing/
│   │   │   ├── __init__.py
│   │   │   ├── routes.py              # /billing/* routes
│   │   │   ├── service.py             # Checkout, portal, plan mapping
│   │   │   └── webhook_handler.py     # Stripe webhook event handlers
│   │   ├── onboarding/
│   │   │   ├── __init__.py
│   │   │   ├── routes.py              # /onboarding/* routes + SSE stream
│   │   │   └── service.py             # QR fetch, connection state management
│   │   ├── dashboard/
│   │   │   ├── __init__.py
│   │   │   ├── routes.py              # /api/dashboard/* routes
│   │   │   └── service.py             # Aggregate summary from counters+subscription+connection
│   │   ├── bot_config/
│   │   │   ├── __init__.py
│   │   │   ├── routes.py              # /config/bot routes
│   │   │   └── service.py             # Read/write bot_configs
│   │   └── admin/
│   │       ├── __init__.py
│   │       ├── routes.py              # /admin/* routes
│   │       └── service.py             # Customer list, search, disable/enable
│   │
│   ├── services/                      # Existing bot services (preserved)
│   │   ├── google_ai_service.py       # (existing)
│   │   ├── openai_service.py          # (existing)
│   │   ├── outbound_delivery.py       # (existing — wraps Evolution send)
│   │   ├── observability.py           # (existing — extended with tenant_id)
│   │   └── ...
│   │
│   ├── shared/                        # Cross-cutting shared services (new)
│   │   ├── __init__.py
│   │   ├── tenant_guard.py            # TenantGuard class
│   │   ├── entitlement_service.py     # EntitlementService.get_entitlement()
│   │   ├── usage_counter.py           # UsageCounter.increment()
│   │   ├── stripe_client.py           # StripeClient wrapper
│   │   ├── evolution_client.py        # EvolutionClient wrapper + circuit breaker
│   │   └── audit_log_service.py       # AuditLog.log()
│   │
│   ├── decorators/                    # (existing — extended)
│   │   ├── auth.py                    # @login_required, @admin_required
│   │   └── tenant.py                  # @tenant_context (loads TenantGuard into g)
│   │
│   ├── views.py                       # Existing webhook route (extended with enforcement)
│   ├── views_dashboard.py             # Existing dashboard (will migrate to modules/)
│   ├── templates/                     # Jinja2 templates (extended)
│   │   ├── auth/
│   │   ├── billing/
│   │   ├── onboarding/
│   │   ├── dashboard/
│   │   ├── bot_config/
│   │   └── admin/
│   └── static/                        # CSS, JS (existing + new)
│
├── migrations/                        # Alembic migrations
│   └── versions/
│       └── 001_initial_saas_schema.py
│
├── jobs/                              # Background/scheduled jobs
│   └── usage_reconciliation.py        # Daily metering reconciliation cron
│
├── tests/
│   ├── test_auth.py
│   ├── test_billing_webhook.py
│   ├── test_usage_enforcement.py      # CRITICAL: idempotency + block tests
│   ├── test_tenant_isolation.py       # CRITICAL: cross-tenant access tests
│   ├── test_onboarding.py
│   ├── test_admin.py
│   └── test_api_contracts.py
│
├── docs/
│   └── operations_runbook.md          # (existing — extend with SaaS ops)
│
├── requirements.txt                   # (extend with flask-login, flask-session,
│                                      #  flask-migrate, stripe, psycopg2-binary,
│                                      #  sqlalchemy)
├── .env.example
└── gunicorn.conf.py                   # (existing)
```

### New Dependencies

```
# requirements additions
flask-login>=0.6.3
flask-session>=0.8.0
flask-migrate>=4.0.7
flask-sqlalchemy>=3.1.1
stripe>=10.0.0
psycopg2-binary>=2.9.9
bcrypt>=4.1.2
```

---

## 11. Implementation Patterns and Consistency Rules

These rules must be followed by all implementing agents to ensure compatible, conflict-free code.

### Naming Conventions

| Entity | Convention | Example |
|---|---|---|
| DB table names | snake_case, plural | `usage_events`, `bot_configs` |
| DB column names | snake_case | `tenant_id`, `created_at` |
| SQLAlchemy models | PascalCase, singular | `UsageEvent`, `BotConfig` |
| Python files | snake_case | `usage_counter.py` |
| Blueprint names | snake_case | `auth_bp`, `billing_bp` |
| URL routes | kebab-case | `/bot-config`, `/qr-code` |
| API JSON fields | snake_case | `conversations_used`, `is_blocked` |
| Environment vars | SCREAMING_SNAKE_CASE | `STRIPE_SECRET_KEY` |

### API Response Format

**All** JSON API endpoints return the envelope defined in Section 9. No bare responses. HTTP status codes:
- 200: success
- 201: created
- 400: bad request / validation
- 401: unauthenticated
- 402: payment required (no active subscription)
- 403: forbidden
- 404: not found
- 409: conflict
- 422: validation error
- 503: upstream dependency unavailable

### Error Codes (complete list)

| Code | Meaning |
|---|---|
| `VALIDATION_ERROR` | Input failed validation |
| `EMAIL_TAKEN` | Signup with duplicate email |
| `INVALID_CREDENTIALS` | Wrong email/password |
| `ACCOUNT_DISABLED` | Tenant disabled by admin |
| `NO_ACTIVE_SUBSCRIPTION` | Feature requires active subscription |
| `ALREADY_SUBSCRIBED` | Attempt to subscribe when already subscribed |
| `INVALID_PLAN` | Unknown plan key |
| `INVALID_TOKEN` | Password reset token invalid |
| `TOKEN_EXPIRED` | Password reset token expired |
| `LIMIT_EXCEEDED` | Conversation quota reached |
| `EVOLUTION_UNAVAILABLE` | Evolution API circuit open |
| `NOT_FOUND` | Resource does not exist or tenant mismatch |

### Tenant Context Pattern

Every request handler that accesses tenant data must:
1. Have `@login_required` applied.
2. Load `TenantGuard` via `@tenant_context` decorator (which sets `g.tenant_guard`).
3. Pass `g.tenant_guard` to all service calls.

```python
@bp.route("/config/bot", methods=["GET"])
@login_required
@tenant_context          # sets g.tenant_guard
def get_bot_config():
    config = BotConfigService.get(g.tenant_guard)
    return ok(config.to_dict())
```

### Date/Time Convention

- All timestamps: UTC, stored as `TIMESTAMPTZ` in PostgreSQL.
- All API responses: ISO 8601 with Z suffix: `"2026-05-04T10:30:00Z"`.
- No naive datetimes in Python code — always `datetime.now(timezone.utc)`.

### Logging Convention

Every log line must include:
```python
logger.info("message", extra={
    "tenant_id": str(tenant_id),
    "correlation_id": g.correlation_id,   # set by middleware on each request
    "module": "billing.webhook"
})
```

### Test Isolation

- Each test function gets a fresh DB transaction, rolled back after the test.
- Stripe and Evolution API calls must be mocked — no live API calls in tests.
- Tenant isolation tests must assert that querying one tenant cannot return another tenant's rows.

---

## 12. Risks, Tradeoffs, and Rollout Phases

### Tradeoff Matrix

| Decision | Benefit | Cost | Accepted? |
|---|---|---|---|
| Modular monolith | Simple ops, fast dev | Cannot scale components independently | Yes — v1 traffic |
| Row-level isolation (app-layer) | Simple schema, flexible | Requires discipline; no DB-level enforcement | Yes — with TenantGuard + CI tests |
| Stripe as SoT, local mirror | Fast entitlement reads | Risk of drift on webhook failure | Yes — with reconciliation job |
| SSE for QR status | No extra infra | 1 persistent conn per user | Yes — v1 user count |
| Pre-generation enforcement | Saves AI cost on blocked tenants | Race at exact limit boundary | Yes — atomic counter mitigates |
| No microservices | Low ops complexity | Harder to scale in future | Yes — migration path defined |

### Key Risks (from PRD, architecture-validated)

| Risk | Architecture Mitigation |
|---|---|
| R2: Double-counting (PRD) | Idempotency key per message (ENF-05, ENF-06) |
| R3: Stripe webhook drift | Event dedup in audit_log + daily reconciliation job |
| R4: Tenant data leakage | TenantGuard mandatory + CI isolation tests |
| R5: Enforcement bypass under concurrency | Atomic compare-and-set; transaction wrapping steps 9-11 |
| R1: Evolution API instability | Circuit breaker in EvolutionClient; reconnect UX |

### Rollout Phases (Aligned to PRD Incremental Delivery)

| Phase | Scope | Architecture components | Gate |
|---|---|---|---|
| **Phase 1: Foundation** | Multi-tenant model, auth, subscription model wiring | models/, migrations, auth module, billing module (webhook handler), TenantGuard, shared/ | All tenant isolation tests pass; ENF rules 1-3 enforced |
| **Phase 2: Activation** | Stripe checkout, QR onboarding, connection lifecycle | billing/routes, onboarding module, SSE endpoint, EvolutionClient circuit breaker | Signup-to-connected flow works end to end in staging |
| **Phase 3: Operations** | Dashboard usage, enforcement, upgrade UX | dashboard module, usage_counter, enforcement sequence in views.py, blocked UX | ENF-04 through ENF-12 all pass; metering reconciliation job runs clean |
| **Phase 4: Internal Control** | Admin panel, audit log, launch hardening | admin module, audit_log_service, @admin_required, CSRF hardening, pen test | Admin actions logged; zero open Critical/High risks |

### Implementation Checkpoints

- [ ] Schema migration `001_initial_saas_schema.py` reviewed and applied to staging
- [ ] `TenantGuard` in place and all existing routes wrapped before Phase 2 begins
- [ ] Stripe webhook handler deployed and tested with Stripe CLI before Checkout goes live
- [ ] EvolutionClient circuit breaker tested with a simulated API outage before QR flow ships
- [ ] Usage enforcement sequence (steps 1-12 in Section 5.6) code-reviewed against ENF rules before Phase 3 ships
- [ ] Tenant isolation tests in CI must remain green through all phases
- [ ] Metering reconciliation job verified with a manual run before Phase 3 launch
- [ ] Admin panel behind separate auth check; tested with a non-admin session before Phase 4 ships
