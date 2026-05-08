# Operations Runbook

Canonical operations document for on-call engineers and operators.

For a one-page command reference during active incidents, see `docs/on_call_quick_reference.md`.

## 0. Process management

### Start (production)

**Linux / macOS (Gunicorn):**
```bash
python serve.py
# or directly:
gunicorn -c gunicorn.conf.py wsgi:app
```

**Windows (Waitress):**
```powershell
python serve.py
```

Default bind: `0.0.0.0:8000`. Override with `APP_HOST` / `APP_PORT` environment variables.

### Restart (graceful)

Gunicorn (Linux/macOS) — sends `HUP` to reload workers without dropping connections:
```bash
kill -HUP $(cat gunicorn.pid)
# or via process manager (systemd/supervisor):
systemctl restart whatsapp-bot
```

Waitress (Windows) — no hot-reload; stop and start the process:
```powershell
# Stop: Ctrl-C or kill the process
# Start:
python serve.py
```

### Stop

```bash
# Linux/macOS
kill -TERM $(cat gunicorn.pid)
# or
systemctl stop whatsapp-bot

# Windows — kill via Task Manager or:
Stop-Process -Name python -Confirm
```

### Health check (confirm service is up)

```bash
curl -s http://localhost:8000/health
# expect: {"status": "healthy", ...}
```

```powershell
Invoke-WebRequest http://localhost:8000/health -UseBasicParsing | Select-Object StatusCode, Content
```

### Evolution API container (Docker)

```bash
# Start (first time or after removal)
docker run -d --name evolution-api -p 8080:8080 \
  -e AUTHENTICATION_API_KEY=<EVOLUTION_API_KEY> \
  evoapicloud/evolution-api:latest

# Stop
docker stop evolution-api

# Start (existing, stopped container)
docker start evolution-api

# Restart
docker restart evolution-api

# Status
docker ps --filter "name=evolution-api"

# Logs (last 100 lines)
docker logs --tail 100 evolution-api
```

Replace `<EVOLUTION_API_KEY>` with the value of `EVOLUTION_API_KEY` in `.env`.

### Database migration (run once per release that includes schema changes)

```bash
# PowerShell
$env:DATABASE_URL="sqlite:///./data/saas.db"
python -m alembic upgrade head

# bash/zsh
DATABASE_URL="sqlite:///./data/saas.db" python -m alembic upgrade head
```

No migration is needed for the SQLite reliability state store (`data/runtime_state.db`); its schema initializes automatically on first start.

## 1. Alert and escalation triggers

Escalate immediately when any of the following are observed:
- Health remains degraded for 2 consecutive checks
- `fallback_sent` increments (retry exhaustion occurred)
- Repeated signature validation failures (403 bursts)
- Sustained increase in webhook processing errors

Minimum ownership protocol:
- Assign one incident commander
- Assign one comms owner
- Record timestamps for detect, mitigate, recover

## 2. Monitoring endpoint map

Use the correct endpoint family for the task.

| Purpose | Endpoint | Used by |
|---|---|---|
| Public health API | GET `/health` | Unauthenticated JSON; public/webhook observability |
| Public metrics API | GET `/metrics` | Unauthenticated JSON; public/webhook observability |
| Operator dashboard health API | GET `/api/health` | JSON; dashboard UI polling (no session required) |
| Operator dashboard metrics API | GET `/api/metrics` | JSON; dashboard UI polling (no session required) |
| Operator dashboard logs API | GET `/api/logs` | JSON; logs screen polling (no session required) |
| Operator thread inspector API | GET `/api/thread-inspector` | JSON; requires operator session and `user_id` query parameter |
| Operator metrics HTML | GET `/operator/metrics` | HTML page; requires operator session (`/operator/access`) |

Suggested cadence:
- Poll health every 30 seconds during incidents; every 5 minutes during normal operations
- Capture metrics snapshots at incident open and close

### Actionable alert thresholds

| Indicator | Normal | Warning | Escalate |
|---|---|---|---|
| Health state | `healthy` | Any degraded check | Two consecutive degraded checks |
| Error rate (webhook processing) | Baseline | +20% increase over 5 min window | +50% increase or any sustained plateau |
| `fallback_sent` counter | 0 per hour | Any non-zero | Increasing sequence |
| `outbound_failure` counter | 0 per hour | 1–2 per hour | 3+ per hour or sudden spike |
| Duplicate suppression hits | Low | Unexpected burst | Burst exceeds message volume |
| Signature 403 rate | 0 | 1–2 isolated | 3+ in 10 min (may indicate replay attack) |

## 3. Signature failure triage

For 403 on POST `/webhook`:
1. Confirm APP_SECRET matches Meta app secret exactly
2. Confirm server clock is synchronized
3. Confirm headers `X-Hub-Signature-256` and timestamp are present
4. Check replay-window behavior in logs (duplicates may be validly rejected)

For 403 on verification GET `/webhook`:
1. Confirm VERIFY_TOKEN in runtime config matches Meta callback setting
2. Re-run verification in Meta dashboard

## 4. Fallback and outbound failure verification

Expected retry behavior:
- 1 initial attempt plus 3 retries
- Backoff schedule: 1s, 2s, 4s

Expected fallback behavior after retry exhaustion:
- Deterministic fallback reply is sent
- Operator-review signal is emitted

Operational checks:
1. Inspect logs for fallback marker and correlation ID
2. Inspect metrics for outbound-failure and fallback counters
3. Confirm recovery or proceed to rollback

## 5. Rollback playbook

Code rollback:
1. Identify last known good commit
2. Deploy previous commit
3. Restart app process
4. Run release smoke checklist and confirm service restoration

Config rollback:
1. Restore prior environment values
2. Restart process
3. Verify health and smoke checks pass

State/backend rollback:
- If sqlite store causes runtime issues, set STATE_STORE_BACKEND to memory temporarily
- Record dedup window reset risk after restart

Agent rollback:
1. Identify the last known good agent selection (visible in `data/agent_selection.json`)
2. Restore prior agent selection via the `/agents` operator page or by editing `data/agent_selection.json` directly
3. Restart app process if agent selection is not hot-reloadable
4. Confirm active agent via `/api/health` response or operator log entries
5. Document which agent was reverted and the reason in post-incident evidence

## 6. Post-incident evidence capture

Capture all of the following:
- Incident start/end time and impact scope
- Root cause and corrective action
- Correlation IDs for representative failures
- Metrics snapshots before and after mitigation
- Customer-facing communication notes
- Follow-up tasks with owners and due dates

Release artifact links for go/no-go package:
- `_bmad-output/test-artifacts/test-results-summary.json`
- `_bmad-output/test-artifacts/staging-validation-report.json`
- `_bmad-output/test-artifacts/go-no-go-report.md`
- `_bmad-output/test-artifacts/risk-register.yaml`
- `_bmad-output/test-artifacts/manual-attestations.md`
- `docs/release_smoke_checklist.md`

Launch gate evaluation command:
```bash
python start/evaluate_launch_gates.py
```
This reads `_bmad-output/test-artifacts/launch-gates.yaml` and `_bmad-output/test-artifacts/risk-register.yaml` and produces a GO/NO-GO decision.

## 7. Retention policy

Operational logs must be retained for at least 30 days in the hosting log platform.
This satisfies NFR7 operational retention expectations.

## 8. SQLite state store: enablement and rollback (Story 8.4)

The reliability state store (idempotency deduplication) defaults to an in-memory backend and
can be switched to SQLite for restart continuity without code changes.

### Environment variables

| Key | Default | Description |
|---|---|---|
| `STATE_STORE_BACKEND` | `memory` | Set to `sqlite` to enable persistent store |
| `STATE_STORE_SQLITE_PATH` | `data/runtime_state.db` | Path to the SQLite database file |
| `STATE_STORE_FALLBACK_TO_MEMORY` | `true` | Automatically fall back to memory if SQLite init fails |

These keys are documented in `example.env`.

### Enabling SQLite persistence

1. Set `STATE_STORE_BACKEND=sqlite` in your `.env` file (or deployment environment).
2. Confirm `STATE_STORE_SQLITE_PATH` is writable by the app process.
3. Set `STATE_STORE_FALLBACK_TO_MEMORY=true` (default) to allow graceful degradation if the file
   cannot be opened on startup.
4. Restart the app process. The store initializes the schema on first open; no manual migration
   is required.

### Fallback behavior

If `STATE_STORE_BACKEND=sqlite` and the database file cannot be opened:
- When `STATE_STORE_FALLBACK_TO_MEMORY=true` (default): startup continues with in-memory store;
  a WARNING log entry records the failure path and reason.
- When `STATE_STORE_FALLBACK_TO_MEMORY=false`: startup raises `sqlite3.OperationalError`; the app
  will not start. Use only when you want SQLite to be mandatory.

### Rollback to memory

1. Set `STATE_STORE_BACKEND=memory` (or remove the key).
2. Restart the app process.
3. Note: in-memory state is not seeded from the SQLite file after switching back. Any duplicate
   suppression window resets. This is expected and safe; duplicate messages during the brief
   window after rollback are idempotently handled.

### Resource teardown

Both backends implement `close()` which is called automatically during Flask app-context teardown.
`close()` is idempotent and safe to call multiple times. If a `close()` raises, the teardown
handler logs the error and continues to close remaining extensions.

## 9. Outbound channel extension points (Story 8.2 — interface-prep only)

The outbound delivery layer is abstracted behind `OutboundChannel` in
`app/services/channel_interface.py`.  WhatsApp is the only active adapter.

**Configuration key:** `OUTBOUND_CHANNEL` (default: `whatsapp`).
Changing this to an unsupported value logs a warning and falls back to WhatsApp.

**To add SMS or Messenger in a future story:**
1. Implement a class inheriting `OutboundChannel` and override `send()`.
2. Register it in `_CHANNEL_REGISTRY` with a unique lowercase key.
3. Add the key to `SUPPORTED_CHANNELS`.
4. Add required credential config keys to `validate_config` (app/config.py)
   guarded by `OUTBOUND_CHANNEL == "<new-key>"`.
5. Set `OUTBOUND_CHANNEL=<new-key>` in the environment.

No non-WhatsApp credentials, endpoints, or activation paths are enabled by
this story.  Do not add live channel config before the corresponding
implementation story is sprint-scheduled.
