@echo off
rem AgentQA Studio - one-time setup for Windows 10/11
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python 3.11 or newer is required.
  echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH", then run setup.bat again.
  exit /b 1
)

if not exist .venv (
  echo Creating virtual environment...
  %PY% -m venv .venv || exit /b 1
)
call .venv\Scripts\activate.bat

echo Installing Python packages (behind a corporate proxy, set HTTPS_PROXY first)...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt || exit /b 1

echo Downloading the Chromium browser used for testing (about 150 MB)...
python -m playwright install chromium || exit /b 1

if not exist projects mkdir projects

echo.
echo Setup complete.
echo   demo.bat   - run the full pipeline against the bundled demo portal
echo   start.bat  - open the AgentQA Studio dashboard
where ollama >nul 2>nul
if %errorlevel%==0 (
  echo   Ollama found. Optional local model: ollama pull qwen3:4b
) else (
  echo   Optional: install Ollama from https://ollama.com for the local model assistant.
)
endlocal
