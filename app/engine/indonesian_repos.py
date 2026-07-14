"""
Direct scraping untuk repository kampus Indonesia tanpa batasan API.
Strategi: Akses langsung ke portal OJS (Open Journal Systems) yang digunakan mayoritas kampus.
"""
import requests
import re
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
import time

# Database repository kampus Indonesia yang bisa diakses publik
INDONESIAN_REPOSITORIES = [
    # Tier 1: BSI dan kampus prioritas
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
    
    # Tier 2: Universitas besar Indonesia & Jurnal Turnitin Asli
    "https://123dok.com",
    "https://ejurnal.stmik-budidarma.ac.id",
    "https://repository.um-surabaya.ac.id",
    "https://ejurnal.lkpkaryaprima.id",
    "https://jurnal.sttmcileungsi.ac.id",
    "https://core.ac.uk",
    "https://journal.paramadina.ac.id",
    "https://journal.almuslim.ac.id",
    "https://repository.pnj.ac.id",
    "https://ejournal.catursakti.ac.id",
    "https://jurnal.polibatam.ac.id",
    "https://www.csauthors.net",
    "https://eprints.upj.ac.id",
    "https://kc.umn.ac.id",
    "https://repo.darmajaya.ac.id",
    "https://journal.uin-alauddin.ac.id",
    "https://repository.unair.ac.id",
    "https://eprints.umm.ac.id",
    "https://repository.upi.edu",
    "https://eprints.unm.ac.id",
    "https://repository.its.ac.id",
    "https://eprints.uny.ac.id",
    "https://repository.unpad.ac.id",
    "https://eprints.ums.ac.id",
    "https://repository.ugm.ac.id",
    "https://repository.ipb.ac.id",
    "https://digilib.itb.ac.id",
    
    # Tier 3: Portal jurnal nasional
    "https://garuda.kemdikbud.go.id",
    "https://sinta.kemdikbud.go.id",
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
    
    try:
        # Deteksi platform repository
        platform = detect_platform(repo_url)

        if platform == "ubsi":
            urls_found, texts_found = search_ubsi(repo_url, query, max_results)
        elif platform == "eprints":
            urls_found, texts_found = search_eprints(repo_url, query, max_results)
        elif platform == "dspace":
            urls_found, texts_found = search_dspace(repo_url, query, max_results)
        elif platform == "ojs":
            urls_found, texts_found = search_ojs(repo_url, query, max_results)
        else:
            # Fallback: Google site search
            urls_found = google_site_search_fallback(repo_url, query, max_results)
            
    except Exception as e:
        if "Timeout" in str(e) or "Max retries exceeded" in str(e):
            print(f"[!] {repo_url} mati/timeout. Menambahkan ke Blacklist...")
            DEAD_REPOSITORIES.add(repo_url)
        else:
            print(f"[!] Error searching {repo_url}: {e}")
    
    return urls_found, texts_found

def detect_platform(repo_url):
    """Deteksi platform repository dari URL dan HTML"""
    try:
        res = requests.get(repo_url, timeout=5, verify=False)
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
    except:
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

def search_ubsi(repo_url, query, max_results=5):
    """
    Search UBSI custom platform (repository.bsi.ac.id, repository.nusamandiri.ac.id).
    Endpoint: /repo/cari?q=QUERY. Hasil berupa link /repo/{id}/{slug}.
    Halaman detail memuat metadata + link PDF download.
    """
    urls_found = []
    texts_found = []
    hdr = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    # Perpendek query agar tidak terlalu spesifik (phrase match ketat = 0 hasil)
    short_q = " ".join(query.split()[:6])
    search_url = f"{repo_url}/repo/cari"
    try:
        res = requests.get(search_url, params={"q": short_q}, timeout=15, verify=False, headers=hdr)
    except Exception:
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
            dr = requests.get(full, timeout=10, verify=False, headers=hdr)
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
                    try:
                        import fitz
                        pr = requests.get(pdf_url, timeout=20, verify=False, headers=hdr)
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

def search_eprints(repo_url, query, max_results=5):
    """Search EPrints repository (format: eprints.*.ac.id)"""
    urls_found = []
    texts_found = []
    
    # EPrints advanced search URL
    search_url = f"{repo_url}/cgi/search/simple"
    params = {
        "q": query,
        "_order": "bytitle",
        "t": "fulltext"
    }
    
    res = requests.get(search_url, params=params, timeout=10, verify=False)
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
                        
    return urls_found, texts_found

def search_dspace(repo_url, query, max_results=5):
    """Search DSpace repository (format: repository.*.ac.id)"""
    urls_found = []
    texts_found = []
    
    # DSpace simple search
    search_url = f"{repo_url}/simple-search"
    params = {
        "query": query,
        "sort_by": "score",
        "order": "desc"
    }
    
    res = requests.get(search_url, params=params, timeout=10, verify=False)
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
                        
    return urls_found, texts_found

def search_ojs(repo_url, query, max_results=5):
    """Search OJS (Open Journal Systems) - platform jurnal Indonesia"""
    urls_found = []
    texts_found = []
    
    # OJS search endpoint (varies by version)
    for pattern in OJS_SEARCH_PATTERNS:
        try:
            search_url = repo_url + pattern
            params = {"query": query}
            
            res = requests.get(search_url, params=params, timeout=10, verify=False)
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
                    
        except requests.exceptions.Timeout:
            raise # Lemparkan Timeout agar masuk blacklist
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
    
    print(f"[!] Searching {max_repos} Indonesian repositories...")
    
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
    
    print(f"[!] Found {len(all_urls)} results from Indonesian repositories")
    return all_urls, all_texts