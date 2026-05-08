# Critical Product Paths Release Gate - Quick Reference

**For**: Release Owner  
**When**: Before every production deployment  
**Time**: <2 minutes

---

## Pre-Deployment Checklist

### Step 1: Run Local Gate (2 min)
```bash
cd ~/project
python run_release_gate.py --domain ALL
```

**Expected Output**:
```
============================================================================
RELEASE GATE SUMMARY
============================================================================

  SECURITY                  ✅ PASS
  RELIABILITY               ✅ PASS
  LATENCY                   ✅ PASS
  INTEGRATION               ✅ PASS

Overall: 4/4 domains passed
Duration: 12.34s

🚀 RELEASE GATE PASSED - Safe to deploy
============================================================================
```

### Step 2: Check CI/CD Status
- Go to GitHub Actions
- Verify `release-gate-critical-paths.yml` shows all ✅
- Check PR comments for test results

### Step 3: Decision Tree

```
ALL TESTS PASS?
├─ YES → Deploy with confidence ✅
└─ NO → Investigate
        ├─ Security failure? → BLOCK deployment 🛑
        ├─ Reliability failure? → Investigate + fix
        ├─ Latency failure? → Profile + optimize
        └─ Integration failure? → Root cause analysis
```

---

## Emergency: Test Failures

### 🔒 Security Test Failed (E-CPP-SEC-*)
```
ACTION: BLOCK DEPLOYMENT IMMEDIATELY

Likely cause:
  - Signature validation changed
  - Auth token logic modified
  - Input sanitization removed
  - Provider switch security context broken

Investigation (5 min):
  git log --oneline -10  # Recent changes?
  git diff HEAD~5 app/decorators/security.py  # Check signature logic
  
Recovery:
  Option 1: git revert <commit>
  Option 2: Fix security bug
  Option 3: Contact engineering lead
```

### 🛡️ Reliability Test Failed (E-CPP-REL-*)
```
ACTION: INVESTIGATE - May block deployment

Likely cause:
  - Message idempotency broken
  - Retry logic removed
  - Database error handling changed
  - Startup resilience issue
  - Health check inaccurate

Investigation (10 min):
  python -m pytest tests/test_critical_product_paths.py::CriticalPathReliabilityTests -v --tb=long
  
Recovery:
  Option 1: Fix reliability issue
  Option 2: Revert change
  Option 3: Escalate to engineering lead
```

### ⚡ Latency Test Failed (E-CPP-LAT-*)
```
ACTION: INVESTIGATE - May block deployment

Likely cause:
  - Added expensive operation to webhook handler
  - Logging too verbose
  - Metrics collection blocking
  - Provider initialization slow

Investigation (10 min):
  python -m pytest tests/test_critical_product_paths.py::CriticalPathLatencyTests -v --durations=10
  
Recovery:
  Option 1: Move expensive op to background task
  Option 2: Cache/optimize hot path
  Option 3: Increase SLA (with approval only)
  Option 4: Revert change
```

### 🔗 Integration Test Failed (E-CPP-INT-*)
```
ACTION: INVESTIGATE - Cross-domain issue

Likely cause:
  - Multiple failures cascading
  - Security + reliability combined issue
  - Load testing exposed edge case

Investigation (15 min):
  python -m pytest tests/test_critical_product_paths.py::CriticalPathIntegrationTests -v --tb=long
  
Recovery:
  Option 1: Fix underlying domain issue
  Option 2: Revert related changes
  Option 3: Escalate to engineering lead
```

---

## Common Failure Resolutions

### "Signature Validation Fails"
```bash
# Check if APP_SECRET is set correctly
echo $APP_SECRET

# Verify signature logic unchanged
git diff HEAD app/decorators/security.py

# Regenerate test signatures
python -c "
import hmac, hashlib
payload = '{}'
digest = hmac.new(b'test-secret', payload.encode(), hashlib.sha256).hexdigest()
print(f'sha256={digest}')
"
```

### "Webhook Response Time Slow"
```bash
# Profile the webhook handler
python -m cProfile -s cumulative run.py

# Check for new middleware
grep -n "@app.before_request\|@app.after_request" app/*.py

# Measure baseline
ab -n 100 http://localhost:5000/health
```

### "Idempotency Test Fails"
```bash
# Check message ID cache implementation
grep -A 20 "_get_message_id_store" app/views.py

# Verify expiring store
grep -A 10 "create_expiring_store" app/services/expiring_store.py

# Check TTL config
echo $IDEMPOTENCY_WINDOW_SECONDS
```

---

## Escalation Matrix

| Severity | Action | Owner | Time |
|----------|--------|-------|------|
| 🔒 Security | BLOCK + Escalate | Eng Lead | Immediate |
| 🛡️ Reliability (E-REL-001/004) | BLOCK + Fix | Eng Lead | 15 min |
| ⚡ Latency (>2x SLA) | INVESTIGATE | Eng Lead | 20 min |
| 🔗 Integration | INVESTIGATE | SRE + Eng | 30 min |

**Escalation Contact**: 
- Slack: #release-on-call
- Phone: See runbook
- Pagerduty: release-team

---

## Post-Deployment

### ✅ Deployment Successful
```bash
# Verify production health
curl https://prod.example.com/health

# Check metrics
datadog: dashboard "production-health"
cloudwatch: logs for errors

# Monitor error rate
rollbar / sentry dashboard
```

### ❌ Post-Deployment Issues
```bash
# Check gate results immediately
# If gate passed but production issue occurred:
#   1. Document issue
#   2. Analyze gate gaps
#   3. Add new critical path test
#   4. Prevent recurrence
```

---

## Decision Log Template

```
Date: [DATE]
Deployment ID: [RELEASE TAG]
Release Gate Status: [PASSED/FAILED]

Domain Results:
  Security:     [PASS/FAIL/SKIP]
  Reliability:  [PASS/FAIL/SKIP]
  Latency:      [PASS/FAIL/SKIP]
  Integration:  [PASS/FAIL/SKIP]

Decision: [DEPLOY/HOLD/ROLLBACK]
Reason: [Brief explanation]

Issues (if any):
  - [Issue 1]
  - [Issue 2]

Approvals:
  Release Owner: ____   Date: ____
  Eng Lead:      ____   Date: ____
```

---

## Emergency Bypass Procedure

**ONLY if absolutely critical and approved by both:**
- Release Owner
- Engineering Lead

```bash
# 1. Document the bypass
echo "Deployment bypassed gate due to: [REASON]" >> DEPLOYMENT_LOG.txt

# 2. Create incident ticket
jira create -T incident -S "Gate bypass on $(date)"

# 3. Deploy with monitoring
./deploy_to_production.sh --force

# 4. Monitor closely
watch -n 2 'curl https://prod.example.com/health'

# 5. Post-incident review
# Schedule review within 24 hours
```

---

## Useful Commands

```bash
# Run local tests
python run_release_gate.py --domain ALL

# Run specific domain
python run_release_gate.py --domain SECURITY
python run_release_gate.py --domain RELIABILITY
python run_release_gate.py --domain LATENCY

# Run with timing
python -m pytest tests/test_critical_product_paths.py -v --durations=10

# Check test counts
python -m pytest tests/test_critical_product_paths.py --collect-only

# Run single test
python -m pytest tests/test_critical_product_paths.py::CriticalPathSecurityTests::test_sec_001_webhook_signature_validation_rejects_tampering -v

# View CI logs
gh run list --branch main --workflow release-gate-critical-paths.yml
gh run view <RUN_ID> --log
```

---

## Success Examples

### ✅ Example: Clean Deployment
```
Release tag: v1.2.3
Gate status: PASSED ✅
Duration: 12s
Domains: 4/4 pass
→ Deployed 14:32 UTC
→ Production healthy
```

### ❌ Example: Caught Regression
```
PR #456: Optimize message processing
Gate status: FAILED ❌
Failed: E-CPP-LAT-001 (webhook SLA)
Root cause: Added debug logging to hot path
Fix: Moved logging to background task
Retried: PASSED ✅
→ Deployed 15:22 UTC
```

### 🛑 Example: Security Issue Blocked
```
PR #789: Refactor auth decorator
Gate status: FAILED ❌
Failed: E-CPP-SEC-001 (signature validation)
Root cause: Changed hash algorithm
Action: Reverted PR, fixed in new PR
→ Deployment delayed 2 hours
→ Issue prevented
```

---

## Key Numbers to Remember

| Metric | Threshold | Domain |
|--------|-----------|--------|
| Webhook response | <500ms | Latency |
| Signature check | <5ms | Security |
| Idempotency check | <20ms | Reliability |
| Total gate time | <15s | All |
| Test pass rate | >99% | Quality |

---

## Feedback & Improvements

Gate not catching an issue?
→ File: `docs/RELEASE_GATE_GAP_REPORT.md`

Gate too strict?
→ Discuss with engineering lead before changing SLA

Gate too slow?
→ Profile tests, optimize mocks, run in parallel

---

**Keep this handy during deployments!**

Last Updated: 2026-05-07
