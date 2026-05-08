# Epic 5 Code Review - Sprint 2 Hardening

Date: 2026-05-01
Scope:
- app/utils/whatsapp_utils.py
- app/services/outbound_delivery.py
- app/config.py
- app/views_dashboard.py
- app/services/observability.py
- tests/test_release_gates.py
- _bmad-output/implementation-artifacts/deferred-work.md

## Overall Assessment

- Result: changes are mostly solid and align with Epic 5 hardening goals.
- Test signal: user-reported full pass in prior session (88/88), with the reviewed logic paths largely covered.
- Review mode: adversarial/code-risk focused (bugs, regressions, edge-case behavior, and security leakage risks).

## Findings

### 1) High - OpenAI key redaction misses modern key formats

- File: app/services/observability.py
- Lines: `_OPENAI_KEY_PATTERN` and `sanitize_text` substitution path
- Risk: secret leakage in logs for newer OpenAI keys (for example keys with additional separators/segments) because the regex only matches `sk-` followed by plain alphanumerics.
- Why this matters: observability sanitization is a defense layer; partial matching leaves high-impact credential exposure risk in logs.
- Evidence:
  - `app/services/observability.py` currently uses `_OPENAI_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9]{8,}\b")`
  - this pattern does not robustly cover broader key variants.
- Recommendation:
  - broaden the regex to include known key token separators and segment styles, or use a stricter deny-list pattern for any `sk-` prefixed token-like secret.
  - add tests for representative key shapes (legacy and modern) to lock behavior.

### 2) Medium - Fallback retry count is configured but not actually retried after first failure

- File: app/utils/whatsapp_utils.py
- Lines: `_send_fallback` loop and surrounding exception block
- Risk: `WHATSAPP_FALLBACK_MAX_RETRIES` can be misleading because a failure on first fallback attempt exits through outer exception handling, skipping remaining configured fallback attempts.
- Why this matters: during provider instability, this can reduce recovery probability and create inconsistent operator expectations.
- Evidence:
  - `_send_fallback` wraps the full retry loop in a single `try` block; first thrown `requests.RequestException` exits loop path immediately.
  - `for fallback_attempt in range(fallback_attempts):` exists, but exceptions prevent continued iterations.
- Recommendation:
  - move exception handling inside the fallback attempt loop so each configured attempt is actually exercised.
  - add a test proving first fallback attempt can fail and a later attempt can still succeed.

### 3) Medium - Setup step indicator cannot reach steps 3 or 4

- Files:
  - app/views_dashboard.py (`_setup_current_step`)
  - app/templates/setup.html (expects steps 1..5)
- Risk: accessibility/progress state can be misleading because controller logic only returns 1, 2, or 5 while template exposes explicit step markers for 3 and 4.
- Why this matters: Epic 5.4 calls for precise setup progress signaling; unreachable states weaken operator trust and accessibility semantics.
- Evidence:
  - `_setup_current_step` currently:
    - returns 5 when complete
    - returns 2 when any required key exists
    - else returns 1
  - template includes `setup_current_step == 3` and `== 4` branches that can never be selected.
- Recommendation:
  - introduce state criteria for copy/verify milestones (for example presence + verification action completion marker), or remove unreachable steps from aria-current logic.

## What Looks Good

- CSRF guard enforcement is consistently applied to the key operator POST endpoints.
- `.env` writes are serialized and atomically replaced, reducing corruption/interleaving risk.
- Deferred background delivery service is isolated and app-scoped.
- Correlation ID cap and container sanitization (`set`/`frozenset`) improve log hygiene.

## Residual Risks

- Deferred delivery remains eventually-consistent by design; user-facing success from webhook receipt can precede delivery completion.
- Lock-file approach may still need stale-lock recovery policy for crash scenarios in long-running multi-process environments.

## Suggested Follow-up Tests

1. Add observability sanitization tests for multiple OpenAI key variants.
2. Add fallback-retry behavior test for fail-then-success within configured fallback attempts.
3. Add setup progress tests that assert reachable step 3/4 behavior (or assert simplified, intentional model).

## Review Outcome

- Decision: Accept with follow-up hardening tickets for the 3 findings above.
- Blocking severity: 1 high issue should be prioritized before broader production exposure of logs.