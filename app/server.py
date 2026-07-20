import os
import time
import math
import uuid
import secrets
import urllib3
from dotenv import load_dotenv

# Nonaktifkan peringatan SSL (banyak web kampus SSL-nya kedaluwarsa)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Load API keys from .env file FIRST before anything else uses them
load_dotenv()

from flask import Flask, render_template, request, jsonify, send_file, session
from werkzeug.utils import secure_filename
import threading
from engine.extractor import extract_text_from_pdf, get_sentences
from engine.web_scraper import get_candidate_urls, scrape_all_candidates, load_corpus_bank
from engine.shingling import calculate_similarity
from engine.pdf_generator import generate_report_pdf

app = Flask(__name__)
# Redam log akses HTTP Werkzeug (mis. "GET /status/... 200" tiap detik dari polling
# frontend) agar terminal tidak dibanjiri. Hanya tampilkan WARNING ke atas; error asli
# tetap terlihat. Log progres proses (print [!]/[API]) tidak terpengaruh.
import logging as _logging
_logging.getLogger('werkzeug').setLevel(_logging.WARNING)
# Security: Generate secure secret key for sessions
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32)
# Gunakan absolute path agar direktori selalu berada di dalam folder app/ 
base_dir = os.path.dirname(os.path.abspath(__file__))
app.config['UPLOAD_FOLDER'] = os.path.join(base_dir, 'uploads')
app.config['REPORT_FOLDER'] = os.path.join(base_dir, 'reports')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 # 16MB max


os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['REPORT_FOLDER'], exist_ok=True)

# Store results in memory
results_db = {}

# Jumlah kalimat-probe untuk mencari sumber di internet. SAMA dengan groundtruth
# (run_test_groundtruth.py pakai 100) agar metodologi & skor localhost setara nilai
# tervalidasi. Bisa diturunkan via env bila ingin lebih cepat (mengorbankan recall).
INTERNET_MAX_PROBES = int(os.environ.get("INTERNET_MAX_PROBES", "100"))


def process_document(file_id, filepath, original_filename, exclude_quotes=True, exclude_biblio=True, exclude_small=False, use_semantic=False, use_internet=True):
    def set_progress(pct, msg):
        if file_id in results_db:
            results_db[file_id]['progress'] = pct
            results_db[file_id]['message'] = msg

    try:
        set_progress(5, "Mengekstrak teks dari PDF...")
        print(f"[!] Mulai ekstraksi teks dari: {filepath}")
        doc_text, manipulation_warnings = extract_text_from_pdf(filepath, exclude_quotes, exclude_biblio)
        sentences = get_sentences(doc_text)

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

        print(f"[!] Mencari kandidat sumber (max_probes={INTERNET_MAX_PROBES}, metodologi groundtruth)...")
        urls, preloaded_corpus = get_candidate_urls(sentences, max_probes=INTERNET_MAX_PROBES, progress_cb=ddg_progress)

        def scrape_progress(completed, total, speed="0 KB/s"):
            pct = 50 + int((completed / total) * 35)  # 50% -> 85%
            if total == 0: pct = 85
            speed_text = f" ({speed})" if speed != "0 KB/s" else ""
            set_progress(pct, f"Mengunduh isi sumber ({completed}/{total}){speed_text}...")

        print(f"[!] Mengunduh teks dari {len(urls)} kandidat (bank dipakai sbg cache)...")
        corpus = scrape_all_candidates(urls, preloaded_corpus, progress_cb=scrape_progress)
        print(f"[!] Korpus terkurasi utk dokumen ini: {len(corpus)} sumber.")

        set_progress(85, "Menghitung kemiripan (Algoritma N-Gram)...")
        print("[!] Menghitung similaritas dengan algoritma N-Gram Shingling...")
        # PARAMETER IDENTIK GROUNDTRUTH: hanya semantic_threshold=0.88. TANPA
        # semantic_max_sources/min_source_overlap -> engine berperilaku persis seperti
        # run_test_groundtruth.py, sehingga skor dokumen tervalidasi konsisten saat
        # dites di localhost (korpus sama-sama terkurasi, bukan bank mentah).
        sorted_sources, total_similarity, plagiarized_sentences = calculate_similarity(
            doc_text, corpus, exclude_small, use_semantic=use_semantic,
            semantic_threshold=0.88)

        data = {
            'filename': original_filename.replace('.pdf', ''),
            'total_similarity': round(total_similarity),
            'sources': sorted_sources,
            'plagiarized_sentences': plagiarized_sentences,
            'manipulation_warnings': manipulation_warnings
        }
        
        set_progress(95, "Membangun Laporan PDF...")
        print("[!] Membangun PDF Report...")
        report_pdf_path = os.path.join(app.config['REPORT_FOLDER'], f"{file_id}_report.pdf")
        generate_report_pdf(filepath, report_pdf_path, data)
        
        results_db[file_id].update({
            'status': 'completed',
            'progress': 100,
            'message': 'Selesai.',
            'data': data
        })
        print(f"[!] Selesai. Hasil: {total_similarity}%")
    except Exception as e:
        import traceback
        traceback.print_exc()
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

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    exclude_quotes = request.form.get('exclude_quotes') == 'true'
    exclude_biblio = request.form.get('exclude_biblio') == 'true'
    exclude_small = request.form.get('exclude_small') == 'true'
    # Deteksi parafrasa (Semantic AI) selalu nyala; UI tak lagi menampilkan opsinya.
    # Default True agar tetap aktif walau field 'use_semantic' tidak dikirim form.
    use_semantic = request.form.get('use_semantic', 'true') == 'true'

    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
        
    if file and file.filename.lower().endswith('.pdf'):
        filename = secure_filename(file.filename)
        # SECURITY FIX: Use cryptographically secure UUID instead of predictable timestamp
        file_id = str(uuid.uuid4())
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}.pdf")
        file.save(filepath)
        
        # SECURITY FIX: Store session ID for ownership validation
        if 'session_id' not in session:
            session['session_id'] = secrets.token_urlsafe(32)
        
        results_db[file_id] = {
            'status': 'processing', 
            'progress': 0, 
            'message': 'Memulai proses...',
            'session_id': session['session_id'],  # Track ownership
            'filename': filename
        }
        thread = threading.Thread(target=process_document, args=(file_id, filepath, filename, exclude_quotes, exclude_biblio, exclude_small, use_semantic), daemon=True)
        thread.start()
        
        return jsonify({'file_id': file_id, 'filename': filename})
    return jsonify({'error': 'Hanya file PDF yang diizinkan'}), 400

@app.route('/status/<file_id>')
def status(file_id):
    # SECURITY FIX: Validate ownership before returning status
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
    # SECURITY FIX: Validate ownership before showing report
    if file_id not in results_db:
        return "Laporan tidak ditemukan.", 404
    
    file_data = results_db[file_id]
    current_session = session.get('session_id')
    
    # Check ownership
    if file_data.get('session_id') != current_session:
        return "Akses tidak diizinkan.", 403
    
    if file_data['status'] == 'completed':
        data = file_data['data']
        
        # Dedup per-DOMAIN untuk tampilan web (sama dengan PDF report)
        seen_domains = set()
        unique_sources = []
        for source in data['sources']:
            # Ekstrak domain dari URL
            domain = source['url'].split('//')[-1].split('/')[0] if '//' in source['url'] else source['url']
            if domain in seen_domains:
                continue
            seen_domains.add(domain)
            unique_sources.append(source)
            
        data_for_html = {k:v for k,v in data.items() if k != 'plagiarized_sentences' and k != 'sources'}
        data_for_html['sources'] = unique_sources
        
        return render_template('report.html', data=data_for_html, file_id=file_id)
    return "Laporan belum siap atau terjadi kesalahan.", 404

@app.route('/download/<file_id>')
def download_report(file_id):
    # SECURITY FIX: Validate ownership before allowing download
    if file_id not in results_db:
        return "Laporan tidak ditemukan.", 404
    
    file_data = results_db[file_id]
    current_session = session.get('session_id')
    
    # Check ownership
    if file_data.get('session_id') != current_session:
        return "Akses tidak diizinkan.", 403
    
    report_pdf_path = os.path.join(app.config['REPORT_FOLDER'], f"{file_id}_report.pdf")
    if os.path.exists(report_pdf_path):
        download_name = f"{file_id}_turnitin.pdf"
        if 'data' in file_data:
            original = file_data['data'].get('filename', file_id)
            download_name = f"{original}_turnitin.pdf"
        return send_file(report_pdf_path, as_attachment=True, download_name=download_name)
    return "PDF Report not found", 404

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
        os.system("taskkill /F /IM ngrok.exe >nul 2>&1")
        os.system(f"taskkill /F /PID {os.getpid()} >nul 2>&1")
        os._exit(0)
    

    signal.signal(signal.SIGINT, on_ctrl_c)
    
    print("\n==================================================")
    print(f"[!] Akses Lokal (IP)   : http://{local_ip}:5001")
    
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
                print(f"[!] Akses Publik Ngrok : {public_url.public_url}")
            except Exception as e:
                print(f"[!] Ngrok tidak tersedia: {e}")
        
        ngrok_thread = threading.Thread(target=start_ngrok, daemon=True)
        ngrok_thread.start()
    else:
        print("[!] Akses Publik Ngrok : DINONAKTIFKAN (Gunakan USE_NGROK=true untuk mengaktifkan)")
        
    print("==================================================\n")
    
    # SEC-02: Matikan debug=True untuk mencegah remote code execution via Werkzeug
    app.run(host='0.0.0.0', port=5001, debug=False, use_reloader=False)
