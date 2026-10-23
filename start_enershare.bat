@echo off
echo ======================================================================
echo Starting EnerShare AI - Intelligent Renewable Energy Platform
echo Intelligent Renewable Energy Exchange ^& Smart Storage Optimization
echo ======================================================================
cd /d "%~dp0backend"
echo Launching FastAPI Server at http://localhost:8000/ ...
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
pause
