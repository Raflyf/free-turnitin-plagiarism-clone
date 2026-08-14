"""
Supabase Client Utility Module for Plagiarism Checker
Dukungan terpusat REST API Supabase dengan otomatis batching, error handling, retry & fallback.
"""
import os
import json
import time
import urllib.parse
import requests
import logging

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATHS = [
    os.path.join(BASE_DIR, "..", "..", ".env"),
    os.path.join(BASE_DIR, "..", ".env")
]

def _load_env():
    env_vars = {}
    for p in ENV_PATHS:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            env_vars[k.strip()] = v.strip()
            except Exception:
                pass
    return env_vars

_env = _load_env()
# C1 Fix: Hapus hardcoded fallback fallback key sensitif. Fail-graceful jika env var tidak dikonfigurasi.
SUPABASE_URL = os.environ.get("SUPABASE_URL", _env.get("SUPABASE_URL", ""))
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", _env.get("SUPABASE_KEY", ""))

_session = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=32, pool_maxsize=32)
_session.mount("https://", adapter)
_session.mount("http://", adapter)

if SUPABASE_KEY:
    _session.headers.update({
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    })

def _clean_str(s):
    if not isinstance(s, str):
        return ""
    # PostgreSQL rejects null bytes (\x00 / \u0000) with error 22P05
    s = s.replace('\x00', '').replace('\u0000', '')
    return s.encode('utf-8', 'ignore').decode('utf-8').strip()

def is_supabase_configured():
    return bool(SUPABASE_URL and SUPABASE_KEY)

# H-D2 Fix: Implementasi retry dengan exponential backoff untuk HTTP request ke Supabase
def _request_with_retry(method, url, **kwargs):
    max_retries = kwargs.pop("max_retries", 3)
    backoff_factor = kwargs.pop("backoff_factor", 0.5)
    
    for attempt in range(max_retries):
        try:
            resp = _session.request(method, url, **kwargs)
            if resp.status_code < 500 and resp.status_code != 429:
                return resp
        except (requests.RequestException, Exception) as e:
            if attempt == max_retries - 1:
                logger.warning(f"[Supabase] HTTP request gagal setelah {max_retries} percobaan: {e}")
                raise
        time.sleep(backoff_factor * (2 ** attempt))
    return None

# --- 1. Corpus Bank Supabase Functions ---

def get_bank_urls_supabase():
    """Mengambil seluruh daftar URL yang tersimpan di Supabase corpus_bank secara paralel (support >90.000 URL)."""
    if not is_supabase_configured():
        return None
    try:
        import concurrent.futures
        base_url = f"{SUPABASE_URL}/rest/v1/corpus_bank?select=url"
        
        def fetch_chunk(offset):
            try:
                resp = _request_with_retry("GET", f"{base_url}&limit=1000&offset={offset}", timeout=6.0, max_retries=2)
                if resp and resp.status_code == 200:
                    rows = resp.json()
                    return [r['url'] for r in rows if 'url' in r]
            except Exception:
                pass
            return []

        first_batch = fetch_chunk(0)
        if not first_batch:
            return set()
            
        all_urls = set(first_batch)
        if len(first_batch) < 1000:
            return all_urls

        current_offset = 1000
        batch_step = 16
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
            while True:
                offsets = [current_offset + i * 1000 for i in range(batch_step)]
                results = list(executor.map(fetch_chunk, offsets))
                has_data = False
                for chunk in results:
                    if chunk:
                        all_urls.update(chunk)
                        has_data = True
                        if len(chunk) < 1000:
                            return all_urls
                if not has_data:
                    break
                current_offset += batch_step * 1000
                
        return all_urls
    except Exception as e:
        logger.warning(f"[Supabase] Warning get_bank_urls: {e}")
    return None

def get_bank_texts_supabase(target_urls):
    """Mengambil teks spesifik untuk target_urls dari Supabase (batch 50 URL)."""
    if not is_supabase_configured() or not target_urls:
        return {}
    
    result = {}
    target_list = list(target_urls)
    
    for i in range(0, len(target_list), 50):
        batch = target_list[i:i+50]
        try:
            formatted_urls = ",".join(f'"{_clean_str(u)}"' for u in batch)
            url = f"{SUPABASE_URL}/rest/v1/corpus_bank?select=url,text_content&url=in.({formatted_urls})"
            resp = _request_with_retry("GET", url, timeout=8.0, max_retries=2)
            if resp and resp.status_code == 200:
                rows = resp.json()
                for r in rows:
                    result[r['url']] = r['text_content']
        except Exception as e:
            logger.warning(f"[Supabase] Warning get_bank_texts batch {i}: {e}")
            
    return result

def save_to_corpus_bank_supabase(new_corpus):
    """Menyimpan/meng-upsert dict {url: text} baru ke Supabase corpus_bank (batch 50 items) dengan C3 Fix (on_conflict=url)."""
    if not is_supabase_configured() or not new_corpus:
        return False
    
    items = []
    for u, t in new_corpus.items():
        if isinstance(t, str) and len(t) > 150:
            clean_u = _clean_str(u)
            clean_t = _clean_str(t)
            domain = _clean_str(urllib.parse.urlparse(clean_u).netloc)
            if clean_u and clean_t:
                items.append({"url": clean_u, "domain": domain, "text_content": clean_t})
            
    if not items:
        return False
        
    saved_count = 0
    # C3 Fix: Tambahkan parameter on_conflict=url untuk PostgreSQL conflict resolution
    url = f"{SUPABASE_URL}/rest/v1/corpus_bank?on_conflict=url"
    headers = {"Prefer": "resolution=ignore-duplicates"}
    
    for i in range(0, len(items), 50):
        batch = items[i:i+50]
        try:
            resp = _request_with_retry("POST", url, json=batch, headers=headers, timeout=20.0, max_retries=2)
            if resp and resp.status_code in (200, 201, 409):
                saved_count += len(batch)
            else:
                for single_item in batch:
                    try:
                        r_single = _request_with_retry("POST", url, json=[single_item], headers=headers, timeout=5.0, max_retries=1)
                        if r_single and r_single.status_code in (200, 201, 409):
                            saved_count += 1
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"[Supabase] Warning save_to_corpus_bank batch {i}: {e}")
            
    if saved_count > 0:
        logger.info(f"[Supabase] Berhasil menyimpan {saved_count} sumber baru ke Supabase corpus_bank.")
        return True
    return False

# --- 2. Search Cache Supabase Functions ---

def get_cached_results_supabase(query_hash):
    """Mengambil hasil cache pencarian dari Supabase search_cache."""
    if not is_supabase_configured():
        return None
    try:
        url = f"{SUPABASE_URL}/rest/v1/search_cache?select=results_json&query_hash=eq.{query_hash}"
        resp = _request_with_retry("GET", url, timeout=4.0, max_retries=2)
        if resp and resp.status_code == 200:
            rows = resp.json()
            if rows:
                return rows[0].get('results_json')
    except Exception as e:
        logger.warning(f"[Supabase] Warning get_cached_results: {e}")
    return None

def save_to_cache_supabase(query_hash, engine, results_dict):
    """Menyimpan cache hasil pencarian ke Supabase search_cache dengan C3 Fix (on_conflict=query_hash)."""
    if not is_supabase_configured():
        return False
    try:
        # C3 Fix: tambahkan on_conflict=query_hash
        url = f"{SUPABASE_URL}/rest/v1/search_cache?on_conflict=query_hash"
        payload = {
            "query_hash": query_hash,
            "engine": engine,
            "results_json": results_dict
        }
        headers = {"Prefer": "resolution=merge-duplicates"}
        resp = _request_with_retry("POST", url, json=payload, headers=headers, timeout=5.0, max_retries=2)
        return resp is not None and resp.status_code in (200, 201)
    except Exception as e:
        logger.warning(f"[Supabase] Warning save_to_cache: {e}")
    return False

# --- 3. Analysis Jobs Status Supabase Functions ---

def save_job_status_supabase(file_id, session_id, status, progress=0, message="", result_json=None):
    """Menyimpan atau memperbarui status job analisis di Supabase analysis_jobs dengan C3 Fix (on_conflict=file_id)."""
    if not is_supabase_configured():
        return False
    try:
        # C3 Fix: tambahkan on_conflict=file_id
        url = f"{SUPABASE_URL}/rest/v1/analysis_jobs?on_conflict=file_id"
        payload = {
            "file_id": file_id,
            "session_id": session_id,
            "status": status,
            "progress": progress,
            "message": message
        }
        if result_json is not None:
            payload["result_json"] = result_json
            
        headers = {"Prefer": "resolution=merge-duplicates"}
        resp = _request_with_retry("POST", url, json=payload, headers=headers, timeout=5.0, max_retries=2)
        return resp is not None and resp.status_code in (200, 201)
    except Exception as e:
        logger.warning(f"[Supabase] Warning save_job_status: {e}")
    return False

def get_job_status_supabase(file_id):
    """Mengambil status job analisis dari Supabase analysis_jobs."""
    if not is_supabase_configured():
        return None
    try:
        url = f"{SUPABASE_URL}/rest/v1/analysis_jobs?select=*&file_id=eq.{file_id}"
        resp = _request_with_retry("GET", url, timeout=4.0, max_retries=2)
        if resp and resp.status_code == 200:
            rows = resp.json()
            if rows:
                return rows[0]
    except Exception as e:
        logger.warning(f"[Supabase] Warning get_job_status: {e}")
    return None

# H-D4 Fix: Metode pembersihan otomatis untuk job tua di Supabase
def cleanup_old_jobs_supabase(max_age_hours=24):
    """Menghapus data job analisis lama dari Supabase analysis_jobs (TTL cleanup)."""
    if not is_supabase_configured():
        return False
    try:
        cutoff_time = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - (max_age_hours * 3600)))
        url = f"{SUPABASE_URL}/rest/v1/analysis_jobs?created_at=lt.{cutoff_time}"
        resp = _request_with_retry("DELETE", url, timeout=10.0, max_retries=2)
        return resp is not None and resp.status_code in (200, 204)
    except Exception as e:
        logger.warning(f"[Supabase] Warning cleanup_old_jobs: {e}")
    return False

# C2 Guidance: RLS Security Policy SQL
"""
--- ROW LEVEL SECURITY (RLS) INSTRUCTIONS FOR SUPABASE ---
Jalankan SQL berikut di Supabase SQL Editor untuk mengamankan RLS:

ALTER TABLE corpus_bank ENABLE ROW LEVEL SECURITY;
ALTER TABLE search_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_jobs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow select for anon" ON corpus_bank FOR SELECT USING (true);
CREATE POLICY "Allow insert for anon" ON corpus_bank FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow update for anon" ON corpus_bank FOR UPDATE USING (true);

CREATE POLICY "Allow all for search_cache" ON search_cache FOR ALL USING (true);
CREATE POLICY "Allow all for analysis_jobs" ON analysis_jobs FOR ALL USING (true);
"""
