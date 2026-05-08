# Process and Evidence Hygiene - Implementation Guide

**Date**: 2026-05-02
**Status**: Process improvements implemented
**Scope**: Documentation drift prevention, traceability consistency, release governance hardening

---

## Overview

This guide documents the process and evidence hygiene improvements implemented to address residual risks identified in the Epic 4 Retrospective. These are **not** functional code changes, but rather **process automation** and **governance safeguards** to prevent regression and drift.

### Why These Improvements Matter

- **Documentation drift** was real: aliases existed but without enforcement
- **Contract drift** occurred: documented routes didn't always match implementation
- **Evidence gaps** remained: operational readiness was manual/ad-hoc
- **Traceability** lacked rigor: no automated validation of schema consistency

---

## Implementation Checklist

### 1. Docs-Runtime Endpoint Contract Test ✅ DONE

**File**: [tests/test_docs_runtime_endpoint_contract.py](../tests/test_docs_runtime_endpoint_contract.py)

**What It Does**:
- Verifies all endpoints documented in `docs/operations_runbook.md` are implemented
- Validates endpoint HTTP methods, content-type headers, and accessibility
- Catches route drift before release

**Endpoints Validated**:
- `GET /health` (public health)
- `GET /metrics` (public metrics)
- `GET /api/health` (dashboard health API)
- `GET /api/metrics` (dashboard metrics API)
- `GET /api/logs` (dashboard logs API)
- `GET /operator/metrics` (operator portal metrics)
- `POST /webhook` (inbound webhook)

**Run It**:
```bash
python -m pytest tests/test_docs_runtime_endpoint_contract.py -v
```

**Success Criteria**: All 8 endpoint tests pass
**CI Integration**: Add to GitHub Actions workflow as required pre-merge gate

---

### 2. Launch-Gate Schema Parity Test ✅ DONE

**File**: [tests/test_launch_gate_schema_parity.py](../tests/test_launch_gate_schema_parity.py)

**What It Does**:
- Validates `launch-gates.yaml` schema consistency
- Ensures all gates have required fields (key, name, blocking, domain)
- Verifies blocking gates are mapped to test implementations
- Checks for orphaned or duplicate gate keys

**Gate Key Format**:
- Expected: `E4-SEC-05`, `E4-OPS-01`, `E4-REL-04`
- Validates uniqueness and proper domain classification

**Run It**:
```bash
python -m pytest tests/test_launch_gate_schema_parity.py -v
```

**Success Criteria**: No duplicate/invalid gate keys; all blocking gates have implementation references
**CI Integration**: Add to pre-merge validation gates

---

### 3. Sprint-Status Integrity Validator ✅ DONE

**File**: [validate_sprint_status_integrity.py](../validate_sprint_status_integrity.py)

**What It Does**:
- Validates `sprint-status.yaml` for consistency
- Checks story/epic status transitions (prevents invalid state leaps)
- Ensures epic status reflects aggregate of story statuses
- Validates retrospective markers for completed epics
- Confirms `last_updated` timestamp is fresh

**Valid Story Statuses**:
- `backlog` → `ready-for-dev`, `in-progress`, `done`
- `ready-for-dev` → `in-progress`, `backlog`, `done`
- `in-progress` → `review`, `backlog`, `done`
- `review` → `in-progress`, `done`, `backlog`
- `done` → `backlog`

**Run It**:
```bash
python validate_sprint_status_integrity.py
```

**Integration into Pre-Merge Checks**:
```bash
# Add to CI/CD pipeline
python validate_sprint_status_integrity.py || exit 1
```

**Success Criteria**: 
- No invalid status transitions
- All epic statuses correctly reflect story completion
- Retrospectives exist for completed epics
- `last_updated` < 24 hours old

---

### 4. Documentation Alias Integrity Linter ✅ DONE

**File**: [validate_docs_alias_integrity.py](../validate_docs_alias_integrity.py)

**What It Does**:
- Enforces alias file policy (redirect-only, no substantive docs)
- Verifies aliases reference canonical documents
- Checks canonical docs have sufficient content
- Prevents circular reference chains
- Ensures alias files are brief (< 15 lines)

**Alias Mappings**:
- `docs/setup-guide.md` → `docs/setup_guide.md` (canonical)
- `docs/runbook.md` → `docs/operations_runbook.md` (canonical)

**Run It**:
```bash
python validate_docs_alias_integrity.py
```

**Integration**: Add to pre-merge checks
```bash
python validate_docs_alias_integrity.py || exit 1
```

**Success Criteria**:
- All alias files are < 15 lines
- All alias files reference canonical docs
- No circular references
- Canonical docs have > 30 lines of substance

---

### 5. Environment and Readiness Validator ✅ DONE

**File**: [validate_environment_and_readiness.py](../validate_environment_and_readiness.py)

**What It Does**:
- Standardizes environment validation (removes ambiguity)
- Checks `.env` file existence and required variables
- Validates Python environment and virtual environment
- Checks dependency installation
- Generates JSON report for traceability

**Required Variables** (base):
- `WHATSAPP_PROVIDER`
- `APP_SECRET`
- `OPENAI_API_KEY`

**Provider-Specific Variables**:
- Evolution: `EVOLUTION_API_URL`, `EVOLUTION_API_KEY`, `EVOLUTION_INSTANCE_NAME`
- Meta: `ACCESS_TOKEN`, `PHONE_NUMBER_ID`, `VERSION`

**Run It**:
```bash
python validate_environment_and_readiness.py
```

**Output**: 
- Console pass/fail summary
- JSON report at: `_bmad-output/test-artifacts/environment-validation-report.json`

**Success Criteria**:
- .env file exists
- All required variables are set
- Python dependencies installed
- Report artifact created

---

## Operational Evidence Artifacts

### 6. Clean-Room Onboarding Dry-Run Template ✅ DONE

**File**: [_bmad-output/test-artifacts/clean-room-onboarding-template.md](_bmad-output/test-artifacts/clean-room-onboarding-template.md)

**What It Is**:
- Standardized checklist for executing fresh onboarding on clean VM
- Captures timing evidence (target: 45 min E2E, 2 min config entry)
- Records command transcript and test results
- Provides observability validation points

**Execution Steps**:
1. Obtain clean VM (no prior config)
2. Follow template checklist
3. Record all timings and results
4. Save as evidence artifact: `clean-room-onboarding-[DATE].md`
5. Link to smoke checklist for release gate

**Success Criteria**:
- Onboarding completed in ≤ 45 minutes
- All tests passed
- Logs contain expected correlation IDs
- Artifact signed off by executor

**Release Impact**: Confirms operator onboarding procedures are correct and timely

---

### 7. Incident Tabletop Exercise Template ✅ DONE

**File**: [_bmad-output/test-artifacts/incident-tabletop-template.md](_bmad-output/test-artifacts/incident-tabletop-template.md)

**What It Is**:
- Scenario-based walkthrough of incident response
- Validates runbook correctness and team capability
- Tests observability sufficiency under stress
- Documents decision points and escalation paths

**Example Scenarios**:
1. Signature validation failures (403 spike) + APP_SECRET mismatch
2. Fallback retry exhaustion + message delivery halted
3. Emergency rollback procedures

**Execution Steps**:
1. Assemble cross-functional team (SRE, developer, product, security)
2. Walk through scenario using tabletop format
3. Identify decision points and validate runbook guidance
4. Test observability (health, metrics, logs endpoints)
5. Record outcomes and gaps

**Success Criteria**:
- Team can identify root cause in < 10 minutes
- Remediation or rollback path is clear
- All observability endpoints are accessible
- Post-incident actions documented

**Release Impact**: Validates operational readiness and incident response capability

---

## Integration into Release Process

### Pre-Merge Validation Gates

Add these scripts to CI/CD pipeline (GitHub Actions or equivalent):

```yaml
validation-gates:
  - name: Docs-Runtime Endpoint Contract
    run: python -m pytest tests/test_docs_runtime_endpoint_contract.py -v
  
  - name: Launch-Gate Schema Parity
    run: python -m pytest tests/test_launch_gate_schema_parity.py -v
  
  - name: Sprint-Status Integrity
    run: python validate_sprint_status_integrity.py
  
  - name: Docs Alias Integrity
    run: python validate_docs_alias_integrity.py
  
  - name: Environment Readiness
    run: python validate_environment_and_readiness.py
```

### Pre-Release Evidence Requirements

Before final release sign-off, ensure these artifacts exist and are passing:

1. ✅ All automated validation checks pass (above)
2. ✅ Clean-room onboarding dry-run completed and signed off
3. ✅ Incident tabletop completed with acceptable results
4. ✅ Sprint status integrity verified
5. ✅ All documentation aliases pass linting
6. ✅ Endpoint contract tests pass

---

## Observability and Troubleshooting

### Running Individual Validators

```bash
# Endpoint contract
python -m pytest tests/test_docs_runtime_endpoint_contract.py -v

# Gate schema parity
python -m pytest tests/test_launch_gate_schema_parity.py -v

# Sprint status
python validate_sprint_status_integrity.py

# Docs aliases
python validate_docs_alias_integrity.py

# Environment
python validate_environment_and_readiness.py
```

### Troubleshooting Common Failures

| Error | Cause | Resolution |
|---|---|---|
| `404` on endpoint test | Route not implemented | Add missing route to Flask app |
| `Invalid gate key format` | Gate key doesn't match pattern | Fix key in launch-gates.yaml to match `E4-XXX-##` |
| `Epic status mismatch` | Epic status doesn't reflect stories | Update epic status in sprint-status.yaml |
| `Alias too long` | Redirect file has too much content | Move content to canonical file |
| `Missing environment variable` | .env incomplete | Run `python validate_environment_and_readiness.py` for guided fix |

---

## Evidence Artifacts Location

All generated evidence and reports are stored in `_bmad-output/test-artifacts/`:

- `environment-validation-report.json` - Environment readiness evidence
- `clean-room-onboarding-[DATE].md` - Onboarding execution proof
- `incident-tabletop-[DATE].md` - Incident response validation
- `release-quality-matrix.md` - Aggregate release readiness summary

---

## Next Steps

1. **Integrate into CI/CD**: Add all validation scripts to GitHub Actions pre-merge gates
2. **Execute Evidence**: Schedule clean-room onboarding and incident tabletop for next release
3. **Monitor Drift**: Run validators before every merge and release
4. **Iterate**: Collect lessons and refine templates based on execution experience

---

## Related Documentation

- [Epic 4 Retrospective](../_bmad-output/implementation-artifacts/epic-4-retro-2026-05-01.md)
- [Operations Runbook](../docs/operations_runbook.md)
- [Setup Guide](../docs/setup_guide.md)
- [Release Smoke Checklist](../docs/release_smoke_checklist.md)

---

**Owner**: Amelia (Developer)
**Last Updated**: 2026-05-02
**Status**: ✅ Implementation Complete
