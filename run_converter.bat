@echo off
setlocal EnableExtensions
title REDCap Single-Line Converter (Portable CMD)

set "ROOT=%~dp0"
set "SCRIPT=%ROOT%redcap_flatten.py"
if not exist "%SCRIPT%" set "SCRIPT=%ROOT%..\scripts\redcap_flatten.py"

call :find_python
if not defined PY_CMD (
    echo [ERROR] Python 3 not found.
    echo Place the official Python Windows embeddable zip inside "%ROOT%py\"
    echo ^(no admin rights needed^) or install Python 3 for your user account.
    pause
    exit /b 1
)

if "%~1"=="" (
    %PY_CMD% "%SCRIPT%" -i
) else (
    %PY_CMD% "%SCRIPT%" %*
)
set "RC=%ERRORLEVEL%"
if "%~2"=="" pause
exit /b %RC%

:find_python
if exist "%ROOT%py\python.exe" (
    set "PY_CMD="%ROOT%py\python.exe""
    exit /b 0
)
if exist "%ROOT%..\py\python.exe" (
    set "PY_CMD="%ROOT%..\py\python.exe""
    exit /b 0
)
where python >nul 2>nul
if %ERRORLEVEL%==0 (
    set "PY_CMD=python"
    exit /b 0
)
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    set "PY_CMD=py -3"
    exit /b 0
)
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if exist "%%~fD\python.exe" (
        set "PY_CMD="%%~fD\python.exe""
        exit /b 0
    )
)
exit /b 1
