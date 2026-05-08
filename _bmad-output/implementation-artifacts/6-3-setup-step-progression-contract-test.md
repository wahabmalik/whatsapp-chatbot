---
story_id: "6.3"
story_key: "6-3-setup-step-progression-contract-test"
status: "done"
epic: 6
story: 3
created: "2026-05-02"
depends_on:
  - "3.2 (setup wizard and escalation workflow)"
  - "5.4 (setup UX and escalation precision polish)"
---

# Story 6.3: Setup Step Progression Contract Test

## Goal

Lock setup progression semantics with an automated accessibility contract test that verifies reachable steps and accurate `aria-current` state across setup lifecycle states.

## Background

Epic 5 corrected `aria-current` drift risk, but retrospective feedback highlighted how easily UI/controller divergence can reappear. This story formalizes the expected setup state model in tests so accessibility progression remains stable through future template/controller changes.

## Acceptance Criteria

1. Automated tests validate `aria-current="step"` maps to the correct active step for key setup states (initial, partial, complete).
2. Tests verify step progression is reachable and monotonic across expected state transitions.
3. Tests fail if template output and controller-derived step state diverge.
4. Coverage is scoped to progression contract behavior only; no new setup feature logic is introduced.

## Test Strategy

- Add focused route/template integration assertions for setup page rendering.
- Use deterministic fixtures for setup-complete and setup-incomplete states.
- Validate exactly one active step marker at a time and expected step ordering.
- Ensure accessibility contract checks are lightweight enough for standard CI runs.

## Files Likely To Be Touched

- `tests/test_setup_step_conformance.py`
- `tests/test_story_1_1_and_1_2.py`
- `app/templates/setup.html`
- `app/views.py`

## Story Completion Status

- Story implemented with focused progression contract coverage.
- Status set to `done`.

## Tasks / Subtasks

- [x] Extend setup progression contract coverage in `tests/test_setup_step_conformance.py` for key lifecycle states.
- [x] Add direct controller-to-template parity assertions so route output fails on divergence.
- [x] Verify reachable monotonic step progression without changing setup feature behavior.
- [x] Validate the focused suite and nearby setup/sprint regression coverage.

## Dev Agent Record

### Debug Log

- Added route-level parity checks that derive the expected active step from `_setup_current_step()` for the same rendered environment state.
- Added route progression assertions for the reachable sequence `1 -> 2 -> 3 -> 4 -> 5` to lock monotonic setup advancement.
- Kept the implementation test-only because existing setup controller and template behavior already satisfied the contract once the missing cross-layer assertions were added.

### Completion Notes

- Acceptance Criteria 1 and 3 are covered by direct controller/template agreement checks over initial, partial, near-complete, complete, and verified states.
- Acceptance Criterion 2 is covered by route-level reachability and monotonic progression assertions.
- Acceptance Criterion 4 is satisfied because no setup runtime logic or template behavior was changed.

## File List

- `tests/test_setup_step_conformance.py`
- `_bmad-output/implementation-artifacts/6-3-setup-step-progression-contract-test.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`

## Change Log

- 2026-05-02: Added controller/template parity and monotonic route progression contract coverage for setup steps.
- 2026-05-02: Marked story 6.3 complete and updated sprint tracking.

## Status

- done
