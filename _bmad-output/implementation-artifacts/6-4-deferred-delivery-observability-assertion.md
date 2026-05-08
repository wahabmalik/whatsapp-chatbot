---
story_id: "6.4"
story_key: "6-4-deferred-delivery-observability-assertion"
status: "done"
epic: 6
story: 4
created: "2026-05-02"
depends_on:
  - "2.3 (outbound delivery retry and fallback)"
  - "5.3 (observability cleanup and delivery telemetry)"
---

# Story 6.4: Deferred-Delivery Observability Assertion

## Goal

Add a contract test that proves deferred background delivery emits a final observable outcome suitable for operators and release-gate evidence.

## Background

Deferred delivery is operationally critical, but retrospective review identified a gap in explicit final-outcome assertions for background paths. This story adds CI-guarded validation that terminal success/failure state is reflected in logs or artifacts consumed by operations.

## Acceptance Criteria

1. A test exercises deferred delivery and asserts a terminal outcome record exists for the background flow.
2. Terminal observability assertion distinguishes success and failure outcomes with stable fields used by existing tooling.
3. The test verifies outcome evidence is present in expected log/artifact channels without relying on manual inspection.
4. Test remains deterministic and avoids flaky timing behavior through controlled async execution or mocks.

## Test Strategy

- Extend deferred-delivery observability tests with explicit terminal-state assertions.
- Capture structured logs/artifacts emitted by the background path and assert required fields.
- Validate both success and failure terminal cases where practical with fixtures/mocks.
- Keep assertions aligned with release-gate expectations and existing observability schema.

## Files Likely To Be Touched

- `tests/test_deferred_delivery_observability.py`
- `tests/test_release_gates.py`
- `app/services/delivery.py`
- `app/services/observability.py`

## Story Completion Status

- Story implemented and validated against targeted deferred-delivery and release-gate tests.
- Status set to `done`.

## Tasks / Subtasks

- [x] Extend deferred-delivery observability tests with explicit terminal success assertions.
- [x] Extend deferred-delivery observability tests with explicit terminal failure assertions across log and operator artifact channels.
- [x] Align background deferred-delivery structured log entries with stable correlation fields used by release-gate evidence.
- [x] Validate focused deferred-delivery tests, focused release-gate tests, and the full pytest suite.

## Dev Agent Record

### Debug Log

- Added red-phase contract tests in `tests/test_deferred_delivery_observability.py` for terminal success/failure evidence.
- Updated deferred background completion to bind the request correlation ID in the worker thread and include `correlation_id` in buffered log entries.
- Extended `tests/test_release_gates.py` to assert terminal deferred success and failure evidence through stable fields.
- Validation: `pytest tests/test_deferred_delivery_observability.py --tb=short -q`
- Validation: `pytest tests/test_release_gates.py -k deferred_delivery --tb=short -q`
- Validation: `pytest tests/ --tb=short -q`

### Completion Notes

- Background deferred delivery now preserves correlation IDs in both runtime log context and structured dashboard log records.
- Terminal success and failure flows are both asserted using stable fields shared with operator-facing artifacts.

## File List

- `app/utils/whatsapp_utils.py`
- `tests/test_deferred_delivery_observability.py`
- `tests/test_release_gates.py`

## Change Log

- 2026-05-02: Added deferred terminal-outcome observability assertions and aligned background log correlation fields.

## Status

- Done.
