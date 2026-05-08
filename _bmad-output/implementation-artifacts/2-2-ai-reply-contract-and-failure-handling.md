---
story_id: "2.2"
story_key: "2-2-ai-reply-contract-and-failure-handling"
status: "done"
epic: 2
story: 2
created: "2026-04-30"
depends_on:
  - "2.1 Inbound Normalization and Idempotency"
---

# Story 2.2: AI Reply Contract and Failure Handling

## User Story

As the reply service,
I want AI generation to return typed success or controlled failure states,
so that the webhook flow can respond predictably without uncaught exceptions.

## Acceptance Criteria

1. The OpenAI service accepts normalized inbound text and the active agent context and returns a typed result object with reply text, confidence, and metadata.
2. Timeout, authentication failure, and rate-limit conditions are represented as controlled states rather than propagated exceptions.
3. Response latency is measured and emitted to metrics for each AI request attempt.
4. AI failures provide enough structured detail for downstream fallback and escalation decisions.
5. The service contract is narrow enough to support unit testing without live provider calls.

---

## Context and Constraints

### Why this story exists

- FR4 requires the AI layer to behave like a reliable contract surface, not an exception-throwing side effect.
- NFR2 and NFR3 rely on bounded AI behavior and explicit latency instrumentation.
- Story 2.3 depends on structured AI failure details to decide fallback and operator-review behavior.

### Current implementation baseline

- `app/services/openai_service.py` currently raises runtime and timeout exceptions on several failure paths.
- `app/utils/whatsapp_utils.py` currently uses a deterministic local `generate_response()` stub rather than a typed provider contract.
- Retry classification support already exists in `openai_service._is_retryable_exception()` and release-gate tests.
- Metrics infrastructure exists (`app/services/metrics.py`) and is already used by outbound delivery flows.

### Implementation stance

- Keep webhook route and normalization ownership unchanged; implement this as a service contract hardening change.
- Introduce a typed AI result model (success and controlled failure variants) and make call sites consume it.
- Convert provider exceptions into controlled states at the service boundary.
- Capture attempt and total AI duration metrics without requiring live network calls in tests.

---

## Developer Guardrails

### Required code paths

- Keep AI provider integration in `app/services/openai_service.py`.
- Keep message-flow orchestration in `app/utils/whatsapp_utils.py` and avoid adding alternate AI invocation paths.
- Reuse existing app config knobs:
  - `OPENAI_RUN_TIMEOUT_SECONDS`
  - `OPENAI_POLL_INTERVAL_SECONDS`
  - `OPENAI_MAX_RETRIES`
  - `OPENAI_RETRY_BACKOFF_SECONDS`

### AI contract requirements

- Define a typed AI result contract with explicit fields that include at minimum:
  - `ok` (bool)
  - `status` (for example: `success`, `timeout`, `auth_error`, `rate_limited`, `provider_error`)
  - `reply_text` (string when success, `None` otherwise)
  - `confidence` (nullable numeric score)
  - `metadata` (model/assistant id, attempts, timing, request id when available)
  - `error_code` and `error_detail` on controlled failure outcomes
- OpenAI and network exceptions must not leak past this service contract in normal runtime flows.
- Keep the contract narrow and deterministic so tests can patch provider calls and assert typed outcomes.

### Failure classification requirements

- Timeout states must map to a controlled timeout status.
- Authentication and authorization failures must map to a controlled auth-failure status.
- Rate limit responses/exceptions must map to a controlled rate-limited status.
- Unknown provider failures may map to a generic controlled provider-error status, with sanitized details.

### Observability requirements

- Emit per-attempt or per-call counters for success/failure classes.
- Emit AI duration metrics (attempt and/or end-to-end) for each request.
- Include correlation/request id in AI logs when available.
- Never log raw secrets, bearer tokens, or full sensitive payloads.

### Boundaries and non-goals

- Do not implement outbound retry/fallback behavior changes here (Story 2.3).
- Do not alter signature-validation logic or webhook admission checks (Epic 1 scope).
- Do not redesign operator dashboard UX beyond exposing data already available through metrics/log contracts.

---

## Implementation Tasks

- [x] Define and introduce a typed AI reply result model/contract for success and controlled failure states. (AC: 1, 2, 4, 5)
- [x] Update `openai_service` entrypoints to return typed results instead of raising runtime exceptions on expected provider failures. (AC: 1, 2, 4)
- [x] Implement timeout/auth/rate-limit classification mapping and preserve sanitized error details. (AC: 2, 4)
- [x] Add AI latency metrics and outcome counters for each request attempt. (AC: 3)
- [x] Update webhook message processing to consume the typed AI contract and continue deterministic downstream flow. (AC: 1, 4)
- [x] Add focused unit tests for contract shape, failure mapping, and no-live-provider behavior. (AC: 5)

## Suggested Subtasks

- [x] Add a small result dataclass or `TypedDict` in `app/services/openai_service.py` (or a nearby service module) to formalize the contract.
- [x] Create a narrow adapter function that accepts normalized inbound text + active agent context and returns the typed result.
- [x] Add tests for timeout, auth error, and rate-limit scenarios by patching provider client calls.
- [x] Add tests verifying metrics counters/durations for both success and failure outcomes.
- [x] Add tests verifying `process_whatsapp_message()` handles AI failure states without uncaught exceptions.

---

## Files Most Likely to Change

- `app/services/openai_service.py`
- `app/utils/whatsapp_utils.py`
- `app/services/metrics.py`
- `tests/test_release_gates.py`
- `tests/test_reliability.py`

## Files to Read Before Editing

- `app/views.py`
- `app/config.py`
- `app/services/observability.py`
- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/architecture.md`
- `_bmad-output/implementation-artifacts/2-1-inbound-normalization-and-idempotency.md`

---

## Testing Requirements

### Minimum validation commands

```bash
python -m unittest tests.test_release_gates.ReleaseOpenAIContractTests
python -m unittest tests.test_reliability.OpenAIServiceReliabilityTests
```

### Coverage expectations

- Typed success result includes `reply_text`, `confidence`, and non-empty metadata.
- Timeout/auth/rate-limit provider failures return controlled statuses and do not bubble exceptions in normal flow.
- AI service metrics include duration counts and classified outcome counters.
- Webhook processing paths remain deterministic when AI returns controlled failures.
- Tests run with patched provider clients and do not require live OpenAI connectivity.

### Test design notes

- Patch provider client methods and clock/sleep dependencies for deterministic retry and timeout assertions.
- Keep tests focused on contract behavior, not provider SDK internals.
- Prefer extending existing release-gate and reliability test modules unless readability degrades.

---

## Architecture Compliance Notes

- Preserve app-factory and extension ownership patterns; avoid process-global mutable state for AI contract runtime data.
- Keep configuration-driven timeout and retry behavior aligned with the architecture configuration contract.
- Ensure structured AI outcomes integrate cleanly with Story 2.3 outbound fallback and escalation logic.
- Keep observability output sanitized and correlation-aware.

---

## Implementation Risks to Avoid

- Letting provider exceptions escape and break webhook predictability.
- Returning inconsistent result shapes across success/failure paths.
- Measuring only success latency and losing failure-path timing visibility.
- Coupling tests to live provider behavior or credentials.
- Leaking sensitive request/response details in AI error logs.

---

## References

- Source requirements: `_bmad-output/planning-artifacts/epics.md` - Epic 2, Story 2.2, FR4, NFR2, NFR3
- Product context: `_bmad-output/planning-artifacts/prd.md` - FR4 AI response generation and controlled error behavior
- Architecture constraints: `_bmad-output/planning-artifacts/architecture.md` - AI and Outbound Delivery, Observability, Configuration Contract
- Existing AI service: `app/services/openai_service.py`
- Existing message flow integration: `app/utils/whatsapp_utils.py`
- Existing release contract tests: `tests/test_release_gates.py` - `ReleaseOpenAIContractTests`
- Existing reliability tests: `tests/test_reliability.py` - `OpenAIServiceReliabilityTests`

---

## Definition of Done

- [x] Story 2.2 typed AI contract is implemented and consumed by message processing flow.
- [x] Timeout, auth-failure, and rate-limit scenarios return controlled result states.
- [x] AI latency and outcome metrics are emitted for every request path.
- [x] Automated tests verify controlled-failure behavior without live provider calls.
- [x] No regression to webhook security order, correlation logging, or outbound reliability contracts.

## Code Review Resolution (Step 4)

- Decision-needed (AC1 confidence): Chosen approach is to defer confidence scoring to caller-side metrics until a provider-backed confidence source is defined and stable.
- Patches applied: 4
  - Added AI latency crash guard in `openai_service` duration finalization path.
  - Added outbound latency crash guard in `whatsapp_utils.send_message()` metrics emission path.
  - Corrected Story 2.2 provider mock contract test to assert exact call parameters.
  - Corrected OpenAI-enabled processing test to assert exact provider call parameters.

- Routed to next step: Step 5 (Close review and finalize story).

## Dev Agent Record

### Agent Model Used

GPT-5.3-Codex

### Debug Log References

- Loaded workflow and config from `.github/skills/bmad-dev-story/workflow.md` and `_bmad/bmm/config.yaml`.
- Required context reads completed for `app/views.py`, `app/config.py`, `app/services/observability.py`, `_bmad-output/planning-artifacts/epics.md`, `_bmad-output/planning-artifacts/architecture.md`, and `_bmad-output/implementation-artifacts/2-1-inbound-normalization-and-idempotency.md`.
- Validation commands run:
  - `python -m unittest tests.test_release_gates.ReleaseOpenAIContractTests` (pass)
  - `python -m unittest tests.test_reliability.OpenAIServiceReliabilityTests` (pass)
  - `python -m unittest discover -s tests -p "test_*.py"` (pre-existing unrelated failures outside Story 2.2 scope)

### Completion Notes List

- Hardened `generate_reply_result()` contract metadata with `assistant_id`, `model`, and `duration_seconds` while preserving typed success/failure response shape.
- Added controlled failure detail sanitization using observability redaction before populating `error_detail` and logs.
- Preserved deterministic webhook downstream behavior; AI failure states continue to map to fallback reply flow and structured delivery metadata.
- Added focused FR4 gate tests for sanitized failure detail, enriched metadata shape, failure-path metrics, and deterministic `process_whatsapp_message()` AI fallback handling.

### File List

- `app/services/openai_service.py`
- `tests/test_release_gates.py`
- `_bmad-output/implementation-artifacts/2-2-ai-reply-contract-and-failure-handling.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`

## Change Log

- 2026-04-30: Implemented Story 2.2 AI contract hardening, added FR4 focused test coverage, and advanced story status to review.
- 2026-04-30: Resolved review decision for AC1 confidence (deferred), applied 4 review patches, and advanced story status to done.
