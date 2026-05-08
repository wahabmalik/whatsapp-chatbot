---
story_id: "5.4"
story_key: "5-4-setup-ux-and-escalation-precision-polish"
status: "ready-for-dev"
epic: 5
story: 4
created: "2026-05-01"
depends_on:
  - "3.2 (setup wizard and escalation workflow)"
  - "4.2 (setup guide, runbook, and monitoring operations)"
---

# Story 5.4: Setup UX and Escalation Precision Polish

## User Story

As an operator,
I want setup and escalation cues to reflect real workflow state with fewer false positives,
so that the dashboard feels accurate and intervention signals are easier to trust.

## Acceptance Criteria

1. Escalation keyword matching avoids obvious substring false positives while preserving deterministic configured keyword behavior.
2. The setup step indicator updates `aria-current="step"` to reflect the actual current step instead of always marking Welcome.
3. Fallback and escalation operator signals expose enough traceability for triage without degrading the end-user message experience.
4. UI copy and operator guidance affected by these changes remain aligned with the documented setup and operations flows.
5. Regression tests cover at least one false-positive keyword case and the setup-step accessibility state behavior.

---

## Context and Constraints

### Deferred backlog items consolidated here

- Escalation keyword matching uses substring rather than word-boundary behavior.
- `aria-current="step"` is hardcoded on the Welcome step.
- Fallback user message does not include a correlation ID, leaving traceability to logs and operator views only.

### Design stance

- Improve precision without making escalation behavior opaque or too dependent on fuzzy matching.
- Preserve operator-friendly traceability through dashboard/log surfaces rather than leaking raw identifiers into user-facing copy unless explicitly justified.
- Keep setup accessibility improvements narrow and measurable.

### Likely files

- `app/templates/setup.html`
- `app/static/js/dashboard.js`
- `app/utils/whatsapp_utils.py`
- `docs/setup_guide.md`
- `docs/operations_runbook.md`
- `tests/test_reliability.py`
- `tests/test_story_1_1_and_1_2.py`

---

## Implementation Tasks

- [ ] Replace naive substring escalation matching with a deterministic token or word-boundary strategy and keep configured keywords testable. (AC: 1)
- [ ] Update setup UI rendering so the active step communicates real progress through `aria-current`. (AC: 2)
- [ ] Improve operator-visible fallback traceability without forcing a raw correlation ID into the user-facing fallback text unless the design explicitly chooses it. (AC: 3)
- [ ] Align any changed copy or operator guidance across setup and runbook docs. (AC: 4)
- [ ] Add focused regression tests for false-positive escalation matching and setup accessibility state changes. (AC: 5)

## Testing Requirements

### Minimum validation commands

```bash
python -m pytest tests/test_story_1_1_and_1_2.py -q
python -m pytest tests/test_reliability.py -q
```

### Coverage expectations

- A message like `management` does not trigger the `agent` escalation keyword unless explicitly configured to do so.
- Setup step state changes remain accessible and stable across initial, incomplete, and complete flows.
- Operator traceability for fallback events remains available after the copy/UX refinement.

## References

- `_bmad-output/implementation-artifacts/deferred-work.md`
- `_bmad-output/implementation-artifacts/3-2-setup-wizard-and-escalation-workflow.md`
- `_bmad-output/implementation-artifacts/4-2-setup-guide-runbook-and-monitoring-operations.md`
- `app/templates/setup.html`
- `app/static/js/dashboard.js`
- `app/utils/whatsapp_utils.py`

## Story Completion Status

- Story document created and context-complete for implementation.
- Status set to `ready-for-dev`.