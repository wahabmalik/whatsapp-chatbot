# QA Baseline - 2026-05-07

Project: Malixis Reply v1 (WhatsApp AI Bot SaaS)
Tester: Quinn (QA)

## Commands executed

- c:/Users/wahab/OneDrive/Documents/GitHub/python-whatsapp-bot/.venv/Scripts/python.exe -m pytest tests/test_critical_product_paths.py -q --tb=short -s
- c:/Users/wahab/OneDrive/Documents/GitHub/python-whatsapp-bot/.venv/Scripts/python.exe -m pytest tests/ -q --tb=short -x
- c:/Users/wahab/OneDrive/Documents/GitHub/python-whatsapp-bot/.venv/Scripts/python.exe -m pytest tests/test_critical_product_paths.py::CriticalPathLatencyTests::test_lat_001_webhook_response_time_sla -q --tb=short -s
- c:/Users/wahab/OneDrive/Documents/GitHub/python-whatsapp-bot/.venv/Scripts/python.exe -m pytest tests/test_docs_runtime_endpoint_contract.py::DocsRuntimeEndpointContractTests::test_all_documented_endpoints_implemented -q --tb=short -s
- c:/Users/wahab/OneDrive/Documents/GitHub/python-whatsapp-bot/.venv/Scripts/python.exe -m pytest tests/ -q --tb=short

## Overall result

- Status: NO-GO
- Suite result: 56 failed, 620 passed, 5 skipped, 27 subtests passed
- Runtime: 426.82s

## Root-cause clusters

### Cluster A - Thread Inspector route removed, references remain (Critical)

Symptoms:
- /api/thread-inspector missing from route map
- Logs page render fails with BuildError for dashboard.thread_inspector_api
- Multiple endpoint contract and reliability tests fail as cascade

Evidence:
- app/templates/logs.html references dashboard.thread_inspector_api
- No thread_inspector_api route in app/views_dashboard.py

### Cluster B - dashboard.html requires escalation object not supplied by view (Critical)

Symptoms:
- /operator returns 500
- Jinja2 UndefinedError: escalation is undefined

Evidence:
- app/templates/dashboard.html uses escalation.has_stop_signal
- app/views_dashboard.py operator_dashboard renders dashboard.html without escalation in context

### Cluster C - _set_env_value now depends on request session context (High)

Symptoms:
- Config write safety and recovery tests fail with RuntimeError: working outside of request context
- Concurrency config-write tests fail due session access in helper function

Evidence:
- _set_env_value calls record_config_change(... operator_role=_current_dashboard_role())
- _current_dashboard_role reads flask session

### Cluster D - Billing checkout/success/portal regressions (High)

Symptoms:
- checkout responses attempt to JSON serialize MagicMock in tests
- success callback/idempotency assertions fail
- portal redirect assertion fails (expected Stripe URL)

Likely focus area:
- app/views_auth.py billing_checkout, billing_success, billing_portal

### Cluster E - Endpoint contract drift (Medium)

Symptoms:
- setup status tests expect /setup-status semantics while code serves /api/setup/status
- observability tests expect Prometheus content at route/path differing from current implementation

Evidence:
- setup status URL originates from app/views_dashboard.py -> setup_status_api
- metrics route exists at app/views.py /metrics and app/views_dashboard.py /api/metrics; tests indicate expected contract drift

### Cluster F - Critical-path latency test flake under suite contention (Medium)

Symptoms:
- test_lat_001 fails in suite run (>500ms)
- same test passes in isolation

Likely cause:
- async outbound retry activity/network interactions leaking into timing measurement

## Recommendation

1. Restore thread inspector endpoint contract or remove all references in templates/docs/tests in one coordinated change.
2. Reconcile operator dashboard context contract by always supplying escalation structure to dashboard template.
3. Decouple _set_env_value from request context (default operator role fallback) to restore pure helper behavior in non-request tests.
4. Repair billing flow contract to return plain strings and re-verify pending_webhook idempotency behavior.
5. Align endpoint contracts (setup status + metrics/prometheus) and documentation with tests.
6. Stabilize latency test by isolating network/deferred delivery side effects in test setup.

## Gate decision

- Release gate state: BLOCKED
- Blockers are structural contract regressions, not isolated flaky tests.
