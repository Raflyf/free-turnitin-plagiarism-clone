import os
import time
import math
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
import threading
from engine.extractor import extract_text_from_pdf, get_sentences
from engine.web_scraper import get_candidate_urls, scrape_all_candidates
from engine.shingling import calculate_similarity
from engine.pdf_generator import generate_report_pdf

app = Flask(__name__)
# Gunakan absolute path agar direktori selalu berada di dalam folder app/ 
base_dir = os.path.dirname(os.path.abspath(__file__))
app.config['UPLOAD_FOLDER'] = os.path.join(base_dir, 'uploads')
app.config['REPORT_FOLDER'] = os.path.join(base_dir, 'reports')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 # 16MB max

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['REPORT_FOLDER'], exist_ok=True)

# Store results in memory
results_db = {}

def process_document(file_id, filepath, original_filename, exclude_quotes=True, exclude_biblio=True, exclude_small=False):
    def set_progress(pct, msg):
        if file_id in results_db:
            results_db[file_id]['progress'] = pct
            results_db[file_id]['message'] = msg

    try:
        set_progress(5, "Mengekstrak teks dari PDF...")
        print(f"[!] Mulai ekstraksi teks dari: {filepath}")
        doc_text, manipulation_warnings = extract_text_from_pdf(filepath, exclude_quotes, exclude_biblio)
        sentences = get_sentences(doc_text)
        
        def ddg_progress(completed, total):
            pct = 5 + int((completed / total) * 35) # 5% to 40%
            set_progress(pct, f"Mencari web ({completed}/{total})...")
            
        print(f"[!] Mencari kandidat dari web...")
        urls, preloaded_corpus = get_candidate_urls(sentences, max_probes=120, progress_cb=ddg_progress)
        
        def scrape_progress(completed, total):
            pct = 40 + int((completed / total) * 40) # 40% to 80%
            if total == 0: pct = 80
            set_progress(pct, f"Mengunduh isi web ({completed}/{total})...")
            
        print(f"[!] Mengunduh teks dari {len(urls)} kandidat...")
        corpus = scrape_all_candidates(urls, preloaded_corpus, progress_cb=scrape_progress)
        
        set_progress(85, "Menghitung kemiripan (Algoritma N-Gram)...")
        print("[!] Menghitung similaritas dengan algoritma N-Gram Shingling...")
        sorted_sources, total_similarity, plagiarized_sentences = calculate_similarity(doc_text, corpus, exclude_small)
        
        data = {
            'filename': original_filename.replace('.pdf', ''),
            'total_similarity': int(math.floor(total_similarity)),
            'sources': sorted_sources,
            'plagiarized_sentences': plagiarized_sentences,
            'manipulation_warnings': manipulation_warnings
        }
        
        set_progress(95, "Membangun Laporan PDF...")
        print("[!] Membangun PDF Report...")
        report_pdf_path = os.path.join(app.config['REPORT_FOLDER'], f"{file_id}_report.pdf")
        generate_report_pdf(filepath, report_pdf_path, data)
        
        results_db[file_id] = {
            'status': 'completed',
            'progress': 100,
            'message': 'Selesai.',
            'data': data
        }
        print(f"[!] Selesai. Hasil: {total_similarity}%")
    except Exception as e:
        import traceback
        traceback.print_exc()
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

    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
        
    if file and file.filename.endswith('.pdf'):
        filename = secure_filename(file.filename)
        file_id = f"skripsi_final_{int(time.time() * 1000)}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}.pdf")
        file.save(filepath)
        
        results_db[file_id] = {
            'status': 'processing', 
            'progress': 0, 
            'message': 'Memulai proses...'
        }
        thread = threading.Thread(target=process_document, args=(file_id, filepath, filename, exclude_quotes, exclude_biblio, exclude_small), daemon=True)
        thread.start()
        
        return jsonify({'file_id': file_id, 'filename': filename})
    return jsonify({'error': 'Hanya file PDF yang diizinkan'}), 400

@app.route('/status/<file_id>')
def status(file_id):
    data = results_db.get(file_id, {'status': 'not_found'})
    return jsonify(data)

@app.route('/report/<file_id>')
def report(file_id):
    if file_id in results_db and results_db[file_id]['status'] == 'completed':
        data = results_db[file_id]['data']
        data_for_html = {k:v for k,v in data.items() if k != 'plagiarized_sentences'}
        return render_template('report.html', data=data_for_html, file_id=file_id)
    return "Laporan belum siap atau terjadi kesalahan.", 404

@app.route('/download/<file_id>')
def download_report(file_id):
    report_pdf_path = os.path.join(app.config['REPORT_FOLDER'], f"{file_id}_report.pdf")
    if os.path.exists(report_pdf_path):
        download_name = f"{file_id}_turnitin.pdf"
        if file_id in results_db and 'data' in results_db[file_id]:
            original = results_db[file_id]['data'].get('filename', file_id)
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
        os._exit(0)
    
    signal.signal(signal.SIGINT, on_ctrl_c)
    
    print("\n==================================================")
    print(f"[!] Akses Lokal (IP)   : http://{local_ip}:5001")
    
    # Jalankan Ngrok di thread terpisah agar crash-nya tidak mematikan Flask
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
    print("==================================================\n")
    
    app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=False)
