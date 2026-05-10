param(
    [string]$Domain = "dares-undrafted-varsity.ngrok-free.dev",
    [int]$Port = 8000,
    [int]$RestartDelaySeconds = 3,
    [switch]$PoolingEnabled,
    [switch]$RunOnce,
    [int]$ExistingEndpointRecheckSeconds = 30
)

$ErrorActionPreference = "Stop"
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

if ($Port -lt 1 -or $Port -gt 65535) {
    throw "Port must be between 1 and 65535."
}

$ngrok = Get-Command ngrok -ErrorAction SilentlyContinue
if (-not $ngrok) {
    throw "ngrok is not installed or not available on PATH."
}

$publicHealthUrl = "https://$Domain/health"
$arguments = @("http", $Port.ToString(), "--url", "https://$Domain")
if ($PoolingEnabled) {
    $arguments += "--pooling-enabled"
}

Write-Host "Starting ngrok watchdog..."
Write-Host "Domain: $Domain"
Write-Host "Port: $Port"
Write-Host "Run once: $RunOnce"

while ($true) {
    Write-Host "Launching: ngrok $($arguments -join ' ')"

    $output = @()
    $exitCode = 0
    try {
        $output = & $ngrok.Source @arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    catch {
        $output = @($output) + @($_.ToString())
        $exitCode = if ($LASTEXITCODE) { $LASTEXITCODE } else { 1 }
    }

    if ($output) {
        $output | ForEach-Object { Write-Host $_ }
    }

    $combinedOutput = ($output | Out-String)

    if ($exitCode -eq 0) {
        if ($RunOnce) {
            exit 0
        }
        Write-Host "ngrok exited cleanly. Restarting in $RestartDelaySeconds second(s)..."
        Start-Sleep -Seconds $RestartDelaySeconds
        continue
    }

    if ($combinedOutput -match "ERR_NGROK_334|already online") {
        $isHealthy = $false
        try {
            $response = Invoke-WebRequest -Uri $publicHealthUrl -Method GET -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                $isHealthy = $true
            }
        }
        catch {
            $isHealthy = $false
        }

        if ($isHealthy) {
            if ($RunOnce) {
                Write-Host "Endpoint already online and healthy at $publicHealthUrl"
                exit 0
            }
            Write-Warning "Endpoint already online (ERR_NGROK_334) but health check passed. Rechecking in $ExistingEndpointRecheckSeconds second(s)..."
            Start-Sleep -Seconds $ExistingEndpointRecheckSeconds
            continue
        }
    }

    if ($RunOnce) {
        exit $exitCode
    }

    Write-Warning "ngrok exited with code $exitCode. Restarting in $RestartDelaySeconds second(s)..."
    Start-Sleep -Seconds $RestartDelaySeconds
}
