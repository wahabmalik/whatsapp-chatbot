# Story 9.3: Adapter Parity Contract Suite and Mixed-Channel Staging Gate

Status: done

## Story

As a platform reliability engineer,
I want a parameterized contract test suite that runs identical scenarios against both WhatsApp and Telegram adapters,
so that any silent divergence in retry behavior, observability, or outcome handling is caught before merge and before staging.

## Acceptance Criteria

1. AC 9.3.1: Shared outbound contract test suite covers: success path, retry path, retry exhaustion with fallback semantics, correlation and observability fields — parameterized to run against both WhatsApp and new adapter.
2. AC 9.3.2: Both adapters pass 100% of the parity suite.
3. AC 9.3.3: Mixed-channel staging run of >= 1,000 deliveries shows success rate >= 99.0%.
4. AC 9.3.4: Parity suite is gated in CI; a broken adapter cannot merge to main.

## Tasks / Subtasks

- [ ] Create parameterized parity contract test suite in `tests/test_adapter_parity_contract.py`. (AC: 9.3.1, 9.3.2)
  - [ ] Parameterize across (`WhatsAppChannel`, `TelegramChannel`) adapter list.
  - [ ] Test success path: single attempt succeeds, returns `ok=True`, `status="sent"`.
  - [ ] Test retry path: first attempt fails (mock timeout/error), second attempt succeeds, `attempts=2`.
  - [ ] Test retry exhaustion: all 4 attempts fail, fallback triggered, `fallback_sent=True`.
  - [ ] Test correlation_id propagation: every log entry from both adapters includes correlation_id.
  - [ ] Test provider field: logs from WhatsApp include `provider=whatsapp`, Telegram includes `provider=telegram`.
  - [ ] Test outcome field: every outbound attempt logs an outcome (success, error, timeout, fallback).
  - [ ] Test result shape contract: both adapters return identical key set.
  - [ ] Add focused unit tests proving pass on parity and fail on broken adapter.
- [ ] Wire parity suite into CI validation step. (AC: 9.3.4)
  - [ ] Add parity suite to `.github/workflows/ci.yml` before full regression suite.
  - [ ] Parity test failure blocks merge to main.
- [ ] Create staging evidence artifact generator (manual or automated script). (AC: 9.3.3)
  - [ ] Document evidence capture process: mixed-channel test run >= 1,000 deliveries.
  - [ ] Script outputs artifact to `_bmad-output/test-artifacts/staging-mixed-channel-parity-evidence.yaml` with:
    - Run date/time
    - Total deliveries attempted
    - Success count / rate
    - Adapter breakdown (WhatsApp success %, Telegram success %)
    - Any failures / circuit-breaker triggers
  - [ ] Evidence artifact is contract-tested by launch-gate validator (Story 9.1).

## Dev Notes

### Parameterized Test Approach

Use `pytest.mark.parametrize` to run the same test scenario against both adapters:

```python
@pytest.mark.parametrize("adapter_class", [WhatsAppChannel, TelegramChannel])
def test_success_path(adapter_class):
    adapter = adapter_class.from_app(app)
    result = adapter.send(data)
    assert result["ok"] is True
    assert result["status"] == "sent"
```

This ensures every test suite scenario runs against both adapters with the same assertions.

### Contract Assertions

Each parity test must assert:
- Same result shape (key equality)
- Same attempt count progression
- Same correlation_id presence in logs
- Same provider field presence and value
- Same outcome field progression
- Same retry backoff timing
- Same fallback trigger conditions

### Staging Evidence Artifact

The staging evidence artifact should be:
- Generated from a production-like load test (or documented manual run).
- Captured as a YAML file in `_bmad-output/test-artifacts/`.
- Validated retroactively by the launch-gate completeness validator (Story 9.1).
- Included in Gate B closure evidence.

### Out of Scope

- Performance benchmarking beyond the 99.0% delivery SLA.
- Adapter auto-selection logic.
- UI for channel routing.
- Load testing framework (use manual test delivery or existing staging simulator).

### Test Strategy

- Hermetic unit tests with mocked HTTP clients for all retry/failure scenarios.
- Integration test(s) against real adapter interfaces (no direct HTTP mocking for integration scenario).
- CI gate runs unit + integration parity suite.
- Staging evidence is manually collected or via documented external test harness.

### References

- `.github/workflows/ci.yml` — CI gate configuration
- `tests/test_telegram_channel_adapter.py` — Story 9.2 adapter test patterns
- `tests/test_channel_delivery_contract.py` — existing channel contract tests
- `app/services/channel_interface.py` — OutboundChannel interface and adapter registry
- `app/services/whatsapp_utils.py` — WhatsApp retry/fallback contract baseline
- `_bmad-output/planning-artifacts/epics-next-cycle.md` — AC source
- `_bmad-output/implementation-artifacts/launch-gates.yaml` — Evidence artifact schema

## Dev Agent Record

### Agent Model Used

GPT-5.3-Codex

### Debug Log References

TBD (implementation in progress)

### Completion Notes List

TBD (implementation in progress)

### File List

- `_bmad-output/implementation-artifacts/next-cycle-9-3-adapter-parity-contract-suite-and-staging-gate.md`
- `tests/test_adapter_parity_contract.py` (to be created)
- `.github/workflows/ci.yml` (to be updated)
- `_bmad-output/test-artifacts/staging-mixed-channel-parity-evidence.yaml` (to be created, populated by staging test)

### Change Log

| Date | Change |
| --- | --- |
| 2026-05-10 | Story 9.3 created from epics-next-cycle.md; Story 9.1 and 9.2 marked done; ready for dev. |
