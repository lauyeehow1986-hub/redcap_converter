@echo off
setlocal EnableExtensions
title REDCap Single-Line Converter (Portable Hybrid GUI)

set "ROOT=%~dp0"
set "SERVER=%ROOT%redcap_gui_server.py"
if not exist "%SERVER%" set "SERVER=%ROOT%..\scripts\redcap_gui_server.py"
set "HTML=%ROOT%redcap_converter.html"
if not exist "%HTML%" set "HTML=%ROOT%..\assets\redcap_converter.html"

call :find_python
if not defined PY_CMD (
    echo [INFO] Python 3 not found - opening zero-install Offline Browser GUI instead...
    if exist "%HTML%" (
        start "" "%HTML%"
        exit /b 0
    )
    echo [ERROR] Could not find redcap_converter.html or Python 3.
    pause
    exit /b 1
)

if not "%~1"=="" if exist "%~1" (
    %PY_CMD% "%SERVER%" --input "%~1"
    set "RC=%ERRORLEVEL%"
    if not "%RC%"=="0" pause
    exit /b %RC%
)

%PY_CMD% "%SERVER%" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" pause
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
