# Sprint Plan - Next Iteration (2026-05-07)

Status: Approved baseline
Approved on: 2026-05-08
Approved by: Wahab (Project Lead)
Decision: Proceed with Epic 9-12 direction as the official next-cycle planning baseline

## Problem and User

### Problem
The current product baseline is stable and launch-ready across both tracks, but growth value is still locked in deferred scope:
- SaaS v1 deferred P1 customer value (notifications, history, analytics, reconnection support).
- Next-cycle reliability and expansion scope (first production non-WhatsApp adapter, analytics productization, SQLite operational confidence, CI governance hardening).

Without a focused next iteration, the team risks entering maintenance-only mode and losing roadmap momentum after achieving a clean gate.

### Target Users
- Primary: non-technical SMB owners/operators using WhatsApp bot automation.
- Secondary: internal support/admin operators who need fast diagnosis and safe controls.
- Tertiary: product/engineering team requiring sustainable quality gates as scope expands.

## Goals and Metrics

### Iteration Goals
1. Deliver measurable post-v1 customer value while preserving reliability baseline.
2. Convert deferred roadmap items into implementation-ready stories with explicit scope boundaries.
3. Keep release confidence high through enforceable CI governance and contract discipline.

### Success Metrics
- Reliability: no regression in release gate outcome; full suite remains green.
- Product value: at least 2 customer-visible P1 features released in this iteration.
- Operations: no increase in Sev-1/Sev-2 incidents attributable to new scope.
- Delivery quality: 100% of stories include explicit risk-closure evidence template.

### Non-Goals
- Full BI platform build.
- More than one new production adapter in the same iteration.
- New enterprise RBAC/admin surface beyond current operator needs.

## Prioritized Requirements

### P0 (Must-Have This Iteration)
1. One production-ready non-WhatsApp adapter using existing abstraction, with parity contracts.
2. Analytics productization v1 from event foundation to operator-consumable reporting.
3. SQLite soak + rollback readiness package with explicit operational evidence.
4. CI governance enforcement for contract drift and story closure quality.

### P1 (Pull If Capacity Allows)
1. In-app billing/usage notification center.
2. Conversation history viewer in dashboard.
3. Self-serve phone reconnection troubleshooting assistant.

### P2 (Future)
1. Team seats and RBAC.
2. API access for enterprise.
3. Add-on/overage billing model.

## MVP Scope (Next Iteration)

### Sprint 1 - Reliability and Expansion Foundation
1. Story 9.1: Governance baseline upgrade (contract categories + story evidence template gate).
2. Story 9.2: Production adapter delivery (single non-WhatsApp adapter) behind channel interface.
3. Story 9.3: Adapter parity contract suite and mixed-channel staging gate.

### Sprint 2 - Analytics and Operational Hardening
1. Story 10.1: Analytics reporting API for conversation outcomes/trends from event foundation.
2. Story 10.2: Dashboard analytics v1 (lightweight trends and escalation indicators).
3. Story 11.1: SQLite 24h soak automation and evidence artifact generation.
4. Story 11.2: Rollback drill automation and acceptance artifact for <= 15 min objective.

### Sprint 3 - Customer Value Pull (Conditional)
1. Story 12.1: Notification center (billing and usage alerts).
2. Story 12.2: Conversation history viewer (read-only v1).
3. Story 12.3: Reconnection assistant (guided troubleshooting path).

Pull rule: Sprint 3 stories are pulled only if Sprint 1 and Sprint 2 P0 gates are complete and test/regression posture remains stable.

## Risks and Mitigations

1. Risk: scope sprawl across adapter + analytics + platform hardening.
Mitigation: strict WIP limit of 2 active stories; freeze P1 pull until all P0 gates are green.

2. Risk: reliability regression from adapter expansion.
Mitigation: parity contract suite is mandatory; no merge without baseline WhatsApp parity pass.

3. Risk: analytics work expands into full BI project.
Mitigation: enforce v1 analytics boundary (operational trends only, no data warehouse scope).

4. Risk: inconsistent story closure quality.
Mitigation: CI gate requiring structured closure evidence block for every done story.

## Planning Decision

- Existing backlog from completed epics is effectively closed.
- Outstanding roadmap work exists, but it is post-v1/next-cycle scope rather than unfinished v1 commitments.
- Recommended next iteration: start at Epic 9 with the above story sequence and gate discipline.

## MR Promotion (2026-05-09)

Source artifact:
- _bmad-output/planning-artifacts/research/market-india-d2c-ecommerce-smb-whatsapp-research-2026-05-09.md

Planning constraint adopted:
- ICP: India D2C ecommerce SMB operators using WhatsApp for sales/support workflows.
- Geography: India only.

Promoted planning implications (next 1-2 sprints):

1. Add India D2C onboarding defaults as first-class scope in the conditional customer-value pull.
- Proposed scope insertion under Sprint 3: "D2C starter templates" bundle (abandoned cart, order status, COD confirmation, support triage).
- Story candidate: 12.4 - India D2C Starter Template Pack.

2. Move message-cost governance from future optimization to near-term delivery.
- Proposed scope insertion under Sprint 3: projected spend signal and template-category tagging before campaign/send actions.
- Story candidate: 12.5 - Messaging Cost Guardrails v1.

3. Elevate compliance/sendability observability from implicit to explicit UX.
- Proposed scope insertion under Sprint 3: consent capture ledger, template status visibility, and quality-alert-driven throttling cues.
- Story candidate: 12.6 - Compliance and Sendability Control Surface.

Execution rule:
- Keep existing Sprint 3 pull condition unchanged; if Sprint 1-2 P0 gates are not complete, these promoted stories defer with Epic 12.

Evidence quality note:
- Confidence is high on competitive packaging and pricing structure.
- Confidence is medium on exact India WhatsApp user-size estimates due to secondary-source dependence.
