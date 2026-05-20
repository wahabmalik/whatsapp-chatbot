# Story 9.2: Production Adapter Delivery (Single Non-WhatsApp Channel)

Status: done

## Story

As a platform operator,
I want a second production-ready outbound delivery channel wired behind the existing ChannelAdapter interface,
so that I have a non-WhatsApp fallback delivery path with the same reliability guarantees as the WhatsApp adapter.

## Acceptance Criteria

1. AC 9.2.1: Adapter is wired behind the existing `OutboundChannel` interface without modifying WhatsApp routing logic.
2. AC 9.2.2: Channel-specific credentials are validated at startup; missing credentials put the adapter into disabled state (not crash state).
3. AC 9.2.3: Routing policy is explicit and config-driven (`OUTBOUND_CHANNEL=telegram`); no silent fallback to a different channel without log evidence.
4. AC 9.2.4: All outbound log entries from the new adapter include `provider`, `correlation_id`, and outcome fields — no credential values in logs.
5. AC 9.2.5: Adapter integrates with existing retry and fallback contract (same 4-attempt schedule: immediate + 3 retries at 1s/2s/4s, then 2-attempt fallback text).

## Tasks / Subtasks

- [x] Implement `TelegramChannel` adapter in `app/services/telegram_channel.py`. (AC: 9.2.1, 9.2.4, 9.2.5)
  - [x] Define `TelegramChannel(OutboundChannel)` class with `send()`, `_send_with_retry()`, `_try_once()`, `_send_fallback()`.
  - [x] Implement `_extract_text(data)` helper to parse WhatsApp-format JSON payload to plain text.
  - [x] Add `from_app(cls, app)` classmethod to construct adapter from Flask app config.
  - [x] Implement same retry backoff schedule as WhatsApp path: `(1, 2, 4)` seconds, 4 total attempts.
  - [x] Log `provider=telegram`, `correlation_id`, `outcome` on every send attempt — never log credential values.
- [x] Wire disabled state: credentials absent at instantiation → `_enabled=False` → log warning at startup, return error dict on send(). (AC: 9.2.2)
- [x] Register Telegram in `channel_interface.py`: add `CHANNEL_TELEGRAM`, extend `SUPPORTED_CHANNELS`, update `get_outbound_channel()` factory, add `_probe_telegram_channel()`. (AC: 9.2.1, 9.2.3)
- [x] Add Telegram config vars to `app/config.py`: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_DEFAULT_CHAT_ID`, `TELEGRAM_SEND_TIMEOUT_SECONDS`. (AC: 9.2.2, 9.2.3)
- [x] Call `_probe_telegram_channel(app)` from `create_app()` in `app/__init__.py`. (AC: 9.2.2)
- [x] Write tests in `tests/test_telegram_channel_adapter.py`: disabled state, send success, retry exhaustion, fallback, log field contract, result shape contract. (AC: 9.2.1–9.2.5)
- [x] Update `ScopeGuardTests` in `tests/test_channel_delivery_contract.py` to reflect that Telegram is now in supported channels. (AC: 9.2.1)

## Dev Notes

### Chosen Channel: Telegram Bot API

The adapter targets the Telegram Bot API (`https://api.telegram.org/bot{token}/sendMessage`). This channel was selected as the first non-WhatsApp adapter because:
- REST-based API with similar request/response shape to WhatsApp (single endpoint, JSON body).
- No infrastructure overhead beyond a bot token and chat ID.
- Can be enabled or disabled in staging without external dependencies.
- Credentials are a single `TELEGRAM_BOT_TOKEN` and `TELEGRAM_DEFAULT_CHAT_ID` (routing target).

### New Config Variables

| Variable | Default | Purpose |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | `None` | Bot API token from @BotFather. Required for enabled state. |
| `TELEGRAM_DEFAULT_CHAT_ID` | `None` | Target chat or group ID for outbound messages. Required for enabled state. |
| `TELEGRAM_SEND_TIMEOUT_SECONDS` | `10.0` | HTTP timeout for Telegram API calls. |

Set `OUTBOUND_CHANNEL=telegram` in environment to activate the adapter.

### Adapter Contract Alignment

- `send()` returns the same required keys as `WhatsAppChannel`: `ok`, `status`, `error`, `fallback_sent`, `operator_review_flagged`, `operator_review_reason`, `attempts`, `response_status`.
- Retry schedule: `_RETRY_BACKOFF = (1, 2, 4)` — identical to `_retry_backoff_schedule()` in `whatsapp_utils.py`.
- Fallback retries: `WHATSAPP_FALLBACK_MAX_RETRIES` (default 2) — reuses the same config key for consistency.
- Disabled result: `ok=False, status="error", error="telegram_adapter_disabled", attempts=0`.
- Fallback result: `ok=False, status="fallback_sent"|"error", operator_review_flagged=True`.

### Payload Extraction

The `data` parameter passed to `send()` is a serialised WhatsApp-format JSON string (`{"text": {"body": "..."}, "to": "...", ...}`). `_extract_text()` parses it and returns `payload["text"]["body"]` as the Telegram message text. Falls back to raw `data` string if JSON parse fails.

### Log Safety

`SafeObservabilityFilter` sanitizes `_KEY_VALUE_PATTERN` and `_AUTH_BEARER_PATTERN` in all log records (Story 1.3). Bot token format (`123456:ABC-DEF1234...`) does not match these patterns, so Telegram adapter logs must **never** include the token string directly. Log only `"set"` / `"missing"` for credential status at startup.

### Startup Probe

`_probe_telegram_channel(app)` in `channel_interface.py`:
- Only runs when `OUTBOUND_CHANNEL=telegram`.
- Imports `TelegramChannel` (confirms module is importable).
- Calls `TelegramChannel.from_app(app)` (confirms constructor runs, logs enabled/disabled state).
- Never raises — missing credentials → disabled state already logged by adapter.

### WhatsApp Path — Zero Changes

`WhatsAppChannel`, `WhatsAppChannel.send()`, `send_message()`, `process_whatsapp_message()`, all retry paths and fallback paths in `whatsapp_utils.py` are unchanged.

### Out of Scope

- More than one new adapter.
- Auto-selection or UI for channel routing.
- Adapter parity contract suite (that is Story 9.3).

### References

- `app/services/channel_interface.py` — OutboundChannel ABC and WhatsAppChannel
- `app/utils/whatsapp_utils.py` — retry/fallback schedule to match
- `app/services/observability.py` — get_correlation_id(), SafeObservabilityFilter
- `app/config.py` — config loading and validate_config()
- `app/__init__.py` — create_app(), startup probe pattern
- `tests/test_channel_delivery_contract.py` — existing channel interface contract tests
- `_bmad-output/planning-artifacts/epics-next-cycle.md` — AC source

## Dev Agent Record

### Agent Model Used

GPT-5.3-Codex

### Debug Log References

- Implemented adapter in `app/services/telegram_channel.py` with explicit config-driven routing (`OUTBOUND_CHANNEL=telegram`) and disabled-state behavior when credentials are missing.
- Updated channel factory and startup probes in `app/services/channel_interface.py` and `app/__init__.py`.
- Added Telegram config loading in `app/config.py`.
- Added Story 9.2 tests in `tests/test_telegram_channel_adapter.py` and updated channel contract tests in `tests/test_channel_delivery_contract.py`.

### Completion Notes List

- AC 9.2.1 complete: `TelegramChannel` now implements `OutboundChannel`; `get_outbound_channel()` returns Telegram when configured while WhatsApp delegation path remains intact.
- AC 9.2.2 complete: Missing Telegram credentials produce a disabled adapter state (startup warning + non-throwing error result on send).
- AC 9.2.3 complete: Routing is explicit/config-driven via `OUTBOUND_CHANNEL`; per-message override uses `delivery_context["telegram_chat_id"]` only.
- AC 9.2.4 complete: Adapter logs include `provider=telegram`, `correlation_id`, and `outcome` fields; tests verify token is not logged.
- AC 9.2.5 complete: Retry/fallback contract matches WhatsApp semantics (4 primary attempts using 1/2/4 backoff, then fallback attempts).
- Validation:
  - `python -m pytest tests/test_channel_delivery_contract.py tests/test_telegram_channel_adapter.py -v` → 50 passed
  - `python -m pytest -q` → blocked by pre-existing Python 3.9 incompatible type-hint syntax in unrelated tests (`tests/test_critical_product_paths.py`, `tests/test_reliability.py`, `tests/test_story_3_3.py`)

### File List

- `_bmad-output/implementation-artifacts/next-cycle-9-2-production-adapter-delivery-single-non-whatsapp-channel.md`
- `app/services/telegram_channel.py`
- `app/services/channel_interface.py`
- `app/config.py`
- `app/__init__.py`
- `tests/test_telegram_channel_adapter.py`
- `tests/test_channel_delivery_contract.py`

### Change Log

| Date | Change |
| --- | --- |
| 2026-05-08 | Story created from epics-next-cycle.md; Story 9.1 implementation (governance baseline) confirmed done as dependency. |
| 2026-05-08 | Implemented Telegram production adapter with disabled-state startup behavior, factory wiring, config loading, and full Story 9.2 test coverage. |
