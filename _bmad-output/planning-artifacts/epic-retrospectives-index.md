# Epic Retrospectives Index

## Purpose

This index centralizes all epic retrospective artifacts and provides a planning-ready summary for roadmap and carry-forward decisions.

## Retrospective Links

- [Epic 1 Retrospective (2026-05-02)](../implementation-artifacts/epic-1-retro-2026-05-02.md)
- [Epic 2 Retrospective (2026-05-02)](../implementation-artifacts/epic-2-retro-2026-05-02.md)
- [Epic 3 Retrospective (2026-05-02)](../implementation-artifacts/epic-3-retro-2026-05-02.md)
- [Epic 4 Retrospective (2026-05-01)](../implementation-artifacts/epic-4-retro-2026-05-01.md)
- [Epic 5 Retrospective (2026-05-01)](../implementation-artifacts/epic-5-retro-2026-05-01.md)
- [Epic 6 Retrospective (2026-05-02)](../implementation-artifacts/epic-6-retro-2026-05-02.md)
- [Epic 7 Retrospective (2026-05-02)](../implementation-artifacts/epic-7-retro-2026-05-02.md)

## Summary Table

| Epic | Date | Total Stories | Key Achievement | Open Item Carried Forward |
| --- | --- | --- | --- | --- |
| Epic 1 | 2026-05-02 | 3 | Secure startup, signature enforcement, and correlation-safe observability foundation established | Keep strict environment isolation in tests (`patch.dict(..., clear=True)`) and maintain route inventory discipline |
| Epic 2 | 2026-05-02 | 3 | Deterministic inbound-to-reply pipeline with typed AI outcomes and retry/fallback behavior | Maintain explicit contract tests for retry and background observability in all new delivery paths |
| Epic 3 | 2026-05-02 | 3 | Runtime agent control, setup and escalation flow, and operator activity/context surfaces delivered | Keep full-lifecycle setup and accessibility contracts locked as integration tests |
| Epic 4 | 2026-05-01 | 3 | Launch-gate discipline and operator runbook alignment formalized (including CF4.1 cross-functional contract closure) | Continue clean-room and incident-tabletop evidence as release-gate artifacts |
| Epic 5 | 2026-05-01 | 4 | CSRF/config hardening, observability cleanup, and setup/escalation precision improvements completed | Convert remaining implicit edge policies into explicit CI contracts |
| Epic 6 | 2026-05-02 | 4 | Contract-test debt retired for retry, setup progression, sanitization depth, and deferred observability | Add and enforce baseline test-count capture at epic open/close |
| Epic 7 | 2026-05-02 | 12 | Carry-forward hygiene complete with CI sprint-integrity guardrails and +28 deterministic tests | Resolve one pre-existing logs-filter test failure and schedule escalation false-positive coverage |

## Cross-Reference for Future Roadmap Planning

Use this index alongside these planning artifacts during roadmap definition and course-correction cycles:

- PRD baseline: `_bmad-output/planning-artifacts/prd.md`
- Epic decomposition baseline: `_bmad-output/planning-artifacts/epics.md`
- Contract test coverage map: `_bmad-output/implementation-artifacts/test-coverage-map.md`
- Sprint status source of truth: `_bmad-output/implementation-artifacts/sprint-status.yaml`

Recommended planning usage:

1. Start with the most recent retrospective (Epic 7) for active carry-forward items.
2. Validate any new scope against unresolved open items in the summary table.
3. Promote recurring carry-forward items into explicit acceptance criteria before story kickoff.

## Versioning Note

Version-aligned planning index created on 2026-05-02 during sprint course correction step 2.
