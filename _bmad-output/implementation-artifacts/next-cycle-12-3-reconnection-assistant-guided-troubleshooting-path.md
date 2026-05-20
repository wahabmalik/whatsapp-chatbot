# Story 12.3: Reconnection Assistant (Guided Troubleshooting Path)

Status: ready-for-dev

## Story

As an operator,
I want a guided reconnection assistant when channel connectivity drops,
so that I can restore service quickly without waiting for engineering support.

## Acceptance Criteria

1. AC 12.3.1: Connection Status section displays current state, last seen timestamp, and reconnect action.
2. AC 12.3.2: Reconnect flow guides QR fetch, scan confirmation, and connection verification.
3. AC 12.3.3: Common failures are explained with concrete next steps.
4. AC 12.3.4: Reconnection attempts are logged with correlation_id, outcome, and timestamp.
5. AC 12.3.5: Unrecoverable states present a clear contact-support path.

## Tasks / Subtasks

- [ ] Implement dashboard connection-status panel and reconnect CTA wiring.
- [ ] Implement guided reconnection flow states and provider probes.
- [ ] Add failure classification and remediation copy for known failure modes.
- [ ] Persist reconnection audit events with correlation metadata.
- [ ] Add unit and integration tests for flow, failure handling, and audit logging.

## Dev Notes

- Source requirements: _bmad-output/planning-artifacts/epics-next-cycle.md (Story 12.3).
- Keep behavior provider-agnostic; do not hardcode WhatsApp-only assumptions in service boundaries.
- Reuse existing observability and operator auth controls.

## Dev Agent Record

### Agent Model Used

GPT-5.3-Codex

### Completion Notes List

- Restored implementation artifact with canonical key so sprint-status can mark this story as ready-for-dev.
- Implementation remains pending; this artifact is a planning-ready baseline.

### File List

- _bmad-output/implementation-artifacts/next-cycle-12-3-reconnection-assistant-guided-troubleshooting-path.md

### Change Log

| Date | Change |
| --- | --- |
| 2026-05-18 | Restored canonical Story 12.3 implementation artifact and set to ready-for-dev for sprint kickoff. |
