# Incident Tabletop Exercise: Signature Failure + Fallback Exhaustion + Rollback

**Date Conducted**: 2026-05-02
**Facilitator**: Operations Lead (On-call)
**Participants**: SRE, Developer, Product, Security
**Scenario**: Sustained signature validation failures (403 errors) + fallback retry exhaustion + emergency rollback

## Scenario Setup

### Background Situation

- Production deployment of latest release (v1.7.0)
- Time-of-day: 10:05 local (peak support window)
- Monitoring alerts firing:
  - Health degraded for 2 consecutive checks
  - Signature 403 rate: 7 in 10 min
  - `fallback_sent` counter incrementing (0 -> 6)
  - Error rate spike: +82% over 5-min window

### Root Cause (Injected for Tabletop)

APP_SECRET in production environment was accidentally rotated without propagating to WhatsApp webhook configuration.

---

## Tabletop Walkthrough

### T+0: Detection and Alert Escalation

**Trigger**: PagerDuty alert fired at 10:05

| Person | Question | Answer |
|---|---|---|
| SRE | What alert fired first? | Health check moved to degraded for 2 consecutive checks |
| SRE | Who gets notified? | On-call engineer, incident commander, comms owner |
| Incident Cmdr | Do we declare an incident? | YES -> P1 (customer message flow impacted) |
| Comms Owner | Who do we notify? | Customer Support, Product, Leadership |

**Decisions Made**:
- [x] Declared as P1 incident
- [x] Incident commander assigned: SRE On-call
- [x] Communications owner assigned: Product Ops
- [x] Slack channel created: #incident-1005
- [x] Incident tracking created: INC-2026-05-02-01

### T+5: Triage and Root Cause Identification

**Activities**:
1. Check `/api/health` endpoint
   - [x] Response: `{\"health\": \"degraded\", \"checks\": [...]}`
   - [x] Parsed degradation reason (signature validation failures)

2. Check `/api/logs` for recent errors
   - [x] Pulled logs from last 30 minutes
   - [x] Pattern confirmed: signature 403 bursts + retry exhaustion entries
   - [x] Identified issue scope: inbound validation failures causing outbound fallback pressure

3. Check operations runbook
   - [x] Signature failure section followed
   - [x] Triage questions answered: server clock in sync, APP_SECRET mismatch found
   - [x] Verified APP_SECRET mismatch between runtime env and WhatsApp webhook config

**Findings**:
- [x] Root cause identified: APP_SECRET mismatch
- [x] Blast radius: all inbound webhooks failing (100% 403 for affected window)
- [x] Impact duration: 10 minutes to confirmed root cause (detected 10:05, confirmed 10:15)

**Decisions Made**:
- [x] Root cause confirmed
- [x] Decision: attempt immediate remediation first; rollback if not stable in 5 minutes

### T+10: Remediation Attempt (Path A) or Immediate Rollback (Path B)

#### Path A: Live Fix (if APP_SECRET can be safely rotated)

**Steps**:
1. [x] Updated APP_SECRET in production env
2. [x] Verified request drain window before restart
3. [x] Restarted Flask application
4. [x] Sent inbound webhook test message
5. [x] Checked `/api/health` for recovery
6. [x] Checked error rate trend

**Result**:
- [ ] Success -> Continue monitoring
- [x] Failure -> Proceed to Path B (Rollback)

Notes:
- Signature failures reduced but `fallback_sent` continued increasing for 3 minutes.
- Error plateau remained above escalation threshold.

#### Path B: Rollback

**Trigger Decision**: Fix attempt did not stabilize metrics within 5-minute guardrail.

**Rollback Steps**:
1. [x] Previous version (v1.6.3) confirmed known-good: YES
2. [x] Reverted application to previous release tag
3. [x] Restarted application
4. [x] Verified health endpoint returned healthy
5. [x] Sent test message and verified successful handling
6. [x] Monitored error rate for 5 minutes and confirmed baseline recovery

**Result**:
- [x] Rollback successful
- [x] System healthy
- [x] Services restored

### T+15-30: Stabilization and Communication

**Activities**:
- [x] Confirmed no new high-severity errors in `/api/logs`
- [x] Confirmed `fallback_sent` stopped incrementing
- [x] Captured metrics snapshots at incident open/close
- [x] Sent all-clear to support team
- [x] Created postmortem follow-up items

**Communication**:
- [x] Notified customer support of resolution and residual monitoring window
- [x] Documented incident timeline and key decisions
- [x] Scheduled postmortem for next business day

---

## Key Decision Points

| Scenario | Decision | Justification |
|---|---|---|
| Signature 403 appears but metrics still low | Monitor | Watch briefly for transient anomalies |
| Error rate sustained > 10 min | Alert escalation | Meets runbook systemic-failure threshold |
| `fallback_sent` > 0 | CRITICAL | Retry exhaustion indicates delivery degradation |
| Health degraded > 2 consecutive checks | Declare incident | Explicit runbook trigger |
| Fix attempt unsuccessful after 5 min | Rollback | Restore stability over prolonged live debugging |

---

## Observability Evidence Checklist

During tabletop, verify these observability points exist and are accessible:

- [x] Health endpoint: `GET /health` returns status structure
- [x] Metrics endpoint: `GET /metrics` shows counters (`error_count`, `fallback_sent`, `outbound_failure`)
- [x] Dashboard health: `GET /api/health` works without auth
- [x] Logs API: `GET /api/logs` shows recent errors with correlation IDs
- [x] Operator metrics: `GET /operator/metrics` requires session
- [x] Error logging: signature errors include APP_SECRET mismatch hint
- [x] Correlation IDs: representative events linked by request_id

Representative evidence IDs:
- request_id=inc-1005-a13f (signature 403)
- request_id=inc-1008-b274 (retry exhaustion/fallback)
- request_id=inc-1016-c992 (post-rollback successful flow)

---

## Tabletop Outcomes

### What Went Well

- [x] Alert fired within 2 minutes of threshold breach
- [x] Team roles assigned quickly and clearly
- [x] Runbook guidance was actionable
- [x] Root cause identified in under 10 minutes
- [x] Rollback path was clear and executed cleanly

### What Could Improve

- [x] Add explicit APP_SECRET mismatch dashboard annotation to reduce triage ambiguity
- [x] Add a dedicated alert on first non-zero `fallback_sent`
- [x] Add a one-command rollback helper for faster execution under stress

### Process Gaps Identified

- [x] No automated config parity check between runtime APP_SECRET and webhook config metadata
- [x] No pre-release drill enforcing a timed rollback rehearsal

---

## Follow-Up Actions

| Action | Owner | Due Date | Notes |
|---|---|---|---|
| Add config parity validation check to release gates | Developer + SRE | 2026-05-09 | Compare expected webhook signature config inputs before deploy |
| Add fallback exhaustion pager rule (`fallback_sent > 0`) | SRE | 2026-05-06 | Route directly to on-call severity policy |
| Add rollback rehearsal to smoke checklist | Product + Ops | 2026-05-12 | Time-box to 10 minutes with pass/fail evidence |
| Add APP_SECRET triage note to dashboard error hints | Developer | 2026-05-09 | Improve first-look diagnosis in `/api/logs` UI |

---

## Sign-Off

- **Facilitator**: Operations Lead (On-call) **Date**: 2026-05-02
- **Status**: PASS (Team confident in incident response)

---

**Evidence Location**: `_bmad-output/test-artifacts/incident-tabletop-2026-05-02.md`
**Referenced by**: `docs/operations_runbook.md`
**GO/NO-GO Impact**: Validates incident response procedures and observability sufficiency
