#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Quick sanity check for WhatsApp bot and Evolution API setup.
  
.DESCRIPTION
  Tests both Flask bot (port 8000) and Evolution API (port 8080) connectivity.
  
.USAGE
  .\test-setup.ps1
#>

param(
    [string]$BotHost = "127.0.0.1",
    [int]$BotPort = 8000,
    [string]$EvoHost = "localhost",
    [int]$EvoPort = 8080,
    [string]$ApiKey = "change-me-strong"
)

$ErrorActionPreference = "SilentlyContinue"

Write-Output "`n=== WhatsApp Bot Setup Validation ==="
Write-Output "Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`n"

# Test Flask Bot Health
Write-Output "1. Testing Flask Bot Health (http://$($BotHost):$($BotPort)/health)..."
try {
    $bot_health = Invoke-WebRequest -Uri "http://$($BotHost):$($BotPort)/health" -TimeoutSec 5
    $bot_health_json = $bot_health.Content | ConvertFrom-Json
    
    if ($bot_health.StatusCode -eq 200) {
        Write-Output "   ✅ Bot Health: OK (Status=$($bot_health_json.status), Uptime=$($bot_health_json.uptime_seconds)s)"
    } else {
        Write-Output "   ⚠️  Bot Health: Status $($bot_health.StatusCode)"
    }
} catch {
    Write-Output "   ❌ Bot Health: FAILED - $($_.Exception.Message)"
}

# Test Flask Bot Webhook
Write-Output "`n2. Testing Flask Bot Webhook (http://$($BotHost):$($BotPort)/webhook)..."
try {
    $bot_webhook = Invoke-WebRequest -Uri "http://$($BotHost):$($BotPort)/webhook" -TimeoutSec 5
    $bot_webhook_json = $bot_webhook.Content | ConvertFrom-Json
    
    if ($bot_webhook.StatusCode -eq 200) {
        Write-Output "   ✅ Bot Webhook: OK (Provider=$($bot_webhook_json.provider), Status=$($bot_webhook_json.status))"
    } else {
        Write-Output "   ⚠️  Bot Webhook: Status $($bot_webhook.StatusCode)"
    }
} catch {
    Write-Output "   ❌ Bot Webhook: FAILED - $($_.Exception.Message)"
}

# Test Evolution API
Write-Output "`n3. Testing Evolution API (http://$($EvoHost):$($EvoPort))..."
try {
    $evo_status = Invoke-WebRequest -Uri "http://$($EvoHost):$($EvoPort)" `
        -Headers @{"apikey"=$ApiKey} `
        -TimeoutSec 5 -ErrorAction Continue
    
    if ($evo_status.StatusCode -ge 200 -and $evo_status.StatusCode -lt 300) {
        Write-Output "   ✅ Evolution API: REACHABLE (Status=$($evo_status.StatusCode))"
    } elseif ($evo_status.StatusCode -ge 300) {
        Write-Output "   ⚠️  Evolution API: REACHABLE but Status=$($evo_status.StatusCode) (may be expected)"
    }
} catch [System.Net.Http.HttpRequestException] {
    if ($_.Exception.InnerException.InnerException.Message -like "*refused*" -or $_.Exception.Message -like "*refused*") {
        Write-Output "   ❌ Evolution API: CONNECTION REFUSED (container not running?)"
    } else {
        Write-Output "   ⚠️  Evolution API: $($_.Exception.Message)"
    }
} catch {
    Write-Output "   ❌ Evolution API: FAILED - $($_.Exception.Message)"
}

# Check Docker Status
Write-Output "`n4. Checking Docker Status..."
try {
    $docker_path = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
    if (Test-Path $docker_path) {
        Write-Output "   ✅ Docker executable found at: $docker_path"
        
        # Try to list containers (may fail if daemon not ready)
        $containers = & $docker_path ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Output "   ✅ Docker daemon responsive`n"
            Write-Output $containers
        } else {
            Write-Output "   ⚠️  Docker daemon may be initializing..."
        }
    } else {
        Write-Output "   ❌ Docker executable not found at: $docker_path"
    }
} catch {
    Write-Output "   ⚠️  Docker check: $($_.Exception.Message)"
}

Write-Output "`n=== Summary ==="
Write-Output "If both Flask Bot and Evolution API show ✅, your setup is ready."
Write-Output "If Evolution API is ❌, run: docker start evolution-api"
Write-Output "If Flask Bot is ❌, run: python run.py (in project root with .venv activated)"
Write-Output ""
