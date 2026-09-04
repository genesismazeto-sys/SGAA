@echo off
setlocal
cd /d "%~dp0"

set "APP_HOST=127.0.0.1"
set "APP_PORT=5000"
for %%I in ("%~dp0.") do set "REPO_ROOT=%%~fI"

if "%LOCALAPPDATA%"=="" (
	echo [run2.bat] LOCALAPPDATA is not available.
	echo [run2.bat] Install Windows with a local user profile, then run this file again.
	pause
	exit /b 1
)

set "SGAA_VENV=%LOCALAPPDATA%\SGAA\venv"

powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%\tools\bootstrap_sgaa_runtime.ps1" -RepositoryRoot "%REPO_ROOT%" -VenvPath "%SGAA_VENV%" -RequirementsPath "%REPO_ROOT%\requirements.txt"
if errorlevel 1 (
	pause
	exit /b 1
)

set "PYTHON_EXE=%SGAA_VENV%\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
	echo [run2.bat] The machine-local SGAA Python was not created correctly.
	pause
	exit /b 1
)

powershell -NoProfile -Command ^
	"$listener = Get-NetTCPConnection -LocalPort %APP_PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; " ^
	"if (-not $listener) { exit 0 }; " ^
	"$proc = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $listener.OwningProcess); " ^
	"$commandLine = ($proc.CommandLine -replace '\r?\n', ' ').Trim(); " ^
	"Write-Host '[run2.bat] Port %APP_PORT% is already in use.'; " ^
	"if ($commandLine) { Write-Host ('[run2.bat] Current process: PID=' + $listener.OwningProcess + ' CMD=' + $commandLine) } else { Write-Host ('[run2.bat] Current process: PID=' + $listener.OwningProcess) }; " ^
	"Write-Host '[run2.bat] Close that process or change APP_PORT before starting this project.'; " ^
	"exit 1"
if errorlevel 1 (
	pause
	exit /b 1
)

echo [run2.bat] Starting app at http://%APP_HOST%:%APP_PORT%
powershell -NoProfile -NonInteractive -NoExit -Command "$env:APP_HOST='%APP_HOST%'; $env:APP_PORT='%APP_PORT%'; & '%PYTHON_EXE%' 'main.py'"
