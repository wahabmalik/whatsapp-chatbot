# Setup Guide

Canonical setup document for first-time onboarding.

Audience: operator or developer performing first-time setup.

Targets:
- Config-entry target: < 2 minutes (once values are ready)
- End-to-end onboarding target: <= 45 minutes to first verified test message

## 1. Prerequisites

Prepare these before starting:
- Python 3.9+
- git
- One WhatsApp transport:
	- Evolution API server URL, API key, and instance name
	- or Meta Developer app with WhatsApp product enabled
- OpenAI API key
- Public HTTPS callback URL (ngrok or deployed host)

## 2. Install and run locally

```bash
git clone https://github.com/your-org/python-whatsapp-bot.git
cd python-whatsapp-bot
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Configure environment

Copy template and fill required values:

```bash
copy example.env .env
```

Required keys:
- For Evolution API:
	- WHATSAPP_PROVIDER=evolution
	- EVOLUTION_API_URL
	- EVOLUTION_API_KEY
	- EVOLUTION_INSTANCE_NAME
	- OPENAI_API_KEY
	- APP_SECRET (set a local value for signature/replay checks and staging validation command compatibility)
- For Meta Cloud API:
	- WHATSAPP_PROVIDER=meta
	- ACCESS_TOKEN
	- APP_SECRET
	- PHONE_NUMBER_ID
	- VERSION (for example v18.0)
	- VERIFY_TOKEN
	- OPENAI_API_KEY

Security hygiene:
- Never commit `.env`.
- Keep tokens/secrets out of screenshots and shared logs.

## 4. Launch app and setup flow

Apply database migrations before first startup (SaaS schema):

```bash
# PowerShell
$env:DATABASE_URL="sqlite:///./data/saas.db"
python -m alembic upgrade head

# bash/zsh
export DATABASE_URL="sqlite:///./data/saas.db"
python -m alembic upgrade head
```

Start app:

```bash
python run.py
```

Production-style launch (cross-platform):

```bash
python serve.py
```

Behavior:
- Linux/macOS: starts Gunicorn with `gunicorn.conf.py`
- Windows: starts Waitress (Gunicorn is Unix-only)

Direct Gunicorn launch (Linux/macOS only):

```bash
gunicorn -c gunicorn.conf.py wsgi:app
```

Optional Gunicorn environment overrides:
- GUNICORN_BIND (default: 0.0.0.0:8000)
- GUNICORN_WORKERS (default: 2 x CPU + 1)
- GUNICORN_THREADS (default: 1)
- GUNICORN_TIMEOUT (default: 120)
- GUNICORN_GRACEFUL_TIMEOUT (default: 30)
- GUNICORN_KEEPALIVE (default: 5)
- GUNICORN_LOG_LEVEL (default: info)

Optional Waitress override (Windows):
- WAITRESS_THREADS (default: 8)

Open setup:
- http://127.0.0.1:8000/setup

Expected behavior:
- Missing keys are shown as explicit validation errors
- Webhook processing remains blocked until required keys are valid

## 5. Configure provider callback

For Evolution API:
- Set the instance webhook URL to https://<public-host>/webhook
- If you configure `EVOLUTION_WEBHOOK_SECRET`, send the same value in the configured header name (default: `apikey`)

For Meta WhatsApp configuration:
- Callback URL: https://<public-host>/webhook
- Verify Token: must exactly match VERIFY_TOKEN from `.env`
- Subscribe webhook field: messages

Success condition:
- Evolution: GET `/webhook` returns ready status 200.
- Meta: GET `/webhook` verification challenge returns 200.

## 6. Send first test message

1. Open agent selection page: http://127.0.0.1:8000/agents
2. Select and save an active agent
3. Send a WhatsApp message to the configured test number

Expected signals:
- `/webhook` accepts and processes inbound message
- Reply is returned to sender
- Metrics and logs are updated

## 7. Verify monitoring endpoints

Use this endpoint map to avoid confusion between public API endpoints and operator dashboard endpoints.

| Purpose | Endpoint | Notes |
|---|---|---|
| Public health API | GET `/health` | Unauthenticated JSON; webhook/public observability |
| Public metrics API | GET `/metrics` | Unauthenticated JSON; webhook/public observability |
| Operator dashboard health API | GET `/api/health` | JSON; used by dashboard UI polling |
| Operator dashboard metrics API | GET `/api/metrics` | JSON; used by dashboard UI polling |
| Operator dashboard logs API | GET `/api/logs` | JSON; used by dashboard UI polling |
| Operator metrics page | GET `/operator/metrics` | HTML page; requires operator session (see `/operator/access`) |

## 8. Troubleshooting quick table

| Symptom | Likely cause | Action |
|---|---|---|
| 403 during webhook verify | VERIFY_TOKEN mismatch | Match token exactly in `.env` and Meta config |
| 403 on inbound POST /webhook | APP_SECRET mismatch or invalid signature header | Recheck APP_SECRET and request signature configuration |
| 403 on inbound POST /webhook with Evolution | EVOLUTION_WEBHOOK_SECRET mismatch | Match the configured header value and secret |
| No outbound reply | Expired token, invalid Evolution API key, upstream outage, retry exhaustion | Recheck provider credentials, inspect metrics/logs, follow runbook |
| App fails startup | Missing/invalid env key | Fix key and restart |

For operational incident handling, see `docs/operations_runbook.md`.

## 9. Release validation

Before promoting to staging or production, run the release smoke checklist:
- `docs/release_smoke_checklist.md`

Automation commands:
```bash
python -m unittest discover tests
python start/generate_test_results_summary.py
python start/staging_validation.py
python start/evaluate_launch_gates.py
```

A GO decision from the launch gate evaluator is required before production release.  
Evidence artifacts are written to `_bmad-output/test-artifacts/`.
