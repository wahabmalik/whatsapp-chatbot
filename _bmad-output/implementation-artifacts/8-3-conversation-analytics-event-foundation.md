---
story_id: "8.3"
story_key: "8-3-conversation-analytics-event-foundation"
status: "done"
epic: 8
story: 3
created: "2026-05-02"
estimate: "3 days"
type: "P1 feature prep"
depends_on:
  - "1.3 (correlation logging and observability baseline)"
  - "2.2 (ai reply contract and failure handling)"
  - "2.3 (outbound delivery retry and fallback)"
  - "3.2 (setup wizard and escalation workflow)"
---

# Story 8.3: Conversation Analytics Event Foundation

## Story

As an operations lead,
I want structured conversation events captured consistently,
so that we can report on escalation trends and support outcomes in upcoming analytics features.

## Epic 8 Transition Context

This is the second selected P1 non-goal carry-in for the transition sprint. Scope is event foundation and schema consistency, not full dashboard analytics UI.

## Acceptance Criteria

1. Structured analytics events are emitted for inbound receive, AI outcome, escalation flag, and outbound outcome.
2. Event schema includes correlation ID, conversation/user key, outcome status, and timestamp.
3. Events inherit existing sanitization requirements and do not expose secrets or raw PII.
4. A lightweight verification surface (artifact or endpoint) exposes recent events for staging checks.
5. Tests verify schema consistency and at least one escalation trend signal.
6. Event emission maintains sanitization guarantees and keeps P95 request-handling regression within 5% versus baseline.

## Tasks

- [x] Define a stable analytics event schema with required fields. (AC: 1, 2)
- [x] Emit events from inbound, AI, escalation, and outbound stages. (AC: 1)
- [x] Ensure event payload sanitization aligns with current log redaction policy. (AC: 3)
- [x] Provide a lightweight verification surface for recent events. (AC: 4)
- [x] Add focused tests for schema and escalation signal consistency. (AC: 5)
- [x] Capture baseline and post-change timing evidence for request handling. (AC: 6)

## Validation Commands

```powershell
.venv\Scripts\python.exe -m pytest tests/test_deferred_delivery_observability.py -q
.venv\Scripts\python.exe -m pytest tests/test_log_sanitization_extended.py -q
```

## Risk Closure Criteria

- [x] No secret or raw PII leaks introduced in analytics payloads.
- [x] Schema remains stable for downstream reporting consumers.
- [x] Measured latency delta remains inside the 5% guardrail.

## References

- `_bmad-output/planning-artifacts/next-cycle-readiness.md`
- `_bmad-output/planning-artifacts/epics.md`
- `app/services/`
- `app/views.py`
- `tests/`

## Completion State

- Story completed and validated on 2026-05-03.
- Analytics schema and endpoint contracts remained stable with sanitization guarantees preserved.
- Persistence-backed verification surface confirmed via JSONL store + API endpoint checks.

## Dev Agent Record

### Files Changed

- `app/services/conversation_analytics.py` - Implemented schema v1 event emission, sanitization, persistence, and summary utilities.
- `app/views.py` - Added analytics verification endpoint integration for recent events and summary output.
- `tests/test_conversation_analytics_event_foundation.py` - Added schema, trend-signal, and persistence continuity tests.

### Completion Notes

- AC1 and AC2: Emitted structured events for inbound, AI outcome, escalation, and outbound stages with required stable fields.
- AC3: Event details are sanitized and avoid raw PII exposure.
- AC4: `/api/analytics/events` provides recent event verification with escalation summary metrics.
- AC5: Focused tests cover schema consistency and escalation trend signal behavior.
- AC6: Latency guardrail evidence captured through same-session emit-on/emit-off comparison approach described in project memory.
