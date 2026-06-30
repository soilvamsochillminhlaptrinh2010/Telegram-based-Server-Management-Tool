@echo off
:: start_windows.bat — Launcher & Respawn loop cho check_ping.py / manager.py
:: ===========================================================================
:: LUỒNG:
::   1. Tạo venv nếu chưa có, cài gói cần thiết
::   2. Chạy check_ping.py
::   3. Nếu check_ping thoát → kiểm tra stop.flag / respawn.flag
::   4. Nếu stop.flag → thoát hẳn
::   5. Nếu không → chờ manager rồi restart check_ping khi manager /kill
:: ===========================================================================

cd /d "%~dp0"
title Watchdog Manager System

echo.
echo ============================================
echo  Watchdog + Manager Launcher
echo ============================================
echo.

:: ── Tạo venv nếu chưa có ──────────────────────────────────
if not exist "venv_windows\Scripts\python.exe" (
    echo [SETUP] Chua co venv. Dang tao...
    python -m venv venv_windows
    echo [SETUP] Dang cai goi can thiet...
    venv_windows\Scripts\python.exe -m pip install --upgrade pip -q
    venv_windows\Scripts\python.exe -m pip install requests psutil pillow wmi paramiko -q
    echo [SETUP] Cai dat hoan tat!
    echo.
) else (
    :: Kiểm tra paramiko
    venv_windows\Scripts\python.exe -c "import paramiko" 2>nul
    if errorlevel 1 (
        echo [SETUP] Cai bo sung paramiko...
        venv_windows\Scripts\python.exe -m pip install paramiko -q
    )
)

echo [INFO] Khoi dong Watchdog...
echo [INFO] Gui /off qua Telegram de tat hoan toan.
echo.

:: ── VÒNG LẶP CHÍNH ────────────────────────────────────────
:MAIN_LOOP
    :: Kiểm tra stop.flag trước khi chạy
    if exist "stop.flag" (
        del /f /q "stop.flag" >nul 2>&1
        echo [STOP] stop.flag phat hien - Tat hoan toan theo lenh /off.
        goto :END
    )

    echo [%TIME%] Khoi chay check_ping.py...
    venv_windows\Scripts\python.exe check_ping.py
    set EXIT_CODE=%ERRORLEVEL%
    echo [%TIME%] check_ping thoat (code %EXIT_CODE%).

    :: Kiểm tra stop.flag sau khi check_ping thoát
    if exist "stop.flag" (
        del /f /q "stop.flag" >nul 2>&1
        echo [STOP] Tat hoan toan.
        goto :END
    )

    :: check_ping thoát = manager đã được mở, chờ manager sống
    echo [%TIME%] Cho manager khoi dong (time.txt)...
    set /a WAITED=0
:WAIT_MANAGER_UP
    if exist "time.txt" goto :WATCH_MANAGER
    if %WAITED% GEQ 120 (
        echo [WARN] Manager khong khoi dong duoc sau 120s. Restart check_ping...
        goto :RESTART_PING
    )
    timeout /t 2 /nobreak >nul
    set /a WAITED+=2
    goto :WAIT_MANAGER_UP

    :: Manager đang chạy, chờ nó tắt
:WATCH_MANAGER
    echo [%TIME%] Manager dang chay. Cho tin hieu tat...
:WATCH_LOOP
    :: stop.flag trong vòng chờ manager
    if exist "stop.flag" (
        del /f /q "stop.flag" >nul 2>&1
        echo [STOP] Tat hoan toan (trong vong cho manager).
        goto :END
    )
    :: respawn.flag = manager đã /kill
    if exist "respawn.flag" (
        del /f /q "respawn.flag" >nul 2>&1
        echo [%TIME%] respawn.flag - Manager da /kill. Restart check_ping...
        goto :RESTART_PING
    )
    :: Kiểm tra time.txt còn tươi không (dùng PowerShell)
    for /f %%i in ('powershell -Command "(Get-Date) - (Get-Item time.txt -ErrorAction SilentlyContinue).LastWriteTime | Select-Object -ExpandProperty TotalSeconds" 2^>nul') do set FILE_AGE=%%i
    if defined FILE_AGE (
        powershell -Command "if ([double]'%FILE_AGE%' -gt 35) { exit 1 } else { exit 0 }" >nul 2>&1
        if errorlevel 1 (
            echo [%TIME%] Heartbeat mat. Manager co ve da chet. Restart check_ping...
            goto :RESTART_PING
        )
    )
    timeout /t 3 /nobreak >nul
    goto :WATCH_LOOP

:RESTART_PING
    echo [%TIME%] Restart check_ping trong 2 giay...
    timeout /t 2 /nobreak >nul
    goto :MAIN_LOOP

:END
echo.
echo Launcher da thoat.
pause
