# Epic 9-12 Planning Artifacts - Next Cycle

generated: 2026-05-08
source_plan: sprint-plan-next-iteration-2026-05-07.md
source_prd: prd.md
status: Approved baseline
approved_by: Wahab (Project Lead)

---

## Epic 9 — Reliability Governance and First Production Adapter

**Goal:** Harden CI governance so all future scope is gated behind contract quality, then deliver the first non-WhatsApp production channel adapter behind the existing abstraction.

**User Value:** Support operations team gets a second delivery channel with the same reliability guarantees as WhatsApp, backed by enforceable quality gates that prevent regressions as the product expands.

**Exit Criteria:**
- Contract-test categories and evidence-template CI gate are active and blocking on main.
- One non-WhatsApp adapter live in staging with 100% parity suite pass.
- Mixed-channel delivery success >= 99.0% over >= 1,000 test deliveries.

**Risks:** R9-1 (adapter drift from WhatsApp baseline), R9-4 (governance weakens as scope expands).

---

### Story 9.1 — Governance Baseline Upgrade

**Type:** reliability / ci
**Priority:** P0
**Sprint:** 1

**Problem:** Stories can be merged without evidence templates. Contract tests have no mandatory category enforcement. Launch-gate artifact completeness is not CI-checked.

**Acceptance Criteria:**
- AC 9.1.1: CI check exists that blocks merge when mandatory contract-test category is missing for any adapter or analytics surface.
- AC 9.1.2: Story done-closure evidence template gate is active — merges missing the structured closure block are rejected by CI.
- AC 9.1.3: Launch-gate artifact completeness check runs on merge to main and fails the build if required sections are absent.
- AC 9.1.4: All existing Epics 1-8 story artifacts are retrospectively backfill-compatible (schema does not break on existing files).

**Out of Scope:** Rewriting existing story files; new RBAC enforcement.

**Test Strategy:** CI enforcement contract test — assert gate fires on a deliberately incomplete artifact and passes on a compliant one.

---

### Story 9.2 — Production Adapter Delivery (Single Non-WhatsApp Channel)

**Type:** feature / integration
**Priority:** P0
**Sprint:** 1

**Problem:** The channel abstraction from Epic 8.2 is interface-ready but no production non-WhatsApp adapter exists. Operators are locked into a single delivery channel.

**Acceptance Criteria:**
- AC 9.2.1: Adapter is wired behind the existing `ChannelAdapter` interface without modifying WhatsApp routing logic.
- AC 9.2.2: Channel-specific credentials are validated at startup; missing credentials put the adapter into disabled state (not crash state).
- AC 9.2.3: Routing policy is explicit and config-driven; no silent fallback to a different channel without log evidence.
- AC 9.2.4: All outbound log entries from the new adapter include `provider`, `correlation_id`, and outcome fields — no credential values in logs.
- AC 9.2.5: Adapter integrates with existing retry and fallback contract (same retry schedule and exhaustion semantics as WhatsApp path).

**Out of Scope:** More than one new adapter; adapter auto-selection logic; UI for channel routing.

**Test Strategy:** Unit tests for adapter contract; integration test wiring adapter into send path with mock credentials.

---

### Story 9.3 — Adapter Parity Contract Suite and Mixed-Channel Staging Gate

**Type:** reliability / test
**Priority:** P0
**Sprint:** 1

**Problem:** Without a shared outbound contract suite, the new adapter can silently diverge from WhatsApp baseline behaviors (retry, fallback, correlation, observability) without detection.

**Acceptance Criteria:**
- AC 9.3.1: Shared outbound contract test suite covers: success path, retry path, retry exhaustion with fallback semantics, correlation and observability fields — parameterized to run against both WhatsApp and new adapter.
- AC 9.3.2: Both adapters pass 100% of the parity suite.
- AC 9.3.3: Mixed-channel staging run of >= 1,000 deliveries shows success rate >= 99.0%.
- AC 9.3.4: Parity suite is gated in CI; a broken adapter cannot merge to main.

**Out of Scope:** Performance benchmarking beyond the 99.0% delivery SLA.

**Test Strategy:** Parameterized pytest suite; staging run documented as Gate C evidence artifact.

---

## Epic 10 — Analytics Productization v1

**Goal:** Convert the raw event foundation from Epic 8.3 into operator-consumable reporting: an API surface and a lightweight dashboard view.

**User Value:** Support operations lead can see message volume trends, escalation trends, delivery outcome breakdown, and latency summaries without needing raw JSONL access.

**Exit Criteria:**
- Analytics reporting API stable and contract-tested.
- Dashboard analytics v1 live in staging.
- Reporting freshness <= 60s from event to display.
- Retention-cap behavior verified by contract test.

**Risks:** R9-2 (analytics scope balloons into BI project). Strict v1 boundary: operational trends only, no data warehouse.

---

### Story 10.1 — Analytics Reporting API

**Type:** feature / api
**Priority:** P0
**Sprint:** 2

**Problem:** Analytics events are captured in `conversation_analytics_events.jsonl` but there is no API for operators or dashboards to consume aggregated insights.

**Acceptance Criteria:**
- AC 10.1.1: `GET /api/analytics/summary` returns: message volume trend (daily, last 7 days), escalation trend (daily, last 7 days), delivery outcome breakdown (success/retry/failure counts), and latency summary (p50/p95/p99 from event data) — all sourced from the event foundation.
- AC 10.1.2: Response format is stable and contract-tested; any breaking change fails the consumer contract test.
- AC 10.1.3: Retention policy is applied: events older than the configured cap are excluded from query results and a pruning mechanism exists.
- AC 10.1.4: Endpoint is protected by existing operator authentication (no public access).
- AC 10.1.5: API responds within <= 500ms for <= 10,000 stored events.

**Out of Scope:** Export formats; data warehouse integration; real-time streaming; per-user drill-down beyond wa_id.

**Test Strategy:** Unit tests for aggregation logic; contract test for response schema stability; retention-cap contract test.

---

### Story 10.2 — Dashboard Analytics v1

**Type:** feature / frontend
**Priority:** P0
**Sprint:** 2

**Problem:** Operators must read raw event files to understand operational health. There is no visual surface for trends or outcome summaries.

**Acceptance Criteria:**
- AC 10.2.1: Analytics section in operator dashboard displays: message volume trend chart (7-day), escalation rate indicator, delivery outcome breakdown (success/retry/failure proportions), and latency trend.
- AC 10.2.2: Data refreshes from the Analytics Reporting API (Story 10.1) — no separate data path.
- AC 10.2.3: Dashboard analytics section is visible only to authenticated operators (no public exposure).
- AC 10.2.4: Section degrades gracefully when fewer than 24h of events exist (shows "Insufficient data" state, does not crash or show misleading zeros).
- AC 10.2.5: No new JS framework dependencies introduced beyond current stack.

**Out of Scope:** Export/download of chart data; real-time push updates; custom date ranges beyond 7-day default.

**Test Strategy:** UI contract test asserting presence of analytics section and graceful degradation state; integration test against Story 10.1 API.

---

## Epic 11 — SQLite Operational Readiness Gate

**Goal:** Produce explicit, documented evidence that SQLite is production-ready: a 24h staging soak, a rollback drill, and a restart continuity check — all automated and artifact-generating.

**User Value:** Platform owner can make an evidence-backed decision to enable SQLite in production with a documented rollback path they've drilled, not just assumed.

**Exit Criteria:**
- 24h staging soak automated and artifact generated with zero Sev-1/Sev-2 incidents.
- Rollback drill automated and completes <= 15 min.
- Restart continuity check passes.
- Operational playbook updated with SQLite section.

**Risks:** R9-3 (SQLite behavior differs across runtime environments). Soak + rollback evidence must explicitly cover the target production OS (Linux).

---

### Story 11.1 — SQLite 24h Soak Automation and Evidence Artifact

**Type:** reliability / ops
**Priority:** P0
**Sprint:** 2

**Problem:** SQLite is implemented as an optional rollout slice (Epic 8.4) but there is no staged evidence that it is stable over a sustained production-representative load. The "optional" safety posture cannot be upgraded to "recommended" without this evidence.

**Acceptance Criteria:**
- AC 11.1.1: Automated soak harness runs a representative message volume through the SQLite path for 24h in staging and captures: error rate, latency percentiles, memory trend, and any crash/exception events.
- AC 11.1.2: Soak results are written to a structured evidence artifact file (`sqlite-soak-evidence-<date>.md`) with pass/fail determination against defined thresholds.
- AC 11.1.3: Pass threshold: zero Sev-1/Sev-2 SQLite incidents (crashes, data loss, or silent corruption) during soak.
- AC 11.1.4: Enablement test and failover-to-memory behavior check are run as part of soak setup and results captured in the artifact.
- AC 11.1.5: Restart continuity check: service restart mid-soak with state recovery assertion passes.

**Out of Scope:** Multi-node replication; migration to a different persistence engine.

**Test Strategy:** Soak harness script; evidence artifact reviewed and approved as Gate C prerequisite.

---

### Story 11.2 — Rollback Drill Automation and Acceptance Artifact

**Type:** reliability / ops
**Priority:** P0
**Sprint:** 2

**Problem:** A rollback from SQLite to memory-store has no documented drill. Without evidence that the rollback completes in <= 15 min, the operations team cannot commit to the SQLite path.

**Acceptance Criteria:**
- AC 11.2.1: Rollback drill script exists that: disables SQLite flag, restarts service, verifies memory-store path is active, and asserts no data corruption in the transition.
- AC 11.2.2: Drill execution is timed and the elapsed time is captured in the evidence artifact.
- AC 11.2.3: Acceptance criterion: drill completes in <= 15 min end-to-end.
- AC 11.2.4: Evidence artifact (`sqlite-rollback-drill-<date>.md`) contains: steps executed, timings, pass/fail per step, and sign-off section.
- AC 11.2.5: Operational runbook is updated with a "SQLite Rollback Procedure" section referencing the drill artifact.

**Out of Scope:** Automated rollback triggered by monitoring alert (on-call automation is P2 scope).

**Test Strategy:** Timed drill run; artifact reviewed as Gate C prerequisite alongside soak evidence.

---

## Epic 12 — SaaS v1 Customer Value Pull (Conditional Sprint 3)

**Goal:** Deliver the highest-impact deferred P1 customer features: in-app notifications, conversation history visibility, and a self-serve reconnection assistant.

**Pull Condition:** Epic 12 stories are only pulled into Sprint 3 after Epic 9 P0 gate and Epic 10/11 P0 gate are both complete AND full suite remains green. If either gate is incomplete at Sprint 2 close, Epic 12 is deferred to the following cycle.

**User Value:** SMB operators get actionable billing/usage alerts, visibility into conversation history without raw DB access, and a guided troubleshooting path when their WhatsApp connection drops.

**Exit Criteria (conditional):**
- Notification center delivers in-app billing and usage alerts.
- Conversation history viewer provides read-only access with search.
- Reconnection assistant guides operators through common failure resolutions without engineering involvement.

**Risks:** Sprint 3 pull is conditional — reliability regression in Epics 9-11 defers this entire epic without penalty.

---

### Story 12.1 — Notification Center (Billing and Usage Alerts)

**Type:** feature / saas
**Priority:** P1
**Sprint:** 3 (conditional)

**Problem:** Operators have no in-app alerts for billing events (trial expiry, payment failure) or usage thresholds. They discover problems after impact (failed payments, unexpected service suspension).

**Acceptance Criteria:**
- AC 12.1.1: Notification center panel in operator dashboard displays: trial expiry warnings (7-day, 1-day), payment failure alerts, and usage threshold warnings (configurable % of plan limit).
- AC 12.1.2: Notifications are persisted per tenant and dismissed individually; dismissal survives page reload.
- AC 12.1.3: Billing alerts are triggered by Stripe webhook events (existing Stripe integration); no polling.
- AC 12.1.4: Usage threshold alerts are computed from conversation analytics event counts (Story 10.1 data).
- AC 12.1.5: Notifications are tenant-isolated — no cross-tenant leakage.

**Out of Scope:** Email/SMS notification delivery; push notifications; admin-broadcast notification type.

**Test Strategy:** Unit tests for notification persistence and isolation; integration test for Stripe event → notification creation flow.

---

### Story 12.2 — Conversation History Viewer (Read-Only v1)

**Type:** feature / saas
**Priority:** P1
**Sprint:** 3 (conditional)

**Problem:** Operators cannot review past conversation threads without direct database access. Support escalations are blind to context.

**Acceptance Criteria:**
- AC 12.2.1: "Conversations" section in operator dashboard displays a paginated list of conversations (wa_id, date, message count, escalation flag) sourced from the idempotency/analytics event store.
- AC 12.2.2: Clicking a conversation shows the message thread (sender, text body, timestamp, delivery status) in chronological order.
- AC 12.2.3: Search by wa_id and date range works with results returned in <= 2s for <= 10,000 stored conversations.
- AC 12.2.4: Data is tenant-isolated; operators only see their tenant's conversations.
- AC 12.2.5: View is strictly read-only — no reply, edit, or delete actions.

**Out of Scope:** Bulk export; full-text message search beyond wa_id + date range; conversation tagging or labeling.

**Test Strategy:** Contract test for history API schema stability; tenant isolation test; performance assertion for search SLA.

---

### Story 12.3 — Reconnection Assistant (Guided Troubleshooting Path)

**Type:** feature / saas
**Priority:** P1
**Sprint:** 3 (conditional)

**Problem:** When the WhatsApp connection drops (Evolution API QR expiry, token rotation, instance restart), operators have no guided path to resolve it. They either wait for engineering support or follow undocumented steps.

**Acceptance Criteria:**
- AC 12.3.1: "Connection Status" section in operator dashboard shows: current connection state (connected / disconnected / QR required / error), last seen timestamp, and a "Reconnect" action button when applicable.
- AC 12.3.2: "Reconnect" flow guides the operator through: step 1 — display new QR code (fetched from Evolution API), step 2 — QR scan confirmation, step 3 — connection state verification with pass/fail outcome.
- AC 12.3.3: Common failure reasons are surfaced with plain-language explanations and specific next steps (QR expiry, token rotation needed, instance not running).
- AC 12.3.4: Reconnection attempts are logged with correlation ID, outcome, and timestamp for operator audit trail.
- AC 12.3.5: If automatic reconnection is not possible (e.g., instance unreachable), the assistant shows a "Contact support" path rather than a broken spinner.

**Out of Scope:** Automatic reconnection without operator action; multi-instance management; provider-switching from the reconnection assistant.

**Test Strategy:** Unit tests for connection state transitions; integration test for QR fetch and confirmation flow with mocked Evolution API.

---

## Delivery Sequencing Summary

| Sprint | Stories | Gate |
|--------|---------|------|
| Sprint 1 | 9.1, 9.2, 9.3 | Gate B: CI governance + parity suite + adapter staging pass |
| Sprint 2 | 10.1, 10.2, 11.1, 11.2 | Gate C: analytics freshness + SQLite soak + rollback drill |
| Sprint 3 (conditional) | 12.1, 12.2, 12.3 | Gate D: no open High risks + runbook updated + smoke checklist passes |

**Pull rule for Sprint 3:** All Sprint 1 and Sprint 2 P0 gate criteria must be green AND full suite must remain clean. If blocked, Epic 12 moves to the next cycle without penalty to Epic 9-11 completion.

---

## Acceptance Metrics Reference

| Area | Metric | Target |
|------|--------|--------|
| Adapter delivery | Mixed-channel success rate | >= 99.0% over 1,000 deliveries |
| Adapter parity | Parity contract suite | 100% pass (WhatsApp + new adapter) |
| Analytics freshness | Event-to-dashboard latency | <= 60s |
| Analytics reliability | Event ingestion success | >= 99.9% in staging |
| SQLite soak | Sev-1/Sev-2 incidents | 0 during 24h soak |
| SQLite rollback | Drill completion time | <= 15 min |
| Governance | Mandatory contract test coverage | 0 bypass merges on main |
| Governance | Regression escapes | 0 Sev-1 escapes from contract drift |
