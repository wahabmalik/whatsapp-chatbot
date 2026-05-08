---
story_id: "saas-1.1"
story_key: "saas-1-1-database-schema-bootstrap-and-tenant-model"
status: "done"
epic: saas-1
story: 1
sprint_status_file: _bmad-output/implementation-artifacts/sprint-status-saas-v1.yaml
created: "2026-05-04"
updated: "2026-05-04"
depends_on: []
---

# Story saas-1.1: Database Schema Bootstrap and Tenant Model

## User Story

As an engineer,
I want the core SaaS database schema created within the Flask app factory lifecycle,
so that all subsequent stories have a stable, tenant-aware data foundation to build on.

## Acceptance Criteria

1. Given the Flask application starts up, when the database init step runs, then the following
   tables exist: `tenants`, `users`, `tenant_memberships`, `tenant_settings`, `subscriptions`,
   `entitlements`, `usage_counters`, `usage_idempotency`, `billing_events`,
   `tenant_whatsapp_sessions`, `audit_logs`.

2. Every business entity table includes `tenant_id` as a non-nullable indexed column.

3. A repository base class (or equivalent abstraction) enforces that all data access methods
   require a `tenant_id` parameter — unscoped queries raise an explicit error.

4. The database connection is registered as a Flask app extension with a `close()` method
   so it participates in app teardown lifecycle cleanly.

5. Startup validation confirms database connectivity; missing or unreachable database logs a
   clear error. If DATABASE_URL is not set, the SaaS module is skipped (existing bot remains
   unaffected) and a warning is logged.

## Tasks / Subtasks

- [x] Add `sqlalchemy` to requirements.txt
- [x] Create `app/models/` package with all 11 required tables as SQLAlchemy ORM models
- [x] Create `app/saas_db.py` — SaaSDatabase Flask extension class with init_app(), create_tables(), verify_connectivity(), close()
- [x] Create `app/repositories/base.py` — TenantScopedRepository enforcing tenant_id
- [x] Wire SaaS DB into app factory: load DATABASE_URL in config.py, register extension in __init__.py
- [x] Write tests in `tests/test_saas_1_1_schema_and_tenant_model.py` verifying all ACs
- [x] Run tests and confirm all pass

## Dev Notes

- Use SQLAlchemy core (no Flask-SQLAlchemy) to keep dependency surface minimal.
- In-memory SQLite (`:memory:`) is used in tests; production targets Postgres via DATABASE_URL env var.
- Table name mapping (canonical arch §4 → AC conceptual names):
  - `bot_configs` (arch) = `tenant_settings` (AC) — use `tenant_settings` as the table name here for AC compliance; story 4.2 will reference `tenant_settings`
  - `connection_states` (arch) = `tenant_whatsapp_sessions` (AC) — use `tenant_whatsapp_sessions`; story 3.2 references `tenant_whatsapp_sessions`
  - `usage_events` (arch) — NOT in AC table list; will be added in story 4.3 as a separate table
  - `audit_log` (arch) = `audit_logs` (AC) — use `audit_logs`
- SaaS DB extension is only initialized when DATABASE_URL config key is present.
- Existing bot functionality (Evolution/Meta webhook, OpenAI) must remain fully unaffected.
- ENF-03: `tenants.is_active` kill switch column must be present from the start.

## Dev Agent Record

### Debug Log

- Implemented SQLAlchemy model layer and shared model utilities for Story saas-1.1.
- Added `SaaSDatabase` Flask extension with startup initialization, table creation, connectivity check, session factory, and teardown `close()` support.
- Added tenant-scope guard base (`TenantGuard` with `TenantScopedRepository` alias) to block unscoped repository access.
- Wired `DATABASE_URL` into runtime config and app factory startup flow.
- Implemented Story saas-1.1 validation tests in `tests/test_saas_1_1_schema_and_tenant_model.py`.
- Validation run: `python -m pytest tests/test_saas_1_1_schema_and_tenant_model.py -q` passed (`21 passed`).
- Regression run: `python -m pytest --tb=short -q` passed (`474 passed, 5 skipped, 29 subtests passed`).

### Completion Notes

- Story saas-1.1 is complete and validated end-to-end.
- Startup now supports optional SaaS DB initialization: missing `DATABASE_URL` logs a warning and leaves existing bot behavior unaffected.
- Tenant-scoped repository contract is enforced via explicit `tenant_id` validation.
- Story-specific tests are green, and full regression suite is green with no detected regressions.

## File List

- _bmad-output/implementation-artifacts/saas-1-1-database-schema-bootstrap-and-tenant-model.md
- requirements.txt
- app/models/__init__.py
- app/models/base.py
- app/saas_db.py
- app/repositories/__init__.py
- app/repositories/base.py
- app/config.py
- app/__init__.py
- tests/test_saas_1_1_schema_and_tenant_model.py
- alembic.ini
- migrations/env.py
- migrations/script.py.mako
- migrations/versions/001_initial_saas_schema.py

### Change Log

- 2026-05-04: Implemented canonical SaaS schema bootstrap (arch §4), tenant guard enforcement, fail-fast startup DB validation, and initial Alembic migration for Story saas-1.1.
- 2026-05-04: Finalized Story saas-1.1 close-out with passing story suite and full regression validation; status confirmed as done.
