# Sprint Plan - Next Iteration (2026-05-18)

Status: Active planning baseline
Prepared by: Amelia (Developer)
Project: python-whatsapp-bot
Scope source: _bmad-output/planning-artifacts/epics-next-cycle.md

## Cycle Objective
Deliver the approved next-cycle scope with strict gate discipline: complete reliability governance and adapter parity first, then analytics plus SQLite operational readiness, then conditional customer-value pull only if all P0 gates remain green.

## Story Inventory and Ordering

### Sprint 1 - Gate B (P0)
1. Story 9.1 - Governance Baseline Upgrade
2. Story 9.2 - Production Adapter Delivery (Single Non-WhatsApp Channel)
3. Story 9.3 - Adapter Parity Contract Suite and Mixed-Channel Staging Gate

### Sprint 2 - Gate C (P0)
1. Story 10.1 - Analytics Reporting API
2. Story 10.2 - Dashboard Analytics v1
3. Story 11.1 - SQLite 24h Soak Automation and Evidence Artifact
4. Story 11.2 - Rollback Drill Automation and Acceptance Artifact

### Sprint 3 - Gate D Pull (P1, conditional)
1. Story 12.1 - Notification Center (Billing and Usage Alerts)
2. Story 12.2 - Conversation History Viewer (Read-Only v1)
3. Story 12.3 - Reconnection Assistant (Guided Troubleshooting Path)
4. Story 12.4 - India D2C Starter Template Pack
5. Story 12.5 - Messaging Cost Guardrails v1
6. Story 12.6 - Compliance and Sendability Control Surface

## Dependency Graph

1. 9.1 -> 9.2 -> 9.3
2. 9.3 -> 10.1 -> 10.2
3. 9.3 -> 11.1 -> 11.2
4. 10.2 and 11.2 -> 12.1, 12.2, 12.3
5. 10.1, 10.2, 12.4 -> 12.5
6. 12.4, 10.2 -> 12.6

## Gating Conditions

### Gate B (Sprint 1 exit, blocking)
- CI governance gates active for contract categories, closure evidence, and launch-gate artifact completeness.
- One non-WhatsApp adapter integrated via ChannelAdapter and staging-validated.
- Mixed-channel success rate >= 99.0% across >= 1,000 deliveries.

### Gate C (Sprint 2 exit, blocking)
- Analytics summary API contract stable and passing tests.
- Dashboard analytics v1 wired to API and operator-protected.
- SQLite 24h soak artifact shows zero Sev-1/Sev-2 incidents.
- Rollback drill automated with completion <= 15 minutes.

### Gate D (Sprint 3 pull rule, conditional)
- Gate B and Gate C both complete.
- Full regression posture remains green.
- If blocked, all Epic 12 stories defer without penalty.

## Required Startup Actions
1. Confirm Gate B validators are green in CI on the current main baseline.
2. Confirm story status artifact ownership and update cadence (daily status updates).
3. Assign implementation owners for Sprint 1 stories (9.1/9.2/9.3) and lock WIP <= 2 stories.
4. Pre-provision staging credentials and test fixtures for the selected non-WhatsApp adapter.
5. Schedule soak window and rollback drill window in advance so Sprint 2 evidence can be produced without delay.

## Done Criteria for This Cycle
- All P0 stories (9.1, 9.2, 9.3, 10.1, 10.2, 11.1, 11.2) are done with evidence.
- Gate B and Gate C are both explicitly green in artifacts.
- Epic 12 stories are only executed if pull condition is satisfied.
- Sprint-status file reflects legal statuses and complete dependency coverage.
