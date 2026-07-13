"""
Free API Fallbacks - Google Custom Search JSON API
Menggunakan Google Custom Search API (10,000 queries/day GRATIS)
Jauh lebih reliable daripada scraping atau API trial yang mudah habis.
"""

import requests
import time
import hashlib
import json
import os
from pathlib import Path

# Cache directory
CACHE_DIR = Path(__file__).parent / '.search_cache'
CACHE_DIR.mkdir(exist_ok=True)

def get_cache_key(query):
    """Generate cache key dari query"""
    return hashlib.md5(query.encode()).hexdigest()

def get_cached_results(query, max_age_hours=24):
    """Ambil hasil dari cache jika masih fresh"""
    cache_file = CACHE_DIR / f"{get_cache_key(query)}.json"
    if cache_file.exists():
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_hours < max_age_hours:
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    print(f"[CACHE] Found cached results for query (age: {age_hours:.1f}h)")
                    return data['urls'], data['texts']
            except:
                pass
    return None, None

def save_to_cache(query, urls, texts):
    """Simpan hasil ke cache"""
    cache_file = CACHE_DIR / f"{get_cache_key(query)}.json"
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump({'urls': urls, 'texts': texts}, f)
    except:
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
        from duckduckgo_search import DDGS
        import time
        
        # Limit panjang query (DDG menolak query yang sangat panjang)
        short_query = ' '.join(query.split()[:15])
        
        # Delay singkat acak untuk menghindari rate limit agresif
        time.sleep(0.5)
        
        with DDGS() as ddgs:
            results = list(ddgs.text(short_query, max_results=max_results))
            
            for res in results:
                url = res.get('href', '')
                title = res.get('title', '')
                body = res.get('body', '')
                
                if url:
                    urls_found.append(url)
                    texts_found.append(f"{title}. {body}")
                    
        if urls_found:
            print(f"[DuckDuckGo API] Found {len(urls_found)} results")
        else:
            print("[DuckDuckGo API] Found 0 results (Query mungkin terlalu spesifik)")
            
    except Exception as e:
        print(f"[!] DuckDuckGo API error: {e}")
        
    return urls_found, texts_found

def search_with_fallbacks(query, use_cache=True):
    """
    Search menggunakan Google Custom Search API dengan caching,
    serta otomatis fallback ke DuckDuckGo HTML jika Google belum disetup.
    
    Returns:
        tuple: (list of URLs, list of text snippets)
    """
    
    # Check cache first
    if use_cache:
        cached_urls, cached_texts = get_cached_results(query, max_age_hours=24)
        if cached_urls:
            return cached_urls, cached_texts
    
    # Shorten query jika terlalu panjang (Google CSE limit 2048 chars)
    short_query = ' '.join(query.split()[:20])
    
    # Google Custom Search API credentials
    google_api_keys = [
        'AIzaSyAYHWCzB4cngtXwNG8VX5gl-PejHSj2DdY',  # Key Utama Anda
        'AIzaSyDU_W1ABFJqxob_PdsGfMVHKLPFLgEd0Lk',  # Key Backup Akun Kedua Anda
    ]
    cx_id = '71bc58731f30a4f5d'
    
    all_urls = []
    all_texts = []
    
    is_configured = cx_id != 'YOUR_CX_ID_HERE'
    
    if is_configured:
        # Try each API key with load balancing
        for api_key in google_api_keys:
            try:
                urls, texts = search_google_custom(short_query, api_key, cx_id, max_results=15)
                all_urls.extend(urls)
                all_texts.extend(texts)
                
                if len(all_urls) >= 10:
                    break  # Cukup, jangan buang quota
                    
            except Exception as e:
                print(f"[!] Google API key error: {e}")
                continue
    
    # Fallback ke DuckDuckGo jika Google belum dikonfigurasi atau gagal mencari apapun
    if not all_urls:
        if not is_configured:
            print("[!] Google Custom Search API belum dikonfigurasi. Menggunakan fallback DuckDuckGo HTML...")
        else:
            print("[!] Google Custom Search API tidak menghasilkan data. Mencoba fallback DuckDuckGo HTML...")
            
        try:
            urls, texts = search_duckduckgo_html(short_query, max_results=15)
            all_urls.extend(urls)
            all_texts.extend(texts)
        except Exception as e:
            print(f"[!] Fallback DuckDuckGo error: {e}")
            
    # Cache results
    if use_cache and all_urls:
        save_to_cache(query, all_urls, all_texts)
    
    return all_urls, all_texts