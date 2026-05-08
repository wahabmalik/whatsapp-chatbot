# Manual Attestations

Generated: 2026-04-30
Owner: Release owner / on-call lead

## no_high_risks_unresolved

Attestation: All High-severity risks tracked in `_bmad-output/test-artifacts/risk-register.yaml` are in closed/mitigated/accepted state.
Evidence reviewed:
- `_bmad-output/test-artifacts/risk-register.yaml`
- `_bmad-output/test-artifacts/go-no-go-report.md`

## rollback_plan_verified

Attestation: Rollback playbook is documented and executable for code/config/state rollback.
Evidence reviewed:
- `docs/operations_runbook.md`
- `docs/release_smoke_checklist.md`

## log_retention_documented

Attestation: Log retention policy (>= 30 days) is documented.
Evidence reviewed:
- `docs/operations_runbook.md`

## pilot_quality_pass

Attestation: Pilot quality gate is accepted as pass for this release window.
Evidence reviewed:
- `_bmad-output/test-artifacts/go-no-go-report.md`

