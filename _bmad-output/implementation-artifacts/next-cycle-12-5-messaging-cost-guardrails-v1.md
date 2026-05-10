---
story_id: "12.5"
story_key: "next-cycle-12-5-messaging-cost-guardrails-v1"
status: "ready-for-dev"
epic: next-12
story: "5"
sprint_status_file: _bmad-output/implementation-artifacts/sprint-status-next-cycle.yaml
created: "2026-05-10"
updated: "2026-05-10"
depends_on:
  - next-cycle-10-1-analytics-reporting-api
  - next-cycle-10-2-dashboard-analytics-v1
  - saas-2-3-quota-entitlement-mapping-and-plan-limit-assignment
  - next-cycle-12-4-india-d2c-starter-template-pack
---

# Story 12.5: Messaging Cost Guardrails v1

## User Story

As an India D2C ecommerce SMB operator,
I want to see projected WhatsApp messaging cost before I confirm outbound sends,
so that I can avoid accidental spend spikes and make safer send decisions for sales and support workflows.

## Problem Statement

The approved market research shows that cost sensitivity in this ICP is driven by message-category mix and send volume, not subscription price alone. The current product does not surface projected message spend before operator-triggered outbound actions. That leaves operators exposed to avoidable cost surprises and weakens trust for the India D2C ecommerce slice where template-category economics are part of the core buying and retention logic.

## User Value and Business Outcome

- User value: operators understand likely send cost before committing an outbound action.
- Business outcome: fewer surprise-cost incidents, stronger plan-fit confidence, and a clearer path to monetization discussions grounded in actual usage behavior.

## In Scope

- Pre-send projected spend estimate for dashboard-triggered template sends and starter-pack activation paths that submit/send templated outbound messages.
- Estimate based on template category, recipient count, and configured India pricing table for supported categories.
- Warning threshold requiring explicit operator confirmation when projected spend exceeds threshold.
- Fail-closed behavior when estimation input is missing or invalid.
- Audit logging and analytics tagging of template category and estimate decision metadata.

## Out of Scope

- External invoice reconciliation or provider billing truth comparison.
- Multi-country pricing, FX conversion, or geography-specific tables beyond India.
- Automatic budget optimization or send suppression by AI.
- Full campaign management, segmentation, or recurring campaign scheduling.
- Subscription plan redesign.

## Acceptance Criteria

1. AC 12.5.1: Any dashboard-triggered outbound template send flow covered by this story presents a projected spend estimate before final confirmation, using the selected template category, recipient count, and the configured India-only price table.
2. AC 12.5.2: If the operator changes the template category, recipient count, or target audience size, the estimate recalculates before confirmation and the displayed estimate payload clearly states the inputs used.
3. AC 12.5.3: A configurable warning threshold exists per tenant or environment. When projected spend exceeds that threshold, one-click send is interrupted and the operator must perform an explicit second confirmation acknowledging the estimate.
4. AC 12.5.4: If estimate inputs are unavailable, invalid, or price-table lookup fails, the send fails closed with an actionable operator-visible error and an audit/event log entry; the system must never silently fall back to a zero or null estimate.
5. AC 12.5.5: Outbound analytics and audit records persist the template category, recipient count, projected spend, threshold outcome, operator confirmation decision, and correlation_id for each guarded send decision.
6. AC 12.5.6: The price-table source for this story is explicitly constrained to India-only configuration data. No UI path suggests international pricing support or mixed-geo estimation.
7. AC 12.5.7: The estimator does not alter the existing entitlement/quota enforcement path; it adds cost guardrails before send confirmation without weakening plan-limit blocking or retry/fallback contracts.

## Dependencies and Sequencing Constraints

- Pull condition remains unchanged: Gate B and Gate C must both be complete before this story is pulled.
- Depends on Story 10.1 and Story 10.2 for stable analytics/reporting and dashboard extension points.
- Depends on saas-2.3 quota/entitlement mapping for tenant usage context and existing plan-limit guard patterns.
- Should reuse the template category metadata introduced in Story 12.4 rather than re-deriving category labels in multiple places.
- Can be developed in parallel with Story 12.6 once the shared template metadata contract is agreed, but should land after Story 12.4 if the same template registry model is introduced there.

## Tasks / Subtasks

- [ ] Define a bounded India-only price-table configuration surface and estimator service. (AC: 12.5.1, 12.5.6)
- [ ] Add estimate payload generation for dashboard-triggered template send flows, including recalculation on changed inputs. (AC: 12.5.1, 12.5.2)
- [ ] Add threshold-based explicit confirmation flow for above-threshold sends. (AC: 12.5.3)
- [ ] Enforce fail-closed estimation behavior with actionable operator messaging and audit logging. (AC: 12.5.4)
- [ ] Persist category and estimate decision metadata into analytics/audit surfaces. (AC: 12.5.5)
- [ ] Prove quota and retry/fallback behavior remain unchanged by the new guardrail layer. (AC: 12.5.7)
- [ ] Add focused unit, integration, and contract tests for estimation, threshold branching, and blocked-send semantics. (AC: 12.5.1-12.5.7)

## Risks, Assumptions, and Mitigations

- Risk: operators treat estimates as invoice truth and dispute normal provider variance.
Mitigation: label v1 as projected estimate, store inputs used, and avoid any promise of exact reconciliation.
- Risk: pricing logic expands into a billing engine rewrite.
Mitigation: lock v1 to one country, one price table, one confirmation guardrail, and no invoice sync.
- Risk: fail-closed behavior blocks sends too aggressively if metadata is incomplete.
Mitigation: require explicit template-category metadata in template drafts and add actionable remediation copy for missing inputs.
- Assumption: existing outbound send flows have a stable confirmation boundary where a guardrail can be inserted before dispatch.
Mitigation: confirm the boundary in implementation against `app/views_dashboard.py` and the outbound delivery path before coding begins.

## Test Strategy

### Unit

- Validate estimate math for supported category/recipient-count combinations using the India-only table.
- Validate threshold branching, explicit confirmation requirement, and fail-closed behavior on missing inputs.
- Validate price-table scope rejects non-India or unknown categories.

### Integration

- Exercise dashboard-triggered send flow from operator action to confirmation gate to outbound dispatch decision.
- Assert above-threshold sends require explicit confirmation and below-threshold sends do not.
- Assert estimation failure blocks dispatch and writes audit evidence.

### Contract

- Add schema/contract coverage for any estimate preview API or dashboard JSON response.
- Extend analytics event contract coverage so category and projected-spend fields remain stable once introduced.
- Add blocked-send response contract coverage so operator clients cannot silently mis-handle fail-closed outcomes.

### Gate Expectations

- Targeted pytest suite for estimator logic and guarded-send flow.
- Existing analytics event foundation tests remain green after new fields are added or explicitly versioned.
- Existing quota and outbound retry/fallback contracts remain green and unchanged.
- No Sprint 3 pull exception: this story remains conditional and cannot bypass Gate B or Gate C.

## Definition of Done Evidence Checklist

- [ ] Story status updated in `sprint-status-next-cycle.yaml` according to workflow.
- [ ] India-only price table and threshold defaults documented in completion notes.
- [ ] Targeted pytest output captured for unit, integration, and contract coverage.
- [ ] Audit/event evidence shows estimate inputs, operator confirmation decision, and correlation_id.
- [ ] Failure evidence shows estimate errors fail closed without dispatch.
- [ ] Regression evidence shows quota enforcement and retry/fallback behavior were not weakened.
- [ ] Rollout mode and fallback configuration documented.

## Effort Estimate

- Estimate: 8 story points.
- Complexity rationale: medium-high. The work crosses UI confirmation flow, pricing configuration, outbound dispatch gating, analytics schema, and auditability. Scope stays practical because it is limited to India-only estimation and a single pre-send guardrail pattern.

## Rollout and Fallback / Rollback Notes

- Deploy behind a feature flag with staging validation first.
- Recommended rollout sequence: shadow logging of estimates in staging, then operator-visible estimates for a pilot tenant, then threshold-confirmation enforcement for the same tenant cohort.
- If false positives or metadata gaps create friction, rollback to estimate-visible or warn-only mode by config while preserving all audit records.
- Full rollback disables the estimate gate and hides the confirmation UI without touching historical event data.

## Dev Notes

### Source Grounding

- Research source: `_bmad-output/planning-artifacts/research/market-india-d2c-ecommerce-smb-whatsapp-research-2026-05-09.md`
- Planning source: `_bmad-output/planning-artifacts/sprint-plan-next-iteration-2026-05-07.md`
- Epic source: `_bmad-output/planning-artifacts/epics-next-cycle.md`

### Existing Surfaces Expected To Change

- `app/views_dashboard.py`
- `app/services/quota_service.py`
- `app/services/conversation_analytics.py`
- `app/services/outbound_delivery.py`
- `app/utils/whatsapp_utils.py`
- `app/models/__init__.py`

### Implementation Notes

- Keep money values in the smallest stable unit for storage and comparison to avoid float drift.
- Version any analytics payload addition if existing contract tests require strict key sets.
- Reuse the existing audit and correlation_id patterns rather than introducing a second logging path.

## Story Completion Status

- Story document created and context-complete for implementation.
- Status set to `ready-for-dev`.