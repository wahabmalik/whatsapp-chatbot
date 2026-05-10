# Story 9.1: Governance Baseline Upgrade

Status: done

## Story

As a platform maintainer,
I want CI governance checks that enforce contract-test category coverage, story closure evidence quality, and launch-gate artifact completeness,
so that reliability scope can expand without silent quality drift or weak release decisions.

## Acceptance Criteria

1. AC 9.1.1: CI check exists that blocks merge when mandatory contract-test category is missing for any adapter or analytics surface.
2. AC 9.1.2: Story done-closure evidence template gate is active. Merges missing the structured closure block are rejected by CI.
3. AC 9.1.3: Launch-gate artifact completeness check runs on merge to main and fails the build if required sections are absent.
4. AC 9.1.4: All existing Epics 1-8 story artifacts are retrospectively backfill-compatible (schema does not break on existing files).

## Tasks / Subtasks

- [x] Implement mandatory contract-test category validator and wire it into CI. (AC: 9.1.1)
  - [x] Add validator script for required categories: adapter and analytics.
  - [x] Require at least one adapter contract test artifact and one analytics contract test artifact.
  - [x] Add focused unit tests for validator success and failure paths.
- [x] Implement story closure evidence template validator and wire it into CI. (AC: 9.1.2, 9.1.4)
  - [x] Enforce closure evidence sections for done stories in next-cycle tracking.
  - [x] Preserve backward compatibility for completed Epics 1-8 artifacts by accepting legacy completion section patterns.
  - [x] Add tests proving gate failure for missing closure evidence and pass for legacy-compatible artifacts.
- [x] Implement launch-gate artifact completeness validator and wire it into CI. (AC: 9.1.3)
  - [x] Validate required root sections and required gate fields.
  - [x] Validate source-specific constraints for gate keys (file_exists, file_contains, staging_report, test_results, manual).
  - [x] Add tests for malformed artifact and valid baseline artifact.
- [x] Update CI workflow to run governance validators before full test suite. (AC: 9.1.1, 9.1.2, 9.1.3)

### Review Findings

- [x] [Review][Decision] Sprint-status scope ambiguity resolved with safe assumption: load both sprint-status files, strictly enforce modern closure evidence only for `next-cycle-*` done stories, and preserve historical compatibility for legacy done stories (AC 9.1.4).
- [x] [Review][Patch] YAML/JSON/file-read hardening applied; validator paths now fail with actionable messages instead of unhandled exceptions.
- [x] [Review][Patch] `file_contains` empty-needle guard enforced with focused regression test.
- [x] [Review][Patch] Adapter-missing category scenario covered by dedicated test.
- [x] [Review][Patch] `manual` source empty-key scenario covered by dedicated test.
- [x] [Review][Defer] `glob("test_*.py")` not recursive — pre-existing constraint; no subdirectories exist under `tests/` currently but this silently misses future test subdirectories. [`validate_contract_test_categories.py:21`] — deferred, pre-existing
- [x] [Review][Defer] `file_contains` multi-`::` key confusing — `"path::needle::extra"` is valid `partition` input but the extra `::` becomes part of the needle substring, which may not be intended. Not a false positive but undocumented. [`validate_launch_gate_artifact_completeness.py`] — deferred, pre-existing
- [x] [Review][Patch] `_load_yaml(launch_gates_path)` OSError not caught — extended `except` clause to also catch `OSError` so an unreadable launch-gates.yaml returns a clean issue instead of crashing; added `_OSErrorLaunchGateTest` covering the path. 19/19 pass.

## Dev Notes

### Architecture and Standards Alignment

- Keep implementation as lightweight Python validators in repository root (consistent with existing `validate_*.py` gates).
- CI entrypoint remains `.github/workflows/ci.yml`; governance gates should run before long-running test steps.
- Preserve current launch-gate evidence model centered on `_bmad-output/test-artifacts/launch-gates.yaml` and existing parity tests.

### Contract-Test Category Guidance

- Adapter category evidence can be satisfied by `tests/test_channel_delivery_contract.py`.
- Analytics category evidence can be satisfied by `tests/test_conversation_analytics_event_foundation.py`.
- Validator must fail clearly when either category has no mapped test artifact.

### Story Closure Evidence Template Guidance

- New template for done stories should require explicit closure evidence sections under Dev Agent Record.
- Backward compatibility rule: completed Epics 1-8 stories remain valid if they include legacy completion structure used by prior stories.
- Gate should target sprint-tracked done stories and provide precise missing-section output.

### Launch-Gate Artifact Completeness Guidance

- Validate `version`, `generated`, and non-empty `gates`.
- Validate each gate includes `id`, `label`, `domain`, `blocking`, `source`, `key`.
- Validate `source` belongs to known source set used by existing parity tests.

### Testing Requirements

- Add deterministic unit tests for each new validator script.
- Keep tests hermetic by using temporary files/fixtures for invalid scenarios.
- Ensure existing test suites continue to pass unchanged.

### References

- `_bmad-output/planning-artifacts/sprint-plan-next-iteration-2026-05-07.md`
- `_bmad-output/planning-artifacts/epics-next-cycle.md`
- `_bmad-output/planning-artifacts/architecture-whatsapp-ai-bot-saas-v1.md`
- `.github/workflows/ci.yml`
- `tests/test_channel_delivery_contract.py`
- `tests/test_conversation_analytics_event_foundation.py`
- `tests/test_story_artifact_completion_contract.py`
- `tests/test_launch_gate_parity.py`

## Dev Agent Record

### Agent Model Used

GPT-5.3-Codex

### Debug Log References

- Added three governance validators and wired them into `.github/workflows/ci.yml` before migrations and test suite execution.
- Initial closure-evidence validator was too broad; fixed by scoping strict enforcement to next-cycle stories while preserving legacy compatibility.

### Completion Notes List

- AC 9.1.1 complete: `validate_contract_test_categories.py` enforces mandatory adapter and analytics contract-test categories.
- AC 9.1.2 complete: `validate_story_closure_evidence.py` enforces modern closure evidence for next-cycle done stories.
- AC 9.1.3 complete: `validate_launch_gate_artifact_completeness.py` validates launch-gate root fields, gate schema, and source-key evidence mapping.
- AC 9.1.4 complete: legacy artifacts remain compatible by allowing legacy completion pattern and avoiding false failures on historical sprint files.
- Risk hardening complete: legacy-compatibility logic expanded to accept historical Dev Agent Record formats while preserving strict modern requirements for next-cycle done stories.
- Assumption applied for ambiguity: AC 9.1.2 enforcement is scoped to next-cycle done stories for blocking behavior, while historical done stories remain backward-compatible under AC 9.1.4.
- Validation executed:
  - `python -m unittest tests.test_governance_validators -v` -> 18 passed
  - `python -m pytest tests/test_story_artifact_completion_contract.py tests/test_launch_gate_parity.py -q` -> 30 passed
  - `python validate_contract_test_categories.py` -> pass
  - `python validate_story_closure_evidence.py` -> pass
  - `python validate_launch_gate_artifact_completeness.py` -> pass

### File List

- `.github/workflows/ci.yml`
- `validate_contract_test_categories.py`
- `validate_story_closure_evidence.py`
- `validate_launch_gate_artifact_completeness.py`
- `tests/test_governance_validators.py`
- `_bmad-output/implementation-artifacts/sprint-status-next-cycle.yaml`
- `_bmad-output/implementation-artifacts/next-cycle-9-1-governance-baseline-upgrade.md`

### Change Log

| Date | Change |
| --- | --- |
| 2026-05-08 | Initial story created from next-cycle artifacts with governance-first implementation plan. |
| 2026-05-08 | Implemented governance validators, added unit tests, wired CI gates, and advanced story to review. |
| 2026-05-08 | Hardened closure evidence compatibility for historical artifacts and added strict next-cycle enforcement tests. |
| 2026-05-09 | Closed remaining review findings, hardened sprint-status loading behavior, added multi-file compatibility tests, and revalidated governance + parity suites. |
| 2026-05-10 | Code-review pass: fixed unhandled OSError in _load_yaml for launch-gates.yaml; added _OSErrorLaunchGateTest; 19/19 pass; story closed done. |
