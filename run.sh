#!/usr/bin/env bash
# Jalankan Turnitin Lokal dari lokasi baru (D:/skripsi/project/plagiarism_checker)
# memakai .venv milik project spam email (path absolut, shared).
VENV="D:/skripsi/skripsi_spam/Code_Spam_Email/.venv/Scripts/python.exe"
cd "$(dirname "$0")/app" || exit 1
"$VENV" server.py
