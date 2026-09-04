#!/usr/bin/env bash
# ============================================================
#  Open-Source Plagiarism Detection — Cek Plagiarisme Skripsi Gratis (Linux/macOS)
# ============================================================

cd "$(dirname "$0")" || exit 1

if [ -f ".venv/bin/python" ]; then
    PYTHON_CMD="$(pwd)/.venv/bin/python"
else
    echo "[1/3] Membuat Virtual Environment (.venv)..."
    python3 -m venv .venv || exit 1
    PYTHON_CMD="$(pwd)/.venv/bin/python"
    echo "[2/3] Mengunduh dependensi (requirements.txt)..."
    $PYTHON_CMD -m pip install -r requirements.txt || exit 1
fi

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    cp .env.example .env
fi

echo "[3/3] Menjalankan Server Aplikasi..."
echo "Akses Web: http://localhost:5001"
cd app || exit 1
$PYTHON_CMD server.py
