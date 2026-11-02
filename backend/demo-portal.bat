@echo off
rem Starts the bundled Demo Certificate Portal on http://127.0.0.1:8800
cd /d "%~dp0"
.venv\Scripts\python.exe -m agentqa demo-portal --port 8800
