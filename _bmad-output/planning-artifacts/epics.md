---
stepsCompleted:
  - "step-01-validate-prerequisites"
  - "step-02-design-epics"
  - "step-03-create-stories"
inputDocuments:
  - "_bmad-output/planning-artifacts/prd.md"
  - "_bmad-output/planning-artifacts/architecture.md"
  - "_bmad-output/planning-artifacts/ux-design.md"
  - "docs/botpress_connection.md"
---

# python-whatsapp-bot - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for python-whatsapp-bot, decomposing the requirements from the PRD and Architecture into implementable stories.

---

## Requirements Inventory

### Functional Requirements

FR1: GET `/webhook` must verify `hub.verify_token` against configured VERIFY_TOKEN; return `hub.challenge` (200) on match, 403 on mismatch or missing token.

FR2: All POST requests to `/webhook` must validate the `X-Hub-Signature-256` header via HMAC-SHA256 before processing the message body; reject with 403 and log with correlation ID on failure.

FR3: Parse inbound WhatsApp webhook payloads and normalise into a canonical internal schema (user_id, message_text, timestamp, message_id); detect and skip duplicate events using a configurable expiring state store; exit gracefully on unsupported payload types.

FR4: Accept normalised inbound text and generate an AI-powered reply using the configured OpenAI service; return a typed response object; handle timeout, auth failure, and rate-limit errors as controlled states (not exceptions); record response latency.

FR5: Send the generated reply to the user's WhatsApp number via the Meta Cloud API; apply a retry policy of max 3 attempts with exponential backoff (1 s, 2 s, 4 s); after exhausted retries send a deterministic fallback message and flag for operator review.

FR6: Load the selected agent profile from `data/agent_selection.json` at request time; auto-repair to the first available agent on stale or invalid selection; new selection takes effect on the next inbound message without redeploy.

FR7: Validate all required environment variables at app startup before accepting traffic; exit with clear per-variable error messages on failure; log sanitised config status (sensitive values redacted) on success.

FR8: Attach a unique correlation ID to every inbound webhook request and propagate it through all downstream logs and error messages; sanitise tokens, secrets, and PII from all log output.

FR9 (P1): Maintain a rolling context of the last 5 messages per user for improved AI response coherence; trim oldest when limit is exceeded; reset context on new conversation or after timeout.

FR10 (P1): Detect and flag conversations requiring human escalation when AI confidence is low or message contains escalation keywords; emit escalation flag in logs and write to a queue artifact.

---

### NonFunctional Requirements

NFR1: Availability — webhook endpoint must achieve ≥ 99.5% uptime in production.

NFR2: Latency — end-to-end response time P50 ≤ 4 s, P95 ≤ 8 s.

NFR3: Reliability — inbound-to-reply message success rate ≥ 99% measured in staging over 1 000 test messages.

NFR4: Security — 100% of inbound POST requests undergo signature validation; zero bypass paths permitted at deploy.

NFR5: Scalability — sustain ≥ 10 msg/sec throughput in staging load tests.

NFR6: Recovery — time from first API failure to fallback reply delivered ≤ 10 s.

NFR7: Logging — log retention ≥ 30 days for incident triage.

NFR8: Deployment — operator can complete initial config setup in < 2 minutes from documented runbook.

---

### Additional Requirements

- **App Factory lifecycle**: Flask app factory must own config loading, validation, blueprint registration, and teardown hooks; reliability components are app-scoped extensions, not process globals (Architecture Decision 1).

- **Expiring store seam**: Storage for idempotency and replay detection must be hidden behind a narrow interface (`seen_recently`, `clear`, `close`); a factory resolves either in-memory (default) or SQLite (opt-in) backend at startup (Architecture Decision 3).

- **State store rollout safety**: Default to `STATE_STORE_BACKEND=memory`; opt into `STATE_STORE_BACKEND=sqlite`; when `STATE_STORE_FALLBACK_TO_MEMORY=true`, SQLite init failure must degrade to in-memory without taking down the webhook path (Architecture Decision 2).

- **Replay protection**: Signature decorator must validate HMAC, optional timestamp freshness (`SIGNATURE_MAX_SKEW_SECONDS`), and replay safety (`SIGNATURE_REPLAY_WINDOW_SECONDS`) before any business logic runs.

- **Resource teardown**: Any app-extension that holds external resources must expose a `close()` method; the app factory teardown hook iterates extensions and calls `close()` to prevent connection leaks (Architecture Decision 4).

- **Outbound retry completeness**: Outbound delivery must match PRD FR5 retry-and-fallback expectations end to end (flagged as an open architecture action item).

- **Observability endpoints**: `/health` and `/metrics` (JSON) endpoints must be exposed; in-process metrics include request count, duplicate count, error count, and request duration.

- **Atomic agent selection persistence**: Agent selection writes must use atomic file replacement to avoid corrupt state.

- **Setup guide and runbook**: A first-time setup guide (≤ 45-minute path) and an operations runbook (escalation + rollback) are required release artefacts.

- **Botpress integration context**: `docs/botpress_connection.md` describes the Meta webhook / Verify Token / Callback URL connection sequence — informational only; no new implementation requirements extracted.

---

### UX Design Requirements

- `/setup` must gate first-time operator onboarding, show live env-key readiness, provide a webhook URL copy helper, and run a verification check before allowing completion.
- `/` dashboard must show bot status, active agent, uptime, key message/error/latency summaries, and the latest activity, with 30-second auto-refresh.
- `/agents` must present card-based selection with inline confirmation feedback and disabled-save states when no change is pending.
- `/metrics` must expose live counters and average durations with refresh and reset affordances.
- `/logs` must provide the last 100 message records with status filtering, inline expansion, masked phone numbers by default, and error highlighting.
- Operator UI routes must preserve operator access mode and safe redirects, and the UI must meet the documented accessibility baseline (focus states, labels, `aria-live`, non-color-only status cues).

---

### FR Coverage Map

| FR | Requirement Summary | Epic | Story | Notes |
| --- | --- | --- | --- | --- |
| FR1 | Verify GET `/webhook` challenge and token | Epic 1 | Story 1.2 | Includes positive and negative verification paths |
| FR2 | Enforce POST signature validation | Epic 1 | Story 1.2 | Includes HMAC, timestamp skew, replay protection |
| FR3 | Normalize inbound payloads and suppress duplicates | Epic 2 | Story 2.1 | Covers memory/SQLite store seam and unsupported payload handling |
| FR4 | Generate AI reply with controlled failure states | Epic 2 | Story 2.2 | Includes typed response contract and latency measurement |
| FR5 | Deliver outbound WhatsApp replies with retry and fallback | Epic 2 | Story 2.3 | Includes deterministic fallback and operator-review flag |
| FR6 | Apply runtime agent selection safely | Epic 3 | Story 3.1 | Uses `data/agent_selection.json` with auto-repair |
| FR7 | Validate startup configuration before request handling | Epic 1 | Story 1.1 | Setup UX must remain reachable when keys are missing |
| FR8 | Propagate correlation IDs and sanitize logs | Epic 1 | Story 1.3 | Includes `/health` and `/metrics` observability baseline |
| FR9 | Maintain short per-user conversation context | Epic 3 | Story 3.3 | Uses rolling window of 5 messages per user |
| FR10 | Detect and flag escalation-worthy conversations | Epic 3 | Story 3.2 | Includes queue artifact and operator-facing visibility |

### NFR and Release Coverage Map

| Obligation | Owning Stories | Notes |
| --- | --- | --- |
| NFR1 Availability | 1.1, 1.2, 1.3, 4.1 | Fail-fast validation plus observability and regression gates |
| NFR2 Latency | 2.2, 2.3, 4.1 | AI and outbound durations measured and verified |
| NFR3 Reliability | 2.1, 2.3, 4.1 | Duplicate suppression and retry/fallback coverage |
| NFR4 Security | 1.2, 4.1 | Signature enforcement and negative-path tests |
| NFR5 Throughput | 2.1, 4.1 | Store seam and staging load verification |
| NFR6 Recovery | 2.3, 4.1 | Fallback must land within 10 seconds |
| NFR7 Logging Retention | 1.3, 4.2 | Runbook and ops guidance define retention handling |
| NFR8 Onboarding efficiency | 1.1, 3.2, 4.2 | Distinguish setup wizard speed from full time-to-first-message |
| Setup guide and runbook | 3.2, 4.2 | Required release artifacts |
| Launch gates and pilot readiness | 4.1, 4.2 | Explicit implementation exit criteria |

---

## Epic List

## Epic 1: Secure Runtime Foundation

**Goal:** Ensure the application starts safely, rejects unsafe inbound traffic before business logic runs, and emits traceable operational signals.

**User Value:** Operators can deploy with confidence that configuration errors, webhook verification, and security checks fail safely and are diagnosable.

### Story 1.1: Startup Validation and Setup Gating

As an operator,
I want the app to validate required configuration and surface setup status clearly,
so that I can fix startup issues before the bot accepts traffic.

**Acceptance Criteria**

1. On app startup, all required environment variables are checked for presence, non-empty value, and required format.
2. Startup logging reports per-variable readiness without exposing secrets, tokens, phone numbers, or API keys.
3. Missing or invalid runtime configuration blocks webhook processing but still allows the setup experience to render so operators can complete onboarding.
4. `/setup` renders live pass/fail status for the required keys defined in the UX specification.
5. A setup verification action returns structured success or actionable error details instead of an unhandled stack trace.

**Dependencies:** None.

### Story 1.2: Webhook Verification and Signature Enforcement

As a platform owner,
I want webhook verification and inbound signature enforcement handled centrally,
so that only authentic Meta requests reach message-processing code.

**Acceptance Criteria**

1. `GET /webhook` returns `hub.challenge` with 200 only when `hub.mode=subscribe` and `hub.verify_token` matches the configured token.
2. Invalid, missing, or mismatched verification input returns 403 without leaking secret material.
3. All `POST /webhook` traffic is guarded by HMAC-SHA256 signature validation before request parsing.
4. Signature validation also enforces configured timestamp skew and replay-window checks before business logic executes.
5. Rejection paths log the correlation ID and reason code and do not invoke downstream services.

**Dependencies:** Story 1.1.

### Story 1.3: Correlation Logging and Observability Baseline

As an operator,
I want consistent request tracing and lightweight health metrics,
so that I can diagnose failures and confirm bot status quickly.

**Acceptance Criteria**

1. Each inbound webhook request is assigned a unique correlation ID that propagates through application logs and controlled error responses.
2. Logging sanitizes secrets, tokens, and masked PII in all normal and error paths.
3. The app exposes `/health` and JSON `/metrics` endpoints covering request counts, duplicate counts, error counts, and request durations.
4. Metrics and logs are safe to read even when setup is incomplete, and they do not expose sensitive values.
5. Operator-facing status components can rely on the health and metrics contracts without additional backend discovery work.

**Dependencies:** Stories 1.1 and 1.2.

## Epic 2: Reliable Inbound-to-Reply Pipeline

**Goal:** Convert valid WhatsApp webhook events into safe, typed AI replies and deliver them through Meta with bounded failure handling.

**User Value:** End users receive dependable responses while the system handles duplicates, provider errors, and retries predictably.

### Story 2.1: Inbound Normalization and Idempotency

As the message-processing pipeline,
I want inbound WhatsApp events normalized and deduplicated,
so that downstream services receive one consistent event per real user message.

**Acceptance Criteria**

1. Supported inbound WhatsApp message payloads are normalized into `user_id`, `message_text`, `timestamp`, and `message_id`.
2. Unsupported payload types such as status updates and non-text messages are acknowledged with a handled warning and no downstream processing.
3. Duplicate message IDs are suppressed using the expiring-store interface rather than route-local state.
4. The store factory defaults to in-memory behavior, supports SQLite rollout, and safely falls back to memory when configured to do so.
5. Resource-owning store implementations expose `close()` and integrate with app teardown.

**Dependencies:** Stories 1.1 and 1.2.

### Story 2.2: AI Reply Contract and Failure Handling

As the reply service,
I want AI generation to return typed success or controlled failure states,
so that the webhook flow can respond predictably without uncaught exceptions.

**Acceptance Criteria**

1. The OpenAI service accepts normalized inbound text and the active agent context and returns a typed result object with reply text, confidence, and metadata.
2. Timeout, authentication failure, and rate-limit conditions are represented as controlled states rather than propagated exceptions.
3. Response latency is measured and emitted to metrics for each AI request attempt.
4. AI failures provide enough structured detail for downstream fallback and escalation decisions.
5. The service contract is narrow enough to support unit testing without live provider calls.

**Dependencies:** Story 2.1.

### Story 2.3: Outbound Delivery, Retry, and Fallback

As an end user,
I want replies to be sent reliably even when downstream APIs are unstable,
so that transient failures do not silently drop my conversation.

**Acceptance Criteria**

1. Successful AI replies are formatted correctly and sent via the Meta Cloud API to the originating WhatsApp user.
2. Transient outbound failures trigger a maximum of three attempts with exponential backoff of 1, 2, and 4 seconds.
3. If all retry attempts fail, the system sends the deterministic fallback reply required by the PRD and flags the conversation for operator review.
4. Outbound attempts and durations are recorded in metrics and linked to the request correlation ID.
5. Failure handling does not create duplicate sends for already-confirmed successful deliveries.

**Dependencies:** Story 2.2.

## Epic 3: Operator Control and Support Workflow

**Goal:** Give operators runtime control over agent behavior, escalation handling, setup completion, and the dashboard surfaces needed to monitor the bot.

**User Value:** Operators can manage the live bot without redeploying code and can understand what happened when a conversation needs attention.

### Story 3.1: Runtime Agent Selection Control Plane

As an operator,
I want to switch the active agent safely at runtime,
so that the next inbound message reflects the selected support behavior without a redeploy.

**Acceptance Criteria**

1. Agent definitions are discovered from the supported skills/manifests and rendered in an operator-facing selection view.
2. The selected agent persists to `data/agent_selection.json` using atomic file replacement.
3. Missing, stale, or invalid saved selections auto-repair to the first available safe default agent.
4. Changes take effect on the next inbound message without restarting the Flask process.
5. Operator route guards and safe redirects preserve operator mode across navigation and setup completion.

**Dependencies:** Story 1.3.

### Story 3.2: Setup Wizard and Escalation Workflow

As an operator,
I want guided setup completion and clear escalation signals,
so that I can finish onboarding and intervene quickly when AI automation should stop.

**Acceptance Criteria**

1. `/setup` implements the progressive checklist, copy helper, and verification flow defined in the UX spec, including gated progression until all required keys are present.
2. Setup completion redirects to the operator dashboard rather than dropping operator access state.
3. Conversations with low AI confidence or escalation keywords are flagged with a deterministic reason and queued as an operator-review artifact.
4. Escalation signals are visible in logs or dashboard data contracts without exposing raw secrets or unnecessary PII.
5. Setup and escalation feedback use accessible inline messages or toast announcements with `aria-live` support.

**Dependencies:** Stories 1.1, 1.3, and 2.2.

### Story 3.3: Conversation Context and Operator Activity Views

As an operator,
I want recent conversation context and recent activity surfaced safely,
so that I can understand the current state of a user thread and diagnose issues faster.

**Acceptance Criteria**

1. The application maintains the last five messages per user and resets context on new conversation boundaries or timeout.
2. The dashboard shows recent activity based on a lightweight message-log buffer without requiring a database.
3. The logs view keeps up to 100 entries in FIFO order and supports status filtering, inline expansion, and masked phone numbers by default.
4. Operators can reveal masked numbers intentionally through a stateful control that preserves accessibility semantics.
5. Dashboard, metrics, and logs support mobile navigation, visible focus states, and the refresh behaviors defined in the UX specification.

**Dependencies:** Stories 2.1, 2.2, 2.3, and 3.1.

## Epic 4: Release Readiness and Operational Assurance

**Goal:** Convert the product and architecture commitments into executable validation, operator documentation, and launch gates.

**User Value:** The team can ship with evidence instead of assumptions.

### Story 4.1: Automated Quality and Launch Gates

As a release owner,
I want automated coverage for the critical product paths,
so that security, reliability, and latency regressions block launch before they reach production.

**Acceptance Criteria**

1. Automated tests cover startup validation, webhook verification, signature rejection paths, inbound normalization, AI controlled failures, outbound retry/fallback, and agent-selection repair.
2. Staging validation includes success-rate, latency, and throughput checks aligned to the PRD launch metrics.
3. Launch gates explicitly verify 100% security test pass rate, fallback timing, and no unresolved High risks.
4. Pilot and release readiness evidence is documented in a repeatable checklist rather than ad hoc notes.
5. The implementation plan identifies which checks are blocking for MVP and which remain post-MVP follow-ups.

**Dependencies:** Stories 1.1 through 3.3.

### Story 4.2: Setup Guide, Runbook, and Monitoring Operations

As a support operations lead,
I want concise operational documentation and rollback guidance,
so that the bot can be deployed, monitored, and recovered by the team on call.

**Acceptance Criteria**

1. A setup guide covers the first-time onboarding path from clone to successful verification and first test message.
2. An operations runbook covers escalation handling, troubleshooting signatures, fallback behavior, log/metric inspection, and rollback steps.
3. Documentation distinguishes the quick config-entry target from the broader 45-minute time-to-first-message success metric.
4. Monitoring and alerting expectations are documented for health, error, duplicate, and outbound-failure indicators.
5. Release artifacts include the smoke checklist, runbook, and any operator references needed for the dashboard flows.

**Dependencies:** Stories 1.3, 3.2, and 4.1.

## Epic 5: Sprint 2 Hardening and Experience Polish

**Goal:** Convert deferred review findings into shippable hardening work without reopening completed MVP epics.

**User Value:** Operators keep the same feature set, but the system becomes safer to administer, easier to observe, and less error-prone in day-to-day support workflows.

### Story 5.1: Dashboard CSRF and Config Write Safety

As an operator,
I want setup and dashboard write actions protected against forgery and concurrent file corruption,
so that configuration changes remain trustworthy and recoverable.

**Acceptance Criteria**

1. All operator-facing POST endpoints (`/setup/openai-key`, `/setup/verify`, `/agents`, and any equivalent dashboard mutation routes) reject requests without a valid CSRF token.
2. CSRF failures return a controlled operator-safe response and do not leak secrets or stack traces.
3. The `.env` read-modify-write path uses file locking or an equivalent cross-platform serialization strategy so concurrent writes do not corrupt the file.
4. Configuration writes remain atomic and preserve unrelated keys and comments already present in `.env`.
5. Saving a replacement OpenAI key updates the in-process client state or clearly applies the new key through the same app lifecycle without requiring a blind restart.

**Dependencies:** Stories 1.1 and 3.2.

### Story 5.2: Configuration Validation and Runtime Guardrails

As a platform owner,
I want configuration edge cases and runtime cleanup failures handled explicitly,
so that invalid settings fail early and partial teardown does not leave the app in an undefined state.

**Acceptance Criteria**

1. Unknown `WHATSAPP_PROVIDER` values fail validation with an actionable error instead of silently mapping to `meta`.
2. Outbound provider configuration access uses safe validation-backed reads rather than bracket lookups that can raise `KeyError` after startup.
3. Outbound timeout values are configurable via validated runtime configuration with a documented default.
4. Retry and fallback behavior remains deterministic, and the implementation plan explicitly addresses whether fallback attempts should retry separately from the primary send path.
5. Extension teardown catches and logs per-extension `close()` failures while continuing cleanup of remaining extensions.

**Dependencies:** Stories 1.1 and 2.3.

### Story 5.3: Observability Cleanup and Delivery Telemetry

As an on-call operator,
I want logging and delivery telemetry to be precise and low-noise,
so that incidents can be diagnosed without ambiguous traces or instrumentation drift.

**Acceptance Criteria**

1. Logging sanitization is applied once per record in the intended ownership layer, without repeated filter accumulation across reconfiguration paths.
2. Correlation ID ownership is centralized, length-capped, and still propagated consistently through request handling and controlled errors.
3. Log argument sanitization covers container types used by the app, including `set` and `frozenset`, without exposing secrets.
4. Late-registered handlers and concurrent request logging still preserve the sanitized, correlation-aware observability contract.
5. Outbound delivery telemetry includes attempt-level timing or equivalent visibility that distinguishes slow retries from final terminal outcome only.

**Dependencies:** Stories 1.3, 2.3, and 4.1.

### Story 5.4: Setup UX and Escalation Precision Polish

As an operator,
I want setup and escalation cues to reflect real workflow state with fewer false positives,
so that the dashboard feels accurate and intervention signals are easier to trust.

**Acceptance Criteria**

1. Escalation keyword matching avoids obvious substring false positives while preserving deterministic configured keyword behavior.
2. The setup step indicator updates `aria-current="step"` to reflect the actual current step instead of always marking Welcome.
3. Fallback and escalation operator signals expose enough traceability for triage without degrading the user-facing message experience.
4. Any UX or contract copy affected by these changes stays aligned across setup UI, operator dashboard cues, and supporting docs.
5. Regression tests cover at least one false-positive keyword case and the setup step-state accessibility behavior.

**Dependencies:** Stories 3.2 and 4.2.

## Epic 8: Transition Sprint - Carry-Forward Closure and First P1 Delivery

**Goal:** Close one known pre-existing reliability gap, then deliver the first small slice of deferred P1 roadmap value without destabilizing the MVP baseline.

**User Value:** Operators and pilot stakeholders see active roadmap progress while confidence increases through closure of known test debt and measured feature expansion.

### Story 8.1: Close Pre-existing Epic 3 Test Failure

As a release owner,
I want the long-standing `test_logs_filter_status_error` failure resolved and guarded,
so that the test suite returns to a clean reliability baseline before new roadmap work expands scope.

**Acceptance Criteria**

1. `tests/test_story_3_3.py::OperatorLogsViewTests::test_logs_filter_status_error` passes reliably under the standard project test command.
2. Root cause is corrected in production code (or route/test contract alignment) without introducing a test-only workaround.
3. Adjacent logs-filter behavior remains covered for expected status values and controlled error handling.
4. No unrelated regressions are introduced in dashboard log rendering and filtering paths.
5. Sprint tracking reflects this story as a dedicated carry-forward closure item for Epic 8.
6. Full regression suite (`pytest tests/`) completes with zero failures before Story 8.1 is accepted as done.

**Dependencies:** Stories 3.3 and 7.2.

### Story 8.2: Multi-channel Delivery Interface Preparation (P1)

As a product owner,
I want outbound channel behavior abstracted behind a stable delivery interface,
so that SMS or Messenger channels can be added next with low risk to existing WhatsApp delivery behavior.

**Acceptance Criteria**

1. A channel-agnostic outbound interface exists with WhatsApp as the current concrete implementation.
2. Existing WhatsApp send, retry, and fallback behavior remains unchanged and covered by current tests.
3. Channel selection strategy and extension points are documented for follow-on SMS/Messenger implementations.
4. At least one contract test verifies the abstraction boundary used by the webhook flow.
5. No additional production channel integration is required in this story; this is preparation work only.
6. Scope guard passes: no new external channel credentials, endpoints, or production channel sends are introduced.

**Dependencies:** Stories 2.3 and 5.2.

### Story 8.3: Conversation Analytics Event Foundation (P1)

As an operations lead,
I want structured conversation lifecycle events captured for reporting,
so that we can measure escalation trends and user-support outcomes in the next analytics increment.

**Acceptance Criteria**

1. Message lifecycle events (inbound received, AI reply outcome, escalation flagged, outbound delivery outcome) are emitted in a consistent structured format.
2. Event payloads include correlation ID, conversation/user key, status/outcome fields, and timestamp while preserving existing sanitization controls.
3. Event capture does not change user-visible reply behavior or latency targets materially.
4. A lightweight artifact or endpoint exposes recent analytics events for verification in staging.
5. Tests validate event schema consistency and at least one escalation-trend-relevant signal.
6. Analytics emission does not materially regress latency: measured P95 request handling delta remains within 5% of baseline.

**Dependencies:** Stories 1.3, 2.2, 2.3, and 3.2.

### Story 8.4: Optional SQLite Persistence Rollout Slice

As a platform owner,
I want optional SQLite-backed persistence hardened for production-like continuity,
so that reliability state survives process restarts when capacity allows in this transition sprint.

**Acceptance Criteria**

1. SQLite backend behavior for idempotency/reliability state is validated across process restart scenarios.
2. Fallback-to-memory behavior remains deterministic when SQLite initialization fails under configured fallback mode.
3. Resource lifecycle (`close()` and teardown) remains leak-safe across memory and SQLite backends.
4. Configuration and runbook notes for enabling SQLite remain aligned with actual runtime behavior.
5. Story can be deferred without blocking Epic 8 closure if transition sprint capacity is exhausted.
6. Pull condition is explicit: Story 8.4 may start only after Story 8.1 is done and at least one P1 story (8.2 or 8.3) reaches review.

**Dependencies:** Stories 2.1, 5.2, and 7.9.

### Epic 8 Risk Elimination Gates

The transition sprint is treated as risk-first delivery. Epic 8 may proceed only when these gates are respected:

1. **Gate G8-1 (carry-forward closure first):** Story 8.1 must be completed and verified by full-suite green before feature work in 8.2/8.3 is merged.
2. **Gate G8-2 (scope containment):** Story 8.2 remains interface-prep only; adding live SMS/Messenger production sends is out of scope for Epic 8.
3. **Gate G8-3 (observability safety):** Story 8.3 must preserve sanitization and remain within a 5% P95 handling regression budget.
4. **Gate G8-4 (capacity protection):** Story 8.4 is optional and may only be pulled after mandatory and primary-value work is on track.

### Epic 8 Exit Criteria

Epic 8 is considered complete only when all mandatory conditions hold:

1. Story 8.1 is done and `test_logs_filter_status_error` remains stable in both focused and full-suite runs.
2. At least two P1 carry-in stories are completed (8.2 and/or 8.3), with acceptance tests passing.
3. No new P0/P1 regressions are introduced in webhook reliability, operator logs, or observability sanitization paths.
4. Optional infrastructure scope (8.4) is either completed under gate conditions or explicitly deferred without blocking release.

---

## Delivery Sequence

1. Complete Epic 1 to unblock safe startup, inbound security, and operator-visible system status.
2. Deliver Epic 2 to produce a dependable inbound-to-reply pipeline with bounded failure handling.
3. Deliver Epic 3 to expose runtime control, onboarding, and operator support surfaces.
4. Close Epic 4 with automated validation and operational artifacts before pilot entry.
5. Use Epic 5 as Sprint 2 carry-forward work to harden dashboard writes, config/runtime guardrails, observability fidelity, and UX polish.
6. Execute Epic 8 as a transition sprint: close pre-existing carry-forward failure first, then deliver the first prioritized P1 feature slices.

## Delivery Summary by Epic

### Delivered Outcome Summary

- Epic 1-2: Core MVP (Secure runtime + reliable pipeline) - 6 stories, all delivered.
- Epic 3: Agent selection + escalation - 3 stories, expanded with conversation context and operator activity views.
- Epic 4: Release gates + runbook - 3 stories + 1 cross-functional story.
- Epic 5: Dashboard hardening - 4 new stories (5.1-5.4) covering CSRF, config safety, observability, and UX precision.
- Epic 6: Integration test sweep - 4 stories closing contract-test debt and deferred observability coverage.
- Epic 7: Carry-forward hygiene - 12 stories delivering CI integrity hardening, contract tests, and sprint tracking discipline.

### Scope Evolution vs Original Design

- Epic 3 evolved beyond initial control-plane scope by adding explicit conversation-context behavior and richer operator activity surfaces.
- Epic 5 was introduced mid-project as a dedicated hardening epic, rather than as a post-release backlog bundle.
- Epic 6 and Epic 7 extended the plan from implementation-first delivery to contract-test closure and governance hygiene to reduce regression risk.

### Versioning Note

- Plan baseline re-issued after sprint course correction closeout.
- Delivery record reflects implemented scope through Epic 7 as of 2026-05-02.

## Story Dependency Summary

| Story | Depends On |
| --- | --- |
| 1.1 | None |
| 1.2 | 1.1 |
| 1.3 | 1.1, 1.2 |
| 2.1 | 1.1, 1.2 |
| 2.2 | 2.1 |
| 2.3 | 2.2 |
| 3.1 | 1.3 |
| 3.2 | 1.1, 1.3, 2.2 |
| 3.3 | 2.1, 2.2, 2.3, 3.1 |
| 4.1 | 1.1-3.3 |
| 4.2 | 1.3, 3.2, 4.1 |
| 5.1 | 1.1, 3.2 |
| 5.2 | 1.1, 2.3 |
| 5.3 | 1.3, 2.3, 4.1 |
| 5.4 | 3.2, 4.2 |
| 8.1 | 3.3, 7.2 |
| 8.2 | 2.3, 5.2 |
| 8.3 | 1.3, 2.2, 2.3, 3.2 |
| 8.4 | 2.1, 5.2, 7.9 |

## Implementation Readiness Notes

- The epic/story plan now covers all PRD functional requirements and the operator-facing UX surfaces.
- The remaining planning work after this artifact is to keep architecture, PRD wording, and readiness assessment synchronized as implementation details evolve.
- Any change request that affects security, setup gating, or operator access should update this document's coverage map before implementation starts.

