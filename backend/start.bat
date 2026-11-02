@echo off
rem Starts the AgentQA Studio dashboard on http://127.0.0.1:8700
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup.bat first.
  exit /b 1
)
start "" http://127.0.0.1:8700
.venv\Scripts\python.exe -m agentqa ui --port 8700 --projects-dir projects
