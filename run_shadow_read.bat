@echo off
setlocal
cd /d "%~dp0"

set "APP_HOST=127.0.0.1"
set "APP_PORT=5000"
set "SGAA_VERSIONED_RESOLVER_SHADOW_READ=1"
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
	set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"
)

if not exist "%PYTHON_EXE%" (
	echo [D6] Nao encontrei a virtualenv do projeto em .venv ou venv.
	echo [D6] Crie a venv primeiro antes de iniciar a coleta de shadow read.
	pause
	exit /b 1
)

echo [D6] SGAA_VERSIONED_RESOLVER_SHADOW_READ=1
echo [D6] Workspace: %~dp0
echo [D6] Endpoint de conferencia: /admin/diagnostico/versioned-shadow-reads

powershell -NoProfile -Command ^
	"$listener = Get-NetTCPConnection -LocalPort %APP_PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; " ^
	"if (-not $listener) { exit 0 }; " ^
	"$proc = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $listener.OwningProcess); " ^
	"$commandLine = ($proc.CommandLine -replace '\r?\n', ' ').Trim(); " ^
	"Write-Host '[D6] A porta %APP_PORT% ja esta em uso.'; " ^
	"if ($commandLine) { Write-Host ('[D6] Processo atual: PID=' + $listener.OwningProcess + ' CMD=' + $commandLine) } else { Write-Host ('[D6] Processo atual: PID=' + $listener.OwningProcess) }; " ^
	"Write-Host '[D6] Feche esse processo ou ajuste APP_PORT antes de iniciar a coleta.'; " ^
	"exit 1"
if errorlevel 1 exit /b 1

echo [D6] Executando preflight do endpoint de diagnostico...
set "SHADOW_READ_PREFLIGHT=1"
"%PYTHON_EXE%" "tools\preflight_shadow_read.py"
if errorlevel 1 (
	echo [D6] Preflight falhou. Nao crie solicitacoes antes de corrigir a configuracao.
	pause
	exit /b 1
)
set "SHADOW_READ_PREFLIGHT="

echo [D6] Preflight OK. Iniciando app em http://%APP_HOST%:%APP_PORT%
powershell -NoExit -Command "$env:APP_HOST='%APP_HOST%'; $env:APP_PORT='%APP_PORT%'; $env:SGAA_VERSIONED_RESOLVER_SHADOW_READ='1'; & '%PYTHON_EXE%' 'main.py'"
