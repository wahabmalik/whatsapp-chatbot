---
story_id: "saas-3.1"
story_key: "saas-3-1-evolution-api-qr-fetch-display-and-status-polling"
status: "done"
epic: saas-3
story: "1"
sprint_status_file: _bmad-output/implementation-artifacts/sprint-status-saas-v1.yaml
created: "2026-05-05"
updated: "2026-05-05"
depends_on:
  - saas-2-2-stripe-webhook-ingestion-and-entitlement-state-machine
  - saas-2-3-quota-entitlement-mapping-and-plan-limit-assignment
---

# Story saas-3.1: Evolution API QR Fetch, Display, and Status Polling

## User Story

As a new customer,
I want to see a QR code and scan it with WhatsApp to link my phone number,
so that I can complete onboarding without needing technical support.

## Acceptance Criteria

1. Given a customer with an active subscription is on the onboarding page, when the page
   loads, then a QR code is fetched from Evolution API using the tenant-specific instance and
   rendered immediately.

2. If the tenant does not yet have a connection-state row/instance binding, one is created
   with a unique tenant instance_name at QR-fetch time.

3. The onboarding page shows real-time connection status (`disconnected` -> `connecting` ->
   `connected`) through an SSE status stream scoped to the tenant instance.

4. The QR refreshes before expiry using the returned TTL metadata.

5. If Evolution API calls fail, the API returns a retryable error and the page shows a visible
   retry affordance instead of a blank/erroring screen.

## Tasks / Subtasks

- [x] Add onboarding service for Evolution QR and per-tenant connection-state sync (AC: 1, 2, 3, 4, 5)
- [x] Add onboarding routes: `/onboarding`, `/onboarding/qr-code`, `/onboarding/status-stream` (AC: 1, 3, 5)
- [x] Add onboarding template with QR render, auto-refresh, SSE status indicator, and retry CTA (AC: 1, 3, 4, 5)
- [x] Add Story 3.1 tests for entitled gating, provisioning, QR fetch, SSE stream, and failure mode (AC: 1-5)
- [x] Update sprint status for Epic 3 and Story 3.1 progression to done

## Dev Notes

- Story source: `_bmad-output/planning-artifacts/epics-saas-v1.md` §Story 3.1.
- Architecture references: Screen 3 onboarding contracts and SSE stream from
  `_bmad-output/planning-artifacts/architecture-whatsapp-ai-bot-saas-v1.md`.
- Runtime remains Flask-blueprint based; onboarding routes were integrated in existing auth/billing
  blueprint to keep diffs small while preserving tenant session boundaries.
- Entitlement gate uses existing ENF-01 helper (`can_activate_bot`) to enforce active/trialing only.
- Evolution API instability risk is handled via bounded retries with exponential backoff and a 503
  `EVOLUTION_UNAVAILABLE` response contract.

## Dev Agent Record

### Agent Model Used

GPT-5.3-Codex (Amelia)

### Debug Log

- 2026-05-05: Created Story 3.1 artifact from epic specification and sprint dependencies.
- 2026-05-05: Implemented onboarding service, routes, and UI for tenant-scoped QR flow.
- 2026-05-05: Added Story 3.1 pytest suite and validated acceptance contracts.

### Completion Notes

- Added `app/services/onboarding_service.py` for tenant-scoped instance provisioning, QR fetch,
  status sync, and SSE payload generation.
- Added `/onboarding` page and APIs in `app/views_auth.py`:
  - `GET /onboarding`
  - `GET /onboarding/qr-code`
  - `GET /onboarding/status-stream` (SSE)
- Added `app/templates/onboarding.html` with status indicator, retry CTA, and QR auto-refresh.
- Added test coverage in `tests/test_saas_3_1_evolution_api_qr_fetch_display_and_status_polling.py`.

## File List

- _bmad-output/implementation-artifacts/saas-3-1-evolution-api-qr-fetch-display-and-status-polling.md
- _bmad-output/implementation-artifacts/sprint-status-saas-v1.yaml
- app/services/onboarding_service.py
- app/views_auth.py
- app/templates/onboarding.html
- tests/test_saas_3_1_evolution_api_qr_fetch_display_and_status_polling.py

### Change Log

- 2026-05-05: Story created and implemented to done.
