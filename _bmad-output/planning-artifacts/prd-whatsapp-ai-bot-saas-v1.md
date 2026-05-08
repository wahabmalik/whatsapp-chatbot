---
stepsCompleted: ["step-01-init"]
inputDocuments: []
workflowType: "prd"
date: "2026-05-03"
---

# Product Requirements Document - Malixis Reply v1

Author: Wahab
Date: 2026-05-03
Status: Draft - Ready for architecture and epic breakdown
Version: 1.0

## Problem and User

### Product Vision
A batteries-included SaaS that lets non-technical businesses connect their WhatsApp number in minutes, enable AI auto-replies, and run customer messaging without setup complexity.

### Target User
Primary user:
- Non-technical small business owner or operations manager who needs immediate automated customer replies on WhatsApp.

Secondary users:
- Team member responsible for billing/subscription.
- Internal admin/support operator managing customer health and usage.

### Core Problem
Current AI + WhatsApp automation tools often require API setup, technical configuration, and infrastructure management. This creates onboarding friction and delays value realization for non-technical users.

### Jobs To Be Done
- "When I subscribe, I want to connect my WhatsApp quickly so I can start auto-replying today."
- "When my usage grows, I want clear plan limits and an easy upgrade path."
- "When I run the bot, I want it to stay reliable without technical maintenance."

### Existing Asset Leverage
- Existing Python/Flask bot already handles:
  - AI response generation.
  - Evolution API WhatsApp integration.
- v1 focus is a multi-tenant SaaS management layer, billing, onboarding UX, and usage governance.

## Goals and Metrics

### Product Goals (v1)
1. Enable a new customer to go from signup to live WhatsApp bot in under 10 minutes.
2. Deliver predictable subscription-based usage with strict monthly enforcement.
3. Provide clear self-serve visibility into connection status and usage consumption.
4. Give internal admins complete operational control over customers and account states.

### Success Metrics

| Area | Metric | Target |
| --- | --- | --- |
| Activation | Signup-to-live bot median time | <= 10 minutes |
| Activation | Onboarding completion rate (signup to QR connected) | >= 70% |
| Reliability | Successful AI reply rate while under limit | >= 98% |
| Monetization | Paid conversion from signup | >= 20% (first 90 days) |
| Billing Integrity | Usage-plan enforcement correctness | 100% of limit-hit accounts stop replying |
| Transparency | Dashboard usage freshness | <= 60s lag |
| Supportability | Admin time to identify customer status | <= 2 minutes per account |

### Business Model and Pricing (Confirmed)
- Starter: $29/month, 2,000 AI-powered conversations.
- Pro: $49/month, 5,000 AI-powered conversations.
- Business: $99/month, 15,000 AI-powered conversations.

Conversation definition (billing unit):
- 1 conversation = 1 customer message + 1 AI reply (one full exchange).

### Non-Goals (v1)
- Multi-channel support beyond WhatsApp.
- Complex workflow builder/automation rules.
- Team-level RBAC beyond basic admin capabilities.
- White-label/multi-branding.
- Meta WhatsApp Business API integration.

## Prioritized Requirements

### P0 Requirements (Must-Have for v1 Launch)

#### P0-R1: Authentication and Account Basics
- Email + password signup.
- Login/logout and secure session management.
- Password reset flow.
- Account must be linked to a tenant/workspace context.

Acceptance criteria:
- Users can create and authenticate accounts without technical assistance.
- Tenant isolation enforced for all customer-facing data operations.

#### P0-R2: Plan Selection and Stripe Billing
- User selects plan (Starter/Pro/Business) before activation.
- Stripe checkout for subscription start.
- Subscription status reflected in product (active, past_due, canceled).
- Monthly usage cycle aligned with billing period.

Acceptance criteria:
- No bot activation unless subscription is active.
- Plan limits automatically mapped to monthly conversation quotas.

#### P0-R3: Onboarding with Evolution API QR Connection
- Onboarding page fetches and displays QR code from Evolution API.
- User scans QR with WhatsApp to link phone number.
- Real-time connection status updates (disconnected, connecting, connected).
- Once connected, bot transitions to live state.

Acceptance criteria:
- Connection can be completed without manual support for standard path.
- Connected status persists and is visible in dashboard.

#### P0-R4: Dashboard Visibility
- Display current WhatsApp connection state.
- Display monthly conversations used and plan limit.
- Display progress bar and remaining conversation count.
- Show billing cycle reset date.

Acceptance criteria:
- Usage values are accurate and consistent with enforcement counter.
- Dashboard refresh reflects near-real-time state.

#### P0-R5: Bot Configuration
- Customer can set business name.
- Customer can set custom AI instructions/persona prompt.
- Configuration updates apply to subsequent AI replies.

Acceptance criteria:
- Config values are persisted per tenant.
- AI response behavior reflects updated instructions on new messages.

#### P0-R6: Usage Enforcement and Upgrade Prompt
- System increments usage after each completed exchange (message + reply).
- When plan limit is reached:
  - Bot stops AI auto-replies.
  - Customer dashboard shows limit reached state.
  - Upgrade CTA and next reset date shown.
- On cycle reset or plan upgrade, replies resume automatically.

Acceptance criteria:
- Enforcement is deterministic and auditable.
- No replies generated while blocked state is active.

#### P0-R7: Internal Admin Panel
- Admin can list all customers.
- Admin can view customer status: plan, usage, subscription state, connection state.
- Admin can search/filter customers.
- Admin can manually disable or re-enable a tenant in emergency cases.

Acceptance criteria:
- Admin actions are logged.
- Customer-level operational diagnostics are accessible in one place.

### P1 Requirements (Post-v1, Next Increment)
- In-app notification center for billing/usage alerts.
- Conversation history viewer in dashboard.
- More granular usage analytics (daily trends by week/month).
- Self-serve phone reconnection troubleshooting assistant.

### P2 Requirements (Future)
- Team seats and role-based access.
- API access for enterprise customers.
- Add-on packs or overage billing model.

## MVP Scope

### In Scope (v1 MVP)
- Multi-tenant auth and account management.
- Stripe subscription onboarding with fixed plans.
- Evolution API QR linking flow and live status.
- Core dashboard (connection + usage + limit progress).
- Basic bot persona/instruction config.
- Hard monthly usage enforcement with stop + upgrade prompt.
- Internal admin panel for customer operations.

### Out of Scope (v1 MVP)
- Channels other than WhatsApp.
- Complex AI orchestration, tool calling, or memory management UI.
- Marketplace integrations and CRM sync.
- Advanced analytics dashboards.

### Incremental Delivery Plan (Recommended)
1. Foundation release:
   - Multi-tenant model, auth, subscription model wiring, tenant-safe data boundaries.
2. Activation release:
   - Stripe checkout + onboarding QR + connection lifecycle.
3. Operations release:
   - Dashboard usage metrics + enforcement + upgrade UX.
4. Internal control release:
   - Admin panel, customer controls, audit trail, launch hardening.

## Functional Flows (v1)

### F1: New Customer Activation Flow
1. User signs up.
2. User selects plan and completes Stripe checkout.
3. User lands on onboarding screen.
4. System displays Evolution API QR.
5. User scans QR in WhatsApp.
6. Connection becomes connected.
7. Bot starts auto-replying.

### F2: Live Usage and Enforcement Flow
1. Customer message received.
2. AI generates reply.
3. Usage counter increments by one conversation unit.
4. If usage < limit, continue serving.
5. If usage reaches limit, set blocked status and halt auto-replies.
6. Dashboard displays blocked state and upgrade/reset options.

### F3: Billing Cycle Reset Flow
1. New billing cycle starts (Stripe period reset).
2. Usage counter resets to zero for active subscriptions.
3. Blocked accounts return to active (if payment state is valid).

## Non-Functional Requirements

### Security and Privacy
- Tenant isolation on all reads/writes.
- Passwords stored securely (hash + salt).
- Secure secrets management for API keys and Stripe credentials.
- Basic audit logging for admin actions and critical state changes.

### Reliability
- Ensure resilient handling of transient Evolution API failures.
- Retry policy for outbound AI reply path with safe failure handling.
- Service health endpoints and operational visibility.

### Performance
- Dashboard page load target: <= 2 seconds p50 under expected launch load.
- Status/usage API response target: <= 500ms p50.

### Observability
- Structured logs with tenant ID and correlation IDs.
- Metrics for connection status, reply success/failure, usage increments, and blocked events.

## Data and Metering Rules

### Usage Counter Source of Truth
- Count usage at successful exchange completion boundary:
  - inbound customer message accepted
  - outbound AI reply successfully produced/sent

### Edge Case Rules
- If inbound is received but reply fails permanently, do not count as completed conversation.
- Retries for the same inbound message must not double-count.
- Duplicate webhook/message delivery must be idempotent.

### Limit Enforcement Rules
- Enforcement check runs before generating/sending new AI reply.
- If remaining quota is zero, skip generation and return blocked behavior path.

## Dependencies

### External
- Evolution API for WhatsApp QR and session connectivity.
- GPT-4o mini for AI replies.
- Stripe for subscriptions and billing lifecycle events.

### Internal
- Existing Flask bot runtime and message processing pipeline.
- Existing Evolution API adapter integration code.

## Risks and Mitigations

| ID | Risk | Severity | Preventive Controls | Detective Controls | Response Playbook | Exit Criteria |
| --- | --- | --- | --- | --- | --- | --- |
| R1 | Evolution API instability impacts onboarding or live delivery | High | Circuit breaker + retry with jitter, connection timeout budget, reconnect UX path | Synthetic QR-connect probe every 5 min, alert if success < 98% over rolling 1h | Auto-failover to reconnect mode, incident comms banner, retry queue drain after service recovery | >= 98% successful connection completion in staging and >= 97% in first 14-day production cohort |
| R2 | Incorrect usage counting leads to billing disputes | High | Idempotency keys per inbound message, atomic usage writes, contract tests for duplicate/retry paths | Daily metering reconciliation job and anomaly alert on count deltas > 0.5% | Freeze disputed tenant counter, run replay-safe reconciliation, issue credit if mismatch confirmed | 100% pass on metering contract suite and 0 unresolved billing disputes at launch |
| R3 | Stripe webhook/state drift causes wrong entitlements | High | Verified webhook signatures, replay protection, event versioning, entitlement state machine | Alert on webhook failures > 0.1% and entitlement mismatch dashboard | Replay dead-lettered events, force resync from Stripe API, temporarily degrade to read-only entitlement actions | 0 unresolved entitlement mismatches and 100% pass on webhook replay tests |
| R4 | Multi-tenant data leakage risk | Critical | Tenant-scoped query helpers mandatory, row-level tenant checks in service layer, secure admin boundary | Security tests in CI, tenant-isolation canary tests, log scan for cross-tenant access | Immediate tenant lock + incident response protocol + forensic audit + customer notification workflow | 0 critical/high tenant-isolation findings pre-launch |
| R5 | Limit enforcement bypass under concurrency | High | Atomic compare-and-set counter update and pre-send quota guard | Concurrency stress test monitors for over-limit replies | Trigger protection mode (block sends), backfill counter correction, unblock after integrity validation | 0 bypass events across stress tests at 2x expected peak |
| R6 | AI cost pressure if usage forecasting is wrong | Medium | Per-plan hard caps, model token guardrails, prompt size limits | Cost-per-tenant and gross margin dashboard daily | Temporary response length throttling and rapid pricing review for next cycle | Cost per paid account stays within target gross margin band |
| R7 | AI provider outage or latency spike degrades replies | High | Timeout budgets, retry policy, graceful fallback response template | Provider latency/error SLO alerting (p95 and 5xx rate) | Enter degraded mode with transparent fallback replies and queued retries | >= 99% reply-path availability in staging soak and no Sev-1 unresolved at launch |
| R8 | Abuse/spam traffic consumes quota and harms service quality | Medium | Basic abuse heuristics, per-tenant rate limits, suspicious pattern throttling | Abuse event dashboard and threshold alerts | Auto-throttle tenant, flag for admin review, optional temporary suspension | < 1% tenants with unresolved abuse incidents in first 30 days |
| R9 | Onboarding drop-off due to unclear QR flow | Medium | Guided onboarding copy, status hints, reconnect CTA, retry affordances | Funnel analytics at each onboarding step with alert on completion drop > 10% WoW | UX hotfix release and support outreach playbook | >= 70% signup-to-connected onboarding completion |
| R10 | Admin misuse or accidental suspension impacts customers | Medium | Role separation for support vs super-admin actions, confirmation flows for destructive actions | Audit-log alerts on bulk/critical admin actions | One-click rollback for account state changes and post-incident review | 100% admin critical actions logged and reversible |

### Risk Operating Model (No-Issue Guardrail Plan)
- Daily: automated checks for onboarding success, metering integrity, webhook health, and quota enforcement anomalies.
- Weekly: risk review with product, engineering, and operations; update risk owners and mitigation status.
- Release gate rule: no open Critical risk and no unaccepted High risk before production cut.
- Rollback rule: any Sev-1 incident in first 72 hours triggers immediate rollback decision review.
- Ownership rule: each risk has a single DRI (directly responsible individual) assigned in implementation artifacts.

Note on residual risk:
- v1 can materially reduce risk through controls, but no software launch can guarantee zero incidents; this PRD targets zero unresolved Critical/High risks at launch and fast containment for any incident that occurs.

## Launch Readiness and Acceptance Gates

### Gate A: Product and Technical Readiness
- All P0 requirements implemented and acceptance criteria met.
- Security baseline checks passed for auth and tenant isolation.

### Gate B: Staging Validation
- End-to-end activation flow tested across all plans.
- Metering and enforcement tests pass under normal and edge conditions.
- Admin workflows validated with sample tenant set.

### Gate C: Production Candidate
- Billing lifecycle events stable for create/renew/fail/cancel paths.
- Operational runbook and support SOP prepared.
- No unresolved High/Critical launch defects.

## Open Assumptions
1. Existing Flask and Evolution integration can support tenant-aware session separation with moderate refactor only.
2. GPT-4o mini response quality is sufficient for v1 SMB support scenarios.
3. Stripe checkout and webhook setup can be completed without regional blockers.
4. Initial launch load fits within a single-region deployment posture.

## Future Evolution (Post-v1 Direction)
- Optional overage packs or metered add-ons.
- Rich analytics and funnel insights.
- Guided onboarding assistant and quality presets by industry.
- Additional channels once WhatsApp unit economics and reliability are stable.

## Document Control

Document Status: Ready for architecture and epic/story decomposition
Last Updated: 2026-05-03
Next Action: Create architecture solution and break P0 into implementation stories
