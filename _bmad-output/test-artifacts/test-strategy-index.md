# Test Strategy Index — Coverage Map

**Generated**: 2026-05-02  
**Project**: python-whatsapp-bot  

This document maps each story acceptance criterion to the test file and test class that covers it.

---

## Epic 1 — Startup Validation and Setup Gating

| Story | Acceptance Criterion | Test File | Test Class |
|---|---|---|---|
| 1.1 | Startup validates all required env vars | `tests/test_story_1_1_and_1_2.py` | `StartupValidationTests` |
| 1.1 | Setup route accessible when config incomplete | `tests/test_story_1_1_and_1_2.py` | `StartupValidationTests` |
| 1.1 | Config readiness logged without exposing values | `tests/test_story_1_1_and_1_2.py` | `StartupValidationTests` |
| 1.1 | is_config_value_set boundary behaviour | `tests/test_story_1_1_and_1_2.py` | `IsConfigValueSetBoundaryTests` |
| 1.2 | GET /webhook challenge-response | `tests/test_story_1_1_and_1_2.py` | `WebhookVerifyTests` |
| 1.2 | POST /webhook HMAC enforcement | `tests/test_story_1_1_and_1_2.py` | `WebhookSignatureEnforcementTests` |
| 1.2 | Evolution provider webhook acceptance | `tests/test_story_1_1_and_1_2.py` | `EvolutionWebhookTests` |
| 1.3 | Observability (correlation IDs, metrics) | `tests/test_story_1_3.py` | `ObservabilityTests` |
| 1.3 | Log sanitization | `tests/test_log_sanitization_extended.py` | `LogSanitizationTests` |

---

## Epic 2 — Inbound Normalization, Retry, and Deferred Delivery

| Story | Acceptance Criterion | Test File | Test Class |
|---|---|---|---|
| 2.1 | normalize_inbound_message Meta/Evolution | `tests/test_story_2_1.py` | `NormalizeInboundMetaTests`, `NormalizeInboundEvolutionTests` |
| 2.1 | Duplicate suppression (idempotency) | `tests/test_story_2_1.py` | `DuplicateSuppressionTests` |
| 2.1 | Store backend selection | `tests/test_story_2_1.py` | `StoreBackendSelectionTests` |
| 2.1 | wa_id end-to-end propagation | `tests/test_wa_id_propagation_contract.py` | `WaIdPropagationContractTests` |
| Retry | Retry schedule and backoff | `tests/test_retry_escalation_contract.py` | `RetryScheduleContractTests` |
| Retry | Mixed failure sequences | `tests/test_retry_escalation_contract.py` | `MixedFailureSequenceTests` |
| Retry | Fallback semantics + joint postconditions | `tests/test_retry_escalation_contract.py` | `FallbackSemanticsTests` |
| Retry | Deferred retry contract | `tests/test_retry_escalation_contract.py` | `DeferredRetryContractTests` |
| Retry | Escalation reason priority | `tests/test_retry_escalation_contract.py` | `EscalationReasonPriorityTests` |
| Deferred | Deferred delivery observability | `tests/test_deferred_delivery_observability.py` | _(multiple classes)_ |
| Store | ExpiringKeyStore close lifecycle | `tests/test_expiring_store.py` | `StoreCloseLifecycleTests` |

---

## Epic 3 — Dashboard and Operator UI

| Story | Acceptance Criterion | Test File | Test Class |
|---|---|---|---|
| 3.3 | Dashboard role guards | `tests/test_story_3_3.py` | _(multiple classes)_ |
| 3.x | Reliability across operator pages | `tests/test_reliability.py` | `OperatorMobileNavTests`, _(others)_ |
| 3.x | Endpoint contract compliance | `tests/test_endpoint_contract.py`, `tests/test_endpoint_contracts.py` | _(multiple)_ |

---

## Epic 4 — FAQ Routing and Agent Registry

| Story | Acceptance Criterion | Test File | Test Class |
|---|---|---|---|
| 4.x | FAQ routing | `tests/test_faq_routing.py` | _(multiple)_ |
| 4.x | Agent registry | `tests/test_agent_registry.py` | _(multiple)_ |

---

## Epic 5 — CSRF and Config Write Safety

| Story | Acceptance Criterion | Test File | Test Class |
|---|---|---|---|
| 5.1 | CSRF protection | `tests/test_story_5_1.py`, `tests/test_story_5_1_csrf_and_config_write_safety.py` | `CsrfTests`, _(others)_ |
| 5.1 | SECRET_KEY non-static fallback | `tests/test_story_5_1_csrf_and_config_write_safety.py` | `SecretKeyFallbackAbsenceTests` |

---

## Epic 6 — Sprint Status Integrity and Release Gates

| Story | Acceptance Criterion | Test File | Test Class |
|---|---|---|---|
| 6.x | Sprint status YAML integrity | `tests/test_sprint_status_integrity.py` | _(multiple)_ |
| 6.x | Release gate parity | `tests/test_release_gates.py`, `tests/test_launch_gate_parity.py` | _(multiple)_ |
| 6.x | Launch gate schema parity | `tests/test_launch_gate_schema_parity.py` | _(multiple)_ |
| 6.x | Docs runtime endpoint contract | `tests/test_docs_runtime_endpoint_contract.py` | _(multiple)_ |
| 6.x | Story traceability | `tests/test_story_traceability_contracts.py` | _(multiple)_ |

---

## Epic 7 — Retrospective Carry-Forward

| Story | Acceptance Criterion | Test File | Test Class |
|---|---|---|---|
| 7.1 | CI YAML duplicate key gate | `validate_sprint_status_integrity.py` | _(standalone script + CI step)_ |
| 7.2 | Ops doc route inventory | `tests/test_operational_route_inventory.py` | `OperationalRouteInventoryTests` |
| 7.3 | Operator template url_for contract | `tests/test_operator_template_url_contract.py` | `OperatorTemplateUrlContractTests` |
| 7.4 | Setup wizard full lifecycle | `tests/test_setup_step_conformance.py` | `SetupWizardLifecycleIntegrationTests` |
| 7.5 | Operator mobile nav all page keys | `tests/test_reliability.py` | `OperatorMobileNavTests` |
| 7.6 | Joint fallback+operator_review postcondition | `tests/test_retry_escalation_contract.py` | `FallbackSemanticsTests` |
| 7.7 | wa_id end-to-end propagation | `tests/test_wa_id_propagation_contract.py` | `WaIdPropagationContractTests` |
| 7.8 | Background correlation dispatch convention | `app/utils/whatsapp_utils.py` (doc), `tests/test_deferred_delivery_observability.py` | _(runtime assertion)_ |
| 7.9 | Store close lifecycle detectability | `tests/test_expiring_store.py` | `StoreCloseLifecycleTests` |
| 7.10 | Config truthiness boundaries | `tests/test_story_1_1_and_1_2.py` | `IsConfigValueSetBoundaryTests` |
| 7.11 | SECRET_KEY hardcoded fallback absence | `tests/test_story_5_1_csrf_and_config_write_safety.py` | `SecretKeyFallbackAbsenceTests` |
| 7.12 | This document | `_bmad-output/test-artifacts/test-strategy-index.md` | — |
