# Docify Scripts

This folder contains cross-platform scripts for setting up and managing Docify.

## Scripts

| Script | Platform | Description |
|--------|----------|-------------|
| `setup.sh` | macOS, Linux | Complete first-time setup |
| `setup.ps1` | Windows | Complete first-time setup (PowerShell) |
| `start.sh` | macOS, Linux | Quick start for daily use |
| `start.ps1` | Windows | Quick start for daily use (PowerShell) |

## Setup (First Time)

### macOS / Linux
```bash
./scripts/setup.sh
```

### Windows (PowerShell)
```powershell
.\scripts\setup.ps1
```

### Options

| Option (Bash) | Option (PowerShell) | Description |
|---------------|---------------------|-------------|
| `--skip-models` | `-SkipModels` | Skip AI model download (faster setup, no LLM) |
| `--reset` | `-Reset` | Delete all data and start fresh |
| `--help` | `-Help` | Show help message |

## Daily Start

### macOS / Linux
```bash
./scripts/start.sh          # Start services
./scripts/start.sh --logs   # Start and follow logs
./scripts/start.sh --stop   # Stop all services
./scripts/start.sh --status # Show status
./scripts/start.sh --build  # Rebuild containers
```

### Windows (PowerShell)
```powershell
.\scripts\start.ps1          # Start services
.\scripts\start.ps1 -Logs    # Start and follow logs
.\scripts\start.ps1 -Stop    # Stop all services
.\scripts\start.ps1 -Status  # Show status
.\scripts\start.ps1 -Build   # Rebuild containers
```

## Requirements

- **Docker Desktop** (includes Docker Compose)
- **8GB RAM** minimum (16GB recommended)
- **20GB disk space** (for AI models and data)

## Troubleshooting

### Docker not running
Make sure Docker Desktop is running before executing the scripts.

### Permission denied (macOS/Linux)
Make scripts executable:
```bash
chmod +x scripts/setup.sh scripts/start.sh
```

### PowerShell execution policy (Windows)
If scripts are blocked, run PowerShell as Administrator and execute:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```
