---
story_id: "5.2"
story_key: "5-2-configuration-validation-and-runtime-guardrails"
status: "ready-for-dev"
epic: 5
story: 2
created: "2026-05-01"
depends_on:
  - "1.1 (startup validation and setup gating)"
  - "2.3 (outbound delivery retry and fallback)"
---

# Story 5.2: Configuration Validation and Runtime Guardrails

## User Story

As a platform owner,
I want invalid configuration values and teardown edge cases handled explicitly,
so that runtime behavior stays predictable under misconfiguration and shutdown paths.

## Acceptance Criteria

1. Unknown `WHATSAPP_PROVIDER` values fail validation with an actionable error instead of silently mapping to `meta`.
2. Outbound provider configuration reads use validation-safe access patterns rather than bracket lookups that can raise `KeyError` during runtime.
3. WhatsApp outbound timeout is configurable via a validated setting with a documented default value.
4. The retry/fallback implementation plan explicitly resolves whether fallback delivery gets its own bounded retry policy, and tests reflect the chosen contract.
5. App teardown catches and logs per-extension `close()` failures while still attempting cleanup for the remaining extensions.

---

## Context and Constraints

### Deferred backlog items consolidated here

- `normalize_provider` silently maps unknown values to `meta`.
- Evolution provider path uses bracket notation that can raise `KeyError`.
- Outbound timeout is hard-coded to 10 seconds.
- Fallback send attempts only once with no retry logic.
- Retry timing relies on `time.monotonic()` with only theoretical wrap-around discussion captured today.
- Extension teardown does not catch `close()` exceptions.

### Design stance

- Keep startup validation authoritative for provider and timeout settings.
- Avoid adding new deployment modes or providers; this is a hardening story, not a platform expansion story.
- Preserve Story 2.3's deterministic outbound contract while making policy choices explicit and testable.

### Likely files

- `app/config.py`
- `app/__init__.py`
- `app/utils/whatsapp_utils.py`
- `tests/test_story_1_1_and_1_2.py`
- `tests/test_reliability.py`
- `tests/test_release_gates.py`

---

## Implementation Tasks

- [ ] Add explicit provider-value validation and surface the error through startup/setup flows. (AC: 1)
- [ ] Replace runtime bracket access for required outbound config with validated lookups or typed helpers. (AC: 2)
- [ ] Introduce a validated outbound-timeout setting and update documentation/comments accordingly. (AC: 3)
- [ ] Decide and implement the bounded retry contract for fallback delivery, including focused regression tests. (AC: 4)
- [ ] Make the retry timing source and assumptions explicit so future refactors preserve the intended monotonic-time behavior. (AC: 4)
- [ ] Harden teardown cleanup so one extension close failure does not skip later cleanup work. (AC: 5)

## Testing Requirements

### Minimum validation commands

```bash
python -m pytest tests/test_story_1_1_and_1_2.py -q
python -m pytest tests/test_reliability.py -q
python -m pytest tests/test_release_gates.py -q
```

### Coverage expectations

- Unknown provider values fail with explicit operator-visible diagnostics.
- Outbound timeout configuration accepts valid values and rejects malformed ones.
- Tests pin the final retry policy for primary and fallback sends.
- Teardown continues after one closable extension raises.

## References

- `_bmad-output/implementation-artifacts/deferred-work.md`
- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/architecture.md`
- `app/config.py`
- `app/__init__.py`
- `app/utils/whatsapp_utils.py`

## Story Completion Status

- Story document created and context-complete for implementation.
- Status set to `ready-for-dev`.
