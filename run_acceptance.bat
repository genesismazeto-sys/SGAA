@echo off
rem =====================================================================
rem SGAA -- isolated ACCEPTANCE runtime.
rem
rem   run.bat            -> canonical runtime, port 5000, canonical database.db
rem   run_acceptance.bat -> acceptance runtime, port 5001, disposable database
rem
rem This file owns configuration only.  Every launch step (venv bootstrap,
rem startup preflight, port check, browser open, app start) stays in run.bat,
rem which is called unchanged at the end.  PORT, DATABASE and PUBLIC BASE URL
rem are set together here so they can never drift apart.
rem =====================================================================
setlocal
cd /d "%~dp0"

if "%LOCALAPPDATA%"=="" (
	echo [run_acceptance.bat] LOCALAPPDATA is not available.
	pause
	exit /b 1
)

if "%APP_HOST%"=="" set "APP_HOST=127.0.0.1"
set "APP_PORT=5001"
if "%SGAA_ACCEPTANCE_DB%"=="" set "SGAA_ACCEPTANCE_DB=%LOCALAPPDATA%\SGAA\acceptance_v8\database.db"
set "APP_DATABASE=%SGAA_ACCEPTANCE_DB%"
set "APP_ACCEPTANCE_PUBLIC_BASE_URL=http://localhost:%APP_PORT%"

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

echo [run_acceptance.bat] PORT            = %APP_PORT%
echo [run_acceptance.bat] DATABASE        = %RESOLVED_DB%
echo [run_acceptance.bat] PUBLIC BASE URL = %APP_ACCEPTANCE_PUBLIC_BASE_URL%
echo.

call "%~dp0run.bat"
exit /b %errorlevel%
