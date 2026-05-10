param(
    [string]$TaskName = "python-whatsapp-bot-ngrok",
    [string]$Domain = "dares-undrafted-varsity.ngrok-free.dev",
    [int]$Port = 8000,
    [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [switch]$RunNow
)

$ErrorActionPreference = "Stop"

if ($Port -lt 1 -or $Port -gt 65535) {
    throw "Port must be between 1 and 65535."
}

$watchdogPath = Join-Path $RepoPath "start\ngrok_watchdog.ps1"
if (-not (Test-Path $watchdogPath)) {
    throw "Watchdog script not found at: $watchdogPath"
}

$escapedWatchdog = '"' + $watchdogPath + '"'
$escapedDomain = '"' + $Domain + '"'
$arguments = "-NoProfile -ExecutionPolicy Bypass -File $escapedWatchdog -Domain $escapedDomain -Port $Port"

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
$description = "Keeps ngrok tunnel alive for python-whatsapp-bot webhook tunneling."

try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description $description -Force | Out-Null
    Write-Host "Scheduled task registered: $TaskName"
    Write-Host "Task command: powershell.exe $arguments"
}
catch {
    if ($_.Exception.Message -notmatch "Access is denied") {
        throw
    }

    $startupFolder = [Environment]::GetFolderPath("Startup")
    $launcherPath = Join-Path $startupFolder "$TaskName.cmd"
    $launcherContent = @(
        "@echo off",
        "powershell.exe -NoProfile -ExecutionPolicy Bypass -File $escapedWatchdog -Domain $escapedDomain -Port $Port"
    ) -join "`r`n"

    Set-Content -Path $launcherPath -Value $launcherContent -Encoding Ascii
    Write-Warning "Scheduled Task permission denied. Created Startup launcher instead: $launcherPath"
}

if ($RunNow) {
    Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File $escapedWatchdog -Domain $escapedDomain -Port $Port" -WindowStyle Normal
    Write-Host "Watchdog started in a new PowerShell window."
}
