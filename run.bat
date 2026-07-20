@echo off
REM ============================================================
REM  Jalankan Web App Plagiarism Checker (Turnitin Lokal)
REM  Memakai venv yang di-share dengan project spam email
REM  (torch CUDA + sentence-transformers sudah terinstall di sana).
REM  Buka browser: http://localhost:5001
REM ============================================================
set VENV=D:\skripsi\skripsi_spam\Code_Spam_Email\.venv\Scripts\python.exe

if not exist "%VENV%" (
    echo [ERROR] Python venv tidak ditemukan di:
    echo         %VENV%
    echo Pastikan folder Code_Spam_Email dan .venv-nya masih ada.
    pause
    exit /b 1
)

cd /d "%~dp0app"
echo Menjalankan server... buka http://localhost:5001 di browser.
"%VENV%" server.py
pause
