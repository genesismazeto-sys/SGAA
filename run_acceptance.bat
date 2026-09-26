@echo off
rem =====================================================================
rem SGAA -- isolated ACCEPTANCE runtime.
rem
rem   run.bat            -> canonical runtime,  port 5000, canonical database.db
rem   run_acceptance.bat -> acceptance runtime, port 5000, disposable database
rem
rem SGAA has ONE application port: 5000.  The isolation boundary is the
rem DATABASE, never the port.  That is also why the canonical and the
rem acceptance runtime can never run at the same time, and why this file
rem refuses to start when 5000 is already taken.
rem
rem This file owns configuration and refusal only.  Every launch step (venv
rem bootstrap, startup preflight, browser open, app start) stays in run.bat,
rem which is called unchanged at the end.
rem =====================================================================
setlocal
cd /d "%~dp0"

if "%LOCALAPPDATA%"=="" (
	echo [run_acceptance.bat] LOCALAPPDATA is not available.
	pause
	exit /b 1
)

if "%APP_HOST%"=="" set "APP_HOST=127.0.0.1"
set "APP_PORT=5000"
if "%SGAA_ACCEPTANCE_DB%"=="" set "SGAA_ACCEPTANCE_DB=%LOCALAPPDATA%\SGAA\acceptance_v8\database.db"
set "APP_DATABASE=%SGAA_ACCEPTANCE_DB%"

for %%I in ("%~dp0database.db") do set "CANONICAL_DB=%%~fI"
for %%I in ("%APP_DATABASE%") do set "RESOLVED_DB=%%~fI"

if /i "%RESOLVED_DB%"=="%CANONICAL_DB%" (
	echo [run_acceptance.bat] RECUSADO: APP_DATABASE aponta para o banco canonico.
	echo [run_acceptance.bat]   %RESOLVED_DB%
	echo [run_acceptance.bat] A aceitacao precisa de um banco descartavel fora do repositorio.
	pause
	exit /b 1
)

if not exist "%RESOLVED_DB%" (
	echo [run_acceptance.bat] Banco de aceitacao ausente:
	echo [run_acceptance.bat]   %RESOLVED_DB%
	echo [run_acceptance.bat] Crie uma copia descartavel antes de iniciar a aceitacao.
	pause
	exit /b 1
)

rem Only one SGAA may listen on 5000.  Refused here, before anything starts,
rem so a second runtime can never come up silently beside the canonical one.
powershell -NoProfile -Command ^
	"$listener = Get-NetTCPConnection -LocalPort %APP_PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; " ^
	"if (-not $listener) { exit 0 }; " ^
	"$proc = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $listener.OwningProcess); " ^
	"$commandLine = ($proc.CommandLine -replace '\r?\n', ' ').Trim(); " ^
	"Write-Host '[run_acceptance.bat] RECUSADO: a porta %APP_PORT% ja esta em uso.'; " ^
	"if ($commandLine) { Write-Host ('[run_acceptance.bat] Processo atual: PID=' + $listener.OwningProcess + ' CMD=' + $commandLine) } else { Write-Host ('[run_acceptance.bat] Processo atual: PID=' + $listener.OwningProcess) }; " ^
	"Write-Host '[run_acceptance.bat] Pare o runtime SGAA normal antes de iniciar a aceitacao.'; " ^
	"exit 1"
if errorlevel 1 (
	pause
	exit /b 1
)

echo [run_acceptance.bat] PORT            = %APP_PORT%
echo [run_acceptance.bat] DATABASE        = %RESOLVED_DB%
echo [run_acceptance.bat] PUBLIC BASE URL = http://localhost:%APP_PORT%
echo.

call "%~dp0run.bat"
exit /b %errorlevel%
