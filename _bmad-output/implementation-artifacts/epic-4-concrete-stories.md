# Epic 4 Concrete Implementation Stories and Test Tasks

## Purpose

Convert Epic 4 (Release Readiness and Operational Assurance) into executable work items that produce launch evidence, not just planned intent.

## Assumptions

- Stories 1.1 through 3.3 are functionally implemented but may still need evidence-level validation.
- Existing unit tests in `tests/` provide partial coverage and should be expanded rather than replaced.
- Launch gate targets remain:
  - Message success rate >= 99% across 1000 staging messages
  - P50 latency <= 4s, P95 latency <= 8s
  - Throughput >= 10 msg/sec in staging
  - Fallback delivery <= 10s from first API failure
  - Security critical tests: 100% pass

---

## Story 4.1.1 - Build Critical Path Test Matrix

### Outcome

A traceable matrix maps PRD/FR/NFR launch obligations to automated tests and evidence artifacts.

### Scope

- Create a release quality matrix document at `_bmad-output/test-artifacts/release-quality-matrix.md`.
- Map each of the following to test IDs and pass criteria:
  - Startup validation and setup gating
  - GET webhook verification
  - POST signature rejection paths (invalid header, bad digest, stale timestamp, replay)
  - Inbound normalization and idempotency (memory + sqlite fallback)
  - OpenAI controlled failure states
  - Outbound retry/fallback and operator-review flag
  - Agent selection stale-state auto-repair
- Add ownership and "blocking vs non-blocking" release classification.

### Acceptance Criteria

1. Every Epic 4.1 acceptance point is represented in the matrix.
2. Every mapped check has explicit expected evidence (test report, metrics snapshot, checklist item).
3. Matrix identifies at least one blocking gate each for Security, Reliability, and Operations.

### Concrete Tasks

- [ ] Draft matrix sections: Security, Reliability, Latency/Performance, Ops Docs, Go/No-Go.
- [ ] Assign test IDs with naming convention `E4-<domain>-<number>`.
- [ ] Add trace links to source requirement IDs (FR1-FR10, NFR1-NFR8).

---

## Story 4.1.2 - Expand Automated Test Coverage for Missing Risk Paths

### Outcome

Automated tests cover all critical P0 regression paths identified in Epic 4.1.

### Scope

- Extend `tests/test_reliability.py` with missing scenarios:
  - Positive signature acceptance with valid timestamp and replay uniqueness
  - Correlation ID propagation assertion through error responses/log payload where feasible
  - Outbound retry sequence timing behavior (1s, 2s, 4s) via mocked clock/sleep
  - Fallback sent and operator-review flag emitted after retries exhausted
  - Controlled OpenAI failure mapping to typed state (timeout/auth/rate-limit)
- Add focused test module `tests/test_release_gates.py` for gate aggregation logic/checklist validation.

### Acceptance Criteria

1. Test suite includes explicit assertions for retry attempt count and fallback trigger conditions.
2. Fallback timing test demonstrates compliance with <= 10s recovery target under simulated failure.
3. Security path tests for webhook signature checks are all green and grouped for gate reporting.

### Concrete Tasks

- [ ] Add deterministic mocks around network/provider calls.
- [ ] Add marker or naming convention for security-critical tests.
- [ ] Add helper fixtures for canonical webhook payload generation.

---

## Story 4.1.3 - Implement Staging Validation Runner and Metrics Evidence Export

### Outcome

A repeatable staging validation command produces success-rate, latency, and throughput evidence files.

### Scope

- Add a script at `start/staging_validation.py` (or equivalent) that:
  - Runs a controlled batch of message-flow checks
  - Captures outcome stats: total, success, failure, retries, fallback count
  - Computes latency percentiles (P50/P95)
  - Computes observed throughput
- Export report JSON to `_bmad-output/test-artifacts/staging-validation-report.json`.
- Export human-readable summary to `_bmad-output/test-artifacts/staging-validation-summary.md`.

### Acceptance Criteria

1. Script can be executed from repository root with a single documented command.
2. Output artifacts include timestamp, environment target, and gate pass/fail booleans.
3. Report format is stable enough for CI parsing.

### Concrete Tasks

- [ ] Define report schema with explicit gate keys (`security_pass`, `latency_pass`, etc.).
- [ ] Add percentile utility and deterministic sample-size handling.
- [ ] Include non-zero failure-path sample to validate fallback and escalation counters.

---

## Story 4.1.4 - Add Launch Gate Aggregator and Blocking Decision Logic

### Outcome

Go/No-Go decision becomes deterministic and machine-checkable.

### Scope

- Add launch gate config file: `_bmad-output/test-artifacts/launch-gates.yaml`.
- Add checker script: `start/evaluate_launch_gates.py`.
- Checker consumes:
  - Unit/integration test result summary
  - Staging validation report
  - Risk register status input (manual JSON/YAML)
  - Ops docs completion checklist
- Emit final decision artifact: `_bmad-output/test-artifacts/go-no-go-report.md`.

### Acceptance Criteria

1. Any failed blocking criterion yields `NO-GO` with explicit failure reasons.
2. Output includes unresolved high-risk count and fallback timing verdict.
3. Gate evaluation is reproducible from committed artifacts and script inputs.

### Concrete Tasks

- [ ] Define blocking and advisory criteria in one source-of-truth config.
- [ ] Add parser validation with actionable errors for malformed input artifacts.
- [ ] Add tests for `GO`, `NO-GO`, and `UNKNOWN` decision paths.

---

## Story 4.2.1 - Deliver Operator Setup Guide (First-Time Onboarding)

### Outcome

A concise setup guide enables a clean-room user to reach successful verification and first test message.

### Scope

- Create `docs/setup_guide.md` with:
  - Prerequisites and environment variable checklist
  - `/setup` flow walkthrough and verification endpoint usage
  - Callback URL and verify token setup with Meta
  - First test message and expected signals in dashboard/logs
  - Troubleshooting quick table (symptom -> cause -> fix)
- Explicitly separate:
  - Quick config-entry target (< 2 min)
  - Full time-to-first-message target (<= 45 min)

### Acceptance Criteria

1. Guide is executable as a numbered runbook without hidden prerequisites.
2. Contains expected success/failure outputs for each critical step.
3. Includes safe handling guidance for secrets and token redaction.

### Concrete Tasks

- [ ] Document required env keys from runtime validation source.
- [ ] Add screenshot placeholders/anchors for setup UI states.
- [ ] Add "known-good baseline" checklist before staging handoff.

---

## Story 4.2.2 - Deliver Operations Runbook, Monitoring, and Rollback Playbook

### Outcome

On-call operators can detect, triage, and recover from production issues consistently.

### Scope

- Create `docs/operations_runbook.md` with sections:
  - Incident severity and escalation triggers
  - Signature failure triage flow
  - OpenAI/API instability and fallback verification flow
  - Metrics and logs inspection procedure (`/health`, `/metrics`, `/logs`)
  - Agent selection repair checks
  - Rollback procedure to known-good env/config/code
  - Post-incident evidence capture checklist
- Create `docs/release_smoke_checklist.md` for pre-staging, staging, pilot, and release gates.

### Acceptance Criteria

1. Runbook includes explicit rollback triggers and rollback verification steps.
2. Monitoring section defines thresholds and alert expectations for errors, duplicates, and outbound failures.
3. Smoke checklist can be executed by a team member not involved in implementation.

### Concrete Tasks

- [ ] Add decision trees for "continue", "degrade", and "rollback".
- [ ] Add minimum on-call contact protocol and ownership slots.
- [ ] Add artifact links required for go/no-go meeting package.

---

## Story 4.2.3 - CI Quality Gate Wiring

### Outcome

Critical release checks run automatically and block regressions.

### Scope

- Add CI workflow config (project-appropriate location) to run:
  - Unit/integration tests
  - Security-critical subset with hard fail
  - Launch gate evaluator against staged artifacts
- Persist test and gate artifacts as CI artifacts.

### Acceptance Criteria

1. CI fails immediately when any blocking gate fails.
2. CI output includes links to evidence artifacts used for decision.
3. CI pipeline documents which checks are required for MVP release.

### Concrete Tasks

- [ ] Define workflow stages and dependency order.
- [ ] Add artifact upload step for test/gate reports.
- [ ] Add branch protection recommendation tied to gate status.

---

## Test Task Backlog (Ready to Pick Up)

1. E4-SEC-01: Verify GET webhook token mismatch returns 403 and no secret leakage.
2. E4-SEC-02: Verify POST signature checks reject malformed header, bad digest, stale timestamp, replay.
3. E4-SEC-03: Verify rejection logs include correlation ID and reason code.
4. E4-REL-01: Verify duplicate message suppression in memory and sqlite modes.
5. E4-REL-02: Verify sqlite init failure falls back to memory when configured.
6. E4-REL-03: Verify outbound retry schedule uses exactly 1/2/4 seconds.
7. E4-REL-04: Verify fallback message and operator-review flag after retry exhaustion.
8. E4-PERF-01: Validate P50/P95 latency from staged flow samples.
9. E4-PERF-02: Validate >= 10 msg/sec throughput in staging run.
10. E4-OPS-01: Validate smoke checklist against a clean environment.
11. E4-OPS-02: Validate rollback drill end-to-end with verification checkpoints.
12. E4-OPS-03: Validate setup guide path reaches first test message within target.

---

## Suggested Delivery Order

1. Story 4.1.1 (matrix) - establish traceability baseline.
2. Story 4.1.2 (test gaps) - close critical automation gaps.
3. Story 4.1.3 (staging runner) - generate measurable evidence.
4. Story 4.1.4 (gate evaluator) - codify launch decision.
5. Story 4.2.1 and 4.2.2 (docs/runbook/smoke) - operator readiness.
6. Story 4.2.3 (CI wiring) - enforce continuously.

## Definition of Done for Epic 4

- All blocking tests green.
- Launch gate evaluator returns GO using current artifacts.
- Setup guide, runbook, and smoke checklist are reviewed and runnable.
- No unresolved High risks remain in the release decision package.
