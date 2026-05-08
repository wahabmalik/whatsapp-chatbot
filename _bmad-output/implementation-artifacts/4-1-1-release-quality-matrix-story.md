---
story_id: "4.1.1"
story_key: "4-1-1-release-quality-matrix"
status: "ready-for-dev"
epic: 4
story: 1
created: "2026-04-28"
depends_on:
  - "4.1 (epics acceptance criteria baseline)"
---

# Story 4.1.1: Build Critical Path Test Matrix

## User Story

As a release owner,
I want a traceable matrix that maps every PRD/FR/NFR launch obligation to an automated test or evidence artifact,
so that the Go/No-Go decision is backed by a specific, checkable reference rather than ad hoc notes.

## Acceptance Criteria

1. The matrix document exists at `_bmad-output/test-artifacts/release-quality-matrix.md`.
2. Every row maps: Obligation ID → Story owner → Test ID(s) → Gate classification (Blocking / Advisory) → Evidence artifact path.
3. All FR1–FR10 and NFR1–NFR8 obligations have at least one mapped test or evidence item.
4. The matrix identifies at least one Blocking gate for Security, Reliability, and Operations domains.
5. Every Blocking test ID matches a real test in `tests/`.

---

## Context and Constraints

### Source Obligations

The full obligation list comes from the requirements inventory in `_bmad-output/planning-artifacts/epics.md`:

- FR1 — GET webhook challenge verification
- FR2 — POST HMAC-SHA256 signature enforcement
- FR3 — Inbound normalization + idempotency (memory/sqlite)
- FR4 — OpenAI controlled failure states (typed result)
- FR5 — Outbound retry/fallback (3 attempts, 1/2/4 s backoff)
- FR6 — Runtime agent selection with auto-repair
- FR7 — Startup config validation before request handling
- FR8 — Correlation ID propagation and log sanitization
- FR9 — Per-user rolling conversation context (last 5)
- FR10 — Escalation detection and flag
- NFR1 — Availability >= 99.5% uptime
- NFR2 — P50 <= 4s, P95 <= 8s latency
- NFR3 — >= 99% message success rate over 1000 staging messages
- NFR4 — 100% of POST requests undergo signature validation
- NFR5 — >= 10 msg/sec staging throughput
- NFR6 — <= 10s fallback reply from first API failure
- NFR7 — Log retention >= 30 days
- NFR8 — Config setup < 2 minutes from runbook

### Existing Test Coverage Baseline

| Test File | Classes Covered |
|-----------|-----------------|
| `tests/test_reliability.py` | Config validation, HMAC decorator rejections, webhook idempotency, metrics endpoint, dashboard route guards, OpenAI timeout |
| `tests/test_agent_registry.py` | Agent listing, stale selection repair, atomic writes |
| `tests/test_expiring_store.py` | In-memory expiry, SQLite expiry, factory fallback/raise |
| `tests/test_release_gates.py` | Positive signature acceptance, GET verify flow, health endpoint, send_message error contract, correlation IDs, escalation flag logic |

### Naming Convention

Tests should use the `E4-<DOMAIN>-<NN>` prefix in test IDs within the matrix:

- `E4-SEC-NN` — Security-critical webhook and signature paths
- `E4-REL-NN` — Reliability and idempotency paths
- `E4-PERF-NN` — Latency, throughput, fallback timing checks
- `E4-OPS-NN` — Operational documentation and smoke verification

---

## Implementation Steps

### Step 1 — Draft matrix skeleton

Create `_bmad-output/test-artifacts/release-quality-matrix.md` with the heading structure:

```markdown
# Release Quality Matrix

Generated: <date>
Status: DRAFT

## How to Use
...

## Security Gate (Blocking)

| ID | FR/NFR | Obligation | Test IDs | Evidence | Gate |
...

## Reliability Gate (Blocking)
...

## Latency / Performance Gate (Blocking)
...

## Operations and Docs Gate (Blocking)
...

## Advisory Checks
...
```

### Step 2 — Populate Security rows

Map FR1, FR2, FR4, NFR4 to test IDs in `tests/test_reliability.py` and `tests/test_release_gates.py`:

- E4-SEC-01 → test_rejects_invalid_signature (SecurityDecoratorTests)
- E4-SEC-02 → test_rejects_malformed_signature_header
- E4-SEC-03 → test_rejects_old_timestamp
- E4-SEC-04 → test_rejects_replay_signature
- E4-SEC-05 → test_valid_signature_request_accepted (ReleaseSecurityGateTests)
- E4-SEC-06 → test_webhook_get_challenge_positive_path
- E4-SEC-07 → test_webhook_get_challenge_token_mismatch
- E4-SEC-08 → test_rejection_does_not_expose_app_secret

### Step 3 — Populate Reliability rows

Map FR3, FR5, FR8, NFR3, NFR6 to test IDs:

- E4-REL-01 → test_duplicate_message_is_skipped (WebhookIdempotencyTests)
- E4-REL-02 → test_duplicate_message_is_skipped_with_sqlite_store
- E4-REL-03 → test_factory_falls_back_to_memory_when_sqlite_fails (SQLiteExpiringStoreTests)
- E4-REL-04 → test_send_message_timeout_returns_structured_error (ReleaseOutboundGateTests)
- E4-REL-05 → test_outbound_retry_attempts_match_spec [BLOCKED: Story 2.3]
- E4-REL-06 → test_fallback_sent_after_retry_exhaustion [BLOCKED: Story 2.3]

### Step 4 — Populate Latency/Performance rows

Map NFR2, NFR5, NFR6:

- E4-PERF-01 → Staging validation report: staging-validation-report.json, `latency_p50_ok`, `latency_p95_ok`
- E4-PERF-02 → Staging validation report: `throughput_ok`
- E4-PERF-03 → Staging validation report: `fallback_timing_ok`

### Step 5 — Populate Operations and Docs rows

Map NFR7, NFR8, FR7 setup guide obligations:

- E4-OPS-01 → docs/setup_guide.md exists and covers all required sections
- E4-OPS-02 → docs/operations_runbook.md exists with rollback playbook
- E4-OPS-03 → docs/release_smoke_checklist.md is executable and reviewed
- E4-OPS-04 → setup time validation: timed clean-room run < 45 min, config entry < 2 min

### Step 6 — Add gate summary block

Append a `## Gate Summary` section at the bottom of the matrix:

```markdown
## Gate Summary

| Gate | Blocking Tests | Advisory Tests | Status |
|------|---------------|----------------|--------|
| Security | E4-SEC-01…08 | — | [ ] |
| Reliability | E4-REL-01…06 | — | [ ] |
| Latency/Perf | E4-PERF-01…03 | — | [ ] |
| Operations | E4-OPS-01…04 | — | [ ] |
| Overall Go/No-Go | All blocking | All advisory | [ ] |
```

---

## Definition of Done

- [ ] `_bmad-output/test-artifacts/release-quality-matrix.md` created.
- [ ] All FR1–FR10 and NFR1–NFR8 obligations have at least one row.
- [ ] BLOCKED items are clearly marked with the story that unblocks them.
- [ ] All non-blocked Blocking test IDs pass locally (`python -m unittest discover tests`).
