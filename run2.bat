@echo off
setlocal
cd /d "%~dp0"

set "APP_HOST=127.0.0.1"
set "APP_PORT=5000"
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
	set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"
)

if not exist "%PYTHON_EXE%" (
	echo [run2.bat] Nao encontrei a virtualenv do projeto em .venv ou venv.
	echo [run2.bat] Crie a venv primeiro ou ajuste o caminho do Python neste arquivo.
	pause
	exit /b 1
)

powershell -NoProfile -Command ^
	"$listener = Get-NetTCPConnection -LocalPort %APP_PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; " ^
	"if (-not $listener) { exit 0 }; " ^
	"$proc = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $listener.OwningProcess); " ^
	"$commandLine = ($proc.CommandLine -replace '\r?\n', ' ').Trim(); " ^
	"Write-Host '[run2.bat] A porta %APP_PORT% ja esta em uso.'; " ^
	"if ($commandLine) { Write-Host ('[run2.bat] Processo atual: PID=' + $listener.OwningProcess + ' CMD=' + $commandLine) } else { Write-Host ('[run2.bat] Processo atual: PID=' + $listener.OwningProcess) }; " ^
	"Write-Host '[run2.bat] Feche esse processo ou ajuste APP_PORT antes de iniciar este projeto.'; " ^
	"exit 1"
if errorlevel 1 exit /b 1

echo [run2.bat] Iniciando app em http://%APP_HOST%:%APP_PORT%
powershell -NoExit -Command "$env:APP_HOST='%APP_HOST%'; $env:APP_PORT='%APP_PORT%'; & '%PYTHON_EXE%' 'main.py'"