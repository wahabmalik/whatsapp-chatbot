---
story_id: "8.4"
story_key: "8-4-optional-sqlite-persistence-rollout-slice"
status: "done"
epic: 8
story: 4
created: "2026-05-02"
estimate: "4 days"
type: "optional infrastructure"
depends_on:
  - "2.1 (inbound normalization and idempotency)"
  - "5.2 (configuration validation and runtime guardrails)"
  - "7.9 (store close lifecycle detectability test)"
---

# Story 8.4: Optional SQLite Persistence Rollout Slice

## Story

As a platform owner,
I want SQLite-backed reliability state validated for restart continuity,
so that the system can preserve state beyond process lifetime when transition sprint capacity allows.

## Epic 8 Transition Context

This is an optional infrastructure story. It should be pulled only if mandatory closure plus selected P1 stories are on track.

## Acceptance Criteria

1. SQLite-backed store behavior is verified across app restart scenarios for key reliability state.
2. Configured fallback-to-memory behavior remains deterministic when SQLite initialization fails.
3. Resource lifecycle teardown remains leak-safe for both memory and SQLite implementations.
4. Setup and runbook notes for enabling SQLite match runtime behavior and guardrails.
5. Story can be deferred without blocking Epic 8 completion.
6. Pull gate is enforced: story starts only after Story 8.1 is done and one P1 story is in review or done.

## Tasks

- [x] Add restart-focused coverage for SQLite-backed reliability state. (AC: 1)
- [x] Validate fallback behavior under forced SQLite init failure mode. (AC: 2)
- [x] Confirm teardown path closes resources without regressions. (AC: 3)
- [x] Update operational documentation for SQLite enablement and rollback. (AC: 4)
- [x] Confirm pull-gate criteria are met before implementation starts. (AC: 6)

## Validation Commands

```powershell
.venv\Scripts\python.exe -m pytest tests/test_expiring_store.py -q
.venv\Scripts\python.exe -m pytest tests/test_reliability.py -q
```

## Risk Closure Criteria

- [x] Optional infrastructure work does not displace mandatory Epic 8 closure work.
- [x] SQLite failure path cleanly degrades to memory when configured.
- [x] Operational docs remain aligned with tested runtime behavior.

## References

- `_bmad-output/planning-artifacts/next-cycle-readiness.md`
- `_bmad-output/planning-artifacts/epics.md`
- `app/services/`
- `docs/runbook.md`

## Completion State

- Story implemented and validated on 2026-05-03.
- Estimated effort: 4 days (optional capacity pull).

## Dev Agent Record

### Files Changed

- `tests/test_expiring_store.py` — Added `SQLiteRestartContinuityTests` class (3 new tests for AC1: key survival, expiry after restart, namespace isolation)
- `docs/operations_runbook.md` — Added section 8 "SQLite state store: enablement and rollback" (AC4)

### Completion Notes

- Pull-gate confirmed: 8-1 done, 8-2 and 8-3 both done (>= 1 P1 story done) ✓
- AC1: Three restart-continuity tests added in `SQLiteRestartContinuityTests` — all pass.
- AC2: Covered by pre-existing `test_factory_falls_back_to_memory_when_sqlite_fails` and `test_factory_raises_when_sqlite_fails_and_fallback_disabled` — no changes needed.
- AC3: Covered by pre-existing `StoreCloseLifecycleTests` — no changes needed.
- AC4: Added runbook section 8 with enablement steps, env var table, fallback semantics, rollback notes, and teardown behavior.
- AC5: Story design is deferral-safe; Epic 8 mandatory work was complete before this story started.
- Final: `test_expiring_store.py` 11 passed; `test_reliability.py` 53 passed, 5 subtests passed.

### Change Log

| Date | Change |
|---|---|
| 2026-05-03 | Added SQLiteRestartContinuityTests (3 tests) to test_expiring_store.py |
| 2026-05-03 | Added SQLite enablement section to docs/operations_runbook.md |
