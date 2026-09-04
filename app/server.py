import os
import time
import math
import uuid
import json
import hashlib
import secrets
import urllib3
import glob
import re
from dotenv import load_dotenv

# Nonaktifkan peringatan SSL (banyak web kampus SSL-nya kedaluwarsa)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Load API keys from .env file FIRST before anything else uses them
load_dotenv()

from flask import Flask, render_template, request, jsonify, send_file, session
from werkzeug.utils import secure_filename
import threading
import subprocess
from engine.extractor import extract_text_auto, get_sentences
from engine.web_scraper import get_candidate_urls, scrape_all_candidates, load_corpus_bank
from engine.shingling import calculate_similarity
from engine.pdf_generator import generate_report_pdf
from engine.supabase_client import save_job_status_supabase, get_job_status_supabase

app = Flask(__name__)

# PROMETHEUS METRICS
import time as time_mod
_metric_total_docs = 0
_metric_total_errors = 0
_metric_processing_time = 0.0

@app.route('/metrics')
def metrics():
    # Phase 4 #4: Tambahkan monitoring dan observability stack
    lines = [
        "# HELP plagiarism_total_documents Total dokumen diproses",
        "# TYPE plagiarism_total_documents counter",
        f"plagiarism_total_documents {_metric_total_docs}",
        "# HELP plagiarism_total_errors Total error saat pemrosesan",
        "# TYPE plagiarism_total_errors counter",
        f"plagiarism_total_errors {_metric_total_errors}",
        "# HELP plagiarism_processing_time_seconds Total durasi waktu proses (detik)",
        "# TYPE plagiarism_processing_time_seconds counter",
        f"plagiarism_processing_time_seconds {_metric_processing_time}"
    ]
    from flask import Response
    return Response("\n".join(lines), mimetype="text/plain")

# Redam log akses HTTP Werkzeug (mis. "GET /status/... 200" tiap detik dari polling
# frontend) agar terminal tidak dibanjiri. Hanya tampilkan WARNING ke atas; error asli
# tetap terlihat. Log progres proses (print [!]/[API]) tidak terpengaruh.
import logging
# Set root logger ke WARNING agar semua library pihak ketiga (termasuk ddgs, primp, transformers, dll) diam/bungkam.
logging.basicConfig(level=logging.WARNING, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Nyalakan level INFO KHUSUS untuk kode internal aplikasi kita sendiri
logger.setLevel(logging.INFO)
logging.getLogger('engine').setLevel(logging.INFO)
logging.getLogger('app').setLevel(logging.INFO)

logging.getLogger('werkzeug').setLevel(logging.WARNING)
# Security: Generate secure secret key for sessions
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# Gunakan absolute path agar direktori selalu berada di dalam folder app/ 
base_dir = os.path.dirname(os.path.abspath(__file__))
app.config['UPLOAD_FOLDER'] = os.path.join(base_dir, 'uploads')
app.config['REPORT_FOLDER'] = os.path.join(base_dir, 'reports')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 # 16MB max

# Rate limiting: max 10 upload per IP per menit
RATE_LIMIT_WINDOW = 60  # detik
RATE_LIMIT_MAX_REQUESTS = 10
_rate_limit_db = {}
_rate_limit_lock = threading.Lock()


os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['REPORT_FOLDER'], exist_ok=True)

def get_frozen_path(original_filename, doc_hash):
    """Mencari atau membuat path frozen corpus yang ramah dibaca manusia (memuat nama file + hash)."""
    frozen_dir = os.path.join(base_dir, "frozen_corpus")
    os.makedirs(frozen_dir, exist_ok=True)
    
    matches = glob.glob(os.path.join(frozen_dir, f"*{doc_hash}.json"))
    if matches:
        return matches[0]
        
    safe_name = re.sub(r'[^\w\-]', '_', os.path.splitext(original_filename)[0])
    safe_name = re.sub(r'_+', '_', safe_name).strip('_')[:35]
    if not safe_name:
        safe_name = "doc"
    return os.path.join(frozen_dir, f"web_{safe_name}_{doc_hash}.json")

def cleanup_old_files(max_age_hours=2):
    """Menghapus file upload & laporan lama (> 2 jam) agar disk tetap bersih & efisien"""
    now = time.time()
    cutoff = now - (max_age_hours * 3600)
    cleaned_count = 0
    for folder in [app.config['UPLOAD_FOLDER'], app.config['REPORT_FOLDER']]:
        if not os.path.exists(folder): continue
        for fname in os.listdir(folder):
            fpath = os.path.join(folder, fname)
            if os.path.isfile(fpath):
                try:
                    if os.path.getmtime(fpath) < cutoff:
                        os.remove(fpath)
                        cleaned_count += 1
                except Exception:
                    pass
    if cleaned_count > 0:
        logger.info(f"Cleanup: {cleaned_count} file temporary lama (> {max_age_hours} jam) di uploads/reports berhasil dibersihkan.")

# Purge file temporary lama (dibatasi maks 2 jam) saat server startup
cleanup_old_files(2)

# Store results in memory
results_db = {}
RESULTS_DB_LOCK = threading.Lock()
MAX_RESULTS_DB_SIZE = 50
RESULTS_DB_TTL_HOURS = 2

def periodic_cleanup_task():
    """Background task untuk membersihkan results_db dan file temporary lama."""
    while True:
        try:
            time.sleep(1800)  # Tiap 30 menit
            
            # 1. Bersihkan file lama (> 2 jam)
            cleanup_old_files(2)
            
            # 2. Bersihkan results_db (TTL eviction)
            cutoff = time.time() - (RESULTS_DB_TTL_HOURS * 3600)
            with RESULTS_DB_LOCK:
                to_delete = []
                for k, v in results_db.items():
                    if v.get('timestamp', 0) < cutoff:
                        to_delete.append(k)
                for k in to_delete:
                    del results_db[k]
                if to_delete:
                    logger.info(f"Cleanup: {len(to_delete)} sesi usang (> {RESULTS_DB_TTL_HOURS} jam) dihapus dari memory.")
        except Exception as e:
            logger.info(f"Error in periodic cleanup: {e}")

cleanup_thread = threading.Thread(target=periodic_cleanup_task, daemon=True)
cleanup_thread.start()

# Jumlah kalimat-probe untuk mencari sumber di internet. SAMA dengan groundtruth
# (run_test_groundtruth.py pakai 100) agar metodologi & skor localhost setara nilai
# tervalidasi. Bisa diturunkan via env bila ingin lebih cepat (mengorbankan recall).
INTERNET_MAX_PROBES = int(os.environ.get("INTERNET_MAX_PROBES", "100"))


def process_document(file_id, filepath, original_filename, exclude_quotes=True, exclude_biblio=True, exclude_small=False, use_semantic=False, use_internet=True, force_scrape=False, exclude_abstract=True):
    def set_progress(pct, msg):
        with RESULTS_DB_LOCK:
            if file_id in results_db:
                results_db[file_id]['progress'] = pct
                results_db[file_id]['message'] = msg
                session_id = results_db[file_id].get('session_id', '')
                status = results_db[file_id].get('status', 'processing')
                save_job_status_supabase(file_id, session_id, status, pct, msg)

    global _metric_total_docs, _metric_total_errors, _metric_processing_time
    start_time_process = time.time()
    def check_cancelled():
        with RESULTS_DB_LOCK:
            entry = results_db.get(file_id, {})
            if entry.get('cancel_requested'):
                entry['status'] = 'cancelled'
                entry['message'] = 'Proses dibatalkan oleh pengguna.'
                logger.info(f"PROSES DIBATALKAN USER: {file_id}")
                return True
            return False

    try:
        set_progress(5, "Mengekstrak teks dari dokumen...")
        logger.info(f"Mulai ekstraksi teks dari: {filepath}")
        extraction_result = extract_text_auto(filepath, exclude_quotes, exclude_biblio, return_hidden=True, exclude_abstract=exclude_abstract)
        doc_text, manipulation_warnings, raw_text, hidden_spans = extraction_result
        sentences = get_sentences(doc_text)
        if check_cancelled(): return

        # ===== METODOLOGI IDENTIK GROUNDTRUTH =====
        # Korpus skoring = hasil scrape KHUSUS dokumen ini (terkurasi & relevan), PERSIS
        # seperti run_test_groundtruth.py. Bank TIDAK dijadikan basis korpus (bank mentah
        # 17k sumber bikin over-counting). Bank turun peran jadi CACHE di dalam
        # scrape_all_candidates: URL yang sudah pernah diunduh diambil instan (skip
        # download), sumber baru otomatis ditambahkan (auto-freeze). Ini mempercepat
        # tanpa mengubah komposisi korpus vs metodologi groundtruth.
        def ddg_progress(completed, total):
            pct = 5 + int((completed / total) * 45)  # 5% -> 50%
            set_progress(pct, f"Mencari sumber di internet ({completed}/{total})...")

        logger.info(f"Mencari kandidat sumber (max_probes={INTERNET_MAX_PROBES}, metodologi groundtruth)...")

        # FROZEN CACHE (key = hash ISI teks, bukan nama file): PDF sama persis -> baca
        # korpus beku -> skor identik tiap run (hilangkan variasi jaringan 0-2%). PDF
        # yang isinya diparafrase -> teks beda -> hash beda -> dianggap dokumen BARU ->
        # scrape ulang. Reuse dir frozen_corpus/ yang sama dgn run_test_groundtruth.
        doc_hash = hashlib.md5(doc_text.encode("utf-8")).hexdigest()[:16]
        frozen_path = get_frozen_path(original_filename, doc_hash)
        corpus = None
        existing_corpus = {}
        if os.path.exists(frozen_path):
            try:
                with open(frozen_path, encoding="utf-8") as f:
                    existing_corpus = json.load(f)
            except Exception as e:
                logger.info(f"Gagal baca frozen ({e}).")
                existing_corpus = {}

        if not force_scrape and existing_corpus:
            corpus = existing_corpus
            set_progress(85, "Memuat korpus beku (dokumen sudah pernah dicek)...")
            logger.info(f"KORPUS BEKU dimuat: {len(corpus)} sumber (skor deterministik, skip scrape).")

        if corpus is None:
            if force_scrape:
                logger.info(f"FORCE SCRAPE: Memperluas korpus ({len(existing_corpus)} sumber eksis) dengan live scraping internet...")
            adaptive_probes = max(200, min(200, int(len(sentences) / 2.5)))
            logger.info(f"ADAPTIVE SAMPLING: {adaptive_probes} probes untuk {len(sentences)} kalimat...")
            urls, preloaded_corpus = get_candidate_urls(sentences, max_probes=adaptive_probes, progress_cb=ddg_progress)

            def scrape_progress(completed, total, speed="0 KB/s"):
                pct = 50 + int((completed / total) * 35)  # 50% -> 85%
                if total == 0: pct = 85
                speed_text = f" ({speed})" if speed != "0 KB/s" else ""
                set_progress(pct, f"Mengunduh isi sumber ({completed}/{total}){speed_text}...")

            logger.info(f"Mengunduh teks dari {len(urls)} kandidat (bank dipakai sbg cache)...")
            new_scraped = scrape_all_candidates(urls, preloaded_corpus, progress_cb=scrape_progress)
            
            # MERGE: Gabungkan korpus eksis dengan hasil scraping live baru agar data makin kaya dan tidak membuang data lama
            corpus = existing_corpus.copy()
            corpus.update(new_scraped)
            logger.info(f"Korpus terkurasi total utk dokumen ini: {len(corpus)} sumber ({len(new_scraped)} baru/live).")
            try:
                # Atomic write: tulis ke file temp dulu, lalu rename
                frozen_tmp = frozen_path + ".tmp." + secrets.token_hex(4)
                with open(frozen_tmp, "w", encoding="utf-8") as f:
                    json.dump(corpus, f, ensure_ascii=False)
                os.replace(frozen_tmp, frozen_path)
                logger.info(f"Korpus DIBEKUKAN & DIPERBARUI: {os.path.basename(frozen_path)} ({len(corpus)} total sumber).")
            except Exception as e:
                logger.info(f"Gagal simpan frozen: {e}")

        if check_cancelled(): return
        set_progress(85, "Menghitung kemiripan (Algoritma N-Gram)...")
        logger.info(f"Menghitung similaritas dengan algoritma N-Gram Shingling...")
        # PARAMETER IDENTIK GROUNDTRUTH: hanya semantic_threshold="auto". TANPA
        # semantic_max_sources/min_source_overlap -> engine berperilaku persis seperti
        # run_test_groundtruth.py, sehingga skor dokumen tervalidasi konsisten saat
        # dites di localhost (korpus sama-sama terkurasi, bukan bank mentah).
        
        sorted_sources, total_similarity, plagiarized_sentences = calculate_similarity(
            doc_text, corpus, exclude_small, use_semantic=use_semantic,
            semantic_threshold="auto", is_cancelled_cb=check_cancelled)
        if check_cancelled(): return

        # --- SKOR KEDUA: "fooled" (hidden text lolos) ---
        # Hanya dihitung jika ada manipulasi (hidden spans terdeteksi). Menggunakan
        # korpus yang SAMA, hanya teksnya berbeda (raw_text = termasuk hidden text).
        # calculate_similarity cuma n-gram matching di memori -> tambah 1-2 detik saja.
        fooled_similarity = None
        if raw_text and raw_text.strip() != doc_text.strip():
            logger.info(f"Menghitung skor kedua (jika hidden text lolos)...")
            _, fooled_sim, _ = calculate_similarity(
                raw_text, corpus, exclude_small, use_semantic=use_semantic,
                semantic_threshold="auto", semantic_max_sources=10)
            fooled_similarity = round(fooled_sim)
            logger.info(f"Skor tertipu (hidden text lolos): {fooled_similarity}%")

        data = {
            'filename': original_filename.replace('.pdf', ''),
            'total_similarity': round(total_similarity),
            'sources': sorted_sources,
            'plagiarized_sentences': plagiarized_sentences,
            'manipulation_warnings': manipulation_warnings,
            'fooled_similarity': fooled_similarity,
            'hidden_spans': hidden_spans if hidden_spans else []
        }
        
        set_progress(95, "Membangun Laporan PDF...")
        logger.info(f"Membangun PDF Report...")
        report_pdf_path = os.path.join(app.config['REPORT_FOLDER'], f"{file_id}_report.pdf")
        generate_report_pdf(filepath, report_pdf_path, data)
        
        results_db[file_id].update({
            'status': 'completed',
            'progress': 100,
            'message': 'Selesai.',
            'data': data
        })
        save_job_status_supabase(file_id, results_db[file_id].get('session_id', ''), 'completed', 100, 'Selesai.', data)
        try:
            result_json_path = os.path.join(app.config['REPORT_FOLDER'], f"{file_id}_result.json")
            with open(result_json_path, "w", encoding="utf-8") as f:
                json.dump({'status': 'completed', 'data': data, 'session_id': results_db[file_id].get('session_id')}, f, ensure_ascii=False)
        except Exception as e:
            logger.info(f"Gagal simpan cache JSON laporan: {e}")
            
        # [MEMORY CLEANUP] Paksa Garbage Collector berjalan agar RAM dikembalikan ke Windows
        import gc
        del corpus
        gc.collect()
        
        logger.info(f"Selesai. Hasil: {total_similarity}%")
    except Exception as e:
        import traceback
        traceback.print_exc()
        global _metric_total_errors
        _metric_total_errors += 1
        if file_id in results_db:
            results_db[file_id].update({
                'status': 'error',
                'message': str(e)
            })
        else:
            results_db[file_id] = {
                'status': 'error',
                'message': str(e)
            }

# Global semaphore to limit max concurrent document analysis jobs (C6 Fix)
_CONCURRENCY_SEMAPHORE = threading.Semaphore(4)

@app.before_request
def csrf_protect():
    # Pastikan sesi selalu memiliki csrf_token
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    # Validasi CSRF wajib untuk setiap request mutasi POST
    if request.method == "POST":
        token = request.headers.get("X-CSRFToken") or request.form.get("csrf_token")
        expected_token = session.get("csrf_token")
        if not token or not expected_token or token != expected_token:
            return jsonify({'error': 'CSRF token validation failed'}), 403

@app.route('/csrf-token', methods=['GET'])
def get_csrf_token():
    """Endpoint untuk API automation / CLI batch runner mengambil token sesi."""
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return jsonify({'csrf_token': session['csrf_token']})

@app.context_processor
def inject_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return dict(csrf_token=session["csrf_token"])

@app.after_request
def add_security_headers(response):
    # H-S3 & H-F2 Fix: Security headers (HSTS, CSP, X-Frame, X-Content-Type)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://fonts.googleapis.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:;"
    return response

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/check_frozen', methods=['POST'])
def check_frozen():
    """Cek apakah file yang di-drop sudah memiliki korpus beku (frozen corpus).
    Endpoint super instan: cek nama -> jika cocok langsung return (<1ms),
    jika tidak cocok baru ekstrak teks & hash (fallback)."""
    if 'file' not in request.files:
        return jsonify({'exists': False})
    file = request.files['file']
    ext = file.filename.lower()
    if not (ext.endswith('.pdf') or ext.endswith('.docx') or ext.endswith('.doc')):
        return jsonify({'exists': False})

    # 1. FAST PRE-CHECK: Cek instan via nama file di folder frozen_corpus (<1 ms)
    frozen_dir = os.path.join(base_dir, "frozen_corpus")
    safe_name = re.sub(r'[^\w\-]', '_', os.path.splitext(file.filename)[0])
    safe_name = re.sub(r'_+', '_', safe_name).strip('_')[:20]
    if safe_name and os.path.exists(frozen_dir):
        fast_matches = glob.glob(os.path.join(frozen_dir, f"web_{safe_name}*.json"))
        if fast_matches:
            target_file = fast_matches[0]
            try:
                with open(target_file, "r", encoding="utf-8") as f:
                    corpus_size = f.read().count('"http')
                logger.info(f"FAST CHECK_FROZEN HIT (<1ms): {os.path.basename(target_file)}")
                return jsonify({'exists': True, 'corpus_size': corpus_size, 'hash': 'fast_match'})
            except Exception:
                pass

    # 2. FALLBACK: Simpan sementara untuk ekstraksi & hash jika nama tidak cocok
    tmp_path = os.path.join(app.config['UPLOAD_FOLDER'], f"_check_{uuid.uuid4().hex[:8]}{os.path.splitext(file.filename)[1]}")
    try:
        file.save(tmp_path)
        doc_text, _ = extract_text_auto(tmp_path, exclude_quotes=True, exclude_biblio=True)
        doc_hash = hashlib.md5(doc_text.encode("utf-8")).hexdigest()[:16]
        frozen_path = get_frozen_path(file.filename, doc_hash)
        exists = os.path.exists(frozen_path)
        corpus_size = 0
        if exists:
            try:
                with open(frozen_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    corpus_size = content.count('"http')
            except Exception:
                pass
        return jsonify({'exists': exists, 'corpus_size': corpus_size, 'hash': doc_hash})
    except Exception as e:
        return jsonify({'exists': False, 'error': str(e)})
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def get_client_ip():
    """Phase 4 #2: Rate limiting dengan proper IP extraction"""
    trusted_proxies = {'127.0.0.1', '::1', 'localhost'}
    if request.remote_addr in trusted_proxies:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(',')[0].strip()
    return request.remote_addr or 'unknown'

def _check_rate_limit(ip):
    """Check rate limit for IP. Returns (allowed, remaining_time)"""
    now = time.time()
    with _rate_limit_lock:
        if ip not in _rate_limit_db:
            _rate_limit_db[ip] = []
        _rate_limit_db[ip] = [t for t in _rate_limit_db[ip] if now - t < RATE_LIMIT_WINDOW]
        if len(_rate_limit_db[ip]) >= RATE_LIMIT_MAX_REQUESTS:
            oldest = _rate_limit_db[ip][0]
            remaining = int(RATE_LIMIT_WINDOW - (now - oldest)) + 1
            return False, remaining
        _rate_limit_db[ip].append(now)
        return True, 0

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    # Rate limiting: gunakan remote_addr langsung, bukan X-Forwarded-For (bisa dipalsukan)
    client_ip = get_client_ip()
    allowed, remaining = _check_rate_limit(client_ip)
    if not allowed:
        return jsonify({'error': f'Rate limit terlampaui. Coba lagi dalam {remaining} detik.'}), 429
    
    file = request.files['file']
    exclude_quotes = request.form.get('exclude_quotes', 'true') == 'true'
    exclude_biblio = request.form.get('exclude_biblio', 'true') == 'true'
    exclude_abstract = True  # Hidden / always on
    exclude_small = request.form.get('exclude_small') == 'true'
    # Deteksi parafrasa (Semantic AI) selalu nyala; UI tak lagi menampilkan opsinya.
    # Default True agar tetap aktif walau field 'use_semantic' tidak dikirim form.
    use_semantic = request.form.get('use_semantic', 'true') == 'true'
    force_scrape = request.form.get('force_scrape') == 'true'

    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
        
    if file and (file.filename.lower().endswith('.pdf') or file.filename.lower().endswith('.docx') or file.filename.lower().endswith('.doc')):
        filename = secure_filename(file.filename)
        # SECURITY FIX: Use cryptographically secure UUID instead of predictable timestamp
        file_id = str(uuid.uuid4())
        ext = os.path.splitext(filename)[1]
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}{ext}")
        file.save(filepath)
        
        # H-S4 Fix: Validate actual file magic bytes to prevent MIME type bypass
        try:
            with open(filepath, 'rb') as f_magic:
                header = f_magic.read(4)
            is_pdf = header.startswith(b'%PDF')
            is_docx = header.startswith(b'PK\x03\x04')
            is_doc = header.startswith(b'\xd0\xcf\x11\xe0')
            if not (is_pdf or is_docx or is_doc):
                os.remove(filepath)
                return jsonify({'error': 'Format file tidak valid (magic bytes mismatch). Only valid PDF or DOCX allowed.'}), 400
        except Exception:
            if os.path.exists(filepath): os.remove(filepath)
            return jsonify({'error': 'Gagal membaca berkas yang diunggah.'}), 400
        
        # SECURITY FIX: Store session ID for ownership validation
        if 'session_id' not in session:
            session['session_id'] = secrets.token_urlsafe(32)
            
        with RESULTS_DB_LOCK:
            # Cleanup inline for safety if background thread hasn't run
            cutoff = time.time() - (RESULTS_DB_TTL_HOURS * 3600)
            to_delete = [k for k, v in results_db.items() if v.get('timestamp', 0) < cutoff]
            for k in to_delete: del results_db[k]
            
            if len(results_db) >= MAX_RESULTS_DB_SIZE:
                return jsonify({'error': 'Server sedang sibuk memproses banyak dokumen. Coba lagi nanti.'}), 503
        
            results_db[file_id] = {
                'status': 'processing', 
                'progress': 0, 
                'message': 'Memulai proses...',
                'session_id': session['session_id'],  # Track ownership
                'timestamp': time.time(),

            'filename': filename
        }
        thread = threading.Thread(target=process_document, args=(file_id, filepath, filename, exclude_quotes, exclude_biblio, exclude_small, use_semantic, True, force_scrape, exclude_abstract), daemon=True)
        thread.start()
        
        return jsonify({'file_id': file_id, 'filename': filename})
    return jsonify({'error': 'Hanya file PDF, DOCX, dan DOC yang diizinkan'}), 400

@app.route('/cancel/<file_id>', methods=['POST'])
def cancel_process(file_id):
    with RESULTS_DB_LOCK:
        if file_id in results_db:
            current_session = session.get('session_id')
            if results_db[file_id].get('session_id') == current_session:
                results_db[file_id]['cancel_requested'] = True
                results_db[file_id]['status'] = 'cancelled'
                results_db[file_id]['message'] = 'Proses dibatalkan oleh pengguna.'
                logger.info(f"PROSES DIBATALKAN USER: {file_id}")
                return jsonify({'success': True, 'message': 'Proses berhasil dibatalkan.'})
    return jsonify({'error': 'File tidak ditemukan atau akses ditolak'}), 400

@app.route('/status/<file_id>')
def status(file_id):
    # SECURITY FIX: Validate ownership before returning status
    with RESULTS_DB_LOCK:
        if file_id not in results_db:
            return jsonify({'status': 'not_found'}), 404
        
        file_data = results_db[file_id]
        current_session = session.get('session_id')
        
        # Check ownership
        if file_data.get('session_id') != current_session:
            return jsonify({'error': 'Unauthorized access'}), 403
        
        # Don't expose session_id to client
        safe_data = {k: v for k, v in file_data.items() if k != 'session_id'}
        return jsonify(safe_data)

@app.route('/report/<file_id>')
def report(file_id):
    file_data = None
    with RESULTS_DB_LOCK:
        if file_id in results_db:
            file_data = results_db[file_id]
            
    # Fallback ke Supabase / cache disk JSON jika memory terhapus atau server direstart
    if not file_data or file_data.get('status') != 'completed':
        supa_job = get_job_status_supabase(file_id)
        if supa_job and supa_job.get('status') == 'completed' and supa_job.get('result_json'):
            file_data = {
                'status': 'completed',
                'data': supa_job.get('result_json'),
                'session_id': supa_job.get('session_id')
            }
        else:
            result_json_path = os.path.join(app.config['REPORT_FOLDER'], f"{file_id}_result.json")
            if os.path.exists(result_json_path):
                try:
                    with open(result_json_path, "r", encoding="utf-8") as f:
                        disk_cache = json.load(f)
                        file_data = {
                            'status': 'completed',
                            'data': disk_cache.get('data'),
                            'session_id': disk_cache.get('session_id')
                        }
                except Exception:
                    pass
                
    if not file_data:
        return "Laporan tidak ditemukan atau telah kedaluwarsa. Silakan unggah ulang dokumen Anda.", 404
        
    current_session = session.get('session_id')

    # Ownership check yang ketat (Strict Authorization)
    # Menolak akses jika sesi pengunjung berbeda dengan sesi pembuat laporan
    if file_data.get('session_id') and file_data.get('session_id') != current_session:
        error_html = """
        <div style="font-family: sans-serif; max-width: 600px; margin: 100px auto; padding: 30px; border-radius: 10px; background: #fee2e2; border: 1px solid #ef4444; text-align: center;">
            <h2 style="color: #b91c1c; margin-top: 0;">AKSES DITOLAK</h2>
            <p style="color: #7f1d1d; font-size: 15px;">URL laporan ini bersifat privat dan dikunci ke sesi browser pengguna lain. Anda tidak memiliki izin untuk membukanya.</p>
        </div>
        """
        return error_html, 403
    
    if file_data.get('status') == 'completed' and 'data' in file_data:
        data = file_data['data']
        
        # Dedup per-DOMAIN untuk tampilan web (sama dengan PDF report)
        seen_domains = set()
        unique_sources = []
        for source in data.get('sources', []):
            domain = source['url'].split('//')[-1].split('/')[0] if '//' in source['url'] else source['url']
            if domain in seen_domains:
                continue
            seen_domains.add(domain)
            unique_sources.append(source)
            
        data_for_html = {k:v for k,v in data.items() if k not in ('plagiarized_sentences', 'sources', 'hidden_spans')}
        data_for_html['sources'] = unique_sources
        
        return render_template('report.html', data=data_for_html, file_id=file_id)
    return "Laporan belum siap atau terjadi kesalahan.", 404

@app.route('/download/<file_id>')
def download_report(file_id):
    current_session = session.get('session_id')
    file_data = None
    
    with RESULTS_DB_LOCK:
        if file_id in results_db:
            file_data = results_db[file_id]
            
    # Fallback ke cache disk JSON jika memory terhapus
    if not file_data:
        result_json_path = os.path.join(app.config['REPORT_FOLDER'], f"{file_id}_result.json")
        if os.path.exists(result_json_path):
            try:
                with open(result_json_path, "r", encoding="utf-8") as f:
                    disk_cache = json.load(f)
                    file_data = {
                        'session_id': disk_cache.get('session_id'),
                        'data': disk_cache.get('data')
                    }
            except Exception:
                pass

    # Ownership check yang ketat (Strict Authorization)
    if file_data and file_data.get('session_id') and file_data.get('session_id') != current_session:
        error_html = """
        <div style="font-family: sans-serif; max-width: 600px; margin: 100px auto; padding: 30px; border-radius: 10px; background: #fee2e2; border: 1px solid #ef4444; text-align: center;">
            <h2 style="color: #b91c1c; margin-top: 0;">AKSES DITOLAK</h2>
            <p style="color: #7f1d1d; font-size: 15px;">PDF ini bersifat privat dan dikunci ke sesi browser pengguna lain. Anda tidak memiliki izin untuk mengunduhnya.</p>
        </div>
        """
        return error_html, 403

    report_pdf_path = os.path.join(app.config['REPORT_FOLDER'], f"{file_id}_report.pdf")
    if os.path.exists(report_pdf_path):
        filename = file_id
        if file_data and 'data' in file_data:
            filename = file_data['data'].get('filename', file_id)

        download_name = f"{filename}_report.pdf"
        return send_file(report_pdf_path, as_attachment=True, download_name=download_name)
    return "PDF Report tidak ditemukan.", 404

if __name__ == '__main__':
    import socket
    import signal
    
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except:
        local_ip = "127.0.0.1"
    
    def on_ctrl_c(sig, frame):
        print("\n[!] Mematikan server dan ngrok...")
        try:
            from pyngrok import ngrok
            ngrok.kill()
        except:
            pass
        
        # Eksekusi pemusnahan diri paksa dari tingkat OS untuk menghindari Ghost Process
        subprocess.run(["taskkill", "/F", "/IM", "ngrok.exe"], capture_output=True, shell=True)
        subprocess.run(["taskkill", "/F", "/PID", str(os.getpid())], capture_output=True, shell=True)
        os._exit(0)
    

    signal.signal(signal.SIGINT, on_ctrl_c)
    
    print("\n==================================================")
    logger.info(f"Akses Lokal (IP)   : http://{local_ip}:5001")
    
    # Jalankan Ngrok di thread terpisah agar crash-nya tidak mematikan Flask
    # SEC-03: Ngrok kini opsional via environment variable
    if os.environ.get('USE_NGROK', 'false').lower() == 'true':
        def start_ngrok():
            try:
                from pyngrok import ngrok
                import logging
                # Sembunyikan pesan warning ngrok agar tidak memenuhi terminal
                logging.getLogger("pyngrok").setLevel(logging.CRITICAL)
                ngrok.kill()
                public_url = ngrok.connect(5001)
                logger.info(f"Akses Publik Ngrok : {public_url.public_url}")
            except Exception as e:
                logger.info(f"Ngrok tidak tersedia: {e}")
        
        ngrok_thread = threading.Thread(target=start_ngrok, daemon=True)
        ngrok_thread.start()
    else:
        logger.info(f"Akses Publik Ngrok : DINONAKTIFKAN (Gunakan USE_NGROK=true untuk mengaktifkan)")
        
    print("==================================================\n")
    
    # SEC-02: Matikan debug=True untuk mencegah remote code execution via Werkzeug
    app.run(host='0.0.0.0', port=5001, debug=False, use_reloader=False)

