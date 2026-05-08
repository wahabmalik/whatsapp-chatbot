---
story_id: "3.3"
story_key: "3-3-conversation-context-and-operator-activity-views"
status: "done"
epic: 3
story: 3
created: "2026-04-29"
depends_on:
  - "2.1 Inbound Normalization and Idempotency"
  - "2.2 AI Reply Contract and Failure Handling"
  - "2.3 Outbound Delivery, Retry, and Fallback"
  - "3.1 Runtime Agent Selection Control Plane"
---

# Story 3.3: Conversation Context and Operator Activity Views

## User Story

As an operator,
I want recent conversation context and recent activity surfaced safely,
so that I can understand the current state of a user thread and diagnose issues faster.

## Acceptance Criteria

1. The application maintains the last five messages per user and resets context on new conversation boundaries or timeout.
2. The dashboard shows recent activity based on a lightweight message-log buffer without requiring a database.
3. The logs view keeps up to 100 entries in FIFO order and supports status filtering, inline expansion, and masked phone numbers by default.
4. Operators can reveal masked numbers intentionally through a stateful control that preserves accessibility semantics.
5. Dashboard, metrics, and logs support mobile navigation, visible focus states, and the refresh behaviors defined in the UX specification.

---

## Context and Constraints

### Why this story exists

- FR9 requires bounded per-user conversation memory for reply coherence and operator diagnostics.
- Epic 3 extends existing setup/agent control work with operator-facing runtime visibility.
- UX requires logs and metrics to remain lightweight, in-memory, and mobile-usable without adding infrastructure.

### Current implementation baseline

- Operator dashboard routes and API endpoints already exist in `app/views_dashboard.py`, including `/operator`, `/operator/metrics`, `/logs`, `/api/logs`, and `/api/metrics`.
- Lightweight activity logging already exists via `MessageLogBuffer` in `app/services/message_log.py`, integrated from webhook handling in `app/views.py`.
- Logs status filtering and masked-number reveal controls already exist in `app/templates/logs.html` with client-side reveal behavior in `app/static/js/dashboard.js`.
- Current logs template does not implement true inline expand/collapse state for per-row details; details are rendered as always-visible secondary rows when present.
- Current operator mobile nav in `app/templates/base.html` omits bottom navigation on operator dashboard (`page_key == 'dashboard'`), which conflicts with the UX requirement that dashboard, metrics, and logs support mobile navigation.
- Conversation context memory (last 5 messages per user, reset-on-timeout/new-boundary) is not currently implemented as a dedicated app service; `app/services/openai_service.py` stores thread IDs in a shelf but does not enforce FR9 limits.

### Implementation stance

- Implement FR9 context memory as a focused, app-scoped service with a narrow interface and deterministic behavior.
- Reuse existing operator dashboard and message-log seams; do not introduce a database or external cache.
- Close UX gaps by refining existing templates/scripts rather than redesigning the operator IA.
- Keep privacy and accessibility defaults intact: masked-by-default numbers, explicit reveal control, visible focus, and aria state updates.

---

## Developer Guardrails

### Required code paths

- Keep operator route ownership in `app/views_dashboard.py`.
- Keep recent-activity storage ownership in `app/services/message_log.py`; preserve FIFO semantics with max size 100.
- Keep webhook event ingestion ownership in `app/views.py` and append log entries through `get_message_log_buffer(current_app)`.
- Introduce conversation memory through a dedicated service module under `app/services/` and attach through app extensions, not process globals.

### Conversation context requirements (AC1)

- Provide a per-user rolling context window with strict max length of 5 messages.
- Message shape should be minimal and stable (for example: role, text, timestamp, message_id).
- Reset conditions must be explicit and testable:
  - inactivity timeout (configurable, with safe default),
  - conversation boundary marker (for example explicit reset call when boundary condition is detected).
- Trim oldest messages first when exceeding 5 entries.
- Keep API narrow (for example: `append_message`, `get_context`, `reset_context`, `clear`).

### Operator activity requirements (AC2, AC3, AC4)

- Keep log buffer in memory only; no persistent storage addition.
- Preserve FIFO cap at 100 entries and newest-first rendering behavior in logs/dashboard views.
- Logs screen must support:
  - status filtering (`all`, `sent`, `error`),
  - inline expand/collapse of entry details,
  - masked phone numbers by default,
  - reveal/hide control with stateful `aria-expanded` updates.
- Revealing a number must be intentional and reversible per row.
- Do not expose raw tokens, secrets, or unmasked PII in rendered templates or API payloads by default.

### Responsive/accessibility requirements (AC5)

- Operator dashboard, metrics, and logs must remain navigable at mobile width (<768 px) with persistent route access controls.
- Ensure operator bottom navigation is available on mobile for dashboard, metrics, and logs.
- Preserve visible focus rings and non-color-only status cues.
- Keep refresh behavior aligned with UX:
  - dashboard auto-refresh cadence (30 seconds),
  - metrics manual refresh with visible updated timestamp.

### Existing reusable pieces

- Reuse `MessageLogBuffer` in `app/services/message_log.py`.
- Reuse operator route guards and safe redirect helpers in `app/views_dashboard.py`.
- Reuse existing dashboard JavaScript event wiring in `app/static/js/dashboard.js` for reveal/expand interactions.
- Reuse metrics and health API contracts already exposed by `app/views.py` and `app/views_dashboard.py`.

### Boundaries and non-goals

- Do not add database persistence for logs or context memory in this story.
- Do not redesign setup wizard flow or agent selection semantics from Story 3.2/3.1 scope.
- Do not modify signature validation, webhook verification, or outbound retry logic unless required for integration safety.
- Do not broaden into full escalation redesign; only ensure activity views remain compatible with existing escalation signals.

---

## Previous Story Intelligence

- Story 2.1 established the normalization and idempotency seams in webhook flow; Story 3.3 should consume that stable message shape instead of re-parsing payloads in templates/routes.
- Story 2.3 established correlation-aware outbound and operator-review signaling; Story 3.3 should surface resulting statuses consistently in recent activity/logs.
- Story 1.3 established observability and sanitized contracts; Story 3.3 must preserve masked-by-default operator views and correlation-safe diagnostics.
- Existing dashboard implementation artifact (`spec-dashboard-ui-implementation.md`) already maps intended route/file ownership and should be treated as the UX/implementation baseline for this story.

---

## Git Intelligence Summary

- Recent repository history is shallow (initial commit plus merge/dependency updates), so implementation guidance should prioritize current source-of-truth code over commit archaeology.
- Existing operator/dashboard code in `app/views_dashboard.py`, templates, and tests is the strongest baseline for incremental Story 3.3 delivery.

---

## Implementation Tasks

- [x] Add a dedicated conversation context service with per-user rolling window (`max_messages=5`) and timeout/boundary reset behavior. (AC: 1)
- [x] Integrate conversation context updates into webhook processing using normalized inbound message data and deterministic append order. (AC: 1)
- [x] Surface bounded recent activity on operator dashboard from the existing in-memory message-log buffer with no database dependency. (AC: 2)
- [x] Update logs UI to support true inline expand/collapse details per entry while preserving status filtering and FIFO-backed listing. (AC: 3)
- [x] Preserve masked-by-default phone numbers and implement explicit reveal/hide toggle with stateful `aria-expanded` semantics. (AC: 4)
- [x] Fix operator mobile navigation behavior so dashboard, metrics, and logs remain directly reachable on narrow viewports. (AC: 5)
- [x] Verify dashboard auto-refresh and metrics refresh interactions still function with updated markup and controls. (AC: 5)
- [x] Extend automated tests for conversation context trimming/reset, logs expansion/reveal behavior contracts, FIFO cap, and operator mobile navigation rendering guards. (AC: 1, 2, 3, 4, 5)

## Suggested Subtasks

- [x] Introduce `app/services/conversation_context.py` with a lock-safe in-memory store and app-extension accessor similar to existing service patterns.
- [x] Add configuration key for context timeout (for example `CONVERSATION_CONTEXT_TIMEOUT_SECONDS`) with a conservative default.
- [x] Add tests proving sixth message evicts oldest context entry and reset occurs after timeout.
- [x] Add tests confirming `/logs?status=sent` and `/logs?status=error` filter behavior is preserved.
- [x] Add tests ensuring logs template keeps masked number by default and reveal control exists with `aria-expanded` state.
- [x] Add tests asserting operator mobile nav links are present for dashboard, metrics, and logs contexts.

---

## Files Most Likely to Change

- `app/views.py`
- `app/views_dashboard.py`
- `app/services/message_log.py`
- `app/services/conversation_context.py` (new)
- `app/templates/base.html`
- `app/templates/dashboard.html`
- `app/templates/logs.html`
- `app/static/js/dashboard.js`
- `tests/test_reliability.py`
- `tests/test_release_gates.py`

## Files to Read Before Editing

- `app/__init__.py`
- `app/config.py`
- `app/services/metrics.py`
- `app/services/observability.py`
- `app/services/openai_service.py`
- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prd.md`
- `_bmad-output/planning-artifacts/architecture.md`
- `_bmad-output/planning-artifacts/ux-design.md`
- `_bmad-output/implementation-artifacts/spec-dashboard-ui-implementation.md`

---

## Testing Requirements

### Minimum validation commands

```bash
python -m unittest tests.test_reliability
python -m unittest tests.test_release_gates
```

### Coverage expectations

- Conversation context stores at most 5 messages per user and evicts oldest on overflow.
- Context reset occurs on timeout and explicit boundary reset path.
- Dashboard recent activity remains bounded and renders newest-first entries.
- Logs filtering (`all`/`sent`/`error`) returns expected subsets.
- Logs details support inline expand/collapse semantics without exposing unmasked numbers by default.
- Reveal control updates accessibility state (`aria-expanded`) and toggles masked/full number visibility.
- Operator mobile navigation includes links to dashboard, metrics, and logs.
- Dashboard auto-refresh and metrics manual refresh still update rendered values using existing APIs.

### Test design notes

- Prefer extending `tests/test_reliability.py` for route guard/UI contract tests already anchored there.
- Add focused unit tests for new conversation context service behavior (trim/reset/clear).
- Keep tests hermetic with Flask test app context and no network/API calls.

---

## Architecture Compliance Notes

- Preserve app-factory extension ownership for mutable runtime services; avoid global mutable state for conversation context.
- Keep observability and operator view data lightweight and in-process as defined by architecture.
- Keep operator views dependent on existing `/health`, `/metrics`, and `/api/logs` contracts rather than introducing parallel data channels.
- Keep privacy-safe rendering defaults and sanitized logging contracts from Story 1.3 intact.

---

## Implementation Risks to Avoid

- Unbounded per-user context growth causing memory creep.
- Context leakage across users due to shared/global keys.
- Rendering full phone numbers by default in logs or APIs.
- Mobile operator nav regressions that make logs/metrics unreachable from dashboard.
- Diverging log-row status vocabulary across webhook writes and logs filters.
- Re-parsing raw payloads in templates/routes instead of consuming normalized/event-level data.

---

## References

- Source requirements: `_bmad-output/planning-artifacts/epics.md` - Epic 3, Story 3.3, FR9
- Product context: `_bmad-output/planning-artifacts/prd.md` - FR9 Conversation Context Memory, FR8 logging constraints
- Architecture constraints: `_bmad-output/planning-artifacts/architecture.md` - Operator Experience Support, Observability, app-extension lifecycle
- UX requirements: `_bmad-output/planning-artifacts/ux-design.md` - Dashboard, Metrics, Message Log, mobile nav, accessibility
- Dashboard implementation baseline: `_bmad-output/implementation-artifacts/spec-dashboard-ui-implementation.md`
- Existing operator routes/API: `app/views_dashboard.py`
- Existing webhook ingestion/log append: `app/views.py`
- Existing log buffer service: `app/services/message_log.py`
- Existing operator UI templates/scripts: `app/templates/base.html`, `app/templates/dashboard.html`, `app/templates/logs.html`, `app/static/js/dashboard.js`
- Existing route/UI reliability tests: `tests/test_reliability.py`

---

## Definition of Done

- [x] Story 3.3 acceptance criteria are fully implemented using existing app seams with no database addition.
- [x] Conversation context memory is bounded (5), per-user, and reset-capable (timeout/boundary).
- [x] Operator recent activity and logs views satisfy filtering, expansion, masking, and accessibility requirements.
- [x] Mobile operator navigation works for dashboard, metrics, and logs.
- [x] Focused automated tests pass for context behavior and operator activity view contracts.

## Dev Agent Record

### Agent Model Used

GPT-5.3-Codex

### Debug Log References

- Story implementation status is already `done` in `_bmad-output/implementation-artifacts/sprint-status.yaml`; no sprint-status transition was required in this run.
- Focused validation run executed for Story 3.3 acceptance criteria using reliability and release-gate suites.

### Completion Notes List

- Verified AC1 through AC5 are implemented in the current codebase with no additional architecture changes required.
- Confirmed conversation context behavior, logs masking/filtering/expand semantics, and operator mobile navigation contracts via focused automated tests.
- Confirmed release-gate suite compatibility after Story 3.3 verification.
- Updated this story record to remove duplicate sections and align Definition of Done with verified test evidence.

### File List

- `app/services/conversation_context.py`
- `app/views.py`
- `app/views_dashboard.py`
- `app/templates/base.html`
- `app/templates/logs.html`
- `app/static/js/dashboard.js`
- `tests/test_reliability.py`
- `tests/test_release_gates.py`
- `_bmad-output/implementation-artifacts/3-3-conversation-context-and-operator-activity-views.md`
