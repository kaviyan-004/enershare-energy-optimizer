# EnerShare AI - PowerShell Launcher
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "Starting EnerShare AI - Intelligent Renewable Energy Platform" -ForegroundColor Green
Write-Host "Intelligent Renewable Energy Exchange & Smart Storage Optimization" -ForegroundColor Yellow
Write-Host "======================================================================" -ForegroundColor Cyan

Set-Location "$PSScriptRoot\backend"
Write-Host "Launching FastAPI Server on http://localhost:8000/ ..." -ForegroundColor Green
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
