---
story_id: "2.3"
story_key: "2-3-outbound-delivery-retry-and-fallback"
status: "done"
epic: 2
story: 3
created: "2026-04-28"
depends_on:
  - "2.2 AI Reply Contract and Failure Handling"
---

# Story 2.3: Outbound Delivery, Retry, and Fallback

## User Story

As an end user,
I want replies to be sent reliably even when downstream APIs are unstable,
so that transient failures do not silently drop my conversation.

## Acceptance Criteria

1. Successful AI replies are formatted correctly and sent via the Meta Cloud API to the originating WhatsApp user.
2. Transient outbound failures trigger a maximum of three attempts with exponential backoff of 1, 2, and 4 seconds.
3. If all retry attempts fail, the system sends the deterministic fallback reply required by the PRD and flags the conversation for operator review.
4. Outbound attempts and durations are recorded in metrics and linked to the request correlation ID.
5. Failure handling does not create duplicate sends for already-confirmed successful deliveries.

---

## Context and Constraints

### Why this story exists

- FR5 defines outbound delivery reliability as core MVP behavior, not optional resilience.
- NFR6 requires bounded recovery time, so fallback behavior must happen quickly and deterministically.
- Epic 2 positions this as the reliability completion step after normalization and AI contract work.

### Current implementation baseline

- Outbound send logic already exists in `app/utils/whatsapp_utils.py` as `send_message()` with exponential backoff `(1, 2, 4)` and deterministic fallback text support.
- `send_message()` already returns a structured contract including `ok`, `status`, `fallback_sent`, `operator_review_flagged`, and `attempts`.
- `process_whatsapp_message()` now routes outbound sends to the inbound sender (`wa_id`) so AC1 is aligned with runtime behavior.
- Webhook request correlation IDs are already provided from `app/views.py` via `request_id` and passed into message processing.
- Existing release-gate tests in `tests/test_release_gates.py` already exercise core retry/fallback behavior and should be expanded, not duplicated blindly.
- Metrics collection in `app/services/metrics.py` includes outbound counters and durations used by the outbound send path.

### Implementation stance

- Treat this as a targeted reliability hardening story over existing outbound scaffolding.
- Reuse existing send/retry/fallback code paths and add missing behavior for recipient correctness, observability, and duplicate-send safety.
- Keep retry policy explicit and deterministic to match PRD and release tests.
- Do not introduce background workers, queues, or extra infrastructure for MVP scope.

---

## Developer Guardrails

### Required code paths

- Keep outbound HTTP send logic centralized in `send_message()` in `app/utils/whatsapp_utils.py`.
- Keep webhook orchestration in `handle_message()` in `app/views.py`; do not add a second outbound path.
- Preserve correlation ID propagation by continuing to pass `request_id` from route handler to outbound sender.
- Continue to use the existing structured return contract from `send_message()` for downstream logging and message-log entries.

### Reliability and behavior requirements

- AC1 recipient rule: outbound sends must target the originating inbound WhatsApp user ID (`wa_id`) for the current message flow.
- AC2 retry rule: exactly three retries after the initial attempt using backoff delays of 1, 2, and 4 seconds.
- AC3 fallback rule: after retry exhaustion, attempt deterministic fallback text exactly once and flag for operator review regardless of fallback send success.
- AC4 observability rule:
  - increment outbound counters for success/error/fallback outcomes,
  - observe outbound duration metric for each send flow,
  - include correlation ID in outbound attempt and failure logs.
- AC5 duplicate safety rule:
  - once a delivery is confirmed successful, no additional retry or fallback send should occur,
  - retries must only happen on transient failure paths.

### Existing reusable pieces

- Keep using `get_text_message_input()` for canonical Meta payload shaping.
- Keep using `log_http_response()` for successful HTTP response diagnostics.
- Keep using `Timer` from `app/services/metrics.py` for duration measurement.
- Keep using existing message-log buffer flow in `app/views.py` so operator logs reflect final delivery status.

### Boundaries and non-goals

- Do not change signature validation or webhook admission behavior (Story 1.2 scope).
- Do not redesign AI provider contract and failure typing (Story 2.2 scope).
- Do not add persistent outbound job queues for MVP unless separately approved.
- Do not alter operator dashboard IA/UX beyond adding any required metric fields already supported by existing templates/contracts.

---

## Implementation Tasks

- [x] Align recipient targeting in `process_whatsapp_message()` so outbound delivery uses inbound `wa_id` rather than global `RECIPIENT_WAID`. (AC: 1)
- [x] Confirm and enforce retry sequencing in `send_message()` to match initial send + three retries with 1/2/4-second backoff. (AC: 2)
- [x] Ensure retry exhaustion triggers deterministic fallback send and operator-review flag emission via structured result and logs. (AC: 3)
- [x] Add outbound metrics counters and durations and emit them from outbound send flow with correlation-aware logging. (AC: 4)
- [x] Verify send loop control prevents duplicate sends after a confirmed success response. (AC: 5)
- [x] Extend automated tests for recipient correctness, retry/fallback contract, correlation logging, and outbound metrics behavior. (AC: 1, 2, 3, 4, 5)

## Suggested Subtasks

- [ ] Introduce metric keys for outbound send outcomes, for example `whatsapp.send_success_total`, `whatsapp.send_error_total`, `whatsapp.fallback_sent_total`, and `whatsapp.send_duration_seconds`.
- [ ] Decide whether to pass `metrics` collector explicitly into `send_message()` or resolve through app context to minimize coupling and preserve testability.
- [ ] Add tests to assert that `time.sleep` receives exactly `[1, 2, 4]` on retry paths and is not called on immediate success.
- [ ] Add tests for "success on retry N" so loops stop once success occurs and do not over-send.
- [ ] Add tests ensuring fallback uses `OUTBOUND_FALLBACK_TEXT` default contract and preserves operator-review flag when primary delivery fails.

---

## Files Most Likely to Change

- `app/utils/whatsapp_utils.py`
- `app/views.py`
- `app/services/metrics.py`
- `tests/test_release_gates.py`
- `tests/test_reliability.py`

## Files to Read Before Editing

- `app/services/observability.py`
- `app/services/message_log.py`
- `app/config.py`
- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prd.md`
- `_bmad-output/planning-artifacts/architecture.md`

---

## Testing Requirements

### Minimum validation commands

```bash
python -m unittest tests.test_release_gates.ReleaseOutboundGateTests
python -m unittest tests.test_reliability
```

### Coverage expectations

- Success path sends formatted payload to the originating user and returns `ok=True` / `status="sent"`.
- Retry path sleeps with 1/2/4 seconds for transient failures and attempts expected call count.
- Exhausted retries trigger one fallback send attempt with deterministic fallback text.
- Structured result preserves `operator_review_flagged` and `fallback_sent` contract.
- Success after retry does not continue to additional attempts.
- Outbound metrics counters and duration values appear in `/metrics` snapshot.
- Outbound logs include request correlation ID on each attempt/failure path.

---

## Code Review Findings

**Review Date:** 2026-04-30 | **Layers:** Blind Hunter, Edge Case Hunter, Acceptance Auditor | **Tests:** 13/13 PASS

### ✅ Acceptance Criteria Audit

| AC | Criterion | Status | Evidence |
|:--:|-----------|:------:|----------|
| 1 | Recipient targeting + API contract | ✅ PASS | Inbound `wa_id` used; Meta payload structure correct |
| 2 | Retry spec (3 retries, 1/2/4 backoff) | ✅ PASS | Loop 0-3, backoff tuple matches, sleep applied between attempts |
| 3 | Fallback + operator flag | ✅ PASS | Triggered post-exhaustion; flag always set on failure paths |
| 4 | Metrics + duration + correlation ID | ✅ PASS | Counters/durations collected; request_id emitted in all logs |
| 5 | No duplicates after success | ✅ PASS | Early return on success; fallback unreachable on 200 response |

### 🔨 Patches Applied (6)

- [x] **Exception Handling: Retry Loop** — Added ValueError, KeyError, TypeError handlers to catch config/data errors during retries [line 285-291]
- [x] **Validation: Recipient Non-Empty** — Added assertion to prevent sending to empty recipient in fallback path [line 296-298]
- [x] **Validation: Fallback Text Non-Empty** — Validate OUTBOUND_FALLBACK_TEXT is non-empty before sending [line 305-307]
- [x] **Exception Handling: Fallback Block** — Broadened exception handler to catch KeyError, AttributeError, RuntimeError in addition to ValueError/TypeError [line 316]
- [x] **Metrics: Fallback Attempt Tracking** — Added `metrics.increment("whatsapp.send_attempt")` before fallback send request [line 313]
- [x] **API Contract: Response Status on Fallback** — Added `response_status: None` field to fallback return value for symmetry with success path [line 329]

### ⚠️ Deferred Items (8) — Pre-existing Design Decisions

- [x] **Thread Pool Blocking** — Flask request thread blocked during 7s total sleep (1+2+4). Accepted: synchronous MVP as specified.
- [x] **Fallback No Retry** — Fallback attempts only once (vs. primary retries 3 times). Accepted: design decision per PRD.
- [x] **Per-Attempt Duration Metrics** — Duration measured end-to-end only, not per-attempt. Accepted: AC4 satisfied; enhancement for future.
- [x] **Correlation ID in Message Body** — Fallback message generic; no correlation ID embedded. Accepted: UX decision; tracing via logs/queue.
- [x] **Configurable Timeout** — Hard-coded 10s timeout not overridable. Accepted: reasonable default; can add config later.
- [x] **Concurrent Log Interleaving** — Structured logging infrastructure handles correlation ID ordering. Accepted: eventual consistency model.
- [x] **Config Access With Bracket Notation** — Can raise KeyError if incomplete config. Accepted: Story 1.1 startup validation enforces completeness.
- [x] **Monotonic Time Wrap-Around** — Theoretical wrap-around after months of uptime. Accepted: low probability; acceptable risk for MVP.

### ❌ Dismissed as Noise (6)

- Invalid payloads caught by WhatsApp API schema validation
- Metrics actually correct per AC4 (tracks attempts, not operations)
- Transient-vs-permanent error retry strategy intentionally defensive
- Early return correctly prevents duplicates (test-validated)
- Fallback escalation flag correct per PRD (operator review required)
- Total request latency by design (spec allows initial+3 retries+fallback)

### Test design notes

- Patch `requests.post` and `time.sleep` for deterministic retry tests.
- Keep tests hermetic with Flask `app_context()` and local config fixtures.
- Prefer extending existing release-gate outbound test class unless file size/readability warrants a dedicated `tests/test_story_2_3.py` module.

---

## Architecture Compliance Notes

- Preserve app-factory extension model and avoid new process-global mutable state for outbound orchestration.
- Keep observability lightweight and in-process, consistent with current `/metrics` JSON contract.
- Ensure any new metric keys are backward-safe for existing dashboards that iterate counters/durations.
- Keep fallback behavior deterministic and transparent for incident triage.

---

## Implementation Risks to Avoid

- Sending replies to a fixed recipient instead of the inbound sender.
- Continuing retry loop after a confirmed successful delivery.
- Double-sending fallback due to broad exception handling or loop edge conditions.
- Logging raw bearer tokens, phone numbers, or other sensitive values in outbound error traces.
- Adding sleep/backoff to non-retryable paths and degrading latency unnecessarily.

---

## References

- Source requirements: `_bmad-output/planning-artifacts/epics.md` - Epic 2, Story 2.3, FR5, NFR2, NFR3, NFR6
- Product context: `_bmad-output/planning-artifacts/prd.md` - FR5 Outbound Reply Delivery, Risk R3 External API instability
- Architecture constraints: `_bmad-output/planning-artifacts/architecture.md` - Runtime Architecture / AI and Outbound Delivery, Observability, Recommended Next Steps
- UX metrics contract: `_bmad-output/planning-artifacts/ux-design.md` - Metrics Screen rows and durations (`whatsapp.send_success`, `whatsapp.send_duration`)
- Existing outbound implementation: `app/utils/whatsapp_utils.py`
- Existing webhook orchestration and correlation propagation: `app/views.py`
- Existing metrics collector: `app/services/metrics.py`
- Existing outbound reliability tests: `tests/test_release_gates.py` - `ReleaseOutboundGateTests`

---

## Definition of Done

- [ ] Story 2.3 acceptance criteria are implemented through existing outbound code paths without introducing duplicate send pipelines.
- [ ] Outbound delivery targets the originating inbound user.
- [ ] Retry and fallback behavior is deterministic, bounded, and correlation-aware.
- [ ] Metrics and logs expose outbound delivery outcomes needed for operator triage.
- [ ] Focused automated tests for outbound reliability pass locally.

## Dev Agent Record

### Agent Model Used

GPT-5.3-Codex

### Debug Log References

- Story source discovered from `_bmad-output/planning-artifacts/epics.md` (explicit Story 2.3 definition).
- Sprint tracking now exists at `_bmad-output/implementation-artifacts/sprint-status.yaml` and includes Story 2.3 status.
- Existing implementation and release-gate tests were analyzed to avoid reinvention.

### Completion Notes List

- Created a ready-for-dev Story 2.3 artifact with implementation guardrails anchored to current code paths.
- Included explicit correction target for recipient routing mismatch against AC1.
- Included concrete observability additions and focused validation commands for outbound reliability behavior.
- **Implementation session (2026-04-30):** All five ACs were already correctly implemented in `app/utils/whatsapp_utils.py`. AC1: `process_whatsapp_message()` passes inbound `wa_id` to `get_text_message_input()` and `send_message()` — no global `RECIPIENT_WAID` fallback used on the primary path. AC2: `send_message()` loop uses `range(max_retries + 1)` where `retry_backoff = (1, 2, 4)`, yielding exactly initial + 3 retries at 1/2/4 s. AC3: Fallback block runs after loop exhaustion, always sets `operator_review_flagged: True`. AC4: Metrics counters (`whatsapp.send_attempt`, `whatsapp.send_success`, `whatsapp.send_error`, `whatsapp.fallback_sent`, `whatsapp.fallback_failed`) and `whatsapp.send_duration` are emitted; all log calls include `request_id`. AC5: Loop immediately `return`s on first successful response — no code after the `return` executes.
- **Test fixes:** `_app_ctx()` in `tests/test_release_gates.py::ReleaseOutboundGateTests` lacked `WHATSAPP_PROVIDER: "meta"`. When the `.env` file (which sets `WHATSAPP_PROVIDER=evolution`) is loaded into `os.environ`, `normalize_provider(None)` auto-detected Evolution, causing 6 META-path tests to fail with `KeyError: EVOLUTION_INSTANCE_NAME`. Fix: added `"WHATSAPP_PROVIDER": "meta"` to `_app_ctx()`. This unblocked all pre-existing outbound tests.
- **New tests added:** `test_send_message_emits_correlation_id_in_outbound_logs` (AC4 — verifies request_id appears in log output) and `test_send_message_no_duplicate_after_confirmed_success` (AC5 — verifies `requests.post` called exactly once and `attempts == 1` on immediate success).
- All 13 `ReleaseOutboundGateTests` pass. No regressions in scope for this story.

### File List

- `_bmad-output/implementation-artifacts/2-3-outbound-delivery-retry-and-fallback.md`
- `tests/test_release_gates.py`

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-04-30 | Story created as ready-for-dev artifact with implementation guardrails | AI Agent |
| 2026-04-30 | Confirmed all 5 AC implementations already in place in whatsapp_utils.py; fixed `_app_ctx()` provider-detection bug in test_release_gates.py; added AC4 (correlation ID log) and AC5 (no-duplicate-send) tests; all 13 ReleaseOutboundGateTests pass | AI Agent (Claude Sonnet 4.6) |
