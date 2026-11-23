@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
set "SERVER=%ROOT%redcap_mcp_server.py"
if not exist "%SERVER%" set "SERVER=%ROOT%..\scripts\redcap_mcp_server.py"

if exist "%ROOT%py\python.exe" (
    "%ROOT%py\python.exe" -u "%SERVER%"
    exit /b %ERRORLEVEL%
)
if exist "%ROOT%..\py\python.exe" (
    "%ROOT%..\py\python.exe" -u "%SERVER%"
    exit /b %ERRORLEVEL%
)
where python >nul 2>nul
if %ERRORLEVEL%==0 (
    python -u "%SERVER%"
    exit /b %ERRORLEVEL%
)
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 -u "%SERVER%"
    exit /b %ERRORLEVEL%
)
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if exist "%%~fD\python.exe" (
        "%%~fD\python.exe" -u "%SERVER%"
        exit /b %ERRORLEVEL%
    )
)
echo [ERROR] Python 3 not found for redcap-singleline-mcp 1>&2
exit /b 1
