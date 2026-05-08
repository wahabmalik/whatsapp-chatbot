# Deferred Work

## Deferred from: code review of saas-1-2b-password-reset-flow (2026-05-04)

- **Port 465 / SMTP_SSL not supported** — `build_smtp_dispatch` uses STARTTLS (explicit TLS, port 587). Operators who configure `SMTP_PORT=465` need implicit-TLS via `smtplib.SMTP_SSL`. Add a `SMTP_SSL_MODE` flag or detect port 465 automatically when SMTP hardening is addressed.
- **No rate limiting on `/auth/forgot-password`** — Unauthenticated endpoint with DB write + email dispatch; no guard against tight-loop abuse or SMTP quota exhaustion. Implement per-IP or per-email rate limiting in a security hardening epic.

## Deferred from: code review of saas-1-2a-email-password-signup-login-and-logout (2026-05-04)

- **Orphaned-tenant crash in `authenticate_account`** — `session.query(Tenant).one()` raises `sqlalchemy.exc.NoResultFound` if a user's tenant row is deleted out-of-band. No in-band code path currently deletes tenants, so this cannot trigger in production today. Revisit when tenant deletion/deactivation workflow is built.
- **`SESSION_COOKIE_SECURE` defaults to `False`** — Cookies will be transmitted over plain HTTP unless `SESSION_COOKIE_SECURE=true` is set in the production environment. Document in deployment runbook as a mandatory production env var.

## Resolved in Sprint 2 hardening (2026-05-01)

- Dashboard setup/operator POST routes now enforce CSRF tokens.
- `.env` writes now use cross-process locking plus atomic replace semantics.
- Dashboard OpenAI key saves now refresh the live OpenAI client without requiring restart.
- Setup step state now advances instead of hardcoding `aria-current="step"` on "Welcome".
- Escalation keyword matching now uses boundary-aware matching instead of naive substring checks.
- Outbound send timeout is now configurable via `WHATSAPP_SEND_TIMEOUT_SECONDS`.
- Fallback delivery now supports bounded retry attempts via `WHATSAPP_FALLBACK_MAX_RETRIES`.
- Outbound metrics now capture per-attempt duration via `whatsapp.send_attempt_duration`.
- Provider-specific config access no longer relies on unsafe bracket notation in outbound delivery paths.
- Unknown `WHATSAPP_PROVIDER` values already produce explicit validation errors.
- Extension teardown now guards `close()` failures per extension.
- Correlation logging now avoids duplicate filter attachment, caps correlation ID length, sanitizes `set` and `frozenset` values, and avoids redundant route-level `ensure_correlation_id` ownership.
- Logging now relies on root-filter ownership so late-propagating handlers still pass through sanitization.

## Deferred from: code review of 3-2-setup-wizard-and-escalation-workflow (2026-04-30)

- No remaining local deferred items in this slice.

## Deferred from: code review of 2-3-outbound-delivery-retry-and-fallback (2026-04-30)

- **Concurrent log interleaving on high load** — Multiple threads logging attempt lines may interleave unpredictably if they execute concurrently, making correlation_id-based log grouping difficult in plaintext logs. Structured logging infrastructure (JSON logs with request_id field) handles this; no code fix needed (application-layer concern).
- **Monotonic time wrap-around theoretical risk** — `time.monotonic()` theoretically wraps after ~280 years on some systems. No practical risk for MVP uptime; acceptable.

## Deferred from: code review of 1-1-startup-validation-and-setup-gating (2026-04-30)

- No remaining local deferred items in this slice.

## Deferred from: code review of 1-3-correlation-logging-and-observability-baseline (2026-04-30)

- No remaining local deferred items in this slice.

## Deferred from: Epic 8 retrospective (2026-05-03)

- **Multi-channel production rollout is still deferred**
	- Risk: Interface seam exists, but production SMS/Messenger adapters and routing policy are not yet implemented.
	- Owner: Product + Developer
	- Mitigation: Create next-cycle story set for channel adapters, credential validation, and outbound contract tests per channel.
	- Success criteria: At least one non-WhatsApp adapter is integrated behind existing abstraction with passing contract tests.

- **Analytics productization remains foundation-only**
	- Risk: Events are captured, but retention/governance and consumer-facing reporting scope are still partial.
	- Owner: Operations + Developer
	- Mitigation: Enforce file retention cap (`ANALYTICS_EVENT_STORE_MAX_LINES`) and define next-cycle reporting/retention acceptance criteria.
	- Success criteria: Retention cap is active in runtime and tests; next-cycle analytics stories include dashboard/export + policy contract tests.

- **SQLite operational enablement still requires environment-specific rollout evidence**
	- Risk: Optional SQLite behavior is validated in tests but may vary by deployment/runtime conditions.
	- Owner: Operations
	- Mitigation: Run environment-specific soak + rollback drill using documented runbook steps before non-dev default enablement.
	- Success criteria: Staging runbook drill artifact exists with enable, fallback, and rollback evidence.

- **Story closure evidence quality was inconsistent across Epic 8 files**
	- Risk: Weak completion artifacts can mask whether acceptance/risk criteria were truly closed.
	- Owner: Developer + QA
	- Mitigation: Standardize done-story artifact sections (`Completion State`, `Dev Agent Record`) and enforce with CI test.
	- Success criteria: `tests/test_story_artifact_completion_contract.py` passes and blocks regressions for done Epic 8 story files.
