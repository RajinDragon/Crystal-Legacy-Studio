@echo off
setlocal EnableExtensions
title Crystal Legacy Studio Launcher

pushd "%~dp0"

echo.
echo ==========================================
echo   Crystal Legacy Studio
echo ==========================================
echo.

if not exist "main.py" (
    echo [ERROR] main.py was not found.
    echo Keep this launcher in the same folder as main.py.
    echo.
    pause
    popd
    exit /b 1
)

set "PYTHON_CMD="

where py >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=py"
)

if not defined PYTHON_CMD (
    where python >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=python"
    )
)

if not defined PYTHON_CMD (
    echo [ERROR] Python was not found.
    echo Install Python 3.11 or newer and select "Add Python to PATH".
    echo.
    pause
    popd
    exit /b 1
)

echo Checking required packages...
%PYTHON_CMD% -c "import PIL, cryptography, tkinterdnd2" >nul 2>&1

if errorlevel 1 (
    echo Installing required packages...
    %PYTHON_CMD% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERROR] Dependency installation failed.
        echo Review the messages above, then try again.
        echo.
        pause
        popd
        exit /b 1
    )
)

echo Checking Studio source files...
%PYTHON_CMD% -m compileall -q crystal_legacy_studio main.py
if errorlevel 1 (
    echo.
    echo [ERROR] Studio source validation failed.
    echo This build may be damaged or incomplete.
    echo Review the Python error shown above.
    echo.
    pause
    popd
    exit /b 1
)

echo Starting Crystal Legacy Studio...
echo.
%PYTHON_CMD% main.py

if errorlevel 1 (
    echo.
    echo [ERROR] Crystal Legacy Studio closed because of an error.
    echo Review the messages above.
    echo.
    pause
)

popd
endlocal
