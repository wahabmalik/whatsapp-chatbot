---
story_id: "3.1"
story_key: "3-1-runtime-agent-selection-control-plane"
status: "done"
epic: 3
story: 1
created: "2026-04-29"
depends_on:
  - "1.3 Correlation Logging and Observability Baseline"
---

# Story 3.1: Runtime Agent Selection Control Plane

## User Story

As an operator,
I want to switch the active agent safely at runtime,
so that the next inbound message reflects the selected support behavior without a redeploy.

## Acceptance Criteria

1. Agent definitions are discovered from the supported skills/manifests and rendered in an operator-facing selection view.
2. The selected agent persists to `data/agent_selection.json` using atomic file replacement.
3. Missing, stale, or invalid saved selections auto-repair to the first available safe default agent.
4. Changes take effect on the next inbound message without restarting the Flask process.
5. Operator route guards and safe redirects preserve operator mode across navigation and setup completion.

---

## Context and Constraints

### Why this story exists

- FR6 requires runtime-safe agent switching with no redeploy friction.
- Epic 3 starts with control-plane safety so later stories can depend on stable operator state.
- UX requires operator-only access mode with predictable redirects and accessible save feedback.

### Current implementation baseline

- Agent discovery, persistence, and fallback behavior exist in `app/services/agent_registry.py`:
  - discovery from `_bmad/_config/agent-manifest.csv` and `skills/agent-*` metadata,
  - atomic persistence via `tempfile.NamedTemporaryFile` + `os.replace`,
  - stale-selection repair in `get_selected_agent()`.
- Operator-facing selection routes are implemented in `app/views_dashboard.py` (`GET /agents`, `POST /agents`) and rendered by `app/templates/agents-enhanced.html`.
- Runtime message processing already consumes selected agent at request time via `get_selected_agent()` in `app/utils/whatsapp_utils.py`, so agent changes apply to the next inbound message.
- Operator role guard and safe redirect helpers (`/operator/access`, `_get_safe_redirect_target`) already exist in `app/views_dashboard.py` and are covered by route guard tests.

### Implementation stance

- Treat Story 3.1 as verification/hardening over existing seams, not greenfield implementation.
- Keep single ownership for agent state in `agent_registry` and avoid duplicate caches.
- Preserve atomic write guarantees and stale-selection fallback behavior.
- Keep operator role/redirect behavior centralized in dashboard blueprint guard helpers.

---

## Developer Guardrails

### Required code paths

- Keep agent list + selection ownership in `app/services/agent_registry.py`.
- Keep operator UI/controller ownership in `app/views_dashboard.py` and `app/templates/agents-enhanced.html`.
- Keep runtime behavior consumption at message-processing call sites (`app/utils/whatsapp_utils.py`).
- Keep persisted selection source of truth in `data/agent_selection.json`.

### Agent discovery and persistence requirements (AC1, AC2, AC3)

- Discovery must merge manifest-defined and skills-defined agents without duplicate code collisions.
- Discovery output must remain deterministic (sorted by code) for UI consistency.
- Persisted selection writes must remain atomic and resilient to partial-write failure.
- Invalid/stale selected codes must auto-repair to first safe default and persist repaired value.
- Empty-agent scenarios must not raise exceptions; UI should render safe empty state.

### Runtime and operator flow requirements (AC4, AC5)

- Runtime agent selection must be read on each message flow so next-message effect is guaranteed.
- Save action must return clear JSON success/error payload for toast feedback.
- Operator-only routes must enforce role checks and preserve valid same-origin next targets.
- Unsafe redirect targets (absolute/protocol-relative) must be rejected.
- Setup completion and operator navigation must preserve operator mode across redirects.

### Existing reusable pieces

- Reuse `list_bmad_agents`, `get_selected_agent_code`, `set_selected_agent_code`, and `get_selected_agent` from `app/services/agent_registry.py`.
- Reuse `dashboard` blueprint role guard and redirect helpers in `app/views_dashboard.py`.
- Reuse existing JS toast/save interactions in `app/static/js/dashboard.js`.

### Boundaries and non-goals

- Do not add database persistence or external cache for agent selection.
- Do not move selection ownership into route handlers or templates.
- Do not widen to escalation/context-memory behavior (Story 3.2/3.3 scope).

---

## Previous Story Intelligence

- Story 1.3 established sanitized observability and correlation-safe route behavior; Story 3.1 must keep operator interactions on these stable, setup-safe contracts.
- Existing repository memory confirms route guards and safe redirects are now an explicit control-plane requirement and should not be bypassed.

---

## Git Intelligence Summary

- Recent git history is not story-granular; implementation guidance should rely on current source state and tests.
- Existing route guard and operator tests provide direct behavioral evidence for Story 3.1 acceptance paths.

---

## Implementation Tasks

- [x] Verify agent discovery contract from manifest + skill metadata and preserve deterministic ordering for UI rendering. (AC: 1)
- [x] Validate `data/agent_selection.json` atomic write semantics and error handling remain correct for save failures. (AC: 2)
- [x] Validate stale/missing selection auto-repair to first safe default and persistence of repaired code. (AC: 3)
- [x] Confirm inbound message processing consumes selected agent at request time to guarantee next-message effect. (AC: 4)
- [x] Confirm operator route guards and safe redirects preserve operator mode across `/operator`, `/agents`, and setup handoff. (AC: 5)
- [x] Extend focused tests for agent discovery, fallback repair, atomic save failures, and operator-guard redirect behavior where gaps exist. (AC: 1, 2, 3, 4, 5)

## Suggested Subtasks

- [x] Add/extend tests for empty/invalid/corrupt `agent_selection.json` fallback behavior.
- [x] Add/extend tests for single-agent install behavior (preselected card, disabled save action).
- [x] Add/extend tests for unsafe redirect target rejection (`https://`, `//`) and safe relative redirect acceptance.
- [x] Add/extend tests for save failure path returning structured JSON error used by toast UI.

---

## Files Most Likely to Change

- `app/services/agent_registry.py`
- `app/views_dashboard.py`
- `app/templates/agents-enhanced.html`
- `app/static/js/dashboard.js`
- `app/utils/whatsapp_utils.py`
- `tests/test_reliability.py`
- `tests/test_agent_registry.py`

## Files to Read Before Editing

- `app/__init__.py`
- `app/services/observability.py`
- `app/config.py`
- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prd.md`
- `_bmad-output/planning-artifacts/ux-design.md`
- `_bmad-output/implementation-artifacts/spec-dashboard-ui-implementation.md`

---

## Testing Requirements

### Minimum validation commands

```bash
python -m unittest tests.test_agent_registry
python -m unittest tests.test_reliability
```

### Coverage expectations

- Agent list is discovered and rendered from supported manifests/skills.
- Selection persistence writes are atomic and produce valid JSON state.
- Invalid or stale saved selection auto-repairs to first safe default.
- Agent switch is effective on the next inbound message.
- Operator route guards and safe redirect behavior are preserved.

### Test design notes

- Prefer extending existing `tests/test_agent_registry.py` and `tests/test_reliability.py` modules.
- Keep tests hermetic by patching filesystem reads/writes where needed.
- Validate behavior through route-level and service-level tests instead of UI snapshot-only assertions.

---

## Architecture Compliance Notes

- Keep app-scoped service ownership and avoid process-global mutable selection state outside `agent_registry` locks.
- Preserve same-origin safe redirect patterns and operator role boundaries in dashboard flows.
- Keep persistence lightweight and filesystem-based per architecture constraints.

---

## Implementation Risks to Avoid

- Non-atomic writes corrupting `data/agent_selection.json`.
- Stale selection values causing runtime failures or invisible fallback behavior.
- Hardcoded route targets that break mounted deployments.
- Redirect vulnerabilities via unvalidated `next` values.
- Divergent agent source-of-truth between UI and runtime message path.

---

## References

- Source requirements: `_bmad-output/planning-artifacts/epics.md` - Epic 3 Story 3.1, FR6
- Product context: `_bmad-output/planning-artifacts/prd.md` - FR6 runtime agent selection
- Architecture constraints: `_bmad-output/planning-artifacts/architecture.md` - Agent Control Plane, app-extension/runtime flow
- UX requirements: `_bmad-output/planning-artifacts/ux-design.md` - Agent selector behavior, feedback, empty state
- Existing agent registry implementation: `app/services/agent_registry.py`
- Existing operator routes: `app/views_dashboard.py`
- Existing agent selector UI: `app/templates/agents-enhanced.html`
- Existing runtime usage: `app/utils/whatsapp_utils.py`
- Existing reliability/guard tests: `tests/test_reliability.py`, `tests/test_agent_registry.py`

---

## Definition of Done

- [x] Story 3.1 acceptance criteria are met with existing architecture seams and no duplicate state paths.
- [x] Runtime selection changes are safe, atomic, and effective on next inbound message.
- [x] Operator route guards and safe redirects remain enforced across relevant flows.
- [x] Focused tests for discovery, persistence, fallback repair, and guard behavior pass locally.

## Dev Agent Record

### Agent Model Used

GPT-5.3-Codex

### Debug Log References

- Story scoped from Epic 3 plus current operator route and agent registry implementation.
- Existing code already provides substantial Story 3.1 baseline; artifact focuses on hardening and coverage closure.

### Completion Notes List

- Completed Story 3.1 against existing runtime seams without adding duplicate state ownership.
- Added test coverage for protocol-relative redirect rejection and structured save-failure JSON on `/agents` POST.
- Added test coverage proving runtime-selected agent changes are reflected on the next inbound message.
- Added test coverage for single-agent selector behavior (preselected active card and disabled save action).
- Focused Story 3.1 test suites pass locally (18/18).

### File List

- `_bmad-output/implementation-artifacts/3-1-runtime-agent-selection-control-plane.md`
