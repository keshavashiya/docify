#Requires -Version 5.1
<#
.SYNOPSIS
    Docify - One-Command Setup for Windows

.DESCRIPTION
    This script sets up everything needed to run Docify for the first time on Windows.

.PARAMETER SkipModels
    Skip pulling Ollama models (faster setup, but no LLM features)

.PARAMETER Reset
    Reset everything (WARNING: deletes all data)

.PARAMETER Help
    Show this help message

.EXAMPLE
    .\scripts\setup.ps1

.EXAMPLE
    .\scripts\setup.ps1 -SkipModels
#>

param(
    [switch]$SkipModels,
    [switch]$Reset,
    [switch]$Help
)

# Configuration
$PostgresWaitTimeout = 60
$OllamaWaitTimeout = 120
$BackendWaitTimeout = 90
$ModelPullTimeout = 900

# Colors
$Colors = @{
    Red = "Red"
    Green = "Green"
    Yellow = "Yellow"
    Blue = "Blue"
    Cyan = "Cyan"
}

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

function Write-Banner {
    Write-Host ""
    Write-ColorOutput @"
╔═══════════════════════════════════════════════════════════════════════╗
║                                                                       ║
║       ██████╗  ██████╗  ██████╗██╗███████╗██╗   ██╗                   ║
║       ██╔══██╗██╔═══██╗██╔════╝██║██╔════╝╚██╗ ██╔╝                   ║
║       ██║  ██║██║   ██║██║     ██║█████╗   ╚████╔╝                    ║
║       ██║  ██║██║   ██║██║     ██║██╔══╝    ╚██╔╝                     ║
║       ██████╔╝╚██████╔╝╚██████╗██║██║        ██║                      ║
║       ╚═════╝  ╚═════╝  ╚═════╝╚═╝╚═╝        ╚═╝                      ║
║                                                                       ║
║                   Local-First AI Second Brain                         ║
║                      One-Command Setup                                ║
║                                                                       ║
╚═══════════════════════════════════════════════════════════════════════╝
"@ -Color Cyan
    Write-Host ""
}

function Write-Step {
    param([int]$Step, [string]$Message)
    Write-Host ""
    Write-ColorOutput "[$Step/7] $Message" -Color Blue
    Write-ColorOutput ("━" * 65) -Color Blue
}

function Write-Success {
    param([string]$Message)
    Write-ColorOutput "✓ $Message" -Color Green
}

function Write-Warning {
    param([string]$Message)
    Write-ColorOutput "⚠ $Message" -Color Yellow
}

function Write-Error {
    param([string]$Message)
    Write-ColorOutput "✗ $Message" -Color Red
}

function Write-Info {
    param([string]$Message)
    Write-ColorOutput "ℹ $Message" -Color Cyan
}

function Test-Command {
    param([string]$Command)
    $null = Get-Command $Command -ErrorAction SilentlyContinue
    return $?
}

function Wait-ForService {
    param(
        [string]$Name,
        [scriptblock]$Check,
        [int]$Timeout,
        [string]$Message
    )

    $elapsed = 0
    while ($elapsed -lt $Timeout) {
        try {
            $result = & $Check 2>$null
            if ($LASTEXITCODE -eq 0 -or $result) {
                return $true
            }
        } catch {}

        Write-Host "`r⏳ $Message ($elapsed`s/$Timeout`s)" -NoNewline
        Start-Sleep -Seconds 2
        $elapsed += 2
    }
    Write-Host ""
    return $false
}

function Get-AvailableDiskGB {
    $drive = (Get-Location).Drive.Name
    $disk = Get-PSDrive -Name $drive
    return [math]::Floor($disk.Free / 1GB)
}

function Get-TotalMemoryGB {
    $mem = Get-CimInstance -ClassName Win32_ComputerSystem
    return [math]::Floor($mem.TotalPhysicalMemory / 1GB)
}

# Main Script
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

Write-Banner

# Step 0: Reset if requested
if ($Reset) {
    Write-Step 0 "Resetting Everything"
    Write-Warning "This will delete ALL data including uploaded documents!"
    $confirm = Read-Host "Are you sure? (y/N)"
    if ($confirm -eq 'y' -or $confirm -eq 'Y') {
        Write-Host "Stopping and removing containers..."
        Invoke-Expression "$DockerCompose down -v --remove-orphans" 2>$null
        Write-Success "All containers and volumes removed"
    } else {
        Write-Info "Reset cancelled"
        $Reset = $false
    }
}

# Step 1: Check Prerequisites
Write-Step 1 "Checking Prerequisites"

$missing = 0

# Check Docker
if (Test-Command "docker") {
    $dockerVersion = docker --version
    Write-Success "Docker is installed ($dockerVersion)"
} else {
    Write-Error "Docker is required but not installed"
    Write-Host "  Please install Docker Desktop from: https://docs.docker.com/desktop/install/windows-install/"
    $missing = 1
}

# Check Docker Compose
try {
    docker compose version 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $composeVersion = docker compose version --short
        Write-Success "Docker Compose is installed ($composeVersion)"
    } else {
        throw "Not found"
    }
} catch {
    if (Test-Command "docker-compose") {
        Write-Success "Docker Compose (legacy) is installed"
    } else {
        Write-Error "Docker Compose is required but not installed"
        $missing = 1
    }
}

# Check if Docker daemon is running
try {
    docker info 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Docker daemon is running"
    } else {
        throw "Not running"
    }
} catch {
    Write-Error "Docker daemon is not running"
    Write-Host "  Please start Docker Desktop"
    $missing = 1
}

# Check disk space
$diskGB = Get-AvailableDiskGB
if ($diskGB -ge 10) {
    Write-Success "Disk space: ${diskGB}GB available (10GB+ required)"
} else {
    Write-Warning "Low disk space: ${diskGB}GB available (10GB+ recommended)"
}

# Check memory
$memGB = Get-TotalMemoryGB
if ($memGB -ge 8) {
    Write-Success "System memory: ${memGB}GB (8GB+ required)"
} else {
    Write-Warning "Low memory: ${memGB}GB (8GB+ recommended for LLM)"
}

if ($missing -eq 1) {
    Write-Host ""
    Write-Error "Prerequisites check failed. Please install missing requirements."
    exit 1
}

# Step 2: Setup Environment
Write-Step 2 "Setting Up Environment"

if (Test-Path ".env") {
    Write-Info ".env file already exists"
    $overwrite = Read-Host "Overwrite with defaults? (y/N)"
    if ($overwrite -eq 'y' -or $overwrite -eq 'Y') {
        Copy-Item ".env.example" ".env" -Force
        Write-Success "Environment file updated from .env.example"
    } else {
        Write-Success "Keeping existing .env file"
    }
} else {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Success "Environment file created from .env.example"
    } else {
        Write-Error ".env.example not found!"
        exit 1
    }
}

Write-Info "You can customize settings in .env later"

# Step 3: Start Docker Services
Write-Step 3 "Starting Docker Services"

Write-Info "Building and starting containers (this may take a few minutes on first run)..."

Invoke-Expression "$DockerCompose up -d --build"

Write-Host ""
Write-Info "Waiting for services to be healthy..."

# Wait for PostgreSQL
if (Wait-ForService -Name "postgres" -Check { Invoke-Expression "$DockerCompose exec -T postgres pg_isready -U docify" } -Timeout $PostgresWaitTimeout -Message "Waiting for PostgreSQL...") {
    Write-Success "PostgreSQL is ready"
} else {
    Write-Error "PostgreSQL failed to start"
    exit 1
}

# Wait for Redis
if (Wait-ForService -Name "redis" -Check { Invoke-Expression "$DockerCompose exec -T redis redis-cli ping" } -Timeout 30 -Message "Waiting for Redis...") {
    Write-Success "Redis is ready"
} else {
    Write-Error "Redis failed to start"
    exit 1
}

# Wait for Ollama
if (Wait-ForService -Name "ollama" -Check { Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 5 } -Timeout $OllamaWaitTimeout -Message "Waiting for Ollama...") {
    Write-Success "Ollama is ready"
} else {
    Write-Warning "Ollama is slow to start (may still be initializing)"
}

# Step 4: Initialize Database
Write-Step 4 "Initializing Database"

Write-Info "Creating pgvector extension..."
Invoke-Expression "$DockerCompose exec -T postgres psql -U docify -d docify -c `"CREATE EXTENSION IF NOT EXISTS vector`"" 2>$null
Write-Success "pgvector extension ready"

Write-Info "Running database migrations..."
Invoke-Expression "$DockerCompose exec -T backend alembic upgrade head"
Write-Success "Database migrations complete"

# Step 5: Download AI Models
Write-Step 5 "Downloading AI Models"

if ($SkipModels) {
    Write-Warning "Skipping model download (--SkipModels flag)"
    Write-Info "Run without --SkipModels later to enable LLM features"
} else {
    Write-Info "This may take 5-15 minutes depending on your internet speed..."
    Write-Info "Models will be cached for future runs"
    Write-Host ""

    # Pull embedding model
    Write-ColorOutput "Downloading embedding model (all-minilm:22m)..." -Color Cyan
    Invoke-Expression "$DockerCompose exec -T ollama ollama pull all-minilm:22m"
    Write-Success "Embedding model ready"

    Write-Host ""

    # Pull LLM model
    Write-ColorOutput "Downloading LLM model (mistral:7b-instruct-q4_0)..." -Color Cyan
    Write-ColorOutput "This is a 4GB download - please be patient..." -Color Cyan
    Invoke-Expression "$DockerCompose exec -T ollama ollama pull mistral:7b-instruct-q4_0"
    Write-Success "LLM model ready"
}

# Step 6: Finalize Setup
Write-Step 6 "Finalizing Setup"

Write-Info "Restarting services with models loaded..."
Invoke-Expression "$DockerCompose restart backend celery-worker" 2>$null

# Wait for backend
Start-Sleep -Seconds 5
if (Wait-ForService -Name "backend" -Check { Invoke-WebRequest -Uri "http://localhost:8000/api/health" -UseBasicParsing -TimeoutSec 5 } -Timeout $BackendWaitTimeout -Message "Waiting for backend to be ready...") {
    Write-Success "Backend is healthy"
} else {
    Write-Warning "Backend is still starting..."
}

Write-Success "All services configured"

# Step 7: Summary
Write-Step 7 "Setup Complete!"

Write-Host ""
Write-ColorOutput @"
╔═══════════════════════════════════════════════════════════════════════╗
║                    🎉 Docify is Ready!                                ║
╚═══════════════════════════════════════════════════════════════════════╝
"@ -Color Green

Write-Host ""
Write-Host "Access your Docify instance:" -ForegroundColor White
Write-Host ""
Write-ColorOutput "  Frontend:     " -Color Cyan -NoNewline
Write-Host "http://localhost:3000"
Write-ColorOutput "  API Docs:     " -Color Cyan -NoNewline
Write-Host "http://localhost:8000/docs"
Write-ColorOutput "  Health Check: " -Color Cyan -NoNewline
Write-Host "http://localhost:8000/api/health"
Write-Host ""
Write-Host "Useful Commands:" -ForegroundColor White
Write-Host ""
Write-ColorOutput "  Start:  " -Color Yellow -NoNewline
Write-Host ".\scripts\start.ps1"
Write-ColorOutput "  Stop:   " -Color Yellow -NoNewline
Write-Host "docker-compose down"
Write-ColorOutput "  Logs:   " -Color Yellow -NoNewline
Write-Host "docker-compose logs -f"
Write-ColorOutput "  Status: " -Color Yellow -NoNewline
Write-Host "docker-compose ps"
Write-Host ""

Write-Host "Container Status:" -ForegroundColor White
Invoke-Expression "$DockerCompose ps"
Write-Host ""

if ($SkipModels) {
    Write-Warning "LLM models were skipped. Run setup without -SkipModels to enable AI features."
    Write-Host ""
}

Write-Info "Open http://localhost:3000 in your browser to get started!"
