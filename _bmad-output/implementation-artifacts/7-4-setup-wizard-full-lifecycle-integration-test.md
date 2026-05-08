# Story 7.4: Setup Wizard Full Lifecycle Integration Test

## Status
Done

## Summary
Added an integration test that walks setup through initial, partial, and complete states, then verifies operator redirect behavior preserves operator mode after verification.

## Implemented
- Extended `tests/test_setup_step_conformance.py` with `SetupWizardLifecycleIntegrationTests`.
- Test covers:
  - initial state step label
  - partial state step label
  - complete state step label
  - `/setup/verify` completion
  - `/operator/access?next=/operator` redirect and operator nav presence

## Validation
- `pytest tests/test_setup_step_conformance.py -q`
- Result: 18 passed, 5 subtests passed
