---
story_id: "1.1"
story_key: "1-1-startup-validation-and-setup-gating"
status: "done"
epic: 1
story: 1
created: "2026-04-28"
updated: "2026-04-30"
depends_on: []
---

# Story 1.1: Startup Validation and Setup Gating

## User Story

As an operator,
I want the app to validate required configuration and surface setup status clearly,
so that I can fix startup issues before the bot accepts traffic.

## Acceptance Criteria

1. On app startup, all required environment variables are checked for presence, non-empty value, and required format.
2. Startup logging reports per-variable readiness without exposing secrets, tokens, phone numbers, or API keys.
3. Missing or invalid runtime configuration blocks webhook processing but still allows the setup experience to render so operators can complete onboarding.
4. /setup renders live pass/fail status for the required keys defined in the UX specification.
5. A setup verification action returns structured success or actionable error details instead of an unhandled stack trace.

## Tasks / Subtasks

- [x] Implement startup configuration validation for required environment keys and format checks.
- [x] Ensure startup logging remains sanitized and does not expose sensitive values.
- [x] Keep setup experience reachable when configuration is incomplete.
- [x] Implement /setup pass/fail rendering for required setup keys.
- [x] Implement /setup/verify structured success and structured error responses.
- [x] Add and run automated tests for Story 1.1 acceptance criteria.

## Dev Notes

- Startup validation logic exists in app/config.py via validate_config() and REQUIRED_CONFIG_KEYS.
- App startup stores config errors in app.extensions["config_validation_errors"] and does not crash when configuration is incomplete.
- Setup gating and verification endpoints are in app/views_dashboard.py:
  - /setup renders live key presence state.
  - /setup/verify returns JSON {ok, message, missing} when keys are missing.
- Sanitized logging path is configured with SafeObservabilityFilter in app/config.py.

## Dev Agent Record

### Debug Log

- Loaded planning artifacts for Epic 1 and Story 1.1 context.
- Verified existing implementation paths in app/__init__.py, app/config.py, and app/views_dashboard.py.
- Executed focused test suite:
  - c:/Users/wahab/OneDrive/Documents/GitHub/python-whatsapp-bot/.venv/Scripts/python.exe -m pytest tests/test_story_1_1_and_1_2.py -q
  - Result: 22 passed.
- Implemented review fixes for None-valued required config handling in startup validation and setup readiness checks.
- Added explicit webhook processing block for invalid startup configuration with structured 503 config_invalid response.
- Added startup per-variable readiness logging via CONFIG_READINESS key/value entries without secret values.
- Re-ran focused test suite after updates:
  - c:/Users/wahab/OneDrive/Documents/GitHub/python-whatsapp-bot/.venv/Scripts/python.exe -m pytest tests/test_story_1_1_and_1_2.py -q
  - Result: 31 passed.

### Completion Notes

- Corrected false-positive config presence checks caused by str(None) truthiness and reused a shared is_config_value_set helper across validation and setup.
- Webhook POST now short-circuits with config_invalid while setup routes remain reachable for remediation.
- Startup now logs per-required-key readiness in a sanitized form for operator diagnostics.
- Expanded tests now cover None-path missing config detection, setup verify behavior with truly missing values, webhook block on invalid startup config, and readiness logging expectations.

## File List

- _bmad-output/implementation-artifacts/1-1-startup-validation-and-setup-gating.md
- app/__init__.py
- app/config.py
- app/views.py
- app/views_dashboard.py
- tests/test_story_1_1_and_1_2.py

### Review Findings

- [x] [Review][Patch] SECRET_KEY hardcoded fallback allows operator session forgery during setup [app/config.py: load_configurations]
- [x] [Review][Patch] Config validation error details exposed in 503 webhook response body [app/views.py: handle_message]
- [x] [Review][Defer] Concurrent .env writes in _set_env_value — no file locking; race possible with multiple workers [app/views_dashboard.py: _set_env_value] — deferred, pre-existing
- [x] [Review][Defer] Extension teardown does not catch close() exceptions — remaining extensions left unclosed if one raises [app/__init__.py: _cleanup_extension_resources] — deferred, pre-existing
- [x] [Review][Defer] normalize_provider silently maps unknown WHATSAPP_PROVIDER values to meta — no validation error emitted [app/config.py: validate_config] — deferred, pre-existing

## Change Log

- 2026-04-28: Created story artifact for 1.1 and recorded validation evidence; set status to review.
- 2026-04-30: Addressed Story 1.1 review findings (None-valued config checks, webhook invalid-config blocking, startup readiness logging) and expanded focused regression tests.
- 2026-04-30: Code review complete. 2 patches applied (SECRET_KEY fallback → ephemeral token; removed config key names from 503 body). 3 deferred. Status set to done.
