---
stepsCompleted: ["release-quality-matrix-initial"]
generated: "2026-04-28"
status: "COMPLETE — all launch gates passed (GO)"
---

# Release Quality Matrix

## How to Use

- **Blocking** gates are all passing in the latest gate evaluation.
- **Advisory** gates are currently passing in manual attestations.
- Source of truth for final gate state is `_bmad-output/test-artifacts/go-no-go-report.md`.
- Linked test IDs correspond to classes/methods in `tests/`.
- Evidence paths are relative to the project root.

---

## Security Gate (Blocking)

| ID | FR/NFR | Obligation | Test ID(s) | Evidence Path | Gate | Status |
|----|--------|------------|------------|---------------|------|--------|
| E4-SEC-01 | FR2, NFR4 | Reject invalid HMAC signature with 403 | `SecurityDecoratorTests::test_rejects_invalid_signature` | test run output | Blocking | pass |
| E4-SEC-02 | FR2, NFR4 | Reject malformed X-Hub-Signature-256 header | `SecurityDecoratorTests::test_rejects_malformed_signature_header` | test run output | Blocking | pass |
| E4-SEC-03 | FR2 | Reject stale timestamp (outside skew window) | `SecurityDecoratorTests::test_rejects_old_timestamp` | test run output | Blocking | pass |
| E4-SEC-04 | FR2 | Reject replayed signature | `SecurityDecoratorTests::test_rejects_replay_signature` | test run output | Blocking | pass |
| E4-SEC-05 | FR2, NFR4 | Accept valid signature + timestamp (positive path) | `ReleaseSecurityGateTests::test_valid_signature_request_accepted` | test run output | Blocking | pass |
| E4-SEC-06 | FR1 | GET /webhook returns hub.challenge on valid token | `ReleaseWebhookVerificationTests::test_webhook_get_challenge_positive_path` | test run output | Blocking | pass |
| E4-SEC-07 | FR1 | GET /webhook returns 403 on mismatched verify token | `ReleaseWebhookVerificationTests::test_webhook_get_challenge_token_mismatch` | test run output | Blocking | pass |
| E4-SEC-07b | FR1 | GET /webhook returns 403 on missing mode parameter | `ReleaseWebhookVerificationTests::test_webhook_get_challenge_missing_mode` | test run output | Blocking | pass |
| E4-SEC-08 | FR2, FR8 | Rejection body does not expose APP_SECRET | `ReleaseSecurityGateTests::test_rejection_does_not_expose_app_secret` | test run output | Blocking | pass |

---

## Reliability Gate (Blocking)

| ID | FR/NFR | Obligation | Test ID(s) | Evidence Path | Gate | Status |
|----|--------|------------|------------|---------------|------|--------|
| E4-REL-01 | FR3, NFR3 | Duplicate message suppressed (in-memory store) | `WebhookIdempotencyTests::test_duplicate_message_is_skipped` | test run output | Blocking | pass |
| E4-REL-02 | FR3, NFR3 | Duplicate message suppressed (SQLite store) | `WebhookIdempotencyTests::test_duplicate_message_is_skipped_with_sqlite_store` | test run output | Blocking | pass |
| E4-REL-03 | FR3 | SQLite init failure falls back to memory when configured | `SQLiteExpiringStoreTests::test_factory_falls_back_to_memory_when_sqlite_fails` | test run output | Blocking | pass |
| E4-REL-04 | FR5 | send_message returns structured error on timeout | `ReleaseOutboundGateTests::test_send_message_timeout_returns_structured_error` | test run output | Blocking | pass |
| E4-REL-04b | FR5 | send_message returns structured error on connection failure | `ReleaseOutboundGateTests::test_send_message_request_exception_returns_structured_error` | test run output | Blocking | pass |
| E4-REL-04c | FR5 | send_message returns ok=True on success | `ReleaseOutboundGateTests::test_send_message_success_returns_ok_true` | test run output | Blocking | pass |
| E4-REL-05 | FR5, NFR6 | Outbound retry 3 attempts with 1/2/4s backoff | `ReleaseOutboundGateTests::test_outbound_retry_attempts_match_spec` | test run output | Blocking | pass |
| E4-REL-06 | FR5, NFR6 | Fallback sent and operator-review flag emitted after retry exhaustion | `ReleaseOutboundGateTests::test_fallback_sent_after_retry_exhaustion` | test run output | Blocking | pass |
| E4-REL-07 | FR6 | Stale/invalid agent selection auto-repairs to safe default | `AgentRegistryTests::test_get_selected_agent_repairs_stale_saved_selection` | test run output | Blocking | pass |
| E4-REL-08 | FR7 | Missing required config variable emits per-variable error | `ConfigValidationTests::test_validate_config_missing_required_key` | test run output | Blocking | pass |

---

## Latency / Performance Gate (Blocking)

| ID | NFR | Obligation | Evidence Source | Evidence Path | Gate | Status |
|----|-----|------------|-----------------|---------------|------|--------|
| E4-PERF-01 | NFR2 | P50 latency <= 4s in staging (1000+ messages) | staging-validation-report.json → `latency_p50_ok` | `_bmad-output/test-artifacts/staging-validation-report.json` | Blocking | pass |
| E4-PERF-02 | NFR2 | P95 latency <= 8s in staging | staging-validation-report.json → `latency_p95_ok` | same | Blocking | pass |
| E4-PERF-03 | NFR3 | Message success rate >= 99% over 1000 messages | staging-validation-report.json → `success_rate_ok` | same | Blocking | pass |
| E4-PERF-04 | NFR5 | Throughput >= 10 msg/sec | staging-validation-report.json → `throughput_ok` | same | Blocking | pass |
| E4-PERF-05 | NFR6 | Fallback delivery <= 10s from first API failure | staging-validation-report.json → `fallback_timing_ok` | `_bmad-output/test-artifacts/staging-validation-report.json` | Blocking | pass |

Run command: `python staging_validation.py --count 1000 --app-secret $APP_SECRET`

PowerShell (if APP_SECRET is not exported yet): `$env:APP_SECRET="dev-local-secret"`

---

## Correlation ID Gate (Blocking)

| ID | FR/NFR | Obligation | Test ID(s) | Evidence Path | Gate | Status |
|----|--------|------------|------------|---------------|------|--------|
| E4-COR-01 | FR8 | X-Request-ID forwarded to process_whatsapp_message | `ReleaseCorrelationIdTests::test_correlation_id_propagated_through_valid_message` | test run output | Blocking | pass |
| E4-COR-02 | FR8 | Rejection log includes correlation ID | `ReleaseCorrelationIdTests::test_rejection_log_includes_request_id` | test run output | Blocking | pass |

---

## Operations and Documentation Gate (Blocking)

| ID | NFR/Req | Obligation | Evidence Source | Evidence Path | Gate | Status |
|----|---------|------------|-----------------|---------------|------|--------|
| E4-OPS-01 | NFR8 | docs/setup_guide.md exists and covers all setup sections | file_exists | `docs/setup_guide.md` | Blocking | pass |
| E4-OPS-02 | NFR7 | docs/operations_runbook.md exists with rollback procedure | file_exists | `docs/operations_runbook.md` | Blocking | pass |
| E4-OPS-03 | NFR8 | docs/release_smoke_checklist.md is executable | file_exists | `docs/release_smoke_checklist.md` | Blocking | pass |
| E4-OPS-04 | R4 | No unresolved High risks in risk register | Manual attestation | risk-register.yaml → `no_high_risks_unresolved` | Blocking | pass |
| E4-OPS-05 | R6 | Rollback plan documented and tested | Manual attestation | risk-register.yaml → `rollback_plan_verified` | Blocking | pass |
| E4-OPS-06 | NFR8 | Health endpoint accessible without operator session | `ReleaseHealthGateTests::test_health_endpoint_accessible_without_operator_session` | test run output | Blocking | pass |

---

## Advisory Checks

| ID | Obligation | Source | Status |
|----|------------|--------|--------|
| E4-ADV-01 | Log retention >= 30 days documented | Manual: ops runbook section | pass |
| E4-ADV-02 | Pilot quality score >= 4/5 from pilot users | Manual: pilot report | pass |
| E4-ADV-03 | No shelve-based thread storage in production path | Code review | pass |

---

## Gate Summary

| Gate | Blocking Tests | Blocked Items | Status |
|------|---------------|---------------|--------|
| Security | E4-SEC-01 to 08 | None | ✅ pass |
| Reliability | E4-REL-01 to 08 | None | ✅ pass |
| Latency/Perf | E4-PERF-01 to 05 | None | ✅ pass |
| Correlation ID | E4-COR-01, 02 | None | ✅ pass |
| Operations | E4-OPS-01 to 06 | None | ✅ pass |
| **Overall Go/No-Go** | **All blocking** | **None** | **✅ GO** |

---

## How to Run Tests

```bash
# All tests
python -m unittest discover tests

# Security-critical subset only
python -m unittest tests.test_release_gates.ReleaseSecurityGateTests tests.test_release_gates.ReleaseWebhookVerificationTests

# Gate evaluation (after tests and staging run)
python evaluate_launch_gates.py

# Staging validation (app must be running)
# PowerShell: set once per shell if missing -> $env:APP_SECRET="dev-local-secret"
python staging_validation.py --count 1000 --app-secret $APP_SECRET
```


