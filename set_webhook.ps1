$api_key = "7e8QU1GCRcDYjfiqH2zSVvK0pkZbBPWw"
$instance = "bot-instance"
$webhook_base_url = if ($env:WEBHOOK_BASE_URL) { $env:WEBHOOK_BASE_URL.TrimEnd('/') } else { "https://whatsapp-chatbot-production-c856.up.railway.app" }

# First create the instance (idempotent - ok if already exists)
Write-Host "Creating instance..."
$create_body = '{"instanceName":"bot-instance","qrcode":true,"integration":"WHATSAPP-BAILEYS"}'
try {
    $r = Invoke-WebRequest -Uri "http://localhost:8080/instance/create" -Method POST -Headers @{"apikey"=$api_key;"Content-Type"="application/json"} -Body $create_body -UseBasicParsing
    Write-Host "Instance: $($r.StatusCode)"
} catch {
    Write-Host "Instance already exists (ok)"
}

# Set webhook
Write-Host "Setting webhook to $webhook_base_url/webhook ..."
$wh_body = '{"webhook":{"enabled":true,"url":"' + $webhook_base_url + '/webhook","webhook_by_events":false,"webhook_base64":false,"events":["MESSAGES_UPSERT","CONNECTION_UPDATE","MESSAGES_UPDATE"]}}'
$r2 = Invoke-WebRequest -Uri "http://localhost:8080/webhook/set/$instance" -Method POST -Headers @{"apikey"=$api_key;"Content-Type"="application/json"} -Body $wh_body -UseBasicParsing
Write-Host "Webhook status: $($r2.StatusCode)"
Write-Host $r2.Content

# Get QR code
Write-Host ""
Write-Host "Fetching QR code URL..."
$r3 = Invoke-WebRequest -Uri "http://localhost:8080/instance/connect/$instance" -Headers @{"apikey"=$api_key} -UseBasicParsing
Write-Host $r3.Content
