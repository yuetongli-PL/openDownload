@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"

set "PY="
where python >nul 2>&1
if %ERRORLEVEL%==0 (
    set "PY=python"
    goto :DEPS
)
where py >nul 2>&1
if %ERRORLEVEL%==0 (
    set "PY=py -3"
    goto :DEPS
)
if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (
    set "PY=%LocalAppData%\Programs\Python\Python311\python.exe"
    goto :DEPS
)
echo Python not found. Install Python 3.11+ and add it to PATH.
pause
exit /b 1

:DEPS
%PY% -c "import fastapi,uvicorn,yt_dlp,Crypto" >nul 2>&1
if errorlevel 1 (
    echo Installing Python packages...
    %PY% -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo pip install failed.
        pause
        exit /b 1
    )
)

echo.
echo openDownload  http://127.0.0.1:8765/
echo 不要关闭这个窗口。浏览器会自动打开。
echo.
%PY% -m server
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
    echo.
    echo FAILED
    pause
    exit /b %ERR%
)
exit /b 0
