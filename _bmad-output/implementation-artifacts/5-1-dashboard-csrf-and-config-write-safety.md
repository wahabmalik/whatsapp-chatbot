---
story_id: "5.1"
story_key: "5-1-dashboard-csrf-and-config-write-safety"
status: "ready-for-dev"
epic: 5
story: 1
created: "2026-05-01"
depends_on:
  - "1.1 (startup validation and setup gating)"
  - "3.2 (setup wizard and escalation workflow)"
---

# Story 5.1: Dashboard CSRF and Config Write Safety

## User Story

As an operator,
I want setup and dashboard write actions protected against forgery and concurrent file corruption,
so that configuration changes remain trustworthy and recoverable.

## Acceptance Criteria

1. All operator-facing POST endpoints (`/setup/openai-key`, `/setup/verify`, `/agents`, and any equivalent dashboard mutation routes) reject requests without a valid CSRF token.
2. CSRF failures return controlled JSON or HTML responses that preserve operator UX expectations without exposing secrets or stack traces.
3. The `.env` update path in the dashboard uses cross-platform file locking or equivalent serialization so simultaneous writes do not interleave or truncate the file.
4. Configuration writes remain atomic and preserve unrelated `.env` content already present in the file.
5. Saving a replacement OpenAI key refreshes the live app client state, or applies the new key through an explicit in-process rebind path that no longer depends on a blind app restart.

---

## Context and Constraints

### Why this story exists

- Story 3.2 left dashboard POST routes without CSRF enforcement because the broader dashboard security model was out of sprint scope.
- Story 1.1 deferred the `.env` concurrency race in `_set_env_value`, which becomes a real integrity risk once more than one worker or operator session is active.
- The current setup flow acknowledges that an OpenAI key save may require restart "to apply everywhere"; Sprint 2 should remove that ambiguity for the primary dashboard path.

### Deferred backlog items consolidated here

- No CSRF token validation on POST setup endpoints.
- Concurrent `.env` writes in `_set_env_value`.
- Module-level OpenAI client not refreshed after dashboard key save.

### Required implementation surface

- `app/views_dashboard.py`
- `app/templates/setup.html`
- `app/templates/agents.html`
- `app/static/js/dashboard.js`
- `app/services/openai_service.py`
- Focused route tests in `tests/test_story_1_1_and_1_2.py`, `tests/test_agent_registry.py`, and `tests/test_reliability.py`

### Guardrails

- Preserve existing operator-mode redirects and JSON response shapes where possible.
- CSRF enforcement must work in both browser form-post and fetch/XHR flows used by the dashboard.
- File write serialization must remain Windows-compatible for the current developer environment.
- Do not regress setup reachability when runtime configuration is incomplete.

---

## Implementation Tasks

- [ ] Add a reusable CSRF token issue/validate helper for dashboard operator sessions. (AC: 1, 2)
- [ ] Enforce CSRF validation on all operator dashboard POST endpoints and document any intentionally exempt routes. (AC: 1, 2)
- [ ] Update dashboard templates and JavaScript to send CSRF tokens on form and fetch submissions. (AC: 1, 2)
- [ ] Replace plain read-modify-write `.env` mutation with a locked and atomic update flow. (AC: 3, 4)
- [ ] Rebind or recreate the OpenAI client after a successful key save so the live process uses the new key immediately. (AC: 5)
- [ ] Extend focused tests for valid token, missing token, bad token, and concurrent-safe config update behavior. (AC: 1, 2, 3, 4, 5)

## Testing Requirements

### Minimum validation commands

```bash
python -m pytest tests/test_story_1_1_and_1_2.py -q
python -m pytest tests/test_agent_registry.py -q
python -m pytest tests/test_reliability.py -q
```

### Coverage expectations

- CSRF failures return 403 or equivalent controlled rejection for each protected POST route.
- Happy-path POST flows still return their existing success contracts when the CSRF token is valid.
- `.env` updates preserve adjacent keys and do not corrupt the file under repeated writes.
- OpenAI key save changes the live client state used by subsequent calls.

## References

- `_bmad-output/implementation-artifacts/deferred-work.md`
- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/architecture.md`
- `app/views_dashboard.py`
- `app/services/openai_service.py`
- `/memories/repo/csrf-hardening-test-alignment.md`

## Story Completion Status

- Story document created and context-complete for implementation.
- Status set to `ready-for-dev`.
