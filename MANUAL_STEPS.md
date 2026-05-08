# Manual Setup Steps - If You Need to Restart

**Last updated: 2026-05-08**

> Key values:
> - Evolution API key: `7e8QU1GCRcDYjfiqH2zSVvK0pkZbBPWw`
> - Evolution instance: `bot-instance`
> - docker-compose location: `C:\evolution-api\docker-compose.yml`
> - Bot project: `C:\Users\wahab\OneDrive\Documents\GitHub\python-whatsapp-bot`

## Start Fresh or Resume Setup

### Terminal 1: Start Flask Bot

```powershell
cd C:\Users\wahab\OneDrive\Documents\GitHub\python-whatsapp-bot

# Start bot on port 8000
.venv\Scripts\python.exe run.py
```

**Expected output:**
```
2026-04-30 13:17:30,680 - root - INFO - Flask app started
 * Running on http://0.0.0.0:8000
Press CTRL+C to quit
```

✅ Flask bot is now live on `http://localhost:8000`

---

### Terminal 2: Start Evolution API in Docker (docker-compose)

```powershell
# Ensure Docker Desktop is running first
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
# Wait ~30s for daemon...

# Start Evolution API + PostgreSQL
cd C:\evolution-api
docker-compose up -d

# Verify both containers are up
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

**Expected output:**
```
NAMES                STATUS         PORTS
evolution-api        Up X minutes   0.0.0.0:8080->8080/tcp
evolution-postgres   Up X minutes
```

> ⚠️ Evolution API takes ~30s to run migrations on first start. If HTTP check fails, wait and retry.

```powershell
# Confirm Evolution API is responding
Invoke-WebRequest http://localhost:8080 -UseBasicParsing | Select-Object StatusCode
# Expected: 200
```

✅ Evolution API is now live on `http://localhost:8080`

---

### Terminal 3: Start ngrok Public Tunnel

```powershell
# Open ngrok tunnel (run in a separate window — keep it running)
Start-Process "ngrok" -ArgumentList "http 8000" -WindowStyle Normal

# Wait 3s then get the public URL
Start-Sleep -Seconds 3
Invoke-WebRequest http://127.0.0.1:4040/api/tunnels -UseBasicParsing |
  ConvertFrom-Json | Select-Object -ExpandProperty tunnels |
  ForEach-Object { $_.public_url }
# Note the https:// URL — you'll need it for the webhook
```

### Terminal 3: Test Connectivity

```powershell
# Test Flask Bot
Invoke-WebRequest http://localhost:8000/health -UseBasicParsing | Select-Object StatusCode

# Test Evolution API
Invoke-WebRequest http://localhost:8080 -UseBasicParsing | Select-Object StatusCode
```

---

## Configure Webhook + Get QR Code

A helper script handles both steps. Update `$ngrok_url` to your current ngrok URL first:

```powershell
cd C:\Users\wahab\OneDrive\Documents\GitHub\python-whatsapp-bot

# Edit set_webhook.ps1 to set the correct ngrok URL, then:
powershell -ExecutionPolicy Bypass -File set_webhook.ps1
```

The script will:
1. Create the `bot-instance` if it doesn't exist
2. Set the webhook URL to `<ngrok_url>/webhook`
3. Print the QR code as a base64 PNG → saved to `qr.png`

To render and scan the QR:
```powershell
# Save QR code as image and open it
$api_key = "7e8QU1GCRcDYjfiqH2zSVvK0pkZbBPWw"
$instance = "bot-instance"
$r = Invoke-WebRequest -Uri "http://localhost:8080/instance/connect/$instance" `
  -Headers @{"apikey"=$api_key} -UseBasicParsing
$data = ($r.Content | ConvertFrom-Json).base64 -replace "data:image/png;base64,",""
[System.IO.File]::WriteAllBytes("$PWD\qr.png", [Convert]::FromBase64String($data))
Start-Process qr.png
```

Scan `qr.png` with WhatsApp: **Settings → Linked Devices → Link a Device**

> ⚠️ QR codes expire after ~60 seconds. Re-run the block if you get a scan timeout.

---

## Send Test Message

```powershell
$instance = "bot-instance"
$api_key = "7e8QU1GCRcDYjfiqH2zSVvK0pkZbBPWw"
$recipient_waid = "923359999195"  # From your .env RECIPIENT_WAID

# Send test text message
$msg_body = @{
  number = $recipient_waid
  text = "Hello from Evolution API bot!"
  linkPreview = $false
} | ConvertTo-Json

Write-Output "Sending test message to $recipient_waid..."

$msg_resp = Invoke-WebRequest -Uri "http://localhost:8080/message/sendText/$instance" `
  -Method POST `
  -Headers @{
    "apikey" = $api_key
    "Content-Type" = "application/json"
  } `
  -Body $msg_body

Write-Output "Message sent:"
$msg_resp.Content | ConvertFrom-Json | ConvertTo-Json
```

---

## Check Logs

### Flask Bot Logs (from Terminal 1):
- Watch the running terminal for incoming webhook messages

### Evolution API Logs:
```powershell
docker logs evolution-api -f
# Stop: CTRL+C
```

### PostgreSQL Logs:
```powershell
docker logs evolution-postgres -f
```

### ngrok Traffic Inspector:
Open http://127.0.0.1:4040 in a browser to see all incoming webhook requests in real time.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `evolution-postgres` restarting | Corrupt volume from interrupted start | `cd C:\evolution-api ; docker-compose down -v ; docker-compose up -d` |
| Evolution API `Can't reach database server` | Postgres still initializing | Wait 15s, then `docker-compose up -d` again |
| ngrok `Unable to connect` | Tunnel not started or auth token missing | Run `ngrok config add-authtoken <token>` then restart ngrok |
| Webhook not firing | ngrok URL changed | Update `set_webhook.ps1` with new URL and re-run |
| Bot not responding to messages | Flask bot not running on port 8000 | `netstat -ano \| findstr ":8000"` — restart if missing |
| QR code expired | Scan took >60s | Re-run the QR fetch block and scan within 60s |

---

## Stop & Cleanup

### Stop Flask Bot:
In Terminal 1: Press `CTRL+C`

### Stop Evolution Container:
```bash
docker stop evolution-api
docker rm evolution-api

# Or, if you want to restart it:
docker start evolution-api
```

### Stop Docker:
Close Docker Desktop window, or:
```bash
Get-Process -Name "Docker Desktop" | Stop-Process -Force
```

---

## Common Errors & Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `Connection refused on 8080` | Docker not running | `docker ps` - if fails, start Docker Desktop |
| `Connection refused on 8000` | Flask bot not running | Run `python run.py` in Terminal 1 |
| `403 Forbidden on webhook` | Wrong API key | Update `.env` EVOLUTION_API_KEY and/or webhook headers |
| `Cannot create instance: 409` | Instance already exists | `docker restart evolution-api` or use different instance name |
| `No output from docker run` | Container crashed | `docker logs evolution-api` to see errors |
| `PowerShell Profile Error` | Execution policy | Commands still work; just ignore the policy warning |

---

## Quick Reference: All Endpoints

```
Flask Bot:
  GET    http://localhost:8000/health         → Health status
  GET    http://localhost:8000/webhook        → Webhook ready status
  POST   http://localhost:8000/webhook        → Inbound message handler
  GET    http://localhost:8000/metrics        → Metrics
  GET    http://localhost:8000/setup          → Setup UI

Evolution API:
  POST   http://localhost:8080/instance/create                → Create instance
  GET    http://localhost:8080/instance/connect/{name}        → Get QR code
  GET    http://localhost:8080/instance/logout/{name}         → Disconnect instance
  PUT    http://localhost:8080/instance/settings/{name}       → Configure webhook
  POST   http://localhost:8080/message/sendText/{name}        → Send message
  GET    http://localhost:8080/instance/fetchInstances        → List instances
```

All Evolution endpoints require header: `apikey: change-me-strong`

---

**Last Updated:** 2026-04-30
