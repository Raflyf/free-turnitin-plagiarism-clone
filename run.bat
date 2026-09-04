@echo off
TITLE Open-Source Plagiarism Detection - Plagiarism Checker
chcp 65001 > NUL
setlocal enabledelayedexpansion

echo ============================================================
echo   Open-Source Plagiarism Detection — Cek Plagiarisme Skripsi Gratis
echo ============================================================
echo.

cd /d "%~dp0"

REM 1. Cek atau deteksi Python & Venv
set "PYTHON_CMD="
if exist "D:\skripsi\skripsi_spam\Code_Spam_Email\.venv\Scripts\python.exe" (
    set "PYTHON_CMD=D:\skripsi\skripsi_spam\Code_Spam_Email\.venv\Scripts\python.exe"
) else if exist "D:\code\skripsi_spam\Code_Spam_Email\.venv\Scripts\python.exe" (
    set "PYTHON_CMD=D:\code\skripsi_spam\Code_Spam_Email\.venv\Scripts\python.exe"
) else if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_CMD=%~dp0.venv\Scripts\python.exe"
)

if "%PYTHON_CMD%"=="" (
    python --version > NUL 2>&1
    if errorlevel 1 (
        py --version > NUL 2>&1
        if errorlevel 1 (
            echo [INFO] Python tidak ditemukan di komputer Anda.
            echo [INFO] Mengunduh & menginstall Python 3.11 secara otomatis...
            echo.
            
            winget --version > NUL 2>&1
            if not errorlevel 1 (
                echo [winget] Mengunduh Python 3.11 via Windows Package Manager...
                winget install -e --id Python.Python.3.11 --accept-source-agreements --accept-package-agreements --override "/passive PrependPath=1"
            ) else (
                echo [PowerShell] Mengunduh installer resmi Python 3.11...
                powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile 'python_installer.exe'"
                echo [Installer] Menginstall Python 3.11 (Silent Mode)...
                start /wait python_installer.exe /passive PrependPath=1
                del python_installer.exe > NUL 2>&1
            )
            echo [INFO] Instalasi Python 3.11 selesai.
            echo.
        )
    )

    REM Cari path executable Python secara presisi di komputer bersih
    set "SYS_PYTHON=python"
    if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (
        set "SYS_PYTHON=%LocalAppData%\Programs\Python\Python311\python.exe"
    ) else if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
        set "SYS_PYTHON=%LocalAppData%\Programs\Python\Python312\python.exe"
    ) else if exist "%ProgramFiles%\Python311\python.exe" (
        set "SYS_PYTHON=%ProgramFiles%\Python311\python.exe"
    ) else if exist "%ProgramFiles%\Python312\python.exe" (
        set "SYS_PYTHON=%ProgramFiles%\Python312\python.exe"
    )
    
    echo [1/3] Membuat Virtual Environment (.venv)...
    "!SYS_PYTHON!" -m venv .venv 2>NUL
    if errorlevel 1 (
        py -3.11 -m venv .venv 2>NUL
        if errorlevel 1 (
            python -m venv .venv
        )
    )
    
    if not exist ".venv\Scripts\python.exe" (
        echo [ERROR] Gagal membuat virtual environment! Silakan jalankan ulang run.bat.
        pause
        exit /b 1
    )
    
    set "PYTHON_CMD=%~dp0.venv\Scripts\python.exe"
    
    echo [2/3] Mengunduh & menginstall modul dependensi (requirements.txt)...
    "%PYTHON_CMD%" -m pip install --upgrade pip > NUL 2>&1
    "%PYTHON_CMD%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Gagal menginstall dependensi!
        pause
        exit /b 1
    )
) else (
    echo [INFO] Virtual Environment siap dipakai: %PYTHON_CMD%
)

REM 2. Salin .env.example ke .env jika belum ada
if not exist ".env" (
    if exist ".env.example" (
        echo [INFO] Membuat file .env dari .env.example...
        copy .env.example .env > NUL
    )
)

REM 3. Otomatis Buka Web Browser ke http://localhost:5001 setelah 3 detik
start "" powershell -Command "Start-Sleep -Seconds 3; Start-Process 'http://localhost:5001'"

REM 4. Menjalankan Server Aplikasi
echo.
echo [3/3] Menjalankan Server Aplikasi...
echo Akses Web: http://localhost:5001
echo Tekan Ctrl+C di terminal ini untuk menghentikan server.
echo ============================================================
echo.

cd /d "%~dp0app"
"%PYTHON_CMD%" server.py

pause
