@echo off
cd /d "%~dp0"
call run_full_scrape.bat || goto :eof
call sync_to_gdrive.bat
