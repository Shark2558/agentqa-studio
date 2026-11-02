<#
.SYNOPSIS
  Builds the AgentQA Studio Windows installer: Python, every package and Chromium bundled, no admin rights needed.

.DESCRIPTION
  Run on any Windows 10/11 x64 machine with internet access (or in GitHub Actions, see
  ../.github/workflows/agentqa-release.yml). Output: dist\AgentQA-Studio-Setup-<version>.exe

  1. Python embeddable package (no system Python needed on the target laptop)
  2. pip, then every package from requirements.txt into that Python
  3. Chromium for Playwright, stored inside the install folder
  4. Optional (-WithZap): OWASP ZAP and a Java runtime for the Security Scanner
  5. AgentQA itself and the launchers, then Inno Setup compiles the installer

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File installer\build_installer.ps1 -WithZap
#>
param(
  [string]$PythonVersion = "3.12.10",
  [switch]$WithZap,
  [string]$ZapVersion = "2.16.1",
  [string]$InnoSetup = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"          # Invoke-WebRequest is much faster without the progress bar
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Build = Join-Path $Root "build\AgentQA"
$Cache = Join-Path $Root "build\cache"
$Version = (Select-String -Path (Join-Path $Root "agentqa\__init__.py") -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
Write-Host "Building AgentQA Studio $Version"

if (Test-Path $Build) { Remove-Item $Build -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Build, $Cache | Out-Null

function Get-File($Url, $Name) {
  $target = Join-Path $Cache $Name
  if (-not (Test-Path $target)) { Write-Host "  downloading $Url"; Invoke-WebRequest -Uri $Url -OutFile $target }
  return $target
}

# 1. Python embeddable package --------------------------------------------------------------
$py = Join-Path $Build "python"
$zip = Get-File "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" "python-$PythonVersion-embed-amd64.zip"
Expand-Archive $zip -DestinationPath $py
$tag = ($PythonVersion.Split(".")[0..1] -join "")
# The ._pth file fixes sys.path: the standard library, site-packages and the AgentQA folder, nothing else.
Set-Content -Path (Join-Path $py "python$tag._pth") -Encoding ascii -Value @("python$tag.zip", ".", "Lib\site-packages", "..\app", "import site")
$python = Join-Path $py "python.exe"

# 2. pip and packages -----------------------------------------------------------------------
$getpip = Get-File "https://bootstrap.pypa.io/get-pip.py" "get-pip.py"
& $python $getpip --no-warn-script-location
if ($LASTEXITCODE) { throw "get-pip failed" }
& $python -m pip install --no-warn-script-location -r (Join-Path $Root "requirements.txt")
if ($LASTEXITCODE) { throw "pip install failed" }

# 3. Chromium inside the install folder -------------------------------------------------------
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $Build "browsers"
& $python -m playwright install chromium
if ($LASTEXITCODE) { throw "playwright install failed" }

# 4. AgentQA itself -------------------------------------------------------------------------------
$app = Join-Path $Build "app"
New-Item -ItemType Directory -Force -Path $app | Out-Null
foreach ($item in "agentqa", "demo", "ci", "tools", "README.md", "requirements.txt") {
  Copy-Item (Join-Path $Root $item) -Destination $app -Recurse
}
Get-ChildItem $app -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

# 5. Optional: OWASP ZAP and a Java runtime for it ----------------------------------------------
if ($WithZap) {
  $tools = Join-Path $app "tools"
  $zapZip = Get-File "https://github.com/zaproxy/zaproxy/releases/download/v$ZapVersion/ZAP_${ZapVersion}_Crossplatform.zip" "zap-$ZapVersion.zip"
  Expand-Archive $zapZip -DestinationPath (Join-Path $tools "zap")
  $jreZip = Get-File "https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jre/hotspot/normal/eclipse" "temurin-17-jre.zip"
  $tmp = Join-Path $Cache "jre-unpacked"
  if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
  Expand-Archive $jreZip -DestinationPath $tmp
  Move-Item (Get-ChildItem $tmp -Directory | Select-Object -First 1).FullName (Join-Path $tools "jre")
}

# 6. Launchers --------------------------------------------------------------------------------------
$common = @'
@echo off
setlocal
set "AQ=%~dp0"
set "PLAYWRIGHT_BROWSERS_PATH=%AQ%browsers"
set "PYTHONUTF8=1"
if not defined AGENTQA_DATA set "AGENTQA_DATA=%USERPROFILE%\AgentQA"
if not exist "%AGENTQA_DATA%\projects" mkdir "%AGENTQA_DATA%\projects"
cd /d "%AQ%app"
'@
Set-Content -Encoding ascii -Path (Join-Path $Build "AgentQA Studio.cmd") -Value ($common + @'
echo AgentQA Studio is starting on http://127.0.0.1:8700 (close this window to stop it).
start "" http://127.0.0.1:8700
"%AQ%python\python.exe" -m agentqa ui --port 8700 --projects-dir "%AGENTQA_DATA%\projects"
'@)
Set-Content -Encoding ascii -Path (Join-Path $Build "AgentQA Demo.cmd") -Value ($common + @'
echo Starting the demo portal and the dashboard...
start "Demo portal (close to stop)" /min "%AQ%python\python.exe" -m agentqa demo-portal --port 8800
start "AgentQA Studio (close to stop)" /min "%AQ%python\python.exe" -m agentqa ui --port 8700 --projects-dir "%AGENTQA_DATA%\projects"
if not exist "%AGENTQA_DATA%\projects\demo\project.yaml" "%AQ%python\python.exe" -m agentqa demo-project "%AGENTQA_DATA%\projects\demo"
timeout /t 6 /nobreak >nul
start "" "http://127.0.0.1:8700/p/demo/live"
"%AQ%python\python.exe" -m agentqa pipeline -p "%AGENTQA_DATA%\projects\demo" --policy srs_wins --auto-approve
start "" "http://127.0.0.1:8700/p/demo"
pause
'@)
Set-Content -Encoding ascii -Path (Join-Path $Build "agentqa.cmd") -Value ($common + @'
"%AQ%python\python.exe" -m agentqa %*
'@)

# 7. Smoke test of the bundle, then the installer --------------------------------------------------
& $python -c "import agentqa, playwright, fastapi, openpyxl, PIL; print('bundle imports ok', agentqa.__version__)"
if ($LASTEXITCODE) { throw "bundle smoke test failed" }
if (-not (Test-Path $InnoSetup)) { throw "Inno Setup 6 not found at $InnoSetup (choco install innosetup)" }
& $InnoSetup "/DAppVersion=$Version" (Join-Path $PSScriptRoot "AgentQA.iss")
if ($LASTEXITCODE) { throw "Inno Setup failed" }
Get-ChildItem (Join-Path $Root "dist") -Filter "*.exe" | ForEach-Object { Write-Host ("Built {0} ({1:N0} MB)" -f $_.FullName, ($_.Length / 1MB)) }
