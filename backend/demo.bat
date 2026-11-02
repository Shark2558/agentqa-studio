@echo off
rem End-to-end demo: starts the demo portal and the dashboard, opens Live View,
rem runs every agent, then opens the report.
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup.bat first.
  exit /b 1
)
echo Starting the demo portal in a new window...
start "Demo portal (close to stop)" cmd /c ".venv\Scripts\python.exe -m agentqa demo-portal --port 8800"
.venv\Scripts\python.exe -m agentqa demo-project projects\demo
echo Starting the dashboard in a new window...
start "AgentQA dashboard (close to stop)" cmd /c ".venv\Scripts\python.exe -m agentqa ui --port 8700 --projects-dir projects"
timeout /t 6 /nobreak >nul
start "" "http://127.0.0.1:8700/p/demo/live"

echo.
echo Running the pipeline. Watch it in the browser (Live View).
echo For the demo, the SRS is treated as correct and the plan gate is skipped.
.venv\Scripts\python.exe -m agentqa pipeline -p projects\demo --policy srs_wins --auto-approve
if errorlevel 1 exit /b 1

start "" "http://127.0.0.1:8700/p/demo"
start "" "projects\demo\reports\report.html"
echo.
echo Done. The dashboard stays open: see the release readiness score, review questions,
echo the plan, imported tests and defects there, ask AgentQA questions, or replay the run in Live View.
endlocal
