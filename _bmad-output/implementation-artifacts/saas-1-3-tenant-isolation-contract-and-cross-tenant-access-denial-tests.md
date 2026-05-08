---
story_id: "saas-1.3"
story_key: "saas-1-3-tenant-isolation-contract-and-cross-tenant-access-denial-tests"
status: "done"
epic: saas-1
story: "3"
sprint_status_file: _bmad-output/implementation-artifacts/sprint-status-saas-v1.yaml
created: "2026-05-04"
updated: "2026-05-05"
depends_on:
  - saas-1-1-database-schema-bootstrap-and-tenant-model
  - saas-1-2a-email-password-signup-login-and-logout
  - saas-1-2b-password-reset-flow
---

# Story saas-1.3: Tenant-Isolation Contract and Cross-Tenant Access-Denial Tests

## User Story

As a platform owner,
I want automated tests that verify every customer-plane access path denies cross-tenant access,
so that multi-tenant data safety is continuously enforced by code and CI.

## Acceptance Criteria

1. Given two tenants (A and B), when an authenticated request from tenant A attempts to read data owned by tenant B, the result is denied (403/404) and never leaks tenant B data.

2. The repository-layer test suite covers cross-tenant access rules for tenant settings, subscription state, usage counters, and WhatsApp session records.

3. Unscoped repository access is disallowed by contract; missing/blank tenant context fails fast and is tested.

4. Any endpoint path that reads tenant data uses tenant-scoped repository access rather than raw unscoped SQL in route handlers.

5. The isolation tests run in CI via pytest and block merge on failure.

## Tasks / Subtasks

- [x] Add concrete tenant-scoped repository abstractions for key tenant-bound entities (AC: 2, 3, 4)
- [x] Route customer-plane billing read path through tenant-scoped repositories and deny explicit cross-tenant request attempts (AC: 1, 4)
- [x] Add focused Story 1.3 tests for cross-tenant repository isolation across bot config, subscription, usage counter, and connection state (AC: 1, 2, 3)
- [x] Add endpoint-level isolation test for cross-tenant access denial behavior on the customer-plane billing path (AC: 1, 4)
- [x] Run full test suite to confirm CI-gate compatibility and no regressions (AC: 5)

## Dev Notes

- Story source: `_bmad-output/planning-artifacts/epics-saas-v1.md` section `Story 1.3: Tenant-Isolation Contract and Cross-Tenant Access-Denial Tests`.
- Architecture references:
  - `_bmad-output/planning-artifacts/architecture-whatsapp-ai-bot-saas-v1.md` section `4. Data Model and Tenant Isolation`.
  - Repository contract in `app/repositories/base.py` (`TenantGuard` / `TenantScopedRepository`).
- Current implementation state:
  - Guard base class exists but concrete tenant-scoped repositories are not yet present.
  - `/billing/plans` currently authenticates session but does not yet demonstrate repository-backed tenant read-path enforcement.
- Canonical table mapping for this story:
  - tenant settings -> `bot_configs`
  - subscription state -> `subscriptions`
  - usage counters -> `usage_counters`
  - WhatsApp session records -> `connection_states`
- Constraints:
  - Keep implementation additive and low-risk; do not alter unrelated runtime behavior.
  - Preserve existing auth/session contracts from Story 1.2a.
  - Avoid introducing new dependencies.

## Dev Agent Record

### Agent Model Used

GPT-5.3-Codex

### Debug Log

- 2026-05-04: Story context created and marked ready-for-dev.
- 2026-05-04: Added concrete tenant-scoped repositories for bot config, subscription, usage counter, and connection state.
- 2026-05-04: Updated /billing/plans to enforce tenant identity context and deny explicit cross-tenant tenant_id requests.
- 2026-05-04: Expanded Story 1.3 test contract coverage for blank tenant context fail-fast behavior.
- 2026-05-04: Validation runs completed.
  - tests/test_saas_1_3_tenant_isolation.py: 3 passed
  - tests/test_saas_1_2a_auth_flow.py: 12 passed
  - tests/test_saas_1_2b_password_reset_flow.py: 6 passed
  - full pytest: 497 passed, 5 skipped

### Completion Notes

- Implemented tenant-scoped repositories and exported them through app.repositories.
- Billing plans read-path now uses SubscriptionRepository scoped by authenticated session tenant.
- Explicit cross-tenant query attempts on /billing/plans?tenant_id=<other-tenant> now return 404.
- Added fail-fast test coverage for blank tenant context to enforce unscoped access denial contract.
- Full regression remains green after changes.

## File List

- app/repositories/__init__.py
- app/repositories/tenant_scoped.py
- app/views_auth.py
- tests/test_saas_1_3_tenant_isolation.py
- _bmad-output/implementation-artifacts/saas-1-3-tenant-isolation-contract-and-cross-tenant-access-denial-tests.md
- _bmad-output/implementation-artifacts/sprint-status-saas-v1.yaml

### Change Log

- 2026-05-04: Story context created and moved to ready-for-dev.
- 2026-05-04: Implemented Story 1.3 tenant isolation contract and cross-tenant denial tests; moved to review.
