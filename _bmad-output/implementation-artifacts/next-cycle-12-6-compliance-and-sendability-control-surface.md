---
story_id: "12.6"
story_key: "next-cycle-12-6-compliance-and-sendability-control-surface"
status: "done"
epic: next-12
story: "6"
sprint_status_file: _bmad-output/implementation-artifacts/sprint-status-next-cycle.yaml
created: "2026-05-10"
updated: "2026-05-15"
depends_on:
  - next-cycle-12-4-india-d2c-starter-template-pack
  - next-cycle-10-2-dashboard-analytics-v1
  - 3-2-setup-wizard-and-escalation-workflow
  - 5-3-observability-cleanup-and-delivery-telemetry
---

# Story 12.6: Compliance and Sendability Control Surface

## User Story

As an India D2C ecommerce SMB operator,
I want a clear dashboard surface for consent, template approval state, and sendability risk,
so that I can keep outbound messaging compliant and avoid blocked or degraded sends before they impact customers.

## Problem Statement

The market-research promotion made one point explicit: compliance and sendability are product-critical, not back-office concerns, for this ICP. The current product has operational surfaces and outbound delivery plumbing, but it does not present consent state, template review status, or quality-driven sendability cues as one explicit operator workflow. That creates avoidable policy risk, message rejection risk, and confusing operator behavior when sends fail for reasons the product could have warned about earlier.

## User Value and Business Outcome

- User value: operators can understand whether a contact can be messaged, whether a template is eligible to send, and what action to take when quality risk rises.
- Business outcome: fewer avoidable policy violations, cleaner outbound success rates, and stronger operator trust in the product's send controls.

## In Scope

- Tenant-scoped consent ledger with status, source, and timestamp fields.
- Dashboard visibility for consent status per contact and template approval status per tenant template.
- Quality/sendability alert surface with plain-language recommended actions.
- Pre-dispatch enforcement that blocks non-compliant outbound sends and records audit evidence.
- Secret-safe logging and correlation-aware blocked-send evidence.

## Out of Scope

- Legal advice, consent-text authoring, or jurisdictional compliance beyond the approved India slice.
- Auto-remediation, automatic re-submission, or provider appeal workflows.
- Cross-channel compliance orchestration.
- Marketing preference center or end-user self-service portal.
- Automated throughput throttling based on provider heuristics beyond operator-visible cues and controlled blocking.

## Acceptance Criteria

1. AC 12.6.1: The operator dashboard exposes a tenant-scoped consent ledger view for contacts used in outbound messaging, showing consent status, consent source, and last-updated timestamp, with search/filter support bounded to the tenant.
2. AC 12.6.2: The operator dashboard exposes template sendability state for tenant templates with at least the states approved, pending, rejected, and paused, and shows the last sync timestamp or last known update source.
3. AC 12.6.3: The control surface shows a quality/sendability alert indicator that can represent at minimum: no known issue, warning, and action required, each with plain-language next steps for the operator.
4. AC 12.6.4: The outbound send path blocks dispatch when required consent is missing or when the selected template is in a non-sendable state, and the blocked response includes an actionable operator-safe reason plus correlation_id.
5. AC 12.6.5: Every blocked send and every operator-visible state change recorded by this story is tenant-isolated, audit logged, and free of sensitive credential material.
6. AC 12.6.6: If provider sync data is stale or temporarily unavailable, the UI clearly marks the state as stale/unknown and the system applies a documented safe default rather than pretending the template is sendable.
7. AC 12.6.7: This story does not weaken existing outbound retry/fallback semantics for otherwise eligible sends; only the pre-dispatch eligibility gate is added.

## Dependencies and Sequencing Constraints

- Pull condition remains unchanged: Gate B and Gate C must both be complete before this story can be pulled.
- Depends on Story 12.4 if starter-pack templates are the first templates most operators will see in Sprint 3; reusing the same template registry avoids duplicate metadata models.
- Depends on Story 10.2 for authenticated dashboard/operator surface extensions.
- Depends on Story 5.3 observability and delivery telemetry patterns for correlation-safe logging and blocked-send evidence.
- Can proceed in two internal phases within one story if needed: read-only dashboard visibility first, then send-block enforcement once consent/template state is reliable.
- If implementation reveals missing provider-state read capability, do not expand this story into a full provider integration rewrite; scope the first version to the minimum state sync needed for operator safety.

## Tasks / Subtasks

- [ ] Add tenant-scoped consent ledger persistence and service helpers for create/read/update of consent state. (AC: 12.6.1, 12.6.5)
- [ ] Add template sendability status model/read layer and dashboard presentation for approved/pending/rejected/paused states. (AC: 12.6.2)
- [ ] Add quality/sendability indicator logic and operator guidance copy for warning/action-required states. (AC: 12.6.3, 12.6.6)
- [ ] Insert a pre-dispatch compliance gate into the outbound send path that blocks missing-consent and non-sendable-template cases. (AC: 12.6.4, 12.6.7)
- [ ] Add audit logging and secret-safe blocked-send evidence with correlation_id. (AC: 12.6.4, 12.6.5)
- [ ] Add focused unit, integration, and contract tests for consent visibility, stale-state handling, and blocked-send semantics. (AC: 12.6.1-12.6.7)

## Risks, Assumptions, and Mitigations

- Risk: provider state can be stale or incomplete, causing false blocks or false confidence.
Mitigation: surface freshness explicitly, fail to a documented safe state, and allow staged rollout with read-only mode first.
- Risk: compliance scope balloons into a full legal/compliance platform.
Mitigation: keep v1 limited to consent ledger visibility, template state visibility, and pre-send safety controls.
- Risk: blocked sends frustrate operators if reasons are too technical.
Mitigation: require operator-safe reason codes and plain-language remediation steps in UI copy.
- Assumption: a bounded provider-state read path exists or can be added without redesigning the entire outbound adapter layer.
Mitigation: if the provider path is missing, ship a read-only/stale-aware first slice and keep enforcement limited to reliable states.

## Test Strategy

### Unit

- Validate consent state transitions, freshness evaluation, and template sendability reducer logic.
- Validate quality/sendability indicator mapping for healthy, warning, and action-required states.
- Validate secret-safe blocked-send payload generation.

### Integration

- Exercise dashboard reads for consent ledger and template-state surfaces with authenticated operator access.
- Exercise outbound send attempts where consent is missing, template is pending/rejected/paused, provider state is stale, and send is eligible.
- Assert blocked sends do not reach downstream dispatch while eligible sends preserve existing retry/fallback behavior.

### Contract

- Add contract coverage for the consent/template-state API or dashboard JSON shape.
- Add blocked-send response contract coverage so operator clients receive a stable, actionable payload.
- Add audit/telemetry contract coverage if new blocked-send events are persisted.

### Gate Expectations

- Targeted pytest suite for consent ledger, template-state visibility, and blocked-send enforcement.
- Existing outbound delivery contract tests remain green for successful sends and retry/fallback behavior.
- Existing observability/log-safety tests remain green and prove no credential leakage.
- No exception to Sprint 3 conditional gating.

## Definition of Done Evidence Checklist

- [ ] Story status updated in `sprint-status-next-cycle.yaml` according to workflow.
- [ ] Acceptance criteria mapped to tests and evidence artifacts.
- [ ] Targeted pytest output captured for unit, integration, and contract coverage.
- [ ] UI evidence captured for consent ledger, template-state panel, stale-state indicator, and blocked-send messaging.
- [ ] Audit/log evidence captured showing correlation_id and no secret leakage.
- [ ] Regression evidence shows eligible sends still honor the existing retry/fallback contract.
- [ ] Rollout mode and safe fallback mode documented.

## Effort Estimate

- Estimate: 8 story points.
- Complexity rationale: high. The story spans new compliance-state persistence, dashboard operator UX, provider-state freshness handling, and a pre-dispatch enforcement gate. Scope remains practical because it is deliberately limited to one ICP, one geography, and v1 sendability visibility rather than full compliance automation.

## Rollout and Fallback / Rollback Notes

- Roll out in stages: read-only state visibility in staging first, then blocked-send enforcement for a pilot tenant cohort.
- Keep an emergency config or feature switch to revert enforcement to read-only visibility if stale-state quality is not yet reliable.
- Rollback is non-destructive: hide the control surface or disable enforcement while preserving the ledger, template-state cache, and audit trail.
- Do not delete consent or audit records during rollback.

## Dev Notes

### Source Grounding

- Research source: `_bmad-output/planning-artifacts/research/market-india-d2c-ecommerce-smb-whatsapp-research-2026-05-09.md`
- Planning source: `_bmad-output/planning-artifacts/sprint-plan-next-iteration-2026-05-07.md`
- Epic source: `_bmad-output/planning-artifacts/epics-next-cycle.md`

### Existing Surfaces Expected To Change

- `app/views_dashboard.py`
- `app/models/__init__.py`
- `app/services/config_audit.py`
- `app/services/outbound_delivery.py`
- `app/utils/whatsapp_utils.py`
- `app/services/conversation_analytics.py`

### Implementation Notes

- Prefer explicit reason codes for blocked sends so UI copy and tests can stay stable.
- Separate stale/unknown from approved; never infer approval from missing sync data.
- Reuse existing tenant-isolation and audit-log patterns instead of inventing a second policy store.

## Story Completion Status

- Story document created and context-complete for implementation.
- Status set to `ready-for-dev`.