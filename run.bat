@echo off
setlocal
cd /d "%~dp0"

if "%APP_HOST%"=="" set "APP_HOST=127.0.0.1"
if "%APP_PORT%"=="" set "APP_PORT=5000"
set "APP_LOGIN_URL=http://%APP_HOST%:%APP_PORT%/login"
for %%I in ("%~dp0.") do set "REPO_ROOT=%%~fI"

if "%LOCALAPPDATA%"=="" (
	echo [run.bat] LOCALAPPDATA is not available.
	echo [run.bat] Install Windows with a local user profile, then run this file again.
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
	echo [run.bat] The machine-local SGAA Python was not created correctly.
	pause
	exit /b 1
)

powershell -NoProfile -Command ^
	"$listener = Get-NetTCPConnection -LocalPort %APP_PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; " ^
	"if (-not $listener) { exit 0 }; " ^
	"$proc = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $listener.OwningProcess); " ^
	"$commandLine = ($proc.CommandLine -replace '\r?\n', ' ').Trim(); " ^
	"Write-Host '[run.bat] A porta %APP_PORT% ja esta em uso.'; " ^
	"if ($commandLine) { Write-Host ('[run.bat] Processo atual: PID=' + $listener.OwningProcess + ' CMD=' + $commandLine) } else { Write-Host ('[run.bat] Processo atual: PID=' + $listener.OwningProcess) }; " ^
	"Write-Host '[run.bat] Feche esse processo ou defina APP_PORT com outra porta antes de iniciar este projeto.'; " ^
	"exit 1"
if errorlevel 1 (
	 pause
	 exit /b 1
)

echo [run.bat] Iniciando app em http://%APP_HOST%:%APP_PORT%
echo [run.bat] Abrindo login automaticamente em %APP_LOGIN_URL%
start "" powershell -NoProfile -WindowStyle Hidden -Command ^
	"$url = '%APP_LOGIN_URL%'; $port = [int]%APP_PORT%; " ^
	"for ($i = 0; $i -lt 120; $i++) { " ^
	"  $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; " ^
	"  if ($listener) { Start-Process $url; exit 0 }; " ^
	"  Start-Sleep -Milliseconds 500; " ^
	"}; " ^
	"exit 0"
powershell -NoProfile -NonInteractive -NoExit -Command "$env:APP_HOST='%APP_HOST%'; $env:APP_PORT='%APP_PORT%'; & '%PYTHON_EXE%' 'main.py'"
