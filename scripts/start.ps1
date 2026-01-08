#Requires -Version 5.1
<#
.SYNOPSIS
    Docify - Quick Start for Windows

.DESCRIPTION
    Use this script to start Docify after initial setup.
    For first-time setup, use: .\scripts\setup.ps1

.PARAMETER Build
    Rebuild containers before starting

.PARAMETER Logs
    Follow logs after starting

.PARAMETER Stop
    Stop all services

.PARAMETER Status
    Show status of services

.PARAMETER Help
    Show this help message

.EXAMPLE
    .\scripts\start.ps1

.EXAMPLE
    .\scripts\start.ps1 -Logs
#>

param(
    [switch]$Build,
    [switch]$Logs,
    [switch]$Stop,
    [switch]$Status,
    [switch]$Help
)

# Colors
function Write-ColorOutput {
    param(
        [string]$Message,
        [string]$Color = "White",
        [switch]$NoNewline
    )
    if ($NoNewline) {
        Write-Host $Message -ForegroundColor $Color -NoNewline
    } else {
        Write-Host $Message -ForegroundColor $Color
    }
}

if ($Help) {
    Get-Help $MyInvocation.MyCommand.Path -Detailed
    exit 0
}

# Change to project root
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Split-Path -Parent $ScriptDir)

# Determine docker compose command
$DockerCompose = "docker compose"
try {
    docker compose version 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $DockerCompose = "docker-compose"
    }
} catch {
    $DockerCompose = "docker-compose"
}

# Handle --Stop
if ($Stop) {
    Write-ColorOutput "⏹ Stopping Docify..." -Color Yellow
    Invoke-Expression "$DockerCompose down"
    Write-ColorOutput "✓ All services stopped" -Color Green
    exit 0
}

# Handle --Status
if ($Status) {
    Write-ColorOutput "📊 Docify Status" -Color Cyan
    Write-Host ""
    Invoke-Expression "$DockerCompose ps"
    exit 0
}

Write-Host ""
Write-ColorOutput "🚀 Starting Docify..." -Color Cyan
Write-Host ""

# Check if .env exists
if (-not (Test-Path ".env")) {
    Write-ColorOutput "⚠ No .env file found. Running initial setup..." -Color Yellow
    & ".\scripts\setup.ps1"
    exit 0
}

# Check if Docker is running
try {
    docker info 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Not running"
    }
} catch {
    Write-ColorOutput "✗ Docker is not running. Please start Docker Desktop first." -Color Red
    exit 1
}

# Build args
$buildArg = if ($Build) { "--build" } else { "" }

# Start services
Write-ColorOutput "Starting Docker containers..." -Color Blue
Invoke-Expression "$DockerCompose up -d $buildArg"

# Wait a moment for services
Write-ColorOutput "Waiting for services to be ready..." -Color Blue
Start-Sleep -Seconds 5

# Check health
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8000/api/health" -UseBasicParsing -TimeoutSec 5 -ErrorAction SilentlyContinue
    if ($response.StatusCode -eq 200) {
        Write-Host ""
        Write-ColorOutput "✓ Docify is running!" -Color Green
        Write-Host ""
        Write-ColorOutput "  Frontend:     " -Color Cyan -NoNewline
        Write-Host "http://localhost:3000"
        Write-ColorOutput "  API Docs:     " -Color Cyan -NoNewline
        Write-Host "http://localhost:8000/docs"
        Write-Host ""
    } else {
        throw "Not ready"
    }
} catch {
    Write-Host ""
    Write-ColorOutput "⏳ Services are still starting..." -Color Yellow
    Write-Host "   Check status with: docker-compose ps"
    Write-Host "   View logs with: docker-compose logs -f"
    Write-Host ""
}

# Show container status
Write-Host "Container Status:" -ForegroundColor White
Invoke-Expression "$DockerCompose ps"

if ($Logs) {
    Write-Host ""
    Write-ColorOutput "Following logs (Ctrl+C to exit)..." -Color Blue
    Invoke-Expression "$DockerCompose logs -f"
}
