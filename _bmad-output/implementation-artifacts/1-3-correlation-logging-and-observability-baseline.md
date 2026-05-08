---
story_id: "1.3"
story_key: "1-3-correlation-logging-and-observability-baseline"
status: "done"
epic: 1
story: 3
created: "2026-04-30"
depends_on:
  - "1.1 Startup Validation and Setup Gating"
  - "1.2 Webhook Verification and Signature Enforcement"
---

# Story 1.3: Correlation Logging and Observability Baseline

## User Story

As an operator,
I want consistent request tracing and lightweight health metrics,
so that I can diagnose failures and confirm bot status quickly.

## Acceptance Criteria

1. Each inbound webhook request is assigned a unique correlation ID that propagates through application logs and controlled error responses.
2. Logging sanitizes secrets, tokens, and masked PII in all normal and error paths.
3. The app exposes `/health` and JSON `/metrics` endpoints covering request counts, duplicate counts, error counts, and request durations.
4. Metrics and logs are safe to read even when setup is incomplete, and they do not expose sensitive values.
5. Operator-facing status components can rely on the health and metrics contracts without additional backend discovery work.

---

## Context and Constraints

### Why this story exists

- FR8 in the planning artifacts requires correlation-aware, sanitized observability across the inbound webhook path.
- Epic 1 treats observability as part of the secure runtime foundation, so this work must stay lightweight, centralized, and safe before later dashboard and release-gate stories build on it.
- The UX specification depends on stable health and metrics contracts for `/`, `/metrics`, `/logs`, and `/setup` without a second backend discovery layer.

### Current implementation baseline

- Correlation IDs are already bound in the app factory request lifecycle via `app/__init__.py` using `ensure_correlation_id()`, `get_correlation_id()`, and `clear_correlation_id()`.
- Log redaction is already centralized in `app/services/observability.py` through `SafeObservabilityFilter` and `sanitize_text()` and is wired in `app/config.py`.
- Public JSON observability endpoints already live in `app/views.py` as `/health` and `/metrics`.
- Runtime health state already lives in `app/services/health_check.py`, and metric collection already lives in `app/services/metrics.py`.
- Operator dashboard routes in `app/views_dashboard.py` and acceptance-oriented coverage in `tests/test_story_1_3.py` already depend on this baseline.

### Implementation stance

- Treat Story 1.3 as an alignment and hardening story around the existing observability seams, not a greenfield build.
- Reuse the app-factory hooks, logging filter, metrics collector, and health service already present in the codebase.
- Do not introduce a second correlation context mechanism, a parallel metrics service, or route-local redaction helpers.
- Keep `/health` and `/metrics` readable even when setup is incomplete, but never expose raw secrets, tokens, or full phone numbers.

---

## Developer Guardrails

### Required code paths

- Request correlation remains owned by the `before_request`, `after_request`, and `teardown_request` hooks in `app/__init__.py`.
- Logging sanitization remains owned by `SafeObservabilityFilter` in `app/services/observability.py` and is attached from `app/config.py`.
- Webhook request and error metrics remain owned by `MetricsCollector` in `app/services/metrics.py` and the request handling flow in `app/views.py`.
- Runtime health state remains owned by `get_bot_health()` and `set_last_error()` in `app/services/health_check.py`.
- Dashboard and operator pages continue to consume observability through the existing `/health`, `/metrics`, `/api/health`, and `/api/metrics` contracts rather than custom page-specific data sources.

### Correlation requirements

- Every inbound request must end the response cycle with `X-Request-ID` present, whether the request succeeds or fails.
- If a valid inbound request ID is supplied, preserve it after sanitizing to the allowed character set.
- If no inbound request ID is supplied, generate a UUID and use it consistently through the request lifecycle.
- Controlled error responses from signature validation and webhook verification must include the same `correlation_id` value returned in the response header.
- Request correlation must be cleared at teardown so values do not leak across requests.

### Logging and sanitization requirements

- Redact access tokens, app secrets, verify tokens, OpenAI keys, bearer credentials, and similar key-value patterns from all log output.
- Mask phone numbers rather than logging them raw; current masking convention is prefix plus ellipsis plus last four digits.
- Preserve enough log detail to diagnose failure reason, code path, and request correlation without exposing secret material.
- Keep sanitization centralized in the observability filter so message formatting and structured args receive the same redaction behavior.

### Metrics and endpoint requirements

- `/health` must stay lightweight and return the runtime contract from `get_bot_health()`.
- `/metrics` must stay JSON and expose counters plus duration totals, counts, and averages from `MetricsCollector.snapshot()`.
- Baseline counters must include request count, duplicate count, internal error count, and processed message count even before traffic arrives.
- Baseline durations must include `webhook.handle_message_seconds` even before traffic arrives.
- These observability endpoints must remain callable without operator-session state so monitors and release checks can use them directly.

### Existing reusable pieces

- Keep using `CORRELATION_ID_HEADER`, `ensure_correlation_id()`, `get_correlation_id()`, and `clear_correlation_id()` from `app/services/observability.py`.
- Keep using `SafeObservabilityFilter` from `app/config.py` instead of bespoke redaction at individual call sites.
- Keep using `get_metrics_collector()` and `Timer` from `app/services/metrics.py` for webhook timing and counters.
- Keep using `_error_response()` in `app/views.py` for correlation-aware error payloads where it already matches the route contract.

### Boundaries and non-goals

- Do not convert `/metrics` to Prometheus or another scrape format in this story; architecture explicitly leaves that as a later decision.
- Do not introduce external telemetry infrastructure, background exporters, or a database-backed metrics store.
- Do not move dashboard-only operator HTML into the public observability endpoints.
- Do not broaden this story into outbound retry/fallback instrumentation beyond what the current metrics seam already supports.

---

## Previous Story Intelligence

- Story 1.2 already established that webhook admission control and rejection paths must stay centralized and correlation-aware; Story 1.3 should extend that same correlation contract instead of inventing a second one.
- Story 1.2 explicitly treated `app/__init__.py`, `app/config.py`, `app/services/observability.py`, and `app/views.py` as the core foundation surfaces; keep that ownership consistent here.
- Story 1.2 also established that tests should be extended in focused existing modules when possible; for Story 1.3 the acceptance-oriented test anchor is `tests/test_story_1_3.py`.

---

## Git Intelligence Summary

- Recent visible history is shallow and not story-specific: the repository shows an initial commit plus merge commits and dependency fixes.
- The most useful implementation evidence for this story is the current working tree and acceptance tests, not historical commit sequencing.

---

## Implementation Tasks

- [x] Confirm the app factory binds correlation IDs before route logic, attaches `X-Request-ID` on responses, and clears correlation context on teardown. (AC: 1)
- [x] Confirm all existing rejection paths in webhook verification and signature validation return correlation-aware payloads without secret leakage. (AC: 1, 2, 4)
- [x] Confirm `SafeObservabilityFilter` redacts tokens, secrets, bearer credentials, and phone numbers across both `record.msg` and structured log args. (AC: 2, 4)
- [x] Confirm `/health` and `/metrics` expose the required JSON contracts and remain safe to call before setup is complete. (AC: 3, 4, 5)
- [x] Extend or tighten focused coverage in `tests/test_story_1_3.py` for any missing contract, redaction, or header-propagation cases. (AC: 1, 2, 3, 4, 5)

## Suggested Subtasks

- [x] Verify that an inbound `X-Request-ID` is reflected in both the response header and the controlled error payload.
- [x] Verify that generated request IDs appear on responses when the client does not provide one.
- [x] Verify that `sanitize_text()` handles mixed token, bearer, and phone-number content in a single log message.
- [x] Verify that zero-traffic metrics snapshots still include the baseline keys expected by the operator UI and release tests.
- [x] Verify that health and metrics endpoints work without operator access state and without complete runtime setup.

## Strict Implementation Order

1. Lock contract behavior first:
  - Confirm `X-Request-ID` is always present on responses.
  - Confirm controlled rejection payloads include `correlation_id` and stable `reason` values.
2. Lock sanitization behavior second:
  - Confirm token, secret, bearer, and phone masking rules in `sanitize_text()` and `SafeObservabilityFilter`.
3. Lock endpoint behavior third:
  - Confirm `/health` and `/metrics` are public, setup-safe, and return stable JSON contracts.
4. Lock regression coverage last:
  - Extend focused tests only in `tests/test_story_1_3.py` unless a concrete gap requires another module.

## AC to Test Matrix

| Acceptance Criterion | Required Evidence | Primary Test Target |
| --- | --- | --- |
| AC1 Correlation ID propagation | Response header and JSON `correlation_id` match | `Story13CorrelationIdTests`, `Story13SignatureErrorCorrelationTests` |
| AC2 Sanitized logs | Sensitive substrings absent, masked output present | `Story13LoggingSanitizationTests` |
| AC3 `/health` and `/metrics` baseline | Required keys exist in both responses | `Story13ObservabilityEndpointTests` |
| AC4 Setup-safe observability | Endpoints callable with incomplete setup, no secret leakage | Extend `tests/test_story_1_3.py` |
| AC5 Operator contract stability | Dashboard-consumed contracts unchanged | Extend `tests/test_story_1_3.py` and verify against `app/views_dashboard.py` |

## Hard Completion Gates

- `python -m unittest tests.test_story_1_3` passes with no failures.
- No new duplicate observability subsystem is introduced.
- No operator-session requirement is added to `/health` or `/metrics`.
- No raw token, secret, bearer value, or full phone number appears in logs from story test scenarios.
- Public endpoint contracts remain JSON-stable for operator and release-gate consumers.

---

## Files Most Likely to Change

- `app/__init__.py`
- `app/config.py`
- `app/services/observability.py`
- `app/services/metrics.py`
- `app/services/health_check.py`
- `app/views.py`
- `app/views_dashboard.py`
- `tests/test_story_1_3.py`

## Files to Read Before Editing

- `app/decorators/security.py`
- `app/services/message_log.py`
- `tests/test_story_1_1_and_1_2.py`
- `tests/test_release_gates.py`
- `_bmad-output/implementation-artifacts/1-2-webhook-verification-and-signature-enforcement.md`

---

## Testing Requirements

### Minimum validation command

Run the focused Story 1.3 test module first:

```bash
python -m unittest tests.test_story_1_3
```

### Coverage expectations

- Verification rejection generates a correlation ID when one is not provided.
- Verification rejection preserves an inbound correlation ID when one is provided.
- Signature rejection returns a stable `reason` and `correlation_id` and mirrors the value in `X-Request-ID`.
- `sanitize_text()` redacts credentials and masks phone numbers.
- `/health` returns `status`, `uptime_seconds`, and `last_error`.
- `/metrics` returns baseline counters and duration keys even before traffic exists.
- Public health and metrics access stays available without requiring operator-session state.

### Test design notes

- Prefer black-box route tests through `create_app()` when validating correlation header propagation and public endpoint contracts.
- Keep redaction assertions focused on absence of secret substrings plus presence of the masking pattern.
- Extend `tests/test_story_1_3.py` before creating additional Story 1.3-specific modules unless scope clearly exceeds that file.
- Reuse the full required env fixture pattern already established in the current Story 1.3 tests.

---

## Architecture Compliance Notes

- Architecture Decision 1 requires the app factory to own runtime assembly and request lifecycle hooks, so correlation binding must stay there rather than in route decorators or helpers.
- The architecture explicitly calls for lightweight structured logging with correlation IDs and in-process metrics; keep this story within that footprint.
- `/health` and `/metrics` are named architecture obligations and are already part of the operator experience contract; their response shapes are now depended on by dashboard routes and release-gate tests.
- In-process metrics reset on restart by design; do not hide or paper over that behavior inside Story 1.3.

---

## Implementation Risks to Avoid

- Accidentally leaving correlation IDs set across requests by skipping teardown cleanup.
- Redacting only the log message string while leaving secrets visible in structured logging args.
- Making `/health` or `/metrics` operator-gated, which would break monitoring and release validation.
- Returning observability payloads that differ between public endpoints and operator API endpoints without a documented contract reason.
- Logging full phone numbers, access tokens, or bearer headers while debugging correlation flow.

---

### Review Findings
_Code review date: 2026-04-30 | Layers: Blind Hunter, Edge Case Hunter, Acceptance Auditor_

#### decision-needed
_(none)_

#### patch

- [x] [Review][Patch] **[MEDIUM] `_PHONE_PATTERN` word-boundary loses `+` prefix and fails on embedded numbers** — `\b` matches *after* the `+`, so `\+?` in group 1 always captures zero `+` characters; `+923359999195` masks to `+923...9195` (country prefix leaked). The trailing `\b` also fails when the number is fused to a word char (e.g., `waid_15551234567_x`). Fix: replace `\b` anchors with negative-lookbehind/lookahead (`(?<!\w)` / `(?!\d)`) so the `+` is consumed and embedded numbers are caught. [`app/services/observability.py:22`]
- [x] [Review][Patch] **[MEDIUM] Four counter keys absent from `BASE_COUNTER_KEYS` — missing from `/metrics` baseline** — `webhook.blocked_config_invalid_total`, `webhook.status_updates_total`, `webhook.invalid_events_total`, and `webhook.json_decode_errors_total` are all incremented in `handle_message()` but not in `BASE_COUNTER_KEYS`. On a clean instance, these keys are absent from the `/metrics` snapshot, breaking dashboards or monitors that expect key presence rather than `.get()` with a default. Fix: add all four keys to `BASE_COUNTER_KEYS`. [`app/services/metrics.py:5`]
- [x] [Review][Patch] **[MEDIUM] `json.JSONDecodeError` except clause is unreachable dead code** — `request.get_json()` uses Flask's silent=True default, catching `JSONDecodeError` internally and returning `None`. The `except json.JSONDecodeError:` block at line ~177 of views.py never fires; malformed-JSON bodies silently route to the `invalid_events` branch (404) instead of 400. `webhook.json_decode_errors_total` is therefore never incremented even after adding it to BASE. Fix: call `request.get_json(silent=False)` or use `request.get_json(force=True)` and catch explicitly, or remove the dead branch and handle None body in the `invalid_event` path. [`app/views.py`]
- [x] [Review][Patch] **[LOW] No test for `X-Request-ID` on a successful 200 response (AC1 gap)** — All three existing correlation tests exercise rejection paths (403). AC1 says "every inbound request must end the response cycle with `X-Request-ID` present." A successful webhook POST returning 200 is untested for header propagation. [`tests/test_story_1_3.py`]
- [x] [Review][Patch] **[LOW] No test for `/health` or `/metrics` with incomplete setup (AC4 gap)** — `FULL_REQUIRED_ENV` in every test class supplies all required keys. There is no test calling `/health` or `/metrics` when setup is incomplete (e.g., missing `OPENAI_API_KEY` or `ACCESS_TOKEN`), leaving AC4 "safe to call before setup is complete" unverified. [`tests/test_story_1_3.py`]
- [x] [Review][Patch] **[LOW] Dead `_signature()` helper; valid-POST correlation path untested** — `Story13SignatureErrorCorrelationTests._signature()` is defined but never called. The only POST test uses a bare unsigned body, covering only the "missing signature" rejection. The correlation ID propagation through a *valid* or *invalid* signed request is never exercised, meaning a signature-bypass regression could go undetected. [`tests/test_story_1_3.py`]

#### defer

- [x] [Review][Defer] **Double-filter: `SafeObservabilityFilter` added to both root logger and each handler** — `configure_logging()` calls `root_logger.addFilter(safe_filter)` *and* `handler.addFilter(safe_filter)`, causing `sanitize_text` to run twice per record. Currently idempotent (no correctness impact), but inefficient and the handler-level list grows on repeated `configure_logging()` calls during tests. [`app/config.py:219-223`] — deferred, pre-existing design; correctness not impacted today
- [x] [Review][Defer] **Redundant `ensure_correlation_id` calls inside route handlers** — `handle_message()` (line 193) and `verify()` (line 201) each call `ensure_correlation_id` despite `before_request` already owning that responsibility. Benign (the function short-circuits if an ID exists) but violates the stated architecture ownership boundary. [`app/views.py:193,201`] — deferred, pre-existing baseline pattern; no functional impact
- [x] [Review][Defer] **Correlation ID not length-capped after character sanitization** — `set_correlation_id` strips disallowed chars but applies no maximum length, allowing a crafted header to inflate every log line for that request. Flask's ~16 KB header size limit partially mitigates. [`app/services/observability.py`] — deferred, not a story requirement; Flask header limit provides mitigation
- [x] [Review][Defer] **`_sanitize_arg` does not recurse into `set`/`frozenset`** — Secrets inside a set argument fall through `_sanitize_arg` unchanged and are emitted as `str(set)` by the formatter. No current callsite passes a set to logging. [`app/services/observability.py:36`] — deferred, theoretical; no current callsite triggers this
- [x] [Review][Defer] **Handlers registered after `configure_logging()` returns bypass the filter** — The handler loop is a point-in-time snapshot; Flask/werkzeug handlers added during blueprint registration may miss the filter. Root-logger-level filter guards the propagation path. [`app/config.py:211`] — deferred, root-logger filter covers propagation; full handler enumeration is a follow-on hardening task

---

## References

- Source requirements: `_bmad-output/planning-artifacts/epics.md` - Epic 1, Story 1.3, FR8, NFR1, NFR7
- Product context: `_bmad-output/planning-artifacts/prd.md` - FR8, NFR7, Staging Gate redaction audit, Risk R2, Risk R3
- Architecture constraints: `_bmad-output/planning-artifacts/architecture.md` - Primary Runtime Flow, Decision 1, Observability, Operator Experience Support
- UX dependency context: `_bmad-output/planning-artifacts/ux-design.md` - Dashboard data sources, Metrics Screen, Message Log Screen, Setup flow
- Previous story intelligence: `_bmad-output/implementation-artifacts/1-2-webhook-verification-and-signature-enforcement.md`
- Existing app factory lifecycle: `app/__init__.py`
- Existing logging configuration: `app/config.py`
- Existing observability utilities: `app/services/observability.py`
- Existing metrics service: `app/services/metrics.py`
- Existing health contract: `app/services/health_check.py`
- Existing webhook and public observability endpoints: `app/views.py`
- Existing operator consumers of the contract: `app/views_dashboard.py`
- Existing acceptance-oriented tests: `tests/test_story_1_3.py`

---

## Definition of Done

- [ ] Story 1.3 behavior is implemented through the existing app-factory, observability, metrics, and health-service seams.
- [ ] All Story 1.3 acceptance criteria are covered by focused automated tests.
- [ ] The focused Story 1.3 test module passes locally.
- [ ] `/health` and `/metrics` remain setup-safe, secret-safe, and stable for operator and monitoring consumers.
- [ ] No duplicate correlation, logging, or metrics subsystem is introduced.

## Dev Agent Record

### Agent Model Used

GPT-5.3-Codex (target for upcoming implementation)

### Debug Log References

- Story 1.3 started with 3 failing focused tests caused by dotenv provider bleed into test setup.
- `create_app()` calls `load_dotenv()`, and local `.env` contains `WHATSAPP_PROVIDER=evolution`; tests expecting Meta verification/signature rejection must pin provider explicitly.
- Focused tests were stabilized by setting `WHATSAPP_PROVIDER=meta` and using `patch.dict(..., clear=True)` in Story 1.3 test setup fixtures.

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.

### File List

- `_bmad-output/implementation-artifacts/1-3-correlation-logging-and-observability-baseline.md`