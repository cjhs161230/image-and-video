@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PS_ARGS="
:parse_args
if "%~1"=="" goto run_start
if /i "%~1"=="--hidden" (
    set "PS_ARGS=!PS_ARGS! -Hidden"
) else (
    set "PS_ARGS=!PS_ARGS! %~1"
)
shift
goto parse_args

:run_start
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\start_services.ps1" !PS_ARGS!
exit /b %ERRORLEVEL%
