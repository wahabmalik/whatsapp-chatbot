---
story_id: "6.2"
story_key: "6-2-secret-redaction-pattern-hardening"
status: "done"
epic: 6
story: 2
created: "2026-05-02"
updated: "2026-05-02"
depends_on:
  - "1.3 (correlation logging and observability baseline)"
  - "5.3 (observability cleanup and delivery telemetry)"
---

# Story 6.2: Secret Redaction Pattern Hardening

## Goal

Harden sanitization regression coverage so representative OpenAI key variants are consistently redacted and protected against future pattern drift.

## Background

Epic 5 improved sanitization depth, but retrospective findings identified a remaining confidence gap around token-shape variance. This story expands tests for known key pattern families and edge formatting, without changing product behavior beyond maintaining current redaction guarantees.

## Acceptance Criteria

1. Sanitization tests include representative OpenAI-style key variants (prefix and format variants used across current provider modes).
2. Tests cover keys embedded in strings, dictionaries, lists, sets, and frozensets where sanitization utilities currently recurse.
3. Redacted outputs never expose full raw secret values and preserve stable placeholder behavior expected by logs/tests.
4. Existing sanitization tests continue passing without weakening prior coverage.

## Test Strategy

- Extend sanitization-focused tests with explicit variant fixtures and containerized payloads.
- Reuse existing redaction helpers to keep tests aligned with production sanitization paths.
- Assert both positive redaction (secret hidden) and non-secret pass-through behavior.
- Keep tests deterministic and isolated from environment-specific config.

## Files Likely To Be Touched

- `tests/test_log_sanitization_extended.py`
- `tests/test_release_gates.py`
- `app/services/observability.py`
- `app/config.py`

## Story Completion Status

- Acceptance criteria validated against existing sanitization coverage.
- Validation complete: `tests/test_log_sanitization_extended.py`, `tests/test_story_1_3.py`, and `tests/test_release_gates.py` all passed.
- Status set to `done`.
