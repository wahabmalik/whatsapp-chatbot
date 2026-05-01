---
story_id: "6.1"
story_key: "6-1-fallback-retry-contract-test"
status: "done"
epic: 6
story: 1
created: "2026-05-02"
updated: "2026-05-02"
depends_on:
  - "2.3 (outbound delivery retry and fallback)"
  - "5.2 (configuration validation and runtime guardrails)"
---

# Story 6.1: Fallback Retry Contract Test

## Goal

Codify retry/fallback behavior as a deterministic contract test that proves configured fallback retries are honored when transient errors recover within the allowed retry window.

## Background

Epic 5 retrospective flagged retry semantics as partially implicit. Current coverage validates core delivery and fallback behavior but does not lock a fail-then-recover sequence as a strict CI contract. This story adds a focused test only; it does not introduce new retry features.

## Acceptance Criteria

1. A test simulates transient outbound failures followed by recovery and asserts retry attempts stop once success occurs.
2. The test asserts configured retry count is honored and no premature fallback occurs when success is reached within allowed retries.
3. A complementary assertion verifies fallback path is used when all configured retries fail.
4. Assertions are deterministic and avoid timing flakiness by mocking transport and retry boundaries.

## Test Strategy

- Add or extend unit/integration tests around outbound delivery orchestration.
- Use controlled mocks for transport failures and eventual success.
- Assert both attempt count and terminal outcome (success vs fallback) for fail-then-recover and fail-all scenarios.
- Keep test runtime small and CI-friendly by avoiding sleeps and real network calls.

## Files Likely To Be Touched

- `tests/test_reliability.py`
- `tests/test_retry_escalation_contract.py`
- `app/services/delivery.py`
- `app/utils/whatsapp_utils.py`

## Story Completion Status

- Story document created and context-complete for implementation.
- Status set to `ready-for-dev`.
