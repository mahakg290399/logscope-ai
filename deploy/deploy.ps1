# LogScope AI - Windows PowerShell Automated Deployment Script
$ErrorActionPreference = "Stop"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "LogScope AI - Multi-Component Stack Deployment (Windows)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Check prerequisites
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker is required but not installed or not in PATH."
}

# 2. Check environment file
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Write-Host "[-] Copying .env.example -> .env..." -ForegroundColor Yellow
        Copy-Item ".env.example" ".env"
        Write-Host "[!] Please set your NVIDIA_API_KEY in .env before running production traffic." -ForegroundColor Yellow
    }
}

# 3. Ensure required directories exist
New-Item -ItemType Directory -Force -Path "data" | Out-Null
New-Item -ItemType Directory -Force -Path "logs" | Out-Null

# 4. Validate Docker Compose config
Write-Host "[-] Validating Docker Compose configuration..." -ForegroundColor Gray
docker compose config > $null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker compose configuration validation failed."
}

# 5. Build and start services
Write-Host "[-] Building and launching LogScope stack..." -ForegroundColor Green
docker compose up -d --build

# 6. Wait for health check
Write-Host "[-] Waiting for LogScope services to report healthy..." -ForegroundColor Gray
$maxRetries = 30
$retries = 0
$healthy = $false

while ($retries -lt $maxRetries) {
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -Method Get -TimeoutSec 2 -ErrorAction Stop
        if ($resp.status -eq "ok") {
            $healthy = $true
            break
        }
    } catch {
        # Retry
    }
    $retries++
    Write-Host "    Waiting for services... ($retries/$maxRetries)" -ForegroundColor Gray
    Start-Sleep -Seconds 3
}

if ($healthy) {
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "[SUCCESS] LogScope AI stack is up and running!" -ForegroundColor Green
    Write-Host "Dashboard URL: http://127.0.0.1:8000" -ForegroundColor White
    Write-Host "Health Check : http://127.0.0.1:8000/api/health" -ForegroundColor White
    Write-Host "Telemetry    : http://127.0.0.1:8000/api/telemetry" -ForegroundColor White
    Write-Host "============================================================" -ForegroundColor Green
} else {
    Write-Host "[!] Timed out waiting for LogScope health endpoint. Checking logs:" -ForegroundColor Red
    docker compose logs --tail 30
    exit 1
}
