"""
Batch Uploader for Plagiarism Checker
Mengirim banyak file PDF/DOCX ke server lokal untuk diproses berurutan.
"""
import os
import requests
import time
import json
import uuid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# test_documents berada di dalam folder app/
FOLDER = os.path.join(BASE_DIR, "test_documents")
os.makedirs(FOLDER, exist_ok=True)

URL_CSRF = "http://127.0.0.1:5001/csrf-token"
URL_UPLOAD = "http://127.0.0.1:5001/upload"
URL_STATUS = "http://127.0.0.1:5001/status/"

files = [f for f in os.listdir(FOLDER) if f.lower().endswith(('.pdf', '.docx', '.doc'))]
if not files:
    print(f"[INFO] Tidak ada dokumen uji (.pdf, .docx, .doc) ditemukan di: {FOLDER}")
    print("[INFO] Silakan letakkan dokumen uji di folder tersebut untuk pengujian batch berulang.")
    exit(0)

results = []

for idx, filename in enumerate(files):
    filepath = os.path.join(FOLDER, filename)
    print(f"\n[{idx+1}/{len(files)}] Memproses {filename} ...")

    session = requests.Session()
    csrf_token = ""
    try:
        csrf_resp = session.get(URL_CSRF, timeout=5)
        if csrf_resp.status_code == 200:
            csrf_token = csrf_resp.json().get('csrf_token', '')
    except Exception as err:
        print(f"    [!] Peringatan: Gagal memperoleh CSRF token ({err})")

    headers = {'X-CSRFToken': csrf_token} if csrf_token else {}
    with open(filepath, 'rb') as f:
        # Gunakan force_scrape='false' agar menggunakan frozen_corpus yg sudah terkumpul,
        # sehingga pengujian threshold baru lebih cepat dan konsisten.
        resp = session.post(URL_UPLOAD, files={'file': f}, headers=headers, data={
            'force_scrape': 'false',
            'use_semantic': 'true',
            'exclude_quotes': 'true',
            'exclude_biblio': 'true'
        })

    if resp.status_code != 200:
        print(f"    [!] Gagal upload: {resp.status_code} {resp.text[:100]}")
        continue

    data = resp.json()
    file_id = data.get('file_id')
    print(f"    [OK] file_id={file_id}")

    # Polling status
    max_retries = 600  # 10 menit
    completed_flag = False
    for attempt in range(max_retries):
        try:
            status_resp = session.get(URL_STATUS + file_id, timeout=5)
            if status_resp.status_code == 200:
                status_data = status_resp.json()
                status = status_data.get('status', 'unknown')
                progress = status_data.get('progress', 0)
                message = status_data.get('message', '')
                if progress is not None and message:
                    print(f"    [{progress:>3}%] {message:<60}", end='\r', flush=True)

                if status == 'completed':
                    score = status_data.get('data', {}).get('total_similarity', 'N/A')
                    fooled_score = status_data.get('data', {}).get('fooled_similarity')
                    
                    if fooled_score is not None:
                        score_str = f"{score}% (Terkecoh: {fooled_score}%)"
                    else:
                        score_str = f"{score}%"
                        
                    print(f"\n    [SELESAI] Hasil Similarity: {score_str}")
                    results.append({
                        'file': filename,
                        'score': score_str,
                        'file_id': file_id
                    })
                    completed_flag = True
                    break
                elif status in ('error', 'cancelled'):
                    msg = status_data.get('message', 'Unknown error')
                    print(f"\n    [ERROR] {msg}")
                    results.append({
                        'file': filename,
                        'score': 'ERROR',
                        'file_id': file_id,
                        'error': msg
                    })
                    completed_flag = True
                    break
            else:
                print(f"    [!] Polling HTTP {status_resp.status_code}... retrying ({attempt+1}/{max_retries})   ", end='\r', flush=True)
        except Exception as err:
            print(f"    [!] Menunggu koneksi server ({attempt+1}/{max_retries})...   ", end='\r', flush=True)
        time.sleep(2)
        
    if not completed_flag:
        print(f"\n    [TIMEOUT] Gagal mendapat respon selesai setelah {max_retries} detik.")
        results.append({
            'file': filename,
            'score': 'TIMEOUT',
            'file_id': file_id
        })

print("\n" + "="*80)
print(f"{'HASIL BATCH PROCESSING':^80}")
print("="*80)
print(f"{'NAMA FILE':<60} | {'HASIL SIMILARITY':<25}")
print("-" * 88)
for r in results:
    print(f"{r['file'][:58]:<60} | {r['score']:<25}")
print("="*80)
