---
story_id: "12.4"
story_key: "next-cycle-12-4-india-d2c-starter-template-pack"
status: "done"
epic: next-12
story: "4"
sprint_status_file: _bmad-output/implementation-artifacts/sprint-status-next-cycle.yaml
created: "2026-05-10"
updated: "2026-05-15"
depends_on:
  - next-cycle-10-2-dashboard-analytics-v1
  - next-cycle-11-2-rollback-drill-automation-and-acceptance-artifact
  - 3-2-setup-wizard-and-escalation-workflow
  - 8-3-conversation-analytics-event-foundation
---

# Story 12.4: India D2C Starter Template Pack

## User Story

As an India D2C ecommerce SMB operator using WhatsApp for sales and support,
I want a curated starter pack of WhatsApp-ready templates during onboarding,
so that I can activate proven customer workflows faster without starting from a blank screen or bypassing compliance checks.

## Problem Statement

The chosen ICP and geography are now fixed: India D2C ecommerce SMB operators using WhatsApp for sales/support workflows. The current onboarding path is generic and does not convert the promoted market-research conclusions into concrete operator value. That increases time-to-value, raises setup abandonment risk, and weakens the product's fit against the specific workflows repeatedly signaled in the approved research artifact: abandoned cart recovery, order updates, cash-on-delivery confirmation, and support triage.

## User Value and Business Outcome

- User value: first-run setup becomes immediately relevant to the operator's day-to-day ecommerce messaging needs.
- Business outcome: faster activation for the chosen ICP, higher onboarding completion for eligible tenants, and cleaner qualification data on which starter workflows are actually adopted.

## In Scope

- One fixed pack for one ICP and one geography only: India D2C ecommerce SMBs.
- Four starter templates only: abandoned cart reminder, order status update, COD confirmation, and support triage.
- Tenant-scoped draft creation from onboarding or operator dashboard.
- Visible WhatsApp template-category label on each starter template draft.
- Edit-before-activation flow.
- Activation telemetry capturing whether the starter pack was enabled and which templates were drafted or submitted.

## Out of Scope

- Any geography beyond India.
- Any ICP beyond India D2C ecommerce SMB operators.
- AI-generated template writing, template translation, or multilingual packs.
- Shopify, WooCommerce, catalog, or order-system sync.
- Automatic template submission approval or automatic campaign launch.
- Additional packs beyond the four fixed workflows in this story.

## Acceptance Criteria

1. AC 12.4.1: The onboarding flow and operator dashboard expose an optional "India D2C starter pack" action that is visible only when the tenant is in the Sprint 3 conditional feature cohort; it creates exactly four tenant-scoped draft templates: abandoned cart reminder, order status update, COD confirmation, and support triage.
2. AC 12.4.2: Each draft template is pre-populated with a fixed starter title, body, and template-category label appropriate to the workflow, and all fields remain editable by the operator before activation or provider submission.
3. AC 12.4.3: Starter pack creation is idempotent per tenant. Re-running the action never creates duplicate drafts for the same workflow slug; it either reuses the existing draft or offers an explicit replace action with confirmation.
4. AC 12.4.4: Activating or submitting starter templates does not bypass existing template approval, consent, or sendability controls. Drafts remain unusable for outbound sends until they reach an allowed provider state under the normal control path.
5. AC 12.4.5: The UI surfaces the template category for each draft and links to a plain-language explanation that category affects downstream messaging cost and approval flow.
6. AC 12.4.6: Onboarding telemetry and audit records capture starter-pack adoption with tenant isolation, including: pack enabled yes/no, per-template workflow slug, category label, draft created timestamp, and activation/submission outcome.
7. AC 12.4.7: If template-draft creation fails for any workflow, the failure is shown with actionable copy and logged with correlation_id; partial creation is allowed only when the UI clearly marks which drafts succeeded and which require retry.

## Dependencies and Sequencing Constraints

- Pull condition remains unchanged: this story is not eligible to start until Gate B and Gate C are both complete and full regression posture remains green.
- Depends on Story 3.2 onboarding flow for the operator setup surface and connection-state aware setup path.
- Depends on Story 10.2 dashboard analytics/operator surface for a stable authenticated dashboard extension point.
- Depends on Story 11.2 only because Epic 12 remains gate-blocked behind the Sprint 2 exit package, not because of direct SQLite rollback coupling.
- Should be implemented before Story 12.5 and Story 12.6 if the team wants a single shared template registry, workflow slug set, and category metadata model reused across all three stories.
- If sequencing pressure exists, this story can ship first as draft creation plus edit-before-submit without requiring cost estimation or consent ledger enforcement to be completed in the same PR.

## Tasks / Subtasks

- [x] Define the fixed starter-pack catalogue for the four India D2C workflows, including immutable workflow slugs and default category labels. (AC: 12.4.1, 12.4.2)
- [x] Add a tenant-scoped template draft persistence model/service with idempotent create-or-reuse semantics. (AC: 12.4.1, 12.4.3)
- [x] Add onboarding and dashboard entry points to enable the starter pack and edit drafts before submission. (AC: 12.4.1, 12.4.2)
- [x] Wire approval-state gating so starter drafts cannot be sent until normal provider approval and compliance checks pass. (AC: 12.4.4)
- [x] Emit telemetry and audit events for pack enablement and per-template draft/submission outcomes. (AC: 12.4.6)
- [x] Add failure-state UX and logging for partial or failed draft creation. (AC: 12.4.7)
- [x] Add focused tests for catalogue integrity, tenant isolation, idempotency, and activation flow. (AC: 12.4.1-12.4.7)

## Risks, Assumptions, and Mitigations

- Risk: the starter text drifts into unsupported compliance guidance.
Mitigation: keep copy minimal, editable, and clearly operator-owned; require normal approval flow rather than treating starter content as pre-approved.
- Risk: duplicate draft creation pollutes tenant data.
Mitigation: use stable workflow slugs and idempotent create-or-reuse semantics with explicit replace behavior.
- Risk: scope expands into full campaign builder or ecommerce integration work.
Mitigation: lock scope to four static templates with no catalog sync, campaign automation, or plugin work.
- Assumption: existing onboarding/dashboard auth and tenant-isolation patterns are sufficient for a tenant-scoped draft feature.
Mitigation: require tenant isolation assertions in integration and contract coverage.

## Test Strategy

### Unit

- Validate the fixed starter-pack catalogue exposes exactly four workflows and stable workflow slugs.
- Validate category labels, default copy payloads, and create-or-reuse idempotency rules.
- Validate telemetry payload generation for pack-enabled and template-created events.

### Integration

- Exercise onboarding or dashboard enable flow from authenticated operator request through draft persistence.
- Assert re-running enablement for the same tenant does not create duplicates.
- Assert activation/submission stays blocked when approval/compliance state is not eligible.

### Contract

- Add a stable API/schema contract for any new template-pack read/write endpoint or dashboard JSON response.
- Add tenant-isolation contract coverage so one tenant cannot view or mutate another tenant's starter drafts.
- Add analytics event contract coverage if template adoption events are written into the conversation or onboarding telemetry surface.

### Gate Expectations

- Targeted pytest suite for the new starter-pack feature file(s).
- Existing affected suites remain green for onboarding, dashboard, and tenant-isolation surfaces.
- No change to Sprint 3 pull rule; rollout remains controlled by Sprint 3 cohort flags and tenant cohort membership.

## Definition of Done Evidence Checklist

- [x] Story status updated in `sprint-status-next-cycle.yaml` according to the repo workflow.
- [x] Acceptance criteria mapped to concrete tests or artifact evidence.
- [x] Targeted pytest output captured for starter-pack unit/integration coverage.
- [x] Any new JSON/API contract recorded in tests and shown stable under failure and success paths.
- [x] Operator UI evidence captured for enable, edit, duplicate-prevention, and failure states.
- [x] Audit/telemetry evidence shows tenant-scoped adoption events and no cross-tenant leakage.
- [x] Rollout flag/default and fallback behavior documented in completion notes.

## Effort Estimate

- Estimate: 5 story points.
- Complexity rationale: medium. The story touches onboarding/dashboard UI, tenant-scoped persistence, and approval-safe activation, but remains bounded by four fixed workflows, one geography, one ICP, and no ecommerce platform integration.

## Rollout and Fallback / Rollback Notes

- Roll out behind a tenant-scoped feature flag or equivalent conditional Sprint 3 eligibility check.
- Enable first in staging with one internal tenant using the India D2C slice only.
- If defects appear, disable the entry point without deleting existing drafts; existing drafts remain stored but hidden until the feature is re-enabled.
- Rollback is non-destructive: remove the UI/action path and stop new draft creation while preserving audit history.

## Dev Notes

### Source Grounding

- Research source: `_bmad-output/planning-artifacts/research/market-india-d2c-ecommerce-smb-whatsapp-research-2026-05-09.md`
- Planning source: `_bmad-output/planning-artifacts/sprint-plan-next-iteration-2026-05-07.md`
- Epic source: `_bmad-output/planning-artifacts/epics-next-cycle.md`

### Existing Surfaces Expected To Change

- `app/onboarding/routes.py`
- `app/views_dashboard.py`
- `app/models/__init__.py`
- `app/services/starter_pack.py`
- `app/config.py`
- `app/templates/onboarding.html`
- `app/templates/dashboard.html`

### Implementation Notes

- Keep template metadata explicit and operator-editable; do not auto-generate copy at runtime.
- Model workflow slugs as the stable identity, not the human-readable template title.
- Preserve current authenticated operator patterns and CSRF protections for any new mutating dashboard route.

## Story Completion Status

## Completion State

- Story status: `done`
- Completed on: 2026-05-15
- Acceptance criteria: AC 12.4.1 through AC 12.4.7 implemented and validated via targeted tests.

## Validation Evidence

- `python -m pytest -q tests/test_story_12_4_india_d2c_starter_template_pack.py` -> 5 passed
- `python -m pytest -q tests/test_saas_3_1_evolution_api_qr_fetch_display_and_status_polling.py` -> 10 passed
- `python -m pytest -q tests/test_story_3_3.py -k "operator or dashboard"` -> 15 passed, 18 deselected
- `python -m pytest -q tests/test_analytics_reporting_api_contract.py` -> 4 passed

## Dev Agent Record

### Agent Model Used

GPT-5.3-Codex

### Completion Notes List

- Added fixed India D2C starter template catalogue with four immutable workflow slugs and fixed category labels.
- Added tenant-scoped `starter_template_drafts` model with uniqueness guard on `(tenant_id, workflow_slug)`.
- Implemented idempotent starter-pack enable flow with create/reuse and explicit replace behavior.
- Added onboarding starter-pack APIs for status, enable, draft update, submit, and activate.
- Enforced non-bypass controls so submit/activate obey consent, approval, and sendability gates.
- Added telemetry jsonl emission and audit-log entries for pack enablement and per-template outcomes.
- Added onboarding and operator dashboard UI sections that surface category labels and category-cost explainer links.
- Added focused Story 12.4 test suite for catalogue integrity, isolation, idempotency, and failure handling.

### File List

- app/models/__init__.py
- app/saas_db.py
- app/config.py
- app/services/starter_pack.py
- app/onboarding/routes.py
- app/views_dashboard.py
- app/templates/onboarding.html
- app/templates/dashboard.html
- tests/test_story_12_4_india_d2c_starter_template_pack.py
- _bmad-output/implementation-artifacts/next-cycle-12-4-india-d2c-starter-template-pack.md
- _bmad-output/implementation-artifacts/sprint-status-next-cycle.yaml

### Change Log

| Date | Change |
| --- | --- |
| 2026-05-15 | Implemented Story 12.4 India D2C starter template pack end to end, added tests, and recorded closure evidence. |