---
story_id: "2.1"
story_key: "2-1-inbound-normalization-and-idempotency"
status: "done"
epic: 2
story: 1
created: "2026-04-28"
depends_on:
  - "1.1 Startup Validation and Setup Gating"
  - "1.2 Webhook Verification and Signature Enforcement"
---

# Story 2.1: Inbound Normalization and Idempotency

## User Story

As the message-processing pipeline,
I want inbound WhatsApp events normalized and deduplicated,
so that downstream services receive one consistent event per real user message.

## Acceptance Criteria

1. Supported inbound WhatsApp message payloads are normalized into `user_id`, `message_text`, `timestamp`, and `message_id`.
2. Unsupported payload types such as status updates and non-text messages are acknowledged with a handled warning and no downstream processing.
3. Duplicate message IDs are suppressed using the expiring-store interface rather than route-local state.
4. The store factory defaults to in-memory behavior, supports SQLite rollout, and safely falls back to memory when configured to do so.
5. Resource-owning store implementations expose `close()` and integrate with app teardown.

---

## Context and Constraints

### Why this story exists

- FR3 requires canonical normalization plus duplicate suppression before downstream AI and outbound delivery.
- NFR3 and NFR5 depend on bounded duplicate handling and a predictable idempotency seam.
- Epic 2 depends on Story 2.1 as a contract for Story 2.2 (typed AI reply handling) and Story 2.3 (retry/fallback delivery).

### Current implementation baseline

- Webhook POST admission control is already centralized via `@signature_required` on `webhook_post()` in `app/views.py`.
- `handle_message()` currently suppresses duplicates with `_extract_message_id()` + `_is_duplicate_message()` and app-scoped store creation via `create_expiring_store()`.
- Store backends already exist in `app/services/expiring_store.py`:
  - `ExpiringKeyStore` (in-memory)
  - `SQLiteExpiringKeyStore` (SQLite, closable)
  - fallback-to-memory behavior in `create_expiring_store()`
- Normalization is currently implicit and fragmented (direct nested dict reads in `process_whatsapp_message()`), not represented as a canonical typed object.

### Implementation stance

- Treat this as an extraction-and-hardening story on top of existing flow, not a greenfield rewrite.
- Keep signature enforcement unchanged and strictly upstream of normalization logic.
- Centralize canonical inbound extraction in one helper/service and pass normalized payload downstream.
- Reuse the expiring-store seam; do not create ad hoc module-level caches or route-local duplicate registries.

---

## Developer Guardrails

### Required code paths

- Keep request entrypoint ownership in `app/views.py` (`webhook_post()` and `handle_message()`).
- Keep idempotency state behind `create_expiring_store()` with `extension_key="message_id_store"` and `namespace="webhook_message_id"`.
- Keep teardown lifecycle through app extensions and existing app-factory cleanup behavior.
- Keep unsupported-event handling in webhook flow as a handled path (no unhandled exception / stack trace response).

### Normalization contract requirements

- Introduce or formalize a canonical inbound object containing:
  - `user_id` (WhatsApp wa_id)
  - `message_text` (text body)
  - `timestamp` (source timestamp if present, else safe fallback)
  - `message_id` (Meta message id)
- The canonical object should be produced once and reused, rather than repeatedly traversing nested payload paths.
- The canonical mapping must be deterministic across repeated payloads so idempotency is stable.

### Idempotency and reliability requirements

- Duplicate suppression must continue to call `seen_recently(message_id)` through the store seam.
- Non-empty message IDs are dedupe keys; missing message IDs must not crash the route.
- Store behavior must remain configuration-driven:
  - `STATE_STORE_BACKEND=memory` default
  - `STATE_STORE_BACKEND=sqlite` optional
  - fallback behavior controlled by `STATE_STORE_FALLBACK_TO_MEMORY`
- Resource-owning stores must remain closable and app teardown-compatible.

### Unsupported payload behavior

- Status updates and unsupported message shapes should return a handled `200` acknowledgement with no downstream `process_whatsapp_message()` call.
- Non-WhatsApp or invalid event envelopes may continue current controlled error response contract when appropriate.
- Log unsupported events with correlation ID and without secrets/PII leakage.

### Boundaries and non-goals

- Do not implement AI failure-state contract here (Story 2.2).
- Do not implement outbound retry/fallback logic changes here (Story 2.3).
- Do not change operator route guards/UI behavior here (Epic 3 stories).
- Do not replace the expiring-store seam with direct SQLite usage in routes.

---

## Implementation Tasks

- [x] Introduce or refactor canonical inbound normalization so supported inbound message payloads map to `user_id`, `message_text`, `timestamp`, and `message_id`. (AC: 1)
- [x] Route unsupported payload types (status updates, non-text messages, malformed message shapes) to handled acknowledgements and skip downstream processing. (AC: 2)
- [x] Keep duplicate suppression behind `create_expiring_store()` and ensure duplicates short-circuit before downstream processing. (AC: 3)
- [x] Preserve and validate store-factory backend selection and fallback semantics (`memory`, `sqlite`, fallback). (AC: 4)
- [x] Confirm store `close()` lifecycle remains compatible with app teardown hooks for both memory and SQLite implementations. (AC: 5)
- [x] Add or update focused tests for normalization, unsupported payload handling, duplicate suppression, and store fallback behavior. (AC: 1, 2, 3, 4, 5)

## Suggested Subtasks

- [x] Add a small helper/service for canonical payload extraction and keep it defensive against missing nested keys.
- [x] Adjust `process_whatsapp_message()` inputs to consume normalized data or a narrow adapter object.
- [x] Ensure duplicate check happens once per inbound message and before outbound calls.
- [x] Add explicit tests that duplicate requests do not call downstream processing more than once.
- [x] Add explicit tests for status updates and unsupported/non-text payloads returning handled responses.

---

## Files Most Likely to Change

- `app/views.py`
- `app/utils/whatsapp_utils.py`
- `app/services/expiring_store.py`
- `tests/test_reliability.py`
- `tests/test_story_1_1_and_1_2.py`
- `tests/test_expiring_store.py`

## Files to Read Before Editing

- `app/__init__.py`
- `app/decorators/security.py`
- `app/services/observability.py`
- `app/services/metrics.py`
- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/architecture.md`

---

## Testing Requirements

### Minimum validation commands

Run focused idempotency/store tests first:

```bash
python -m unittest tests.test_expiring_store tests.test_reliability
```

Then run webhook security and flow regression coverage:

```bash
python -m unittest tests.test_story_1_1_and_1_2 tests.test_story_1_3
```

### Coverage expectations

- Supported payload normalizes correctly to canonical fields.
- Unsupported payloads (status updates and non-text) are acknowledged and skipped.
- Duplicate message IDs are suppressed with one downstream processing pass.
- SQLite-backed store supports dedupe behavior equivalently to memory store.
- SQLite init failure respects fallback flag behavior.
- Store lifecycle `close()` remains safe and idempotent.
- No secret leakage in logs or error payloads for unsupported/invalid events.

### Test design notes

- Prefer patching `process_whatsapp_message()` and/or normalization helpers to assert admission and suppression behavior without external API calls.
- Keep tests deterministic by using fixed payload fixtures and controlled timestamps.
- Extend existing test modules where feasible; avoid scattering tiny tests across many files unless readability degrades.

---

## Architecture Compliance Notes

- Story 2.1 must preserve architecture decisions around app-scoped extension lifecycle and the expiring-store seam.
- Reliability state remains behind a narrow interface (`seen_recently`, `clear`, `close`) to allow backend portability.
- The rollout safety path (`sqlite` with optional fallback-to-memory) is mandatory and must not be bypassed in route logic.
- Normalization should reduce structural coupling to raw Meta payload shape, improving future evolution and Story 2.2 contract stability.

---

## Implementation Risks to Avoid

- Creating a second idempotency cache path outside `create_expiring_store()`.
- Letting unsupported payloads trigger downstream processing or outbound side effects.
- Tight-coupling downstream service APIs to raw nested webhook JSON.
- Treating missing timestamp/message fields as hard crashes instead of controlled behavior.
- Regressing signature-first processing order by normalizing before security admission.

---

## Previous Story Intelligence (1.2)

- Keep request admission centralized and fail-closed behavior intact.
- Preserve correlation-aware response/error contract (`correlation_id`, stable reason fields where applicable).
- Reuse existing seams (`app/views.py` route ownership, `app/services/expiring_store.py` lifecycle) rather than introducing duplicate helpers.

---

## References

- Source requirements: `_bmad-output/planning-artifacts/epics.md` - Epic 2 Story 2.1, FR3, NFR3, NFR5
- Product context: `_bmad-output/planning-artifacts/prd.md` - FR3 inbound parsing and idempotency
- Architecture constraints: `_bmad-output/planning-artifacts/architecture.md` - Primary Runtime Flow, Decision 2, Decision 3, Decision 4, Configuration Contract
- UX context: `_bmad-output/planning-artifacts/ux-design.md` - Logs/metrics operator expectations
- Existing webhook flow: `app/views.py`
- Existing payload utilities: `app/utils/whatsapp_utils.py`
- Existing store seam: `app/services/expiring_store.py`
- Existing reliability and webhook tests: `tests/test_reliability.py`, `tests/test_story_1_1_and_1_2.py`, `tests/test_expiring_store.py`

---

## Definition of Done

- [x] Story 2.1 canonical normalization contract is implemented and used by inbound processing.
- [x] Unsupported payloads are handled gracefully with no downstream side effects.
- [x] Duplicate suppression is verified through the expiring-store seam for memory and SQLite modes.
- [x] Store rollout and fallback behavior is preserved and covered by automated tests.
- [x] No regression to webhook security gate ordering, correlation handling, or existing observability baseline.

## Dev Agent Record

### Agent Model Used

GPT-5.3-Codex

### Debug Log References

- Updated canonical inbound normalization in `app/utils/whatsapp_utils.py` to emit deterministic `user_id`, `message_text`, `timestamp`, and `message_id` fields and explicit unsupported payload markers.
- Updated `app/views.py` webhook handling to reuse one normalized payload per request, acknowledge unsupported payloads with handled `200`, and keep dedupe through `create_expiring_store()`.
- Executed required validation suites:
  - `python -m unittest tests.test_expiring_store tests.test_reliability` (51 tests, OK)
  - `python -m unittest tests.test_story_1_1_and_1_2 tests.test_story_1_3` (44 tests, OK)

### Completion Notes List

- Canonical inbound extraction is now centralized and includes deterministic fallback timestamp handling when source timestamps are missing.
- Unsupported non-text payloads now follow a handled acknowledgement path and skip downstream processing.
- Duplicate suppression remains behind the app extension-backed expiring-store seam for memory and SQLite backends.
- Added focused normalization and unsupported webhook handling tests in `tests/test_reliability.py`.

### File List

- `app/utils/whatsapp_utils.py`
- `app/views.py`
- `tests/test_reliability.py`
- `_bmad-output/implementation-artifacts/2-1-inbound-normalization-and-idempotency.md`