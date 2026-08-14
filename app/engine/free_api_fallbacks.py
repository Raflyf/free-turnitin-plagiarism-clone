"""
Free API Fallbacks - Pencarian Web dengan DuckDuckGo + Google CSE (opsional).
Default: DuckDuckGo (tanpa konfigurasi apapun, langsung jalan).
Jika GOOGLE_API_KEYS + GOOGLE_CX_ID diisi di .env, Google CSE dipakai lebih dulu;
DuckDuckGo menjadi fallback jika Google gagal. Kode CSE sengaja dipertahankan
agar siapapun yang memiliki key bisa langsung mengaktifkannya.
"""

import requests
import time
import hashlib
import json
import os
from pathlib import Path

import sqlite3
import threading
from engine.supabase_client import get_cached_results_supabase, save_to_cache_supabase

_CACHE_DB_PATH = Path(__file__).parent / '.search_cache.db'
_cache_lock = threading.Lock()

def _get_cache_conn():
    conn = sqlite3.connect(_CACHE_DB_PATH, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("CREATE TABLE IF NOT EXISTS cache (query_hash TEXT PRIMARY KEY, data TEXT, timestamp REAL)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_query_time ON cache(query_hash, timestamp)")
    return conn

def get_cache_key(query):
    """Generate cache key dari query"""
    return hashlib.md5(query.encode('utf-8')).hexdigest()

def get_cached_results(query, max_age_hours=2160):
    """Ambil hasil dari Supabase/SQLite3 cache jika masih fresh"""
    try:
        q_hash = get_cache_key(query)
        # 1. Coba ambil dari Supabase
        supa_res = get_cached_results_supabase(q_hash)
        if supa_res and isinstance(supa_res, dict):
            return supa_res.get('urls', []), supa_res.get('texts', [])
            
        # 2. Fallback ke SQLite3 lokal
        cutoff = time.time() - (max_age_hours * 3600)
        with _cache_lock:
            conn = _get_cache_conn()
            cur = conn.cursor()
            cur.execute("SELECT data FROM cache WHERE query_hash = ? AND timestamp > ?", (q_hash, cutoff))
            row = cur.fetchone()
            conn.close()
            if row:
                data = json.loads(row[0])
                return data.get('urls', []), data.get('texts', [])
    except Exception:
        pass
    return None, None

def save_to_cache(query, urls, texts):
    """Simpan hasil ke Supabase & SQLite3 cache (atomik, thread-safe)"""
    try:
        q_hash = get_cache_key(query)
        results_dict = {'urls': urls, 'texts': texts}
        
        # 1. Simpan ke Supabase Cloud
        save_to_cache_supabase(q_hash, "search_engine", results_dict)
        
        # 2. Simpan ke SQLite lokal
        data_str = json.dumps(results_dict, ensure_ascii=False)
        with _cache_lock:
            conn = _get_cache_conn()
            conn.execute("INSERT OR REPLACE INTO cache (query_hash, data, timestamp) VALUES (?, ?, ?)",
                         (q_hash, data_str, time.time()))
            conn.commit()
            conn.close()
    except Exception:
        pass

def search_google_custom(query, api_key, cx_id, max_results=10):
    """
    Mencari menggunakan Google Custom Search JSON API
    
    Google Custom Search API:
    - 10,000 queries/day GRATIS
    - Reliable dan fast
    - Official Google API
    - Mendukung site: operator dan advanced search
    
    Setup:
    1. Buat project di https://console.cloud.google.com/
    2. Enable Custom Search API
    3. Buat API key
    4. Buat Custom Search Engine di https://programmablesearchengine.google.com/
    5. Set "Search the entire web" = ON
    """
    urls_found = []
    texts_found = []
    
    try:
        # Google Custom Search JSON API endpoint
        base_url = "https://www.googleapis.com/customsearch/v1"
        
        # Lakukan multiple search dengan variasi query untuk coverage maksimal
        queries = [
            query,  # Original query
            f'{query} site:ac.id',  # Prioritas kampus Indonesia
            f'{query} (repository OR jurnal OR skripsi)',  # Prioritas akademik
        ]
        
        all_urls = set()
        
        for q in queries[:2]:  # Limit 2 query variations untuk menghemat quota
            # Google Custom Search bisa 10 results per call
            for start_index in range(1, min(max_results, 11), 10):
                params = {
                    'key': api_key,
                    'cx': cx_id,
                    'q': q,
                    'num': min(10, max_results - len(all_urls)),
                    'start': start_index
                }
                
                try:
                    response = requests.get(base_url, params=params, timeout=10)
                    
                    if response.status_code == 200:
                        data = response.json()
                        
                        if 'items' in data:
                            for item in data['items']:
                                url = item.get('link', '')
                                title = item.get('title', '')
                                snippet = item.get('snippet', '')
                                
                                if url and url not in all_urls:
                                    all_urls.add(url)
                                    urls_found.append(url)
                                    
                                    # Gabungkan title + snippet sebagai text preview
                                    text = f"{title}. {snippet}"
                                    texts_found.append(text)
                                    
                                    if len(all_urls) >= max_results:
                                        break
                    
                    elif response.status_code == 429:
                        # Rate limit reached
                        print(f"[Google API] Rate limit reached, stopping...")
                        break
                    
                    elif response.status_code in [400, 403]:
                        # Sembunyikan JSON error panjang dari Google karena ini memang diblokir dari pusat (Google Policy)
                        print(f"[Google API] Akses ditolak (HTTP {response.status_code}) - Menggunakan fallback...")
                        break
                        
                    else:
                        print(f"[Google API] Error HTTP {response.status_code}")
                        break
                    
                    # Hindari rate limiting dengan delay kecil antar request
                    time.sleep(0.5)
                    
                except requests.exceptions.Timeout:
                    break
                except Exception as e:
                    print(f"[Google API] Error: {e}")
                    break
                
                if len(all_urls) >= max_results:
                    break
            
            if len(all_urls) >= max_results:
                break
        
        if urls_found:
            print(f"[Google Custom Search] Found {len(urls_found)} results")
        
    except Exception as e:
        pass  # Sembunyikan error global agar tidak panik
    
    return urls_found, texts_found

def search_duckduckgo_html(query, max_results=10):
    """
    Menggunakan library duckduckgo_search (DDGS) yang jauh lebih handal
    dalam mengatasi rate limiting dibandingkan scraping HTML manual.
    """
    urls_found = []
    texts_found = []
    
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        import time
        
        # Ambil 8 kata saja, JANGAN gunakan quotes "" karena spasi/newline dari ekstraksi PDF bisa menggagalkan exact match!
        search_query = " ".join(query.split()[:8])
        
        # Delay singkat acak untuk menghindari rate limit agresif
        time.sleep(0.5)
        
        with DDGS() as ddgs:
            results = list(ddgs.text(search_query, max_results=max_results))
            
            for res in results:
                url = res.get('href', '')
                title = res.get('title', '')
                body = res.get('body', '')
                
                if url:
                    urls_found.append(url)
                    texts_found.append(f"{title}. {body}")
                    
        # (log per-probe dibuang; total dilaporkan sekali di akhir get_candidate_urls)
            
    except Exception as e:
        # Timeout/rate-limit DDG lumrah & terjadi per-probe -> cetak sekali saja per proses.
        if not getattr(search_duckduckgo_html, "_warned", False):
            print(f"[!] DuckDuckGo API error (ditampilkan sekali): {e}")
            search_duckduckgo_html._warned = True

    return urls_found, texts_found

def search_moraref(query, max_results=10):
    """
    Search MORAREF Kemenag (Kementerian Agama RI)
    Mengakses portal jurnal ilmiah seluruh UIN/IAIN/STAIN se-Indonesia
    """
    urls, texts = [], []
    try:
        short_q = " ".join(query.split()[:8])
        url = "https://moraref.kemenag.go.id/api/v1/journal/search"
        resp = requests.get(url, params={"q": short_q, "limit": max_results}, timeout=6)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("data", []) if isinstance(data, dict) else []
            for item in items:
                link = item.get("url") or item.get("link")
                title = item.get("title", "")
                abstract = item.get("abstract", "") or item.get("description", "")
                if link and link not in urls:
                    urls.append(link)
                    texts.append(f"{title}. {abstract}")
    except Exception:
        pass
    return urls, texts

def search_base_academic(query, max_results=10):
    """
    Search BASE (Bielefeld Academic Search Engine)
    Database 300 juta+ publikasi ilmiah open access via OAI-PMH gratis.
    """
    urls, texts = [], []
    try:
        short_q = " ".join(query.split()[:8])
        url = "https://api.base-search.net/cgi-bin/BaseHttpSearchInterface.fcgi"
        params = {"func": "PerformSearch", "query": short_q, "format": "json", "hits": max_results}
        resp = requests.get(url, params=params, timeout=6)
        if resp.status_code == 200:
            data = resp.json()
            docs = data.get("response", {}).get("docs", [])
            for d in docs:
                link = d.get("dcunqualifiedlink") or (d.get("dclink", [""])[0] if d.get("dclink") else None)
                title = d.get("dctitle", "")
                abstract = d.get("dcdescription", "")
                if link and link not in urls:
                    urls.append(link)
                    texts.append(f"{title}. {abstract}")
    except Exception:
        pass
    return urls, texts

def search_internet_archive(query, max_results=10):
    """
    Search Internet Archive Scholar (35M+ publikasi ilmiah & skripsi terdigitalisasi)
    """
    urls, texts = [], []
    try:
        short_q = " ".join(query.split()[:8])
        url = "https://archive.org/advancedsearch.php"
        params = {
            "q": f"{short_q} mediatype:texts",
            "fl[]": "identifier,title,description",
            "rows": max_results,
            "page": 1,
            "output": "json"
        }
        resp = requests.get(url, params=params, timeout=6)
        if resp.status_code == 200:
            docs = resp.json().get("response", {}).get("docs", [])
            for d in docs:
                ident = d.get("identifier")
                title = d.get("title", "")
                desc = d.get("description", "")
                if ident:
                    link = f"https://archive.org/details/{ident}"
                    if link not in urls:
                        urls.append(link)
                        texts.append(f"{title}. {desc}")
    except Exception:
        pass
    return urls, texts

def search_scilit(query, max_results=10):
    """
    Search Scilit API (MDPI Academic Aggregator - 160M+ paper)
    """
    urls, texts = [], []
    try:
        short_q = " ".join(query.split()[:8])
        url = f"https://www.scilit.net/api/v1/articles/search?q={short_q}"
        resp = requests.get(url, timeout=6)
        if resp.status_code == 200:
            data = resp.json()
            articles = data.get("articles", []) if isinstance(data, dict) else []
            for a in articles:
                link = a.get("url") or a.get("doi_url")
                title = a.get("title", "")
                abstract = a.get("abstract", "")
                if link and link not in urls:
                    urls.append(link)
                    texts.append(f"{title}. {abstract}")
    except Exception:
        pass
    return urls, texts

def search_with_fallbacks(query, use_cache=True):
    """
    Search menggunakan gabungan seluruh API & Provider Akademik:
    Google CSE -> MORAREF -> BASE -> Internet Archive -> Scilit -> DuckDuckGo
    """
    if use_cache:
        cached_urls, cached_texts = get_cached_results(query, max_age_hours=24)
        if cached_urls:
            return cached_urls, cached_texts
    
    short_query = ' '.join(query.split()[:20])
    
    import os
    google_env = os.environ.get('GOOGLE_API_KEYS', '')
    google_api_keys = google_env.split(',') if google_env else []
    cx_id = os.environ.get('GOOGLE_CX_ID', '')
    
    all_urls = []
    all_texts = []
    
    is_configured = bool(google_api_keys) and bool(cx_id)
    
    if is_configured:
        for api_key in google_api_keys:
            try:
                urls, texts = search_google_custom(short_query, api_key, cx_id, max_results=15)
                all_urls.extend(urls)
                all_texts.extend(texts)
                if len(all_urls) >= 10:
                    break
            except Exception as e:
                print(f"[!] Google API key error: {e}")
                continue
    
    # Fallback 1: MORAREF Kemenag API (Jurnal UIN/IAIN/STAIN)
    if not all_urls:
        try:
            m_urls, m_texts = search_moraref(short_query, max_results=10)
            all_urls.extend(m_urls)
            all_texts.extend(m_texts)
        except Exception:
            pass

    # Fallback 2: BASE Academic Search Engine (300M+ Records)
    if not all_urls:
        try:
            b_urls, b_texts = search_base_academic(short_query, max_results=10)
            all_urls.extend(b_urls)
            all_texts.extend(b_texts)
        except Exception:
            pass

    # Fallback 3: Internet Archive Scholar (35M+ Papers)
    if not all_urls:
        try:
            ia_urls, ia_texts = search_internet_archive(short_query, max_results=10)
            all_urls.extend(ia_urls)
            all_texts.extend(ia_texts)
        except Exception:
            pass

    # Fallback 4: Scilit MDPI Aggregator (160M+ Papers)
    if not all_urls:
        try:
            s_urls, s_texts = search_scilit(short_query, max_results=10)
            all_urls.extend(s_urls)
            all_texts.extend(s_texts)
        except Exception:
            pass

    # Fallback 5: DuckDuckGo HTML Web Search
    if not all_urls:
        try:
            urls, texts = search_duckduckgo_html(short_query, max_results=15)
            all_urls.extend(urls)
            all_texts.extend(texts)
        except Exception as e:
            print(f"[!] Fallback DuckDuckGo error: {e}")
            
    if use_cache and all_urls:
        save_to_cache(query, all_urls, all_texts)
    
    return all_urls, all_texts