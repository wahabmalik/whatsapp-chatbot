# Incident Tabletop Exercise: Signature Failure + Fallback Exhaustion + Rollback

**Date Conducted**: [DATE]
**Facilitator**: [OPERATIONS LEAD]
**Participants**: [List: SRE, Developer, Product, Security]
**Scenario**: Sustained signature validation failures (403 errors) + fallback retry exhaustion + emergency rollback

## Scenario Setup

### Background Situation

- Production deployment of latest release (v1.X)
- Time-of-day: [TIME] (peak/off-peak)
- Monitoring alerts firing:
  - Health degraded for 2 consecutive checks
  - Signature 403 rate: [3+ in 10 min]
  - `fallback_sent` counter incrementing
  - Error rate spike: +80% over 5-min window

### Root Cause (Injected for Tabletop)

APP_SECRET in production environment was accidentally rotated without propagating to WhatsApp webhook configuration.

---

## Tabletop Walkthrough

### T+0: Detection and Alert Escalation

**Trigger**: PagerDuty alert fires at [TIME]

| Person | Question | Answer |
|---|---|---|
| SRE | What alert fired first? | Health check returned 503 with 3+ failed health checks |
| SRE | Who gets notified? | On-call engineer + incident commander |
| Incident Cmdr | Do we declare an incident? | YES → P1 (revenue impact, API failing) |
| Comms Owner | Who do we notify? | Customer Support, Product, Leadership |

**Decisions Made**:
- [ ] Declared as P1 incident
- [ ] Incident commander assigned: [NAME]
- [ ] Communications owner assigned: [NAME]
- [ ] Slack channel created: #incident-[TIME]
- [ ] Incident tracking created: [TICKET URL]

### T+5: Triage and Root Cause Identification

**Activities**:
1. Check `/api/health` endpoint
   - [ ] Response: `{"health": "degraded", "checks": [...]}`
   - [ ] Parse degradation reason

2. Check `/api/logs` for recent errors
   - [ ] Pull logs from last 30 minutes
   - [ ] Look for patterns (signature errors? AI failures? delivery errors?)
   - [ ] Identify if issue is inbound, outbound, or both

3. Check operations runbook
   - [ ] Signature failure section: Follow triage path
   - [ ] Questions: Is server clock in sync? Does APP_SECRET match?
   - [ ] Action: Verify APP_SECRET in .env vs WhatsApp dashboard

**Findings**:
- [ ] Root cause identified: APP_SECRET mismatch
- [ ] Blast radius: All inbound webhooks failing (100% 403 rate)
- [ ] Impact duration: [TIME] (detected at [TIME])

**Decisions Made**:
- [ ] Root cause confirmed
- [ ] Decision: Immediate remediation vs rollback? [CHOICE]

### T+10: Remediation Attempt (Path A) or Immediate Rollback (Path B)

#### Path A: Live Fix (if APP_SECRET can be safely rotated)

**Steps**:
1. [ ] Update APP_SECRET in .env on production
2. [ ] Verify no in-flight requests that would be invalidated
3. [ ] Restart Flask application (or deploy via CI/CD)
4. [ ] Test inbound webhook: Send test message
5. [ ] Verify `/api/health` returns healthy
6. [ ] Confirm error rate returning to baseline

**Result**:
- [ ] Success → Continue monitoring
- [ ] Failure → Proceed to Path B (Rollback)

#### Path B: Rollback

**Trigger Decision**: Root cause not quickly fixable, or fix made situation worse

**Rollback Steps**:
1. [ ] Is previous version (v1.X-1) known-good? [YES/NO]
2. [ ] Revert code to previous release: `git revert [COMMIT]` or `git checkout [TAG]`
3. [ ] Restart application
4. [ ] Verify health: `curl /health` → 200
5. [ ] Send test message → Should succeed
6. [ ] Monitor error rate for 5 minutes → Should return to baseline

**Result**:
- [ ] Rollback successful
- [ ] System healthy
- [ ] Services restored

### T+15-30: Stabilization and Communication

**Activities**:
- [ ] Confirm no new errors in `/api/logs`
- [ ] Check `fallback_sent` counter → Should stop incrementing
- [ ] Pull metrics snapshot for postmortem
- [ ] Send all-clear to support team
- [ ] Create postmortem task for follow-up

**Communication**:
- [ ] Notify customers of resolution
- [ ] Document incident timeline and decisions
- [ ] Schedule postmortem for next business day

---

## Key Decision Points

| Scenario | Decision | Justification |
|---|---|---|
| Signature 403 appears but metrics still low | **Monitor** | Likely transient; continue observing |
| Error rate sustained > 10 min | **Alert escalation** | Indicates systemic issue; escalate |
| `fallback_sent` > 0 | **CRITICAL** | Retry exhaustion; immediate action required |
| Health degraded > 2 consecutive checks | **Declare incident** | Per ops runbook threshold |
| Fix attempt unsuccessful after 5 min | **Rollback** | Stop digging; restore previous version |

---

## Observability Evidence Checklist

During tabletop, verify these observability points exist and are accessible:

- [ ] Health endpoint: `GET /health` returns status structure
- [ ] Metrics endpoint: `GET /metrics` shows counters (error_count, fallback_sent, etc.)
- [ ] Dashboard health: `GET /api/health` works without auth
- [ ] Logs API: `GET /api/logs` shows recent errors with correlation IDs
- [ ] Operator metrics: `GET /operator/metrics` requires session
- [ ] Error logging: Signature errors include APP_SECRET mismatch hint
- [ ] Correlation IDs: All events linked by request_id

---

## Tabletop Outcomes

### What Went Well

- [ ] Alert fired within [TIME] of anomaly
- [ ] Team oriented quickly
- [ ] Runbook was clear and followed
- [ ] Root cause identified in < 10 minutes
- [ ] Remediation path clear

### What Could Improve

- [ ] [OBSERVATION]
- [ ] [OBSERVATION]
- [ ] [OBSERVATION]

### Process Gaps Identified

- [ ] [GAP]
- [ ] [GAP]

---

## Follow-Up Actions

| Action | Owner | Due Date | Notes |
|---|---|---|---|
| [ACTION] | [OWNER] | [DATE] | [NOTES] |
| [ACTION] | [OWNER] | [DATE] | [NOTES] |

---

## Sign-Off

- **Facilitator**: ________________________________ **Date**: ______________
- **Status**: ✅ PASS (Team confident in incident response) / ❌ FAIL (Needs rework)

---

**Evidence Location**: `_bmad-output/test-artifacts/incident-tabletop-[DATE].md`
**Referenced by**: `docs/operations_runbook.md`
**GO/NO-GO Impact**: Validates incident response procedures and observability sufficiency
