# dev.ps1 — PowerShell development helpers for Project Aether
# Usage: .\scripts\dev.ps1 <command>

param(
    [ValidateSet("venv", "install", "lint", "test", "run-mock")]
    [string]$Command = "help"
)

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$VenvPath = Join-Path $ProjectRoot ".venv"
$VenvActivate = Join-Path $VenvPath "Scripts\Activate.ps1"

switch ($Command) {
    "venv" {
        Write-Host "Creating virtual environment..."
        python -m venv $VenvPath
        Write-Host "Virtual environment created at $VenvPath"
        Write-Host "Activate with: . .\.venv\Scripts\Activate.ps1"
    }
    "install" {
        if (-not (Test-Path $VenvActivate)) {
            Write-Host "Virtual environment not found. Run: .\scripts\dev.ps1 venv"
            exit 1
        }
        Write-Host "Activating venv..."
        & $VenvActivate
        Write-Host "Installing dependencies..."
        pip install -r requirements.txt
    }
    "lint" {
        & $VenvActivate
        flake8 src/ --max-line-length=100
    }
    "test" {
        & $VenvActivate
        pytest tests/ -v
    }
    "run-mock" {
        & $VenvActivate
        $env:AETHER_AI_BACKEND = "mock"
        python src/ai_engine/main.py
    }
    "help" {
        Write-Host @"
Project Aether Development Script

Usage: .\scripts\dev.ps1 <command>

Commands:
  venv      Create Python virtual environment
  install   Activate venv and install requirements.txt
  lint      Run flake8 on src/
  test      Run pytest on tests/
  run-mock  Run Phase 0 mock entrypoint (AETHER_AI_BACKEND=mock)
  help      Show this message

Example workflow:
  .\scripts\dev.ps1 venv
  .\scripts\dev.ps1 install
  .\scripts\dev.ps1 run-mock
  .\scripts\dev.ps1 lint
  .\scripts\dev.ps1 test
"@
    }
    default {
        Write-Host "Unknown command: $Command"
        Write-Host "Run: .\scripts\dev.ps1 help"
        exit 1
    }
}
