---
story_id: "saas-1.2a"
story_key: "saas-1-2a-email-password-signup-login-and-logout"
status: "done"
epic: saas-1
story: 2a
sprint_status_file: _bmad-output/implementation-artifacts/sprint-status-saas-v1.yaml
created: "2026-05-04"
updated: "2026-05-04"
depends_on:
  - saas-1-1-database-schema-bootstrap-and-tenant-model
---

# Story saas-1.2a: Email/Password Signup, Login, and Logout

## User Story

As a new customer,
I want to create an account, log in, and manage my session,
so that I can access my WhatsApp bot workspace without technical assistance.

## Acceptance Criteria

1. Given a visitor on the signup page, when they submit a valid email and password meeting strength requirements, then a new `user` record and linked `tenant` record are created atomically; the user is logged in and redirected to the post-signup flow (plan selection).

2. Passwords are stored using a strong hash+salt algorithm; plaintext passwords never appear in logs or database.

3. Login with correct credentials creates a secure server-side session cookie containing `user_id` and `tenant_id`.

4. Given a logged-in user, when they log out, then the server-side session is invalidated; subsequent requests without re-authentication are rejected and redirected to login.

5. CSRF protection is active on all auth POST routes; failed CSRF validation returns a 400 and does not process the form action.

6. Any page that accesses authenticated customer-plane data without `tenant_id` present in session returns 403 or redirects to login before data access.

## Tasks / Subtasks

- [x] Add auth module structure and blueprint wiring for `GET/POST /auth/signup`, `GET/POST /auth/login`, and `POST /auth/logout`
- [x] Implement auth service logic for signup, login, logout, password hashing, duplicate-email handling, and disabled-account checks
- [x] Create atomic signup provisioning flow: `tenants`, `users`, `bot_configs`, `usage_counters`, and `connection_states` in one database transaction
- [x] Add secure server-side session support and auth session helpers carrying `user_id`, `tenant_id`, and auth state
- [x] Reuse or extract CSRF token generation/validation so every auth POST route enforces 400-on-failure semantics without processing the action
- [x] Add an authenticated post-signup landing route or protected placeholder for `/billing/plans` so the redirect contract is executable before Story 2.1
- [x] Add auth-facing pages for signup/login flows while keeping the implementation additive to the existing app
- [x] Add focused tests covering signup success, duplicate email, invalid signup validation, login success, invalid credentials, disabled tenant rejection, logout invalidation, CSRF failure, and protected-route redirect behavior
- [x] Run the focused story test file and an adjacent SaaS regression slice

## Dev Notes

- Story source: `_bmad-output/planning-artifacts/epics-saas-v1.md` section `Story 1.2a: Email/Password Signup, Login, and Logout`.
- Previous story intelligence from `saas-1-1-database-schema-bootstrap-and-tenant-model.md`:
  - SaaS DB is optional at app startup, but when `DATABASE_URL` is present the SQLAlchemy extension is the canonical access path.
  - Existing schema already includes `tenants`, `users`, `bot_configs`, `usage_counters`, `connection_states`, and `is_admin` on `users`.
  - Tenant access rules are enforced by repository and service boundaries; do not bypass them for customer-plane reads.
- Architecture constraints from `architecture-whatsapp-ai-bot-saas-v1.md`:
  - Auth module responsibility: registration, login, logout, password reset.
  - Signup must provision tenant and dependent rows in one transaction.
  - Session must carry `user_id` and `tenant_id`.
  - Error contracts: `EMAIL_TAKEN` => 409, `VALIDATION_ERROR` => 422, `INVALID_CREDENTIALS` => 401, `ACCOUNT_DISABLED` => 403.
- Local codebase guardrails:
  - Existing CSRF helper lives in `app/views_dashboard.py`; prefer extracting or reusing the same token format instead of inventing a second incompatible scheme.
  - Existing app currently uses Flask's default session behavior, so this story must introduce server-side session storage rather than relying only on signed client cookies.
  - Keep existing webhook and dashboard flows working; auth changes should be additive.
  - Do not log raw passwords, password hashes, or submitted CSRF tokens.
- File structure guidance adapted to current repo conventions:
  - Preferred new paths: `app/auth/__init__.py`, `app/auth/routes.py`, `app/auth/service.py`, and optionally a shared auth/session helper module.
  - Register new blueprint from `app/__init__.py`.
  - Add templates under `app/templates/` only as needed for auth views.
- Testing guidance:
  - Use SQLite-backed test DB through the existing `SaaSDatabase` extension path.
  - Write the auth story test file first and prove it fails before implementation.
  - Validate logout by attempting a protected page after session invalidation.

## Dev Agent Record

### Debug Log

- Story created with implementation-ready context on 2026-05-04.
- Added focused failing auth contract tests before runtime edits.
- Implemented server-side session-backed auth routes and protected billing placeholder.
- Validated auth and adjacent SaaS schema coverage with targeted pytest runs.
- Applied sign-in loop regression hardening on 2026-05-18 for authenticated auth-page redirects and loop-safe `next` fallback behavior.

### Completion Notes

- Added `app/views_auth.py` and `app/services/auth_service.py` for signup/login/logout, session helpers, password hashing, and auth error contracts.
- Registered Flask-Session in the app factory and loaded filesystem-backed session configuration from app config.
- Implemented protected `/billing/plans` placeholder route to satisfy the post-signup and post-logout redirect contract.
- Chose minimal additive HTML responses for auth GET pages instead of introducing new templates in this story slice.
- Focused tests pass for the story contract and the adjacent SaaS schema bootstrap slice.
- Added regression protections so authenticated users are redirected away from `/auth/login` and `/auth/signup`, and loop-prone `next` values now fall back to the default post-login route.

## File List

- _bmad-output/implementation-artifacts/saas-1-2a-email-password-signup-login-and-logout.md
- _bmad-output/implementation-artifacts/sprint-status-saas-v1.yaml
- app/__init__.py
- app/config.py
- app/services/auth_service.py
- app/views_auth.py
- requirements.txt
- tests/test_saas_1_2a_auth_flow.py

### Review Findings

- [x] [Review][Patch] CSRF token not passed to template context — `signup_form()` and `login()` discard `_get_csrf_token()` return value; browser form submissions always receive a 400 CSRF error; AC 5 violated [app/views_auth.py:58,73]
- [x] [Review][Patch] `login_session` does not clear session before writing auth keys — session fixation attack possible [app/services/auth_service.py:login_session]
- [x] [Review][Patch] `authenticate_account` now handles orphaned tenant rows via `.one_or_none()` and returns `INVALID_CREDENTIALS` contract instead of surfacing ORM exceptions [app/services/auth_service.py:authenticate_account]
- [x] [Review][Patch] `SESSION_COOKIE_SECURE` default now derives from `APP_BASE_URL` scheme (`https://` => `True`) with explicit env override support [app/config.py]

### Change Log

- 2026-05-04: Story context created and marked ready-for-dev.
- 2026-05-04: Story moved to in-progress, auth contract tests added, and auth/session implementation completed.
- 2026-05-04: Story validated with targeted pytest coverage and moved to review.
- 2026-05-04: Code review completed — 2 patches applied (CSRF template var, session fixation fix); 2 items deferred. All patches verified with passing tests. Story marked done.
- 2026-05-18: Regression fix applied for sign-in redirect loops; added auth-route loop guards and authenticated auth-page redirect tests.
- 2026-05-18: Closed deferred auth risks by patching orphan-tenant login handling and secure-cookie defaults; added dedicated regression tests.
