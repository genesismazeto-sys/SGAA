@echo off
setlocal
cd /d "%~dp0"

if "%APP_HOST%"=="" set "APP_HOST=127.0.0.1"
if "%APP_PORT%"=="" set "APP_PORT=5000"
set "APP_LOGIN_URL=http://%APP_HOST%:%APP_PORT%/login"

set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" (
	set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
	set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"
) else (
	set "PYTHON_EXE=python"
	echo [run.bat] Virtualenv not found. Using Python from PATH.
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
if errorlevel 1 exit /b 1

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
powershell -NoExit -Command "$env:APP_HOST='%APP_HOST%'; $env:APP_PORT='%APP_PORT%'; & '%PYTHON_EXE%' 'main.py'"