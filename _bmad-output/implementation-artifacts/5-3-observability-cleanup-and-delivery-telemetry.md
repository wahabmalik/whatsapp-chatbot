---
story_id: "5.3"
story_key: "5-3-observability-cleanup-and-delivery-telemetry"
status: "ready-for-dev"
epic: 5
story: 3
created: "2026-05-01"
depends_on:
  - "1.3 (correlation logging and observability baseline)"
  - "2.3 (outbound delivery retry and fallback)"
  - "4.1 (automated quality and launch gates)"
---

# Story 5.3: Observability Cleanup and Delivery Telemetry

## User Story

As an on-call operator,
I want logging and delivery telemetry to be precise and low-noise,
so that incidents can be diagnosed without ambiguous traces or instrumentation drift.

## Acceptance Criteria

1. Logging sanitization is applied once per record in the intended ownership layer without repeated filter accumulation across reconfiguration paths.
2. Correlation ID ownership is centralized, length-capped, and still propagated consistently through request handling and controlled error responses.
3. Log sanitization covers container types used by the app, including `set` and `frozenset`.
4. The observability contract still applies to late-registered handlers or any equivalent logging path the app relies on.
5. Outbound delivery telemetry exposes attempt-level timing or equivalent operator-visible detail that distinguishes slow retries from only the terminal outcome.

---

## Context and Constraints

### Deferred backlog items consolidated here

- Double-filter accumulation in `configure_logging()`.
- Redundant `ensure_correlation_id` inside route handlers.
- No maximum length on correlation ID.
- `_sanitize_arg` does not recurse into `set` / `frozenset`.
- Late-registered handlers may bypass handler-level filters.
- Per-attempt duration metrics unavailable.
- Concurrent log interleaving becomes harder to read under load.

### Design stance

- Preserve the lightweight in-process observability model introduced in Story 1.3.
- Prefer clarifying one ownership layer for sanitization and correlation propagation over adding parallel hooks.
- Keep structured fields stable so launch-gate and operator tooling do not regress.

### Likely files

- `app/config.py`
- `app/services/observability.py`
- `app/views.py`
- `app/utils/whatsapp_utils.py`
- `tests/test_reliability.py`
- `tests/test_release_gates.py`

---

## Implementation Tasks

- [ ] Remove duplicate filter attachment paths and make logging setup idempotent. (AC: 1)
- [ ] Centralize correlation ID assignment, add an explicit max length, and remove redundant handler-local calls. (AC: 2)
- [ ] Extend argument sanitization to additional container types used in logging. (AC: 3)
- [ ] Verify or adjust late-handler coverage so sanitized correlation-aware logging remains the actual runtime contract. (AC: 4)
- [ ] Emit attempt-level outbound timing metrics or structured log fields suitable for operator review and gate reporting. (AC: 5)
- [ ] Add focused tests for sanitization recursion, correlation caps, and retry-attempt telemetry. (AC: 1, 2, 3, 5)

## Testing Requirements

### Minimum validation commands

```bash
python -m pytest tests/test_reliability.py -q
python -m pytest tests/test_release_gates.py -q
```

### Coverage expectations

- Repeated logging configuration does not accumulate duplicate filters.
- Oversized request IDs are truncated predictably.
- Secret-like values inside sets are sanitized.
- Outbound retries emit distinguishable timing evidence per attempt.

## References

- `_bmad-output/implementation-artifacts/deferred-work.md`
- `_bmad-output/planning-artifacts/architecture.md`
- `_bmad-output/implementation-artifacts/1-3-correlation-logging-and-observability-baseline.md`
- `_bmad-output/implementation-artifacts/2-3-outbound-delivery-retry-and-fallback.md`
- `app/services/observability.py`
- `app/config.py`

## Story Completion Status

- Story document created and context-complete for implementation.
- Status set to `ready-for-dev`.
