"""
Direct scraping untuk repository kampus Indonesia tanpa batasan API.
Strategi: Akses langsung ke portal OJS (Open Journal Systems) yang digunakan mayoritas kampus.
"""
import requests
import warnings
import urllib3
import re
import urllib.parse
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
import time
import httpx
import os

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)
try:
    import requests.packages.urllib3.exceptions
    requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
    warnings.filterwarnings("ignore", category=requests.packages.urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

import threading

_shared_client = None
_client_lock = threading.Lock()

def _get_shared_client():
    global _shared_client
    if _shared_client is None:
        with _client_lock:
            if _shared_client is None:
                _shared_client = httpx.Client(
                    http2=False,
                    verify=False,
                    timeout=10.0,
                    limits=httpx.Limits(max_keepalive_connections=30, max_connections=100)
                )
    return _shared_client

def safe_get(url, params=None, timeout=10, headers=None, verify=False):
    """Gunakan HTTPX dengan persistent connection pooling (H-M4 Fix)"""
    if headers is None:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    try:
        client = _get_shared_client()
        return client.get(url, params=params, timeout=timeout, headers=headers)
    except Exception:
        class DummyResponse:
            status_code = 500
            text = ""
            content = b""
        return DummyResponse()

# Database 70+ repository kampus Indonesia yang diakses langsung
INDONESIAN_REPOSITORIES = [
    # Tier 1: UBSI & Kampus Prioritas Utama
    "https://repository.bsi.ac.id",
    "https://jurnal.bsi.ac.id",
    "https://staffv2.bsi.ac.id",
    "https://repository.nusamandiri.ac.id",
    "https://repository.umsu.ac.id", 
    "https://etheses.uin-malang.ac.id",
    "https://ejournal.itn.ac.id",
    "https://eprints.undip.ac.id",
    "https://repository.uinjkt.ac.id",
    "https://eprints.uns.ac.id",
    
    # Tier 2: Universitas Negeri & UIN Besar
    "https://repository.ugm.ac.id",
    "https://repository.ui.ac.id",
    "https://digilib.itb.ac.id",
    "https://repository.unair.ac.id",
    "https://repository.ipb.ac.id",
    "https://repository.unpad.ac.id",
    "https://repository.its.ac.id",
    "https://eprints.uny.ac.id",
    "https://eprints.unm.ac.id",
    "https://repository.upi.edu",
    "https://repository.usu.ac.id",
    "https://repository.unand.ac.id",
    "https://repository.unhas.ac.id",
    "https://repository.unsri.ac.id",
    "https://repository.unila.ac.id",
    "https://etheses.uinjbd.ac.id",  # UIN Bandung
    "https://digilib.uinsgd.ac.id",  # UIN Sunan Gunung Djati
    "https://digilib.uin-suka.ac.id",# UIN Sunan Kalijaga
    "https://journal.uin-alauddin.ac.id",
    
    # Tier 3: Universitas Swasta Besar
    "https://eprints.ums.ac.id",
    "https://eprints.umm.ac.id",
    "https://repository.umy.ac.id",
    "https://eprints.uad.ac.id",
    "https://repository.binus.ac.id",
    "https://openlibrary.telkomuniversity.ac.id",
    "https://repository.gunadarma.ac.id",
    "https://repository.mercubuana.ac.id",
    "https://repository.trisakti.ac.id",
    "https://repository.atmajaya.ac.id",
    "https://repository.um-surabaya.ac.id",
    "https://kc.umn.ac.id",
    "https://repo.darmajaya.ac.id",
    "https://eprints.upj.ac.id",
    
    # Tier 4: Portal Jurnal & Agregator Akademik
    "https://123dok.com",
    "https://ejurnal.stmik-budidarma.ac.id",
    "https://ejurnal.lkpkaryaprima.id",
    "https://jurnal.sttmcileungsi.ac.id",
    "https://core.ac.uk",
    "https://journal.paramadina.ac.id",
    "https://journal.almuslim.ac.id",
    "https://repository.pnj.ac.id",
    "https://ejournal.catursakti.ac.id",
    "https://jurnal.polibatam.ac.id",
    "https://www.csauthors.net",
    "https://garuda.kemdikbud.go.id",
    "https://sinta.kemdikbud.go.id",
    "https://moraref.kemenag.go.id",
]

# Portal OJS yang umum digunakan kampus Indonesia
OJS_SEARCH_PATTERNS = [
    "/index.php/*/search/search",  # OJS 2.x
    "/index.php/*/search",          # OJS 3.x
    "/ojs/index.php/*/search",
    "/search",
]

# Global blacklist untuk server kampus yang sedang down (agar tidak di-query berulang kali)
DEAD_REPOSITORIES = set()

def search_repository_direct(repo_url, query, max_results=5):
    """
    Search langsung ke repository tanpa API.
    Mendeteksi platform (EPrints, DSpace, OJS) dan menyesuaikan strategi.
    """
    if repo_url in DEAD_REPOSITORIES:
        return [], []
        
    urls_found = []
    texts_found = []
    
    hdr = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    if "bsi.ac.id" in repo_url.lower():
        bsi_cookie = os.environ.get("BSI_COOKIE", "")
        if bsi_cookie:
            hdr["Cookie"] = bsi_cookie
    
    try:
        # Deteksi platform repository
        platform = detect_platform(repo_url)

        if platform == "ubsi":
            urls_found, texts_found = search_ubsi(repo_url, query, max_results, hdr)
        elif platform == "eprints":
            urls_found, texts_found = search_eprints(repo_url, query, max_results, hdr)
        elif platform == "dspace":
            urls_found, texts_found = search_dspace(repo_url, query, max_results, hdr)
        elif platform == "ojs":
            urls_found, texts_found = search_ojs(repo_url, query, max_results, hdr)
        else:
            # Fallback: Google site search
            urls_found = google_site_search_fallback(repo_url, query, max_results)
            
    except Exception as e:
        # Pesan error aktual bervariasi: "Read timed out", "ConnectTimeout",
        # "Max retries exceeded", "SSLError". Cek case-insensitive agar repo mati
        # benar-benar masuk blacklist (tidak di-query ulang tiap probe & memblokir pool).
        err = str(e).lower()
        if "bsi.ac.id" not in repo_url.lower() and any(k in err for k in ("timed out", "timeout", "max retries", "sslerror",
                                   "connection", "ssl:")):
            # Cetak sekali saja per host: beberapa worker paralel bisa gagal
            # bersamaan sebelum host masuk set (dulu pesan sama tercetak 4x).
            if repo_url not in DEAD_REPOSITORIES:
                print(f"[!] {repo_url} mati/timeout. Menambahkan ke Blacklist...")
            DEAD_REPOSITORIES.add(repo_url)
        else:
            print(f"[!] Warning searching {repo_url}: {e}")
    
    return urls_found, texts_found

def detect_platform(repo_url):
    """Deteksi platform repository dari URL dan HTML"""
    hdr = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    
    try:
        res = safe_get(repo_url, timeout=10, verify=False, headers=hdr)
        html = res.text.lower()

        # UBSI custom platform (BSI, Nusamandiri) - endpoint /repo/cari
        if "/repo/cari" in html or "repository ubsi" in html:
            return "ubsi"
        elif "eprints" in html or "eprints" in repo_url.lower():
            return "eprints"
        elif "dspace" in html or "dspace" in repo_url.lower():
            return "dspace"
        elif "ojs" in html or "index.php" in repo_url:
            return "ojs"
        else:
            return "unknown"
    except Exception:
        # Deteksi dari URL saja jika request gagal
        url_lower = repo_url.lower()
        if "bsi.ac.id" in url_lower or "nusamandiri" in url_lower:
            return "ubsi"
        elif "eprints" in url_lower:
            return "eprints"
        elif "etheses" in url_lower or "repository" in url_lower:
            return "dspace"
        elif "ejurnal" in url_lower or "ejournal" in url_lower:
            return "ojs"
        return "unknown"

def search_ubsi(repo_url, query, max_results=5, hdr=None):
    """
    Search UBSI custom platform (repository.bsi.ac.id, repository.nusamandiri.ac.id).
    Endpoint: /repo/cari?q=QUERY. Hasil berupa link /repo/{id}/{slug}.
    Halaman detail memuat metadata + link PDF download.
    """
    urls_found = []
    texts_found = []
    if hdr is None: hdr = {'User-Agent': 'Mozilla/5.0'}

    # Perpendek query agar tidak terlalu spesifik (phrase match ketat = 0 hasil)
    short_q = " ".join(query.split()[:6])
    search_url = f"{repo_url}/repo/cari"
    try:
        res = safe_get(search_url, params={"q": short_q}, timeout=15, verify=False, headers=hdr)
    except Exception as e:
        print(f"[!] Warning searching {repo_url}: {e}")
        return urls_found, texts_found
    if res.status_code != 200:
        return urls_found, texts_found

    soup = BeautifulSoup(res.text, 'html.parser')
    seen = set()
    detail_urls = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        # Link item: /repo/<digit>/<slug> (bukan /repo/cari)
        if re.search(r'/repo/\d+', href) and 'cari' not in href:
            title = a.get_text(strip=True)
            if len(title) > 15:
                full = href if href.startswith('http') else repo_url + href
                if full not in seen:
                    seen.add(full)
                    detail_urls.append((full, title))

    # Ambil metadata dari halaman detail (maks max_results)
    for full, title in detail_urls[:max_results]:
        # Judul selalu berguna sebagai teks pembanding minimal
        best_url = full
        best_text = title
        try:
            dr = safe_get(full, timeout=10, verify=False, headers=hdr)
            if dr.status_code == 200:
                dsoup = BeautifulSoup(dr.text, 'html.parser')

                # Tambahkan teks halaman detail (abstrak/metadata) ke teks pembanding
                for s in dsoup(["script", "style", "nav", "footer", "header"]):
                    s.decompose()
                page_text = re.sub(r'\s+', ' ', dsoup.get_text(' ')).strip()
                if len(page_text) > len(best_text):
                    best_text = page_text

                # Cari link PDF download untuk full-text
                pdf_url = None
                for a in dsoup.find_all('a', href=True):
                    h = a['href']
                    if '.pdf' in h.lower() or '/download/' in h.lower():
                        pdf_url = h if h.startswith('http') else repo_url + h
                        break

                if pdf_url:
                    best_text = title
                    try:
                        import fitz
                        pr = safe_get(pdf_url, timeout=20, verify=False, headers=hdr)
                        if pr.status_code == 200 and pr.content[:4] == b'%PDF':
                            doc = fitz.open(stream=pr.content, filetype="pdf")
                            pdf_text = ""
                            for pnum, page in enumerate(doc):
                                if pnum >= 8:
                                    break
                                pdf_text += page.get_text() + " "
                            doc.close()
                            if len(pdf_text) > 200:
                                best_text = re.sub(r'\s+', ' ', pdf_text).strip()
                                best_url = pdf_url
                    except Exception:
                        pass
        except Exception:
            pass

        if len(best_text) > 30:
            urls_found.append(best_url)
            texts_found.append(best_text)

    return urls_found, texts_found

def search_eprints(repo_url, query, max_results=5, hdr=None):
    """Search EPrints repository (format: eprints.*.ac.id)"""
    urls_found = []
    texts_found = []
    
    # EPrints advanced search URL
    search_url = f"{repo_url}/cgi/search/simple"
    params = {
        "exp": query,
        "t": "fulltext"
    }
    
    try:
        res = safe_get(search_url, params=params, timeout=10, verify=False, headers=hdr)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # EPrints result links biasanya di <cite> atau <div class="ep_search_result">
            results = soup.find_all(['cite', 'div'], limit=max_results*2)
            
            for result in results[:max_results]:
                # Ekstrak link
                link = result.find('a', href=True)
                if link:
                    url = link['href']
                    if not url.startswith('http'):
                        url = repo_url + url
                    
                    # Ekstrak abstract/snippet
                    abstract = result.get_text(strip=True)
                    
                    if len(abstract) > 50:
                        urls_found.append(url)
                        texts_found.append(abstract[:500])
    except Exception:
        pass
                        
    return urls_found, texts_found

def search_dspace(repo_url, query, max_results=5, hdr=None):
    """Search DSpace repository (format: repository.*.ac.id)"""
    urls_found = []
    texts_found = []
    
    # DSpace simple search
    search_url = f"{repo_url}/simple-search"
    params = {
        "query": query,
        "order": "desc"
    }
    
    try:
        res = safe_get(search_url, params=params, timeout=10, verify=False, headers=hdr)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # DSpace results biasanya di <div class="artifact-title"> atau <td class="metadataFieldValue">
            results = soup.find_all(['div', 'td'], class_=re.compile(r'artifact|metadata'), limit=max_results*2)
            
            for result in results[:max_results]:
                link = result.find('a', href=True)
                if link:
                    url = link['href']
                    if not url.startswith('http'):
                        url = repo_url + url
                    
                    abstract = result.get_text(strip=True)
                    
                    if len(abstract) > 50:
                        urls_found.append(url)
                        texts_found.append(abstract[:500])
    except Exception:
        pass
                        
    return urls_found, texts_found

def search_ojs(repo_url, query, max_results=5, hdr=None):
    """Search OJS (Open Journal Systems) - platform jurnal Indonesia"""
    urls_found = []
    texts_found = []
    
    # OJS search endpoint (varies by version)
    for pattern in OJS_SEARCH_PATTERNS:
        try:
            search_url = repo_url + pattern
            params = {"query": query}
            
            res = safe_get(search_url, params=params, timeout=10, verify=False, headers=hdr)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'html.parser')
                
                # OJS results dalam <div class="result"> atau <article>
                results = soup.find_all(['div', 'article'], class_=re.compile(r'result|article|item'), limit=max_results)
                
                for result in results:
                    link = result.find('a', href=True)
                    if link:
                        url = link['href']
                        if not url.startswith('http'):
                            url = repo_url + url
                        
                        abstract = result.get_text(strip=True)
                        
                        if len(abstract) > 50:
                            urls_found.append(url)
                            texts_found.append(abstract[:500])
                
                if urls_found:
                    break  # Found results, no need to try other patterns
                    
        except Exception:
            continue
            
    return urls_found, texts_found

def google_site_search_fallback(repo_url, query, max_results=5):
    """
    Fallback: Google site: search tanpa API
    Menggunakan scraping langsung ke Google (rate-limited tapi gratis)
    """
    urls_found = []
    
    try:
        import urllib.parse
        domain = repo_url.replace('https://', '').replace('http://', '').split('/')[0]
        google_query = f"{query} site:{domain}"
        encoded_query = urllib.parse.quote(google_query)
        
        search_url = f"https://www.google.com/search?q={encoded_query}&num={max_results}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        res = requests.get(search_url, headers=headers, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # Extract result URLs from Google
            for link in soup.find_all('a', href=True):
                href = link['href']
                if '/url?q=' in href:
                    # Extract actual URL from Google redirect
                    actual_url = href.split('/url?q=')[1].split('&')[0]
                    actual_url = urllib.parse.unquote(actual_url)
                    
                    if domain in actual_url:
                        urls_found.append(actual_url)
                        
                if len(urls_found) >= max_results:
                    break
                    
        # Rate limit untuk Google
        time.sleep(2)
        
    except Exception as e:
        print(f"[!] Google site search failed: {e}")
    
    return urls_found

def search_all_indonesian_repos(query, max_repos=10, results_per_repo=3):
    """
    Search semua repository Indonesia secara paralel.
    Strategi: Hit repository teratas dulu, expand jika hasil kurang.
    """
    all_urls = []
    all_texts = []

    def search_single_repo(repo_url):
        try:
            urls, texts = search_repository_direct(repo_url, query, results_per_repo)
            return urls, texts
        except:
            return [], []
    
    # Parallel search dengan thread pool
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = []
        for repo_url in INDONESIAN_REPOSITORIES[:max_repos]:
            future = executor.submit(search_single_repo, repo_url)
            futures.append(future)
        
        for future in futures:
            try:
                urls, texts = future.result(timeout=15)
                all_urls.extend(urls)
                all_texts.extend(texts)
            except:
                pass
    
    # Hanya cetak bila benar-benar menemukan sesuatu (kurangi noise per-probe).
    if all_urls:
        print(f"[INDO REPOS] Found {len(all_urls)} results from Indonesian repositories")
    return all_urls, all_texts