@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PS_ARGS="
:parse_args
if "%~1"=="" goto run_stop
if /i "%~1"=="--clean-cache" (
    set "PS_ARGS=!PS_ARGS! -CleanCache"
) else if /i "%~1"=="--clean-uv-cache" (
    set "PS_ARGS=!PS_ARGS! -CleanUvCache"
) else if /i "%~1"=="--force-port" (
    set "PS_ARGS=!PS_ARGS! -ForcePort"
) else (
    set "PS_ARGS=!PS_ARGS! %~1"
)
shift
goto parse_args

:run_stop
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\stop_services.ps1" !PS_ARGS!
exit /b %ERRORLEVEL%
