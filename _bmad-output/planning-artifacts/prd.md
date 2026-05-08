---
stepsCompleted: ["step-01-init"]
inputDocuments:
  - "_bmad-output/implementation-artifacts/sprint-status.yaml"
  - "_bmad-output/implementation-artifacts/epic-8-retro-2026-05-03.md"
  - "_bmad-output/implementation-artifacts/deferred-work.md"
workflowType: "prd"
date: "2026-05-03"
---

# Product Requirements Document - Next Planning Cycle (Epic 9+)

Author: Wahab
Date: 2026-05-03
Status: Draft - Ready for create-architecture
Version: 2.0

## Problem and User

### Current State
- Epics 1-8 are fully complete and closed in sprint status.
- Reliability and contract-test discipline are strong, but roadmap value is still under-realized in four areas:
  - Multi-channel delivery is interface-ready but not production-active for non-WhatsApp channels.
  - Analytics is event-foundation only, without product-facing operational reporting.
  - SQLite is implemented as optional rollout, but production readiness evidence is not yet complete.
  - Governance needs an ongoing mechanism to preserve contract-test quality as scope expands.

### Primary User
- Support Operations Lead and Platform Owner running production support automation.

### Core Problem
- The product is stable but still single-channel and observability-light for operator decision-making.
- Without targeted next-cycle scope, the team risks either overexpansion (scope creep) or under-delivery (no meaningful roadmap progress).

## Goals and Metrics

### Cycle Goals
1. Ship one production-ready non-WhatsApp channel adapter behind the existing channel abstraction.
2. Productize analytics from raw events into operator-usable insights and governed retention behavior.
3. Complete SQLite operational rollout readiness with explicit enablement and rollback confidence.
4. Institutionalize reliability governance so new features cannot bypass contract quality bars.

### Success Metrics (Cycle Exit)

| Area | Metric | Target |
| --- | --- | --- |
| Multi-channel | Non-WhatsApp adapter launch | 1 adapter live in staging and production candidate |
| Multi-channel | Channel delivery success rate | >= 99.0% over 1,000 mixed-channel test deliveries |
| Multi-channel | Adapter parity | 100% pass of shared outbound contract suite for WhatsApp + new adapter |
| Analytics | Event ingestion reliability | >= 99.9% event write success in staging |
| Analytics | Reporting freshness | Dashboard/API reflects new events within <= 60s |
| Analytics | Retention enforcement | 100% pass of retention-cap contract tests |
| SQLite | Soak stability | 24h staging soak with zero Sev-1/Sev-2 SQLite incidents |
| SQLite | Rollback confidence | Documented rollback drill completes in <= 15 min |
| Reliability Governance | Contract suite health | 0 failing mandatory contract tests on main |
| Reliability Governance | Regression control | 0 Sev-1 escapes attributable to interface/contract drift |

### Non-Goals for This Cycle
- Full omnichannel suite (more than one new adapter).
- Advanced BI warehouse or external analytics platform migration.
- Multi-node distributed persistence redesign beyond SQLite rollout hardening.
- Enterprise RBAC/admin console expansion.

## Prioritized Requirements

### Priority P0 (MVP for Epic 9+)

#### P0-R1: First Non-WhatsApp Adapter Production Rollout
- Deliver one adapter (recommended: SMS) wired through existing channel abstraction.
- Keep routing policy explicit, deterministic, and config-validated at startup.
- Enforce channel-specific credential validation and sanitized logging.
- Extend outbound contract tests to guarantee parity behaviors:
  - Success path
  - Retry path
  - Retry exhaustion with fallback semantics
  - Correlation and observability fields

#### P0-R2: Analytics Productization v1
- Preserve current event schema baseline while adding product-facing consumption layer.
- Deliver operator analytics surface (API and/or dashboard views) for:
  - Message volume trend
  - Escalation trend
  - Delivery outcome breakdown
  - Latency trend summaries
- Enforce retention policy behavior using configured cap and pruning semantics.
- Add analytics consumer contract tests for response format stability.

#### P0-R3: SQLite Operational Readiness Gate
- Treat SQLite as rollout-ready only after staged evidence, not just unit/integration correctness.
- Execute and document:
  - Enablement test
  - Failover-to-memory behavior check
  - Rollback drill
  - Restart continuity check
- Keep default safety posture explicit for environments without proven readiness.

#### P0-R4: Reliability and Contract-Test Governance
- Define mandatory contract-test categories for every new adapter and analytics surface.
- Add CI governance checks that block merge on:
  - Contract drift
  - Missing done-story closure evidence template sections
  - Launch-gate artifact incompleteness
- Maintain explicit compatibility for operational command contracts.

### Priority P1 (Post-MVP in this cycle, pull only after P0 stability)
- Additional adapter feasibility spike (no production commitment).
- Analytics export enhancement (batch export formats, no warehouse integration).
- Extended SQLite observability (additional health indicators).

## MVP Scope

### In Scope (MVP)
- One production-ready non-WhatsApp adapter behind existing abstraction.
- Analytics productization from raw event foundation to operator-consumable reporting v1.
- SQLite staging soak + rollback readiness package with documented operational playbook evidence.
- Continuous reliability governance enforced in CI and sprint completion criteria.

### Out of Scope (Non-MVP)
- More than one new production adapter.
- Full analytics platform migration.
- Distributed datastore transition beyond SQLite readiness.
- New enterprise admin surfaces not required for the above four goals.

### Delivery Sequencing (Incremental)
1. Reliability governance baseline updates and gate scaffolding.
2. First non-WhatsApp adapter end-to-end with parity contracts.
3. Analytics productization v1 and retention governance.
4. SQLite operational soak and rollback evidence closure.

## Acceptance Metrics and Launch Gates

### Gate A: Architecture Readiness Gate
- Requirements, constraints, and contracts are traceable from this PRD into architecture outputs.
- Adapter boundary, analytics boundary, and persistence boundary decisions are explicit.
- No unresolved High-risk architecture ambiguity.

### Gate B: Build Completion Gate
- All P0 stories done with risk-closure checklists fully checked.
- Mandatory contract test categories present and passing.
- CI governance checks active for contract drift and story artifact completion format.

### Gate C: Staging Validation Gate
- Mixed-channel delivery success >= 99.0% on 1,000+ message run.
- Analytics freshness <= 60s and retention-cap behavior verified.
- SQLite 24h soak passes with no Sev-1/Sev-2 incidents.
- Rollback drill executed and documented (<= 15 min objective met).

### Gate D: Production Candidate Gate
- No open High risks without explicit acceptance.
- Operations runbook updates approved for new adapter, analytics, and SQLite procedures.
- Release smoke checklist expanded for multi-channel and analytics surfaces and passes.

## Risks and Mitigations

| ID | Risk | Severity | Mitigation | Exit Criteria |
| --- | --- | --- | --- | --- |
| R9-1 | Adapter rollout introduces behavioral drift from WhatsApp baseline | High | Shared contract suite and parity acceptance matrix | 100% parity suite pass for baseline + new adapter |
| R9-2 | Analytics scope balloons into BI project | Medium | Strict v1 reporting scope and non-goal guardrails | P0 analytics deliverables complete without new platform dependencies |
| R9-3 | SQLite behaves differently across runtime environments | High | Staging soak, fallback verification, rollback drill before production-default decisions | Soak + rollback evidence artifact approved |
| R9-4 | Governance weakens as scope expands | High | CI-enforced contract categories, artifact completeness checks, launch-gate automation | Zero bypass merges for mandatory reliability gates |
| R9-5 | Cycle slips due to parallel high-complexity tracks | Medium | Incremental sequencing with WIP limits and explicit pull conditions for P1 | P0 completed within cycle with no unplanned P0 additions |

## Inputs for create-architecture (Structured Handoff)

### Architecture Scope Package
- Domain 1: Channel adapter runtime and routing policy.
- Domain 2: Analytics productization service and presentation contract.
- Domain 3: SQLite rollout operation model and failure-mode controls.
- Domain 4: Governance automation and CI quality gates.

### Required Architecture Decisions
1. Adapter plugin contract: extension points, error model, retry/fallback ownership.
2. Channel routing strategy: config schema, defaults, and safety on invalid channel config.
3. Analytics aggregation model: compute-on-read vs pre-aggregation tradeoff for v1.
4. Retention enforcement mechanism: line cap pruning strategy and observability hooks.
5. SQLite rollout topology: file location, locking, backup/restore, and rollback procedure coupling.
6. Governance enforcement: where to encode mandatory contract categories and artifact checks.

### NFR Budgets to Preserve
- End-to-end delivery reliability: >= 99.0% in mixed-channel staging runs.
- P50/P95 latency: no regression beyond +10% from current WhatsApp baseline.
- Security posture: no downgrade of existing signature/validation controls.
- Operational diagnosability: correlation and sanitization requirements remain mandatory.

### Proposed Epic Skeleton for Next Step
- Epic 9: First non-WhatsApp adapter productionization with parity contracts.
- Epic 10: Analytics productization v1 with retention governance.
- Epic 11: SQLite operational rollout readiness and rollback confidence.
- Epic 12: Reliability governance automation and contract sustainability.

### Open Assumptions for Architecture Validation
- Assumption A1: Existing abstraction from Epic 8 is sufficient for one adapter without refactor.
- Assumption A2: Event-store file model can support v1 analytics freshness target.
- Assumption A3: Current deployment environments permit SQLite file and locking behaviors required for soak-readiness.
- Assumption A4: CI runtime budget can absorb expanded contract suites without blocking developer throughput.

## Document Control

Document Status: Ready for create-architecture
Last Updated: 2026-05-03
Next Action: Run bmad-create-architecture using this PRD as primary input
