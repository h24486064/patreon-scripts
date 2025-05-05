@echo off
REM ====== go to workspace root ======
cd /d "%~dp0.."

REM ====== run quick test (first 3 URLs) ======
python Ver16.py 3

exit /b %errorlevel%
