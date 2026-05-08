---
stepsCompleted:
  - "step-01-document-discovery"
  - "step-02-prd-analysis"
  - "step-03-enf-analysis"
  - "step-04-api-contract-analysis"
  - "step-05-ux-analysis"
  - "step-06-dependency-analysis"
  - "step-07-sizing-analysis"
  - "step-08-metrics-analysis"
  - "step-09-verdict"
inputDocuments:
  - "_bmad-output/planning-artifacts/prd-whatsapp-ai-bot-saas-v1.md"
  - "_bmad-output/planning-artifacts/architecture-whatsapp-ai-bot-saas-v1.md"
  - "_bmad-output/planning-artifacts/ux-design.md"
  - "_bmad-output/planning-artifacts/epics-saas-v1.md"
workflowType: "bmad-check-implementation-readiness"
project: "Malixis Reply v1"
author: "John (Product Manager)"
date: "2026-05-04"
verdict: "CONDITIONAL GO"
---

# Implementation Readiness Report — Malixis Reply v1

**Date:** 2026-05-04  
**Project:** Malixis Reply v1  
**Assessor:** John (Product Manager)  
**Documents Assessed:**

| Document | File | Status |
|---|---|---|
| PRD | `prd-whatsapp-ai-bot-saas-v1.md` | v1.0 Draft — Ready |
| Architecture | `architecture-whatsapp-ai-bot-saas-v1.md` | Approved |
| UX Design | `ux-design.md` | Ready for Implementation |
| Epics & Stories | `epics-saas-v1.md` | Revision 2 — Implementation-ready |

---

## Verdict

> ## ⚠️ CONDITIONAL GO
>
> The backlog is **structurally sound** and may proceed to Sprint Planning **after** the 5
> moderate issues listed in Section 10 are resolved. No functional requirement, enforcement rule,
> API screen, or success metric is unaddressed. However, 5 named inconsistencies in story
> acceptance criteria and schema terminology will cause developer confusion during implementation
> if not corrected before sprint kickoff.
>
> **Recommended action:** Resolve Moderate Issues M1–M5 (estimated 1–2 hours of story editing)
> then confirm GO before Sprint 1 planning session.

---

## 1. Document Discovery Inventory

**No duplicates found.** The user-specified documents are the canonical versions for this
assessment. Older generic files (`prd.md`, `architecture.md`, `epics.md`) exist alongside the
`-saas-v1` variants; those legacy files are out of scope for this assessment.

| Document Type | File Used | Version | Duplicate Present? |
|---|---|---|---|
| PRD | `prd-whatsapp-ai-bot-saas-v1.md` | 1.0 | Yes — `prd.md` (legacy; not assessed) |
| Architecture | `architecture-whatsapp-ai-bot-saas-v1.md` | Approved | Yes — `architecture.md` (legacy; not assessed) |
| UX Design | `ux-design.md` | Ready | No |
| Epics & Stories | `epics-saas-v1.md` | Revision 2 | Yes — `epics.md` (legacy; not assessed) |

**Recommendation:** Rename or archive the legacy generic files (`prd.md`, `architecture.md`,
`epics.md`) to prevent developers accidentally referencing the wrong documents during
implementation.

---

## 2. Functional Requirements Coverage (FR1–FR14)

**Result: ✅ PASS — All 14 FRs covered**

| FR | Summary | Epic | Story | Status |
|---|---|---|---|---|
| FR1 | Email/password auth, login, logout, password reset | Epic 1 | Stories 1.1, 1.2 | ✅ Covered |
| FR2 | Tenant isolation — all customer-plane data scoped | Epic 1 | Story 1.3 | ✅ Covered |
| FR3 | Plan selection + Stripe Checkout + subscription state | Epic 2 | Stories 2.1, 2.2 | ✅ Covered |
| FR4 | Monthly quota mapping from active subscription | Epic 2 | Story 2.3 | ✅ Covered |
| FR5 | Evolution API QR fetch, display, real-time status | Epic 3 | Story 3.1 | ✅ Covered |
| FR6 | Bot live state after QR connected; AI replies begin | Epic 3 | Story 3.2 | ✅ Covered |
| FR7 | Dashboard: connection status, usage, progress, reset date | Epic 4 | Story 4.1 | ✅ Covered |
| FR8 | Bot config: business name + persona prompt per tenant | Epic 4 | Story 4.2 | ✅ Covered |
| FR9 | Atomic idempotent usage increment per completed exchange | Epic 4 | Story 4.3 | ✅ Covered |
| FR10 | Usage limit reached: halt replies, blocked state, CTA | Epic 4 | Story 4.4 | ✅ Covered |
| FR11 | Auto-resume on billing reset or plan upgrade | Epic 4 | Story 4.5 | ✅ Covered |
| FR12 | Idempotent inbound webhook; no double-count on duplicate | Epic 4 | Story 4.3 | ✅ Covered |
| FR13 | Admin panel: list/search/view/disable/enable + audit | Epic 5 | Stories 5.1, 5.2, 5.3 | ✅ Covered |
| FR14 | Bot config changes apply without redeploy | Epic 4 | Story 4.2 | ✅ Covered |

**No gaps.** FR11 and FR12 share Story 4.3/4.5 with FR9 — coverage is intentional (billing
reset in 4.5 handles FR11; idempotency in 4.3 handles FR12).

---

## 3. Enforcement Rules Coverage (ENF-01 through ENF-12)

**Result: ✅ PASS — All 12 ENF rules assigned, all have test story coverage**

| Rule | Constraint | Story Implementation | Test Coverage |
|---|---|---|---|
| ENF-01 | No AI reply unless `subscriptions.status IN ('active', 'trialing')` | Stories 2.2, 2.3 | Story 6.2 |
| ENF-02 | No AI reply if `usage_counters.is_blocked = TRUE` | Story 4.4 | Story 6.2 |
| ENF-03 | No AI reply if `tenants.is_active = FALSE` | Stories 1.3, 5.3 | Story 6.1 |
| ENF-04 | No AI reply unless `connection_states.status = 'connected'` | Story 3.2 | Story 6.2 |
| ENF-05 | Idempotency check before count increment | Story 4.3 | Story 6.2 |
| ENF-06 | Usage event INSERT and counter UPDATE in same DB transaction | Story 4.3 | Story 6.2 |
| ENF-07 | `is_blocked` set atomically when `used >= limit` | Stories 4.3, 4.4 | Story 6.2 |
| ENF-08 | Enforcement check executes **before** OpenAI call | Story 4.4 | Story 6.2 |
| ENF-09 | Failed AI generation → no count, no reply | Story 4.3 | Story 6.2 |
| ENF-10 | Failed send → no count | Story 4.3 | Story 6.2 |
| ENF-11 | Plan upgrade → unblock if new limit > current used | Story 4.5 | Story 6.2 |
| ENF-12 | Billing period reset → `conversations_used = 0`, `is_blocked = FALSE` | Story 4.5 | Story 6.2 |

**Observation:** ENF-04 relies on Evolution API delivery behavior (not an in-app guard) and has
only implicit test coverage in Story 6.2 via bot reply tests. This is architecturally acceptable
(ENF-04 is enforced by the external system) but should be noted in the Story 3.2 implementation
notes so the developer does not attempt to add a redundant in-app check.

---

## 4. API Contract Screens Coverage (arch §9)

**Result: ✅ PASS — All 8 API contract screens referenced in at least one story**

| Screen | API Endpoints | Covered By | Status |
|---|---|---|---|
| Screen 1: Signup / Login | `POST /auth/signup`, `POST /auth/login`, `POST /auth/forgot-password`, `POST /auth/reset-password` | Story 1.2 | ✅ Covered |
| Screen 2: Plan Selection | `GET /billing/plans`, `POST /billing/checkout` | Story 2.1 | ✅ Covered |
| Screen 2 (supplemental): Billing Portal | `GET /billing/portal` | **Not covered by any story** | ⚠️ Gap — see M3 |
| Screen 3: QR Onboarding | `GET /onboarding/qr-code`, `GET /onboarding/status-stream` (SSE) | Story 3.1 | ✅ Covered |
| Screen 4: Dashboard | `GET /api/dashboard/summary` | Story 4.1 | ✅ Covered |
| Screen 5: Bot Configuration | `GET /config/bot`, `PUT /config/bot` | Story 4.2 | ✅ Covered |
| Screen 6: Limit Hit State | Dashboard `is_blocked: true`, `POST /billing/upgrade` | Story 4.4 | ✅ Covered |
| Screen 7: Admin Customer List | `GET /admin/api/customers` | Story 5.1 | ✅ Covered |
| Screen 8: Admin Customer Detail + Actions | `GET /admin/api/customers/{id}`, `POST /admin/api/customers/{id}/disable`, `POST /admin/api/customers/{id}/enable` | Stories 5.2, 5.3 | ✅ Covered |

**Gap identified:** `GET /billing/portal` is defined in arch §9 Screen 2 but is not assigned to
any story. This endpoint provides the Stripe Customer Portal for self-serve billing management
(plan changes, payment method updates). Its absence means existing subscribers cannot manage
their billing after activation. See **M3** below.

---

## 5. UX Design Requirements Coverage (UX-DR1 through UX-DR10)

**Result: ✅ PASS with caveats — All 10 UX-DRs mapped; 3 existing-feature items acceptable;
new SaaS screens lack detailed wireframes**

| UX-DR | Screen | Covered By | Status |
|---|---|---|---|
| UX-DR1 | Setup (`/setup`) — env key checklist + step indicators | Story 1.1 (app prerequisite) | ✅ Mapped |
| UX-DR2 | Dashboard 3-column grid + 30 s auto-refresh | Story 4.1 | ✅ Covered |
| UX-DR3 | Bot Status red dot + "Not running" on health fail | Story 4.1 | ✅ Covered |
| UX-DR4 | Agent Selector radio card layout + toast on save | Existing feature — no SaaS story | ✅ Acceptable (pre-existing) |
| UX-DR5 | Metrics counter table + duration bars + reset dialog | Story 4.1 / existing feature | ✅ Acceptable (pre-existing) |
| UX-DR6 | Message Log ring buffer ≤ 100 entries + masked phones | Existing feature — no SaaS story | ✅ Acceptable (pre-existing) |
| UX-DR7 | Persistent sidebar (desktop) / bottom tab bar (mobile) | Story 4.1 (dashboard shell) | ✅ Covered |
| UX-DR8 | QR Onboarding real-time status + retry affordance | Story 3.1 | ✅ Covered |
| UX-DR9 | Plan selection three cards with price + limit | Story 2.1 | ✅ Covered |
| UX-DR10 | Dashboard blocked overlay + upgrade CTA + reset date | Story 4.4 | ✅ Covered |

**Important caveat:** The `ux-design.md` document was written for the original operator tool
(monitoring-only dashboard). It does not contain wireframes or detailed visual specs for the new
SaaS-specific screens:

- Authentication screens (signup, login, password reset)
- Stripe plan selection page
- QR onboarding flow (full wireframe)
- Bot configuration page
- Admin panel (list, detail, disable/enable)
- Blocked state overlay

UX-DR8, UX-DR9, and UX-DR10 capture brief requirements for three of these gaps, but a developer
implementing those screens has no visual reference beyond the acceptance criteria text in each
story. For a small team with strong frontend instincts, this is acceptable. For a team planning
UI QA or stakeholder review pre-launch, this is a gap. See **Minor Issue MI-2**.

---

## 6. Story Dependency Analysis

**Result: ✅ PASS — No forward dependency violations detected**

The dependency chain is fully sequential and acyclic:

```
1.1 → 1.2 → 1.3 → 2.1 → 2.2 → 2.3 → 3.1 → 3.2
                                             ├─> 4.1
                                             ├─> 4.2
                                             └─> 4.3 → 4.4 → 4.5
                                                              └─> 5.1 → 5.2 → 5.3
                                                                          └─> 6.1 → 6.2 → 6.3 → 6.4
```

Every story's declared `depends-on` correctly references stories that appear earlier in the chain.
No story depends on a story that is not yet complete at its position.

**One inconsistency found (non-blocking):**

Story 2.1 has `depends-on: Story 1.2` in its story card, but the dependency graph at the bottom
of `epics-saas-v1.md` shows `1.3 → 2.1`. These are not in conflict (Story 1.3 depends on 1.2,
so 1.2 is always done before 1.3), but the story card `depends-on` field should be updated to
`depends-on: Story 1.3` for unambiguous sprint planning. See **Minor Issue MI-1**.

**No circular dependencies.** All 20 stories can be ordered for single-developer sequential
execution without contradiction.

---

## 7. Story Sizing — Single Dev Session Completability

**Result: ⚠️ CONDITIONAL PASS — 18/20 stories clearly scoped; Story 1.2 may be too large**

| Story | Scope Assessment | Decision |
|---|---|---|
| 1.1 | DB schema bootstrap — all 8 tables + migration | ✅ One session (schema-only work) |
| 1.2 | 4 auth flows: signup, login, logout, password reset incl. email | ⚠️ **See M5 below** |
| 1.3 | Cross-tenant isolation test suite | ✅ One session |
| 2.1 | Plan selection UI + Stripe Checkout session creation | ✅ One session |
| 2.2 | Stripe webhook handler — 5 event types + idempotency + state machine | ✅ One session (heavy but focused) |
| 2.3 | Quota mapping from subscription → usage_counters init | ✅ One session |
| 3.1 | QR fetch + SSE status stream + retry affordance | ✅ One session |
| 3.2 | Bot live state + tenant routing + enforcement chain wire-up | ✅ One session |
| 4.1 | Dashboard API aggregation + UI polling | ✅ One session |
| 4.2 | Bot config CRUD + prompt injection guard | ✅ One session |
| 4.3 | Atomic usage metering + idempotency | ✅ One session |
| 4.4 | Enforcement guard + blocked state UI | ✅ One session |
| 4.5 | Billing reset + plan upgrade auto-resume | ✅ One session |
| 5.1 | Admin tenant list API + UI | ✅ One session |
| 5.2 | Admin search/filter + per-tenant detail | ✅ One session |
| 5.3 | Admin disable/enable + audit log | ✅ One session |
| 6.1 | Security baseline test suite | ✅ One session |
| 6.2 | Metering + billing lifecycle automated tests | ✅ One session |
| 6.3 | Staging E2E validation + go/no-go report | ✅ One session |
| 6.4 | SaaS ops docs update | ✅ One session |

**Story 1.2 concern:** Covers signup (tenant + user atomic creation), login (Flask-Login session),
logout (session invalidation), AND password reset (token generation, email dispatch, single-use
validation). All four paths require routes, service logic, templates, and tests. This is 4
distinct flows typically delivered as separate stories. See **M5** for the recommended split.

---

## 8. PRD Success Metrics Coverage (SM-1 through SM-9)

**Result: ✅ PASS — All 9 success metrics addressed in story acceptance criteria**

| Metric | Target | Referenced In | Coverage Quality |
|---|---|---|---|
| SM-1: Signup-to-live median time | ≤ 10 minutes | Stories 2.1, 3.1, 6.3 | ✅ E2E timing measured in Story 6.3 staging run |
| SM-2: Onboarding completion rate | ≥ 70% | Stories 3.1, 6.3 | ⚠️ Operational metric — requires production data; staging can only validate the flow completes |
| SM-3: AI reply rate under limit | ≥ 98% | Stories 3.2, 4.3, 6.2 | ⚠️ Operational metric — concurrency test in 6.2 validates no over-limit replies; reliability % requires production traffic |
| SM-4: Paid conversion from signup | ≥ 20% (90 days) | Stories 2.1, 6.3 | ⚠️ Business metric — not testable pre-launch; analytics tracking must be confirmed in staging |
| SM-5: Enforcement correctness | 100% stop at limit | Stories 4.4, 6.2 | ✅ Deterministic — verifiable in automated tests |
| SM-6: Dashboard freshness | ≤ 60 s lag | Stories 4.1, 4.3 | ✅ Verifiable via API timing assertion in Story 4.1 AC |
| SM-7: Admin diagnosis time | ≤ 2 min/account | Stories 5.1, 5.2 | ✅ UX-verifiable via usability walkthrough in Story 5.1 AC |
| SM-8: Dashboard page load P50 | ≤ 2 s | Story 4.1 | ✅ Performance target in Story 4.1 AC |
| SM-9: Status/usage API P50 | ≤ 500 ms | Story 4.1 | ✅ Performance target in Story 4.1 AC |

**Note on SM-2, SM-3, SM-4:** These are operational/business metrics that require live production
traffic to validate with statistical confidence. They should be tracked from day 1 of production
and reviewed at the 14-day and 30-day checkpoints defined in the PRD risk operating model. The
staging E2E run in Story 6.3 can demonstrate the path works but cannot validate the statistical
targets. This is expected and acceptable.

---

## 9. Additional Quality Observations

### Schema Naming Drift (Cross-Story)

The epics document contains a "Note on naming drift" that acknowledges two parallel naming
systems exist:

**Conceptual names** (in PRD and some story ACs):
`tenant_settings`, `tenant_whatsapp_sessions`, `billing_events`, `usage_idempotency`, `entitlements`

**Canonical schema names** (arch §4 SQL):
`bot_configs`, `connection_states`, `audit_log` (with `actor_type='stripe_webhook'`), `usage_events`, `subscriptions`

The note says canonical names supersede conceptual names. However, the naming drift has *not*
been fully cleaned up in all story acceptance criteria. Specific violations that will cause
developer confusion at implementation time are catalogued in Section 10 below.

### Usage Reconciliation Job — No Delivery Story

The architecture (§6) defines a daily cron job (`jobs/usage_reconciliation.py`) that compares
`usage_events` counts against `usage_counters` and alerts on > 0.5% delta. This is referenced
in the PRD risk register (R2 detective control). No story in Epic 6 is assigned to build this
job. Story 6.2 tests against it implicitly, but if no story builds it, it will not ship.
See **Minor Issue MI-3**.

### NFR5 (Structured Observability) — No Dedicated Story

NFR5 requires structured logs with `tenant_id` and correlation IDs on every log line. The
architecture defines an `Observability` shared service but no story explicitly delivers it.
Story 3.2 extends observability and Story 6.1 validates no secrets appear in logs, but
correlation ID injection and structured logging format are not formally acceptance-criteria-tested.
See **Minor Issue MI-4**.

---

## 10. Gap Register

### Moderate Issues — Must resolve before Sprint Planning

These issues are concrete enough to cause a developer to implement the wrong thing.

---

**M1 — `entitlements` terminology in Story 2.2 and 2.3 ACs conflicts with canonical schema**

*Severity:* Moderate  
*Stories affected:* 2.2, 2.3  
*Description:* Story 2.2 AC states "the `entitlements` record for the affected tenant is
updated." Story 2.3 AC states "the `entitlements` record includes `monthly_quota` set to…"
There is no `entitlements` table in the canonical arch §4 schema. The correct table is
`subscriptions` (for plan/limit/status state) combined with `usage_counters` (for block state).
A developer reading the AC literally will look for a non-existent table.  
*Fix:* In Stories 2.2 and 2.3, replace all AC references to "`entitlements` record" with
"`subscriptions` record" (for plan/status changes) and "`usage_counters` record" (for block
state changes). Technical References already use the correct canonical names; the AC prose just
needs to match.

---

**M2 — Story 1.1 AC table list uses conceptual names, not canonical schema names**

*Severity:* Moderate  
*Stories affected:* 1.1  
*Description:* Story 1.1's first AC criterion lists these tables to create:
`tenants`, `users`, `tenant_memberships`, `tenant_settings`, `subscriptions`, `entitlements`,
`usage_counters`, `usage_idempotency`, `billing_events`, `tenant_whatsapp_sessions`, `audit_logs`.

The canonical arch §4 schema defines:
`tenants`, `users`, `subscriptions`, `usage_events`, `usage_counters`, `connection_states`,
`bot_configs`, `audit_log`.

Discrepancies:
- `tenant_memberships` → **not in arch §4** (no membership table defined; single-user per tenant)
- `tenant_settings` → should be `bot_configs`
- `entitlements` → not a table; state lives in `subscriptions` + `usage_counters`
- `usage_idempotency` → should be `usage_events` (idempotency_key is a column on this table)
- `billing_events` → arch §4 uses `audit_log` with `actor_type='stripe_webhook'`; no separate `billing_events` table
- `tenant_whatsapp_sessions` → should be `connection_states`
- `audit_logs` (plural) → should be `audit_log` (singular, per arch §4)

A developer who creates the wrong tables in Story 1.1 will create a cascade of naming errors
across all subsequent stories.  
*Fix:* Update Story 1.1 AC table list to exactly match arch §4: `tenants`, `users`,
`subscriptions`, `usage_events`, `usage_counters`, `connection_states`, `bot_configs`,
`audit_log`. Remove `tenant_memberships` and `entitlements` from the list. Add a note that
`billing_events` are stored as rows in `audit_log` with `actor_type = 'stripe_webhook'`.

---

**M3 — `GET /billing/portal` defined in arch §9 Screen 2 has no story coverage**

*Severity:* Moderate  
*Stories affected:* None (gap)  
*Description:* Architecture §9 Screen 2 defines `GET /billing/portal` which returns a Stripe
Customer Portal URL for existing subscribers to manage their billing (plan changes, payment
method updates, invoice history). This endpoint is defined in the architecture contract but does
not appear in any story's acceptance criteria or technical references. Without this, customers
who want to change their plan or update a payment method have no self-serve path after the
initial checkout.  
*Fix:* Add `GET /billing/portal` to Story 2.1's technical references and acceptance criteria,
or create a thin Story 2.4: "Stripe Customer Portal Access" scoped to: implement the portal
redirect endpoint, add a "Manage billing" link on the dashboard for active subscribers.

---

**M4 — Story 4.2 AC says `tenant_settings` but canonical table is `bot_configs`**

*Severity:* Moderate  
*Stories affected:* 4.2  
*Description:* Story 4.2 AC states "the values are persisted to `tenant_settings` scoped to
their `tenant_id`." The canonical arch §4 table is `bot_configs` (with `tenant_id` PK,
`business_name`, `ai_persona_prompt`, `updated_at`). The Technical References section of Story
4.2 correctly states `bot_configs`, so the inconsistency is only in the AC prose — but the AC
is what a developer signs off against.  
*Fix:* Change Story 4.2 AC "persisted to `tenant_settings`" to "persisted to `bot_configs`."

---

**M5 — Story 1.2 may exceed single-session scope (4 distinct auth flows including email)**

*Severity:* Moderate  
*Stories affected:* 1.2  
*Description:* Story 1.2 covers: (1) new user signup with atomic tenant + user creation;
(2) login with Flask-Login session management; (3) logout with session invalidation; and
(4) password reset with token generation, email dispatch, single-use validation, and expiry.
Each flow requires routes, service logic, Jinja2 templates, and tests. Flow 4 alone introduces
an email-sending dependency (SMTP or transactional email service) that may require environment
configuration not yet scoped. This risks the story spanning two or more dev sessions and
blocking Story 1.3 (which depends on 1.2) from starting on time.  
*Recommended split:*
- **Story 1.2a:** Signup + login + logout (the core session lifecycle; no email needed)
- **Story 1.2b:** Password reset (token generation, email dispatch, single-use expiry)
  `depends-on: Story 1.2a`

Story 1.3 should then declare `depends-on: Story 1.2a` (isolation tests only need auth to
exist, not password reset).

---

### Minor Issues — Address before implementation begins

These issues are informational gaps that will not block Sprint 1 but should be addressed before
their respective stories are dev-started.

---

**MI-1 — Story 2.1 `depends-on` card inconsistent with dependency graph**

Story 2.1 story card declares `depends-on: Story 1.2` but the dependency graph shows
`1.3 → 2.1`. Update Story 2.1 `depends-on` to `Story 1.3` to match the graph and ensure
isolation tests are passing before billing flows begin.

---

**MI-2 — `ux-design.md` lacks wireframes for new SaaS screens**

The ux-design.md was authored for the original operator monitoring tool. It does not contain
visual specifications for: auth screens (signup/login/reset), plan selection page, QR onboarding
flow, bot configuration page, admin panel, or blocked state overlay. These screens are specified
via acceptance criteria in the stories (and briefly via UX-DR8, UX-DR9, UX-DR10) but have no
visual reference. For a small team this is acceptable; if UI QA or stakeholder review is planned,
add a SaaS screens section to ux-design.md before Epic 2 implementation begins.

---

**MI-3 — Usage reconciliation cron job (`jobs/usage_reconciliation.py`) has no delivery story**

The architecture §6 defines a daily cron job that compares `usage_events` row counts against
`usage_counters` and alerts on > 0.5% delta. This is a detective control for PRD Risk R2
(billing dispute prevention). No story in any epic is assigned to build this job. Add a task
to Story 6.2 or create a thin Story 6.5 to implement and configure this job so it ships with
v1 rather than being deferred.

---

**MI-4 — NFR5 structured observability has no explicit delivery story**

NFR5 requires structured logs with `tenant_id` and correlation ID on every log line. The
architecture defines an `Observability` shared service but no story contains acceptance criteria
for: structured log format validation, correlation ID injection per request, or tenant_id
presence on all log lines. Add an explicit AC to Story 6.1 (Security Baseline) or Story 1.1
(foundation) to gate the `Observability` service implementation.

---

## 11. Summary Scorecard

| Validation Check | Result | Score |
|---|---|---|
| FR1–FR14 story coverage | All 14 covered | ✅ 14/14 |
| ENF-01 through ENF-12 assigned | All 12 assigned with test coverage | ✅ 12/12 |
| API contract screens (arch §9) | 8/8 primary screens covered; 1 supplemental endpoint gap | ⚠️ 8/8 + M3 |
| UX-DR1 through UX-DR10 coverage | All 10 mapped; 3 existing-feature exemptions justified | ✅ 10/10 |
| Forward dependency violations | None — clean acyclic chain | ✅ 0 violations |
| Single-session story completability | 19/20 clearly scoped; Story 1.2 flagged | ⚠️ 19/20 |
| SM-1 through SM-9 in ACs | All 9 addressed; 3 are post-launch operational metrics | ✅ 9/9 |
| Moderate issues requiring pre-sprint fix | 5 identified | ⚠️ 5 issues |
| Minor issues (informational) | 4 identified | ℹ️ 4 items |

---

## 12. Pre-Sprint Planning Checklist

Before the Sprint 1 planning session, the following must be completed:

- [ ] **M1** — Fix `entitlements` → `subscriptions`/`usage_counters` in Stories 2.2 and 2.3 ACs
- [ ] **M2** — Fix Story 1.1 AC table list to match canonical arch §4 schema (remove
  `tenant_memberships`, `entitlements`, `billing_events`, `tenant_whatsapp_sessions`, `audit_logs`;
  add `usage_events`, `connection_states`, `bot_configs`, `audit_log`)
- [ ] **M3** — Assign `GET /billing/portal` to Story 2.1 or create Story 2.4
- [ ] **M4** — Fix Story 4.2 AC: `tenant_settings` → `bot_configs`
- [ ] **M5** — Split Story 1.2 into 1.2a (signup + login + logout) and 1.2b (password reset);
  update Story 1.3 `depends-on` accordingly

**Optional but recommended before Epic 2:**
- [ ] **MI-1** — Update Story 2.1 `depends-on` to Story 1.3
- [ ] **MI-3** — Add usage reconciliation job to Story 6.2 ACs or create Story 6.5
- [ ] **MI-4** — Add NFR5 structured logging ACs to Story 6.1 or Story 1.1
- [ ] Archive legacy `prd.md`, `architecture.md`, `epics.md` to prevent reference confusion

---

*Report generated by BMAD bmad-check-implementation-readiness workflow — 2026-05-04*  
*Assessor: John (Product Manager)*
