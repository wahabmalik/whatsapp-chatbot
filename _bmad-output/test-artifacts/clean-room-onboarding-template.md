# Clean-Room Onboarding Dry-Run Evidence

**Date Executed**: [DATE]
**Executor**: [OPERATOR NAME]
**Target Timing**: 45 minutes (config entry < 2 min, E2E < 45 min)
**Actual Duration**: [ACTUAL TIME]

## Pre-Execution Setup

- [ ] Machine: Fresh VM or isolated environment (no prior config)
- [ ] Python: Version [X.Y] verified with `python --version`
- [ ] Git: Cloned fresh from main branch
- [ ] Network: Outbound HTTPS available for WhatsApp + OpenAI APIs

## Execution Checklist

### Phase 1: Install and Configure (Target: 2 min)

- [ ] `git clone` succeeded
- [ ] `python -m venv .venv` succeeded
- [ ] Activation script sourced/executed
- [ ] `pip install -r requirements.txt` completed without errors
- [ ] `copy example.env .env` or `cp example.env .env` succeeded
- [ ] Environment variables set (WHATSAPP_PROVIDER, API keys, etc.)
- [ ] `python validate_environment_and_readiness.py` passed

**Phase 1 Actual Time**: [TIME]

### Phase 2: Verification (Target: 5-10 min)

- [ ] `python -m pytest tests/test_setup_step_conformance.py -v` passed
- [ ] Local health check: `curl http://localhost:5000/health` returned 200
- [ ] Flask server starts: `python run.py` (background, PID: [PID])
- [ ] Webhook endpoint responds: `curl http://localhost:5000/webhook` returned non-404
- [ ] Dashboard accessible: HTTP GET `/operator/access` page loaded

**Phase 2 Actual Time**: [TIME]

### Phase 3: Smoke Test (Target: 30-35 min)

- [ ] Send test message to WhatsApp
- [ ] Message received on operator side
- [ ] Response drafted in dashboard
- [ ] Message sent back via WhatsApp
- [ ] Response received on test number
- [ ] Logs contain expected correlation IDs
- [ ] No critical errors in `curl http://localhost:5000/api/logs`

**Phase 3 Actual Time**: [TIME]

## Evidence Artifacts

### Command Transcript

\`\`\`bash
# Phase 1 - Install
$ git clone https://github.com/your-org/python-whatsapp-bot.git
[output truncated for brevity]
$ python -m venv .venv
$ source .venv/bin/activate  # or .venv\Scripts\activate on Windows
$ pip install -r requirements.txt
$ cp example.env .env
$ [EDITOR] .env  # Set WHATSAPP_PROVIDER, API keys, etc.
$ python validate_environment_and_readiness.py
✅ Environment validation PASSED

# Phase 2 - Verify
$ python -m pytest tests/test_setup_step_conformance.py -v
[test output: PASSED]
$ python run.py &
[Flask output: Running on http://localhost:5000]

# Phase 3 - Smoke test
[Test message sent and received successfully]
\`\`\`

### Test Results

- **test_setup_step_conformance.py**: ✅ PASSED (X/X tests)
- **Health Check**: ✅ PASSED
- **Endpoint Contract**: ✅ PASSED (all documented endpoints reachable)
- **Message Flow**: ✅ PASSED (inbound → AI → outbound)

### Logs/Observability

- **Correlation ID captured**: corr-[ID]
- **Message stored**: message_id=[ID], waid=[RECIPIENT], status=delivered
- **AI response logged**: correlation_id=[ID], model=gpt-3.5-turbo, tokens_used=[COUNT]
- **Metrics accessible**: `curl http://localhost:5000/metrics` returned valid JSON

## Observations and Issues

### Issues Encountered

- [ ] None
- [ ] [DESCRIBE IF ANY]

### Resolutions Applied

[IF ISSUES: DESCRIBE HOW THEY WERE RESOLVED]

## Sign-Off

- **Executor Signature**: ________________________________
- **Date/Time**: ____________________________
- **Status**: ✅ PASS / ❌ FAIL
- **Notes**: [Any final observations]

---

**Evidence Location**: `_bmad-output/test-artifacts/clean-room-onboarding-[DATE].md`
**Referenced by**: `docs/release_smoke_checklist.md`
**GO/NO-GO Impact**: Confirms operator can onboard successfully in < 45 minutes
