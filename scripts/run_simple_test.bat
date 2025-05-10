@echo off
chcp 65001 > nul
set PYTHONIOENCODING=utf-8

REM ====== go to workspace root ======
cd /d "%~dp0.."

REM ====== run quick test (first 3 URLs) ======
python Ver16.py 2 --headless

exit /b %errorlevel%
