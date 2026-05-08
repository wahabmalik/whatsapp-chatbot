# On-Call Quick Reference

**Audience:** Support operations engineers responding to incidents  
**Goal:** Fast-path commands for deploying, monitoring, and recovering the WhatsApp bot  
**Deep-dive:** `docs/operations_runbook.md` | **Release gates:** `docs/release_smoke_checklist.md`

---

## 1. Start / stop / restart

### Bot process

| Action | Linux / macOS | Windows (PowerShell) |
|---|---|---|
| Start (production) | `python serve.py` | `python serve.py` |
| Restart graceful | `kill -HUP $(cat gunicorn.pid)` | Stop then `python serve.py` |
| Stop | `kill -TERM $(cat gunicorn.pid)` | `Stop-Process -Name python -Confirm` |
| Start (dev only) | `python run.py` | `python run.py` |

Default port: **8000**. Override via `APP_HOST` / `APP_PORT` env vars.

### Evolution API (Docker)

```bash
docker start evolution-api          # resume stopped container
docker restart evolution-api        # restart running container
docker stop evolution-api           # graceful stop
docker logs --tail 100 evolution-api  # last 100 log lines
docker ps --filter "name=evolution-api"  # confirm running
```

First-time start:
```bash
docker run -d --name evolution-api -p 8080:8080 \
  -e AUTHENTICATION_API_KEY=<EVOLUTION_API_KEY> \
  evoapicloud/evolution-api:latest
```

---

## 2. Health checks

Run these first whenever an alert fires.

```bash
# Bot health (unauthenticated)
curl -s http://localhost:8000/health

# Bot metrics (unauthenticated)
curl -s http://localhost:8000/metrics

# PowerShell equivalents
Invoke-WebRequest http://localhost:8000/health -UseBasicParsing | Select-Object StatusCode, Content
Invoke-WebRequest http://localhost:8000/metrics -UseBasicParsing | Select-Object Content
```

Expected healthy response from `/health`:
```json
{"status": "healthy", ...}
```

Evolution API ping:
```bash
curl -s http://localhost:8080 -H "apikey: <EVOLUTION_API_KEY>"
# expect: 200 OK
```

---

## 3. Monitoring endpoint map

| Purpose | Endpoint | Auth |
|---|---|---|
| Public health | `GET /health` | None |
| Public metrics | `GET /metrics` | None |
| Dashboard health | `GET /api/health` | None (JSON polling) |
| Dashboard metrics | `GET /api/metrics` | None (JSON polling) |
| Dashboard logs | `GET /api/logs` | None (JSON polling) |
| Operator metrics page | `GET /operator/metrics` | Operator session required |

Poll cadence: every **30 s** during incidents; every **5 min** during normal operations.

---

## 4. Alert thresholds at a glance

| Indicator | Warning | Escalate |
|---|---|---|
| Health state | Any degraded check | Two consecutive degraded checks |
| Webhook error rate | +20 % over 5 min | +50 % or sustained plateau |
| `fallback_sent` counter | Any non-zero | Increasing sequence |
| `outbound_failure` counter | 1–2 per hour | 3+ per hour or sudden spike |
| Signature 403 rate | 1–2 isolated | 3+ in 10 min (possible replay attack) |

---

## 5. Rollback decision tree

### Code rollback

```bash
git log --oneline -10            # identify last known good commit
git checkout <good-commit-hash>  # or deploy that commit via CI
python serve.py                  # restart
# then: run smoke checklist
curl -s http://localhost:8000/health
python -m unittest discover tests
```

### Config rollback

1. Restore previous values in `.env` (or deployment secrets manager)
2. Restart the process
3. Confirm `GET /health` returns `healthy`

### Agent rollback

1. Check current selection: `cat data/agent_selection.json`
2. Restore via operator UI at `/agents`, **or** edit `data/agent_selection.json` directly
3. Restart the process if agent selection is not hot-reloadable
4. Confirm active agent in `/api/health` response or operator logs
5. Record: which agent was reverted and why

### State store rollback (SQLite → memory)

```bash
# In .env: set STATE_STORE_BACKEND=memory  (or remove the key)
# Restart the process
python serve.py
```

> **Side effect:** in-memory state is not seeded from the prior SQLite file.  
> The dedup window resets. Duplicate messages in the brief window after rollback are handled idempotently; no action needed.

---

## 6. First-response triage by symptom

| Symptom | Likely cause | Immediate action |
|---|---|---|
| `GET /health` returns non-healthy | Startup error, missing config, SQLite fault | Check startup logs; confirm all required env keys present |
| 403 on `GET /webhook` (Meta verify) | `VERIFY_TOKEN` mismatch | Match token exactly in `.env` and Meta dashboard |
| 403 on `POST /webhook` (Meta) | `APP_SECRET` mismatch or missing signature header | Recheck `APP_SECRET`; confirm clock sync |
| 403 on `POST /webhook` (Evolution) | `EVOLUTION_WEBHOOK_SECRET` mismatch | Match header value and secret |
| No outbound replies | Expired token / key, upstream outage, retry exhaustion | Recheck provider credentials; check `fallback_sent` and `outbound_failure` counters |
| App fails to start | Missing required env key | Run `python -c "from app.config import validate_config; validate_config()"` to surface missing keys |
| Evolution API 404 or 500 | Container stopped or unhealthy | `docker ps`; restart container; check `docker logs evolution-api` |
| Sustained signature 403 burst | Possible replay attack | Alert security; inspect `X-Hub-Signature-256` and timestamp headers in logs |

---

## 7. Incident command protocol

- Assign **one incident commander** and **one comms owner** before any changes
- Record timestamps: detected → mitigated → recovered
- Capture correlation IDs from failing log entries
- Capture `GET /metrics` snapshot at incident open and close

---

## 8. Post-incident evidence checklist

- [ ] Incident start and end time, impact scope
- [ ] Root cause and corrective action
- [ ] Correlation IDs for representative failures
- [ ] Metrics snapshots (before and after mitigation)
- [ ] Customer-facing communication notes
- [ ] Follow-up tasks with owners and due dates

Full evidence requirements: `docs/operations_runbook.md` § 6

---

## 9. Useful references

| Document | Purpose |
|---|---|
| `docs/operations_runbook.md` | Full incident procedures, SQLite ops, channel extension |
| `docs/release_smoke_checklist.md` | Pre-staging and production release gate checklist |
| `docs/setup_guide.md` | First-time onboarding and provider config |
| `example.env` | All configurable environment keys with defaults |
| `data/agent_selection.json` | Current active agent |
