---
story_id: "saas-1.2b"
story_key: "saas-1-2b-password-reset-flow"
status: "done"
epic: saas-1
story: 2b
sprint_status_file: _bmad-output/implementation-artifacts/sprint-status-saas-v1.yaml
created: "2026-05-04"
updated: "2026-05-04"
depends_on:
  - saas-1-2a-email-password-signup-login-and-logout
---

# Story saas-1.2b: Password Reset Flow

## User Story

As a customer who has forgotten their password,
I want to request a password reset via email and use a single-use token to set a new password,
so that I can regain access to my account without technical assistance.

## Acceptance Criteria

1. Given a user who has forgotten their password, when they request a reset, then a short-lived, signed, single-use token is emailed; the token allows one password change and is invalidated after use or expiry.

2. The forgot-password endpoint always returns 200 (prevents email enumeration); token delivery failure is logged but does not surface to the user as an error.

3. Using an expired or already-used token returns an error and does not allow a password change.

## Tasks / Subtasks

- [x] Add auth routes for `GET/POST /auth/forgot-password` and `GET/POST /auth/reset-password`, keeping CSRF validation mandatory on all POST handlers
- [x] Implement password-reset service functions for token creation, hashed token persistence, expiry handling, single-use invalidation, and password update
- [x] Add dispatch hook support for reset-email delivery and ensure dispatch failures are logged while endpoint response remains success
- [x] Add auth templates for forgot-password and reset-password forms
- [x] Add focused tests for reset-token generation, enumeration-safe response behavior, dispatch-failure masking, successful password reset, single-use token invalidation, and expiry rejection
- [x] Extend auth regression coverage to assert CSRF enforcement on the new password-reset POST routes
- [x] Run targeted story tests and adjacent auth regression slice

## Dev Notes

- Story source: `_bmad-output/planning-artifacts/epics-saas-v1.md` section `Story 1.2b: Password Reset Flow`.
- Architecture alignment from `_bmad-output/planning-artifacts/architecture-whatsapp-ai-bot-saas-v1.md`:
  - `POST /auth/forgot-password` must always return 200 for enumeration resistance.
  - `POST /auth/reset-password` must return `INVALID_TOKEN` or `TOKEN_EXPIRED` on invalid token paths.
  - Reset-token data is persisted on `users.reset_token` and `users.reset_token_expires`.
- Previous story intelligence from `saas-1-2a-email-password-signup-login-and-logout.md`:
  - Reuse existing CSRF helper and auth session patterns.
  - Keep implementation additive in `app/views_auth.py` and `app/services/auth_service.py`.
- Security guardrails:
  - Tokens are stored hashed (`sha256`) and cleared on successful reset or expiry detection.
  - Password policy is reused from signup to avoid weak replacement credentials.

## Dev Agent Record

### Agent Model Used

GPT-5.3-Codex

### Debug Log

- Story context created and status set to ready-for-dev.
- Implemented password-reset routes and service support with single-use token semantics.
- Added template views and comprehensive story tests, then extended auth CSRF regression coverage.

### Completion Notes

- Added password-reset domain logic in `auth_service` for request and reset execution.
- Added new auth endpoints and dispatch hook behavior in `views_auth` without breaking existing auth contracts.
- Added dedicated auth reset templates and validated flow with focused tests.
- Story implementation satisfies all listed acceptance criteria and is ready for code review.

## File List

- _bmad-output/implementation-artifacts/saas-1-2b-password-reset-flow.md
- _bmad-output/implementation-artifacts/sprint-status-saas-v1.yaml
- app/config.py
- app/services/auth_service.py
- app/views_auth.py
- app/templates/auth_forgot_password.html
- app/templates/auth_reset_password.html
- tests/test_saas_1_2a_auth_flow.py
- tests/test_saas_1_2b_password_reset_flow.py

### Change Log

- 2026-05-04: Story context created and marked ready-for-dev.
- 2026-05-04: Story moved to in-progress and password-reset implementation completed with dedicated tests.
- 2026-05-04: Story validated and moved to review.
- 2026-05-04: Code review completed. 2 patches applied, 2 findings deferred. Story marked done.

### Review Findings

- [x] [Review][Patch] EHLO missing in non-TLS SMTP branch [app/utils/email.py ~line 93] — Fixed: added `server.ehlo()` before `server.login()` in the non-TLS path to satisfy RFC 5321 and production SMTP server requirements.
- [x] [Review][Patch] Misleading PASSWORD_RESET_EMAIL_DISPATCHED log when no dispatch wired [app/views_auth.py ~line 131] — Fixed: renamed log to `PASSWORD_RESET_EMAIL_SKIPPED_NO_DISPATCH_CONFIGURED`.
- [x] [Review][Defer] Port 465 / SMTP_SSL not supported [app/utils/email.py] — deferred, pre-existing config concern; STARTTLS on port 587 is the target deployment pattern, implicit TLS (port 465) is out of story scope.
- [x] [Review][Defer] No rate limiting on /auth/forgot-password — deferred, pre-existing; not in story ACs, belongs in a hardening epic.
