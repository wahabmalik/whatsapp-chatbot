---
story_id: "1.2"
story_key: "1-2-webhook-verification-and-signature-enforcement"
status: "done"
epic: 1
story: 2
created: "2026-04-28"
completed: "2026-04-30"
depends_on:
  - "1.1 Startup Validation and Setup Gating"
---

# Story 1.2: Webhook Verification and Signature Enforcement

## User Story

As a platform owner,
I want webhook verification and inbound signature enforcement handled centrally,
so that only authentic Meta requests reach message-processing code.

## Acceptance Criteria

1. `GET /webhook` returns `hub.challenge` with 200 only when `hub.mode=subscribe` and `hub.verify_token` matches the configured token.
2. Invalid, missing, or mismatched verification input returns 403 without leaking secret material.
3. All `POST /webhook` traffic is guarded by HMAC-SHA256 signature validation before request parsing.
4. Signature validation also enforces configured timestamp skew and replay-window checks before business logic executes.
5. Rejection paths log the correlation ID and reason code and do not invoke downstream services.

---

## Context and Constraints

### Why this story exists

- FR1 and FR2 in the planning artifacts make webhook authenticity a release-blocking requirement.
- NFR4 requires 100% validation coverage for inbound POST traffic with no bypass path at deploy.
- Epic 1 positions this work as part of the secure runtime foundation, so the implementation must stay centralized and fail closed.

### Current implementation baseline

- `GET /webhook` verification already lives in `app/views.py` via `verify()` and `webhook_get()`.
- `POST /webhook` is already wrapped by `@signature_required` in `app/views.py`, and the decorator lives in `app/decorators/security.py`.
- Correlation IDs are already created and attached in the app factory and observability layer via `app/__init__.py` and `app/services/observability.py`.
- Replay protection state is already expected to live behind the app-scoped expiring-store seam in `app/services/expiring_store.py`.
- `tests/test_story_1_1_and_1_2.py` already contains Story 1.2 acceptance-oriented coverage and should be extended, not replaced.

### Implementation stance

- Treat this as a hardening and alignment story, not a greenfield build.
- Reuse the existing route, decorator, observability, and expiring-store seams.
- Do not introduce a second webhook route, duplicate correlation ID helper, or route-local replay cache.
- Keep all rejection responses fail-closed with HTTP 403 and structured JSON payloads where the current route style already uses them.

---

## Developer Guardrails

### Required code paths

- `GET /webhook` logic remains owned by `verify()` in `app/views.py`.
- `POST /webhook` admission control remains owned by `signature_required()` in `app/decorators/security.py`.
- Request correlation continues to use `CORRELATION_ID_HEADER`, `ensure_correlation_id()`, and the app factory request hooks in `app/__init__.py`.
- Replay state continues to use `create_expiring_store()` with an app extension, not a module-global mutable structure for app-context requests.

### Security and behavior requirements

- Accept verification only when both of these are true:
  - `hub.mode == "subscribe"`
  - `hub.verify_token == current_app.config["VERIFY_TOKEN"]`
- Return 403 for all other GET verification inputs, including missing mode, missing token, wrong mode, and token mismatch.
- For POST requests, parse `X-Hub-Signature-256` only when it starts with `sha256=`.
- Compute the expected HMAC-SHA256 from the raw request body using `APP_SECRET` and compare with `hmac.compare_digest`.
- Enforce timestamp freshness using `SIGNATURE_MAX_SKEW_SECONDS`.
- Enforce replay protection using `SIGNATURE_REPLAY_WINDOW_SECONDS` and the expiring-store seam.
- Validation must happen before webhook JSON parsing or downstream message handling.
- Rejections must include a stable machine-readable reason value and the request correlation ID.
- Logs must never include `VERIFY_TOKEN`, `APP_SECRET`, raw bearer tokens, or unmasked PII.

### Existing reusable pieces

- Use `_error_response()` in `app/views.py` for verification failures where it fits the route contract.
- Keep using `validate_signature()`, `_is_timestamp_valid()`, `_check_and_store_replay()`, and `_parse_signature_header()` in `app/decorators/security.py` unless there is a specific defect to correct.
- Keep replay storage behind `extension_key="signature_replay_store"` and `namespace="signature_replay"`.
- Preserve the current app-extension lifecycle so teardown can close resource-owning stores.

### Boundaries and non-goals

- Do not implement inbound payload normalization here; that belongs to Story 2.1.
- Do not add outbound retry/fallback logic here; that belongs to Story 2.3.
- Do not move webhook routes out of the existing blueprint unless a blocking defect makes the current location unworkable.
- Do not add external infrastructure or a new persistence dependency for replay protection.

---

## Implementation Tasks

- [x] Confirm GET verification behavior matches the acceptance criteria in `app/views.py`. (AC: 1, 2)
- [x] Confirm POST signature validation blocks entry to `handle_message()` on missing, malformed, invalid, stale, or replayed signatures. (AC: 3, 4, 5)
- [x] Verify all rejection responses include `correlation_id` and a stable `reason` field and do not leak secrets. (AC: 2, 5)
- [x] Keep request-admission logic centralized in `app/decorators/security.py` and avoid route-local security checks in `app/views.py`. (AC: 3, 4, 5)
- [x] Extend or tighten focused tests in `tests/test_story_1_1_and_1_2.py` for any missing negative-path or non-leakage cases. (AC: 1, 2, 3, 4, 5)

## Suggested Subtasks

- [x] Review whether `request.data.decode("utf-8")` is the correct canonical payload source for signature comparison under the current Flask request usage.
- [x] Verify replay protection uses the configured time window and clears predictably in tests.
- [x] Verify a rejected POST never reaches `process_whatsapp_message()` or any other downstream service.
- [x] Verify the response body for GET and POST rejection paths stays structured and stable for tests.
- [x] Add or update test assertions for `correlation_id` presence and absence of leaked token values.

---

## Files Most Likely to Change

- `app/views.py`
- `app/decorators/security.py`
- `tests/test_story_1_1_and_1_2.py`

## Files to Read Before Editing

- `app/__init__.py`
- `app/config.py`
- `app/services/observability.py`
- `app/services/expiring_store.py`
- `README.md` (Webhook security background)

---

## Testing Requirements

### Minimum validation command

Run the focused Story 1.2 test module first:

```bash
python -m unittest tests.test_story_1_1_and_1_2
```

### Coverage expectations

- Positive GET verification path returns the challenge and 200.
- Negative GET paths cover wrong mode, missing params, and token mismatch.
- POST rejects missing signature header.
- POST rejects malformed signature header.
- POST rejects invalid HMAC.
- POST rejects stale timestamp according to configured skew.
- POST rejects replayed signature according to configured replay window.
- POST with valid signature is admitted past the decorator.
- Rejection responses include `correlation_id` and a stable `reason` code.
- Rejection payloads and logs do not expose configured secrets.

### Test design notes

- Prefer patching `process_whatsapp_message()` or `is_valid_whatsapp_message()` to prove admission control behavior without invoking the full downstream pipeline.
- Clear replay state between tests with `clear_signature_replay_cache()`.
- Keep tests deterministic by patching time where timestamp skew matters.
- Extend the existing Story 1.1/1.2 test file instead of scattering this story across multiple new test modules unless the file becomes unmanageably large.

---

## Architecture Compliance Notes

- App factory ownership matters here: request hooks in `app/__init__.py` already attach and clear correlation context, so the story should not invent a second correlation propagation path.
- The architecture requires app-scoped extensions for reliability-sensitive state. Replay protection must continue to sit behind `create_expiring_store()` rather than process-global state during normal app execution.
- Resource-owning stores must remain closable through app teardown. Any new storage behavior must preserve the `close()` lifecycle contract.
- Configuration-driven rollout is already defined in `app/config.py`. If behavior changes require new validation, keep it there rather than route-local parsing.

---

## Implementation Risks to Avoid

- Accidentally validating a transformed payload instead of the raw body bytes used to generate the Meta signature.
- Logging the supplied verify token, secret, or full signed header during rejection debugging.
- Allowing timestamp or replay checks to run after business logic admission.
- Replacing the existing decorator with ad hoc inline checks in the route handler.
- Introducing bypass behavior when `APP_SECRET` or `VERIFY_TOKEN` is missing instead of failing closed.

---

## References

- Source requirements: `_bmad-output/planning-artifacts/epics.md` - Epic 1, Story 1.2, FR1, FR2, NFR4
- Product context: `_bmad-output/planning-artifacts/prd.md` - FR1, FR2, Phase 1 Foundation, Risk R2
- Architecture constraints: `_bmad-output/planning-artifacts/architecture.md` - Primary Runtime Flow, Inbound Edge, Decision 1, Decision 3, Configuration Contract
- UX/setup dependency context: `_bmad-output/planning-artifacts/ux-design.md` - Setup flow verification test expectations
- Existing implementation: `app/views.py`
- Existing security decorator: `app/decorators/security.py`
- App lifecycle and correlation header handling: `app/__init__.py`
- Observability redaction rules: `app/services/observability.py`
- Replay/idempotency store seam: `app/services/expiring_store.py`
- Existing acceptance-oriented tests: `tests/test_story_1_1_and_1_2.py`
- Meta webhook background already captured in repo docs: `README.md` - Step 4: Understanding Webhook Security

---

## Definition of Done

- [x] Story 1.2 behavior is implemented in the existing webhook route and signature decorator code paths.
- [x] All Story 1.2 acceptance criteria are covered by focused automated tests.
- [x] The focused Story 1.2 test module passes locally.

---

## Dev Agent Record

### File List

- `app/config.py` — Added `from __future__ import annotations` to fix Python 3.9 incompatibility with `str | None` union type syntax (blocked all test imports).
- `tests/test_story_1_1_and_1_2.py` — Added 4 new test cases to `WebhookSignatureEnforcementTests`: malformed signature prefix, correlation_id + reason in POST rejection, APP_SECRET non-leakage in POST rejection, correlation_id + reason in GET rejection.

### Change Log

| Date | Change | Files |
|------|--------|-------|
| 2026-04-30 | Add `from __future__ import annotations` for Python 3.9 compat | `app/config.py` |
| 2026-04-30 | Add 4 negative-path/non-leakage test cases (AC 2, 3, 5) | `tests/test_story_1_1_and_1_2.py` |

### Completion Notes

**Implementation audit:** The existing implementation already satisfies all acceptance criteria. `app/views.py::verify()` correctly handles all GET verification paths (AC1, AC2). `app/decorators/security.py::signature_required` correctly guards all POST traffic with HMAC-SHA256 (AC3), timestamp skew enforcement (AC4), replay window enforcement (AC4), and structured 403 rejections with `correlation_id` and `reason` fields that exclude secrets (AC5). No bypass paths exist. Downstream services are unreachable on rejection.

**Root cause of test failures:** `app/config.py` used `str | None` union type syntax (PEP 604) which requires Python 3.10+ at runtime. The runtime is Python 3.9.6. Adding `from __future__ import annotations` makes annotation evaluation lazy, fixing the import-time TypeError. This was the sole blocker preventing all 31 pre-existing test cases from executing.

**New tests added (4):**
- `test_post_webhook_rejects_malformed_signature_prefix` — header present but prefix not `sha256=`
- `test_rejection_response_includes_correlation_id_and_reason` — POST 403 body has `correlation_id` and `reason`
- `test_rejection_payload_does_not_leak_app_secret` — POST 403 body does not contain `APP_SECRET` value
- `test_get_rejection_response_includes_correlation_id_and_reason` — GET 403 body has `correlation_id` and `reason`

**Test results (focused suite):** 35/35 passed (`python -m unittest tests.test_story_1_1_and_1_2`)

**Pre-existing failures in other suites:** The `test_release_gates.py` and `test_story_1_3.py` files contain pre-existing bugs now exposed by the config.py import fix: both use `create_app()` which calls `load_dotenv()`, loading `WHATSAPP_PROVIDER=evolution` from the `.env` file into `os.environ` without the caller patching it to "meta". This causes webhook tests expecting Meta-mode behavior to receive evolution-mode responses. These failures predate Story 1.2 and belong to the scope of Story 1.3 and the release-gate stories respectively. `EVOLUTION_INSTANCE_NAME` KeyError errors in `test_release_gates.py` are similarly pre-existing.

### Debug Log

- Python 3.9.6 does not support `str | None` union-type syntax in function signatures evaluated at import time. Fixed with `from __future__ import annotations` in `app/config.py`.
- `request.data.decode("utf-8")` confirmed correct: Flask's `request.data` holds the raw body bytes; this is the exact payload that Meta signs.
- [ ] Rejection paths are fail-closed, correlation-aware, and secret-safe.
- [ ] No duplicate security mechanism or alternate webhook admission path is introduced.

## Dev Agent Record

### Agent Model Used

GPT-5.4

### Debug Log References

- No sprint-status file was present, so no story status synchronization was applied.
- No prior Story 1.1 implementation artifact was present to inherit notes from.
- Recent git history could not be retrieved through the terminal because local PowerShell profile execution is blocked.

### Completion Notes List

- Story created from current epic, PRD, architecture, UX, and live code-path analysis.
- Story scope is aligned to the existing Flask webhook blueprint and security decorator instead of a greenfield design.

### File List

- `_bmad-output/implementation-artifacts/1-2-webhook-verification-and-signature-enforcement.md`