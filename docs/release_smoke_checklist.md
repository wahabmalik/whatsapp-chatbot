# Release Smoke Checklist

Run this checklist for each promotion stage.  
Operator performing checklist: ___________________  Date: ___________________

## Evidence artifacts and automation

| Step | Command / artifact | Output location |
|---|---|---|
| Run unit tests | `python -m unittest discover tests` | Console |
| Generate test results summary | `python start/generate_test_results_summary.py` | `_bmad-output/test-artifacts/test-results-summary.json` |
| Run staging validation | `python start/staging_validation.py` | `_bmad-output/test-artifacts/staging-validation-report.json` |
| Evaluate launch gates | `python start/evaluate_launch_gates.py` | `_bmad-output/test-artifacts/go-no-go-report.md` |
| Review risk register | Manual | `_bmad-output/test-artifacts/risk-register.yaml` |
| Attest manual gates | Manual | `_bmad-output/test-artifacts/manual-attestations.md` |

Launch gate configuration: `_bmad-output/test-artifacts/launch-gates.yaml`

## Pre-staging

Satisfies launch gate domain: **security** and **reliability** (automated)

- [ ] Environment variables validated and complete (no missing required keys)
- [ ] App boots with no startup validation errors (`GET /health` returns `healthy`)
- [ ] GET `/health` and GET `/api/health` both return healthy payloads
- [ ] `python -m unittest discover tests` — all tests pass
- [ ] Signature validation tests pass (gate: `SAAS6-SEC-ALL`, `SAAS6-SEC-04`)
- [ ] Idempotency tests pass for configured state backend (gates: `SAAS6-REL-01`, `SAAS6-REL-02`, `SAAS6-REL-03`)

## Staging

Satisfies launch gate domain: **reliability** and **performance** (automated via `staging_validation.py`)

- [ ] Webhook verification succeeds with Meta callback challenge (200 on GET `/webhook`)
- [ ] Inbound webhook with valid signature returns success path
- [ ] Invalid signature is rejected with 403 and no secret leakage in response body
- [ ] Outbound retry policy observed: 1 + 3 retries at 1 s / 2 s / 4 s backoff (gate: `SAAS6-REL-05`)
- [ ] Fallback reply is sent after retry exhaustion (gate: `SAAS6-REL-06`)
- [ ] Operator review flag is present for fallback events
- [ ] GET `/metrics` and GET `/api/metrics` report expected counters
- [ ] GET `/api/logs` shows correlation-linked incident records for failed paths
- [ ] P50 latency ≤ 4 s, P95 ≤ 8 s, success rate ≥ 99%, throughput ≥ 10 msg/s (gates: `SAAS6-PERF-01` – `SAAS6-PERF-04`)
- [ ] Staging run uses ≥ 1000 samples (gate: `SAAS6-PERF-06`)
- [ ] `staging-validation-report.json` generated and checked into test-artifacts

## Pilot

Satisfies launch gate: **SAAS6-ADV-02** (advisory)

- [ ] Pilot users can complete target flow without manual intervention
- [ ] No unresolved High-severity risks remain open (gate: `SAAS6-OPS-04`)
- [ ] Escalation path has owner and SLA defined
- [ ] Pilot quality score ≥ 4/5 recorded in `manual-attestations.md#pilot_quality_pass`

## Production release gate

Satisfies launch gates: **SAAS6-OPS-01**, **SAAS6-OPS-02**, **SAAS6-OPS-03**, **SAAS6-OPS-05**

- [ ] `docs/setup_guide.md` present and current (gate: `SAAS6-OPS-01`)
- [ ] `docs/operations_runbook.md` present and current (gate: `SAAS6-OPS-02`)
- [ ] `docs/release_smoke_checklist.md` present and current (gate: `SAAS6-OPS-03`)
- [ ] Unit tests green — `python -m unittest discover tests`
- [ ] Security-critical subset green (gate: `SAAS6-SEC-ALL`)
- [ ] `test-results-summary.json` generated at `_bmad-output/test-artifacts/`
- [ ] `staging-validation-report.json` available at `_bmad-output/test-artifacts/`
- [ ] Risk-register manual gates attested in `risk-register.yaml` (gate: `SAAS6-OPS-04`)
- [ ] Rollback plan documented and tested — see `docs/operations_runbook.md` § 5 (gate: `SAAS6-OPS-05`)
- [ ] Log retention (≥ 30 days) confirmed in runbook (gate: `SAAS6-ADV-01`)
- [ ] Launch gate evaluator reports GO — `python start/evaluate_launch_gates.py`
- [ ] `go-no-go-report.md` attached to release review packet at `_bmad-output/test-artifacts/`

## Rollback readiness

- [ ] Last known good release is identified (commit hash recorded: ___________________)
- [ ] Code rollback procedure tested per `docs/operations_runbook.md` § 5
- [ ] Config rollback procedure tested per `docs/operations_runbook.md` § 5
- [ ] Agent rollback procedure confirmed per `docs/operations_runbook.md` § 5
- [ ] On-call owner acknowledged release window
  - Owner: ___________________  Acknowledged: ___________________

## Operator dashboard references

For monitoring and incident response during and after release:
- Operator metrics HTML: GET `/operator/metrics` — HTML page; requires operator session (`/operator/access`)
- Dashboard health API: GET `/api/health` — JSON; no session required
- Dashboard metrics API: GET `/api/metrics` — JSON; no session required
- Dashboard logs API: GET `/api/logs` — JSON; no session required
- Public health: GET `/health` — unauthenticated JSON
- Public metrics: GET `/metrics` — unauthenticated JSON

See `docs/operations_runbook.md` for incident escalation and triage procedures.
