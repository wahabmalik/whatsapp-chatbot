# Critical Product Paths - Release Gate Documentation

## Overview

**Purpose**: Automated quality gate ensuring security, reliability, and latency regressions are caught before production launch.

**Test Suite**: `tests/test_critical_product_paths.py`

**Owned by**: Release Owner

**Invocation**: Pre-deployment validation step in CI/CD pipeline

---

## Quality Domains Covered

### 1. SECURITY DOMAIN (E-CPP-SEC)

Critical path: Webhook ingestion → Message validation → Processing

| Test ID | Requirement | Risk | SLA |
|---------|-------------|------|-----|
| E-CPP-SEC-001 | Webhook signature validation rejects tampering | Invalid signatures bypass auth | <5ms detection |
| E-CPP-SEC-002 | Replay attack prevention (nonce + time window) | Attacker replays old messages | <10ms detection |
| E-CPP-SEC-003 | Auth token validation in webhook verification | Unauthorized webhook registration | Strict: token required |
| E-CPP-SEC-004 | Input sanitization prevents injection | Malicious payloads break logging | Safe fail on invalid input |
| E-CPP-SEC-005 | Provider switch maintains security context | Credential leakage between providers | Config must be isolated |

**Regression Trigger**: Any signature validation, authentication, or input handling changes

---

### 2. RELIABILITY DOMAIN (E-CPP-REL)

Critical path: Message ingestion → Processing → Delivery (with error recovery)

| Test ID | Requirement | Risk | SLA |
|---------|-------------|------|-----|
| E-CPP-REL-001 | Message idempotency prevents duplicates | Users receive duplicate messages | <20ms idempotency check |
| E-CPP-REL-002 | Retry resilience with exponential backoff | Transient errors cause message loss | Automatic retry, don't fail fast |
| E-CPP-REL-003 | Database error handling (graceful degradation) | DB timeout crashes entire service | Return 500 or queue for retry |
| E-CPP-REL-004 | Missing config doesn't crash (setup mode) | Onboarding unreachable | App always starts |
| E-CPP-REL-005 | Health check accuracy | Stale health state routes to broken instance | Accurate status reporting |

**Regression Trigger**: Any changes to message processing, retry logic, error handling, or database operations

---

### 3. LATENCY DOMAIN (E-CPP-LAT)

Critical path: Request handling → Processing → Response

| Test ID | Requirement | Risk | SLA |
|---------|-------------|------|-----|
| E-CPP-LAT-001 | Webhook response time SLA | Slow webhook causes message backlog | <500ms P99 (normal path) |
| E-CPP-LAT-002 | Provider switch latency acceptable | Provider switching causes spikes | <100ms overhead |
| E-CPP-LAT-003 | Message log buffer is non-blocking | Slow logging causes timeouts | Async/buffered, <10ms for 100 entries |
| E-CPP-LAT-004 | Metrics collection is non-blocking | Metrics backend failures cause timeouts | Non-blocking, <50ms for 2000 ops |

**Regression Trigger**: Any changes to webhook handling, provider logic, logging, or metrics

---

## Running the Tests

### Local Development

```bash
# Run all critical product path tests
python -m pytest tests/test_critical_product_paths.py -v

# Run specific domain
python -m pytest tests/test_critical_product_paths.py::CriticalPathSecurityTests -v
python -m pytest tests/test_critical_product_paths.py::CriticalPathReliabilityTests -v
python -m pytest tests/test_critical_product_paths.py::CriticalPathLatencyTests -v

# Run integration tests only
python -m pytest tests/test_critical_product_paths.py::CriticalPathIntegrationTests -v

# With coverage
python -m pytest tests/test_critical_product_paths.py --cov=app --cov-report=html
```

### CI/CD Pipeline Integration

**Placement**: After unit tests, before deployment

**Exit Code Contract**:
- `0` = All tests pass → Proceed to deployment
- `1` = Any test fails → BLOCK deployment, investigate failure

**Example GitHub Actions**:

```yaml
- name: Critical Product Paths Release Gate
  run: |
    python -m pytest tests/test_critical_product_paths.py -v --tb=short
    if [ $? -ne 0 ]; then
      echo "❌ RELEASE GATE FAILED: Regressions detected"
      exit 1
    fi
    echo "✅ RELEASE GATE PASSED: Safe to deploy"
```

---

## Test Failure Response

### Failure Classification

**CRITICAL** (Block deployment):
- Any E-CPP-SEC test failure
- E-CPP-REL-001 (idempotency) or E-CPP-REL-004 (startup)
- E-CPP-LAT-001 (webhook SLA) >200% degradation

**HIGH** (Investigate, may block):
- E-CPP-REL-002 (retry logic)
- E-CPP-REL-003 (database error handling)
- E-CPP-LAT-002/003/004 (backend latency)

**MEDIUM** (Fix before next release):
- E-CPP-REL-005 (health check accuracy)

### Failure Response Procedure

1. **Identify failing test(s)**
   ```bash
   python -m pytest tests/test_critical_product_paths.py -v --tb=long > failure_report.txt
   ```

2. **Root cause analysis**
   - Check recent code changes (security, messaging, provider logic)
   - Review test error message and stack trace
   - Verify environment configuration

3. **Resolution options**
   - **Revert change** (if recent)
   - **Fix code** (if logic error)
   - **Update test SLA** (if threshold too strict — requires approval)

4. **Re-run tests**
   ```bash
   python -m pytest tests/test_critical_product_paths.py -v
   ```

5. **Document incident**
   - Record test failure cause
   - Note resolution applied
   - Update runbook if systematic issue

---

## Maintaining the Test Suite

### Adding New Critical Paths

1. Identify the product path (request → processing → response)
2. Classify into domain: Security / Reliability / Latency
3. Define acceptance criteria and SLA
4. Write test in appropriate test class
5. Assign test ID (E-CPP-DOMAIN-NNN)
6. Add to this documentation
7. Update CI/CD to run new test

### Updating SLA Thresholds

**Change Control Process**:
1. Baseline current performance
2. Document reason for threshold change
3. Get approval from:
   - Engineering lead (code quality)
   - Release owner (deployment risk)
4. Update test + document change
5. Merge with justification in PR

### Test Performance Optimization

If tests become slow:
1. Check for unnecessary waits/sleeps
2. Consider parallel execution
3. Move intensive tests to separate suite
4. Profile with `pytest --durations=10`

---

## Integration with Other Gates

### Relationship to Other Test Suites

| Suite | Scope | When |
|-------|-------|------|
| `test_release_gates.py` | API contracts, provider routing | Unit-level validation |
| `test_critical_product_paths.py` | End-to-end critical paths, SLAs | Pre-deployment gate ✅ |
| `test_story_*.py` | Story acceptance criteria | Story completion |
| E2E/smoke tests | Full system | Post-deployment validation |

**Key Difference**: CPP tests focus on *regressions* across critical paths; release gates test individual API contracts.

---

## Dashboard & Monitoring

### Metrics to Track

```
critical_product_paths.tests_total (counter)
critical_product_paths.tests_failed (counter)
critical_product_paths.tests_duration_seconds (histogram)
critical_product_paths.security_gate_failures (counter)
critical_product_paths.reliability_gate_failures (counter)
critical_product_paths.latency_gate_failures (counter)
```

### Example Alert Rules

**Alert if**:
- Critical path tests fail 3+ times in a day
- Any security test fails (immediate escalation)
- Latency SLA failures exceed threshold

---

## FAQ

**Q: Can we skip failing tests to deploy?**  
A: No. All E-CPP-SEC tests are non-negotiable. E-CPP-REL/LAT failures require explicit approval from release owner + engineering lead.

**Q: What if test environment is flaky?**  
A: Capture flakiness data, isolate environmental issues, mock external dependencies more aggressively. Do not lower SLA thresholds to hide flakiness.

**Q: Do these tests replace manual QA?**  
A: No. These are automated regression gates. Manual exploratory testing, user acceptance testing, and operational validation are still required.

**Q: How often should we run these?**  
A: Minimally: before every deployment. Ideally: on every code commit (CI/CD integration).

---

## Contact

**Release Gate Owned By**: Release Owner / SRE Team

**Escalation**: If test failures block deployment, contact engineering lead within 15 minutes.

**Change Requests**: Submit via pull request with updated test + documentation.

---

*Last Updated: 2026-05-07*  
*Maintained by: Release & QA Team*
