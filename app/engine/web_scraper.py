import time
import random
import requests
import warnings
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from concurrent.futures import ThreadPoolExecutor

# Sembunyikan peringatan jika situs web yang di-scrape berupa XML/RSS
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

def fetch_semantic_scholar(probe):
    """Mencari paper di Semantic Scholar (Mencakup 200 Juta+ Makalah Akademik)"""
    urls_found = []
    texts_found = []
    try:
        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        short_probe = " ".join(probe.split()[:15])
        params = {
            "query": short_probe,
            "limit": 5,
            "fields": "title,abstract,url"
        }
        res = requests.get(url, params=params, timeout=10)
        if res.status_code == 200:
            data = res.json()
            for paper in data.get('data', []):
                p_url = paper.get('url') or f"https://semanticscholar.org/paper/{paper.get('paperId','')}"
                abstract = paper.get('abstract') or ""
                title = paper.get('title') or ""
                
                combined_text = f"{title}. {abstract}"
                if len(combined_text) > 50:
                    urls_found.append(p_url)
                    texts_found.append(combined_text)
        time.sleep(1) # Hormati rate-limit 100 per 5 menit
    except:
        pass
    return urls_found, texts_found

def fetch_crossref(probe):
    """Mencari metadata jurnal via Crossref (Repositori Terbesar DOI Jurnal)"""
    urls_found = []
    texts_found = []
    try:
        url = "https://api.crossref.org/works"
        short_probe = " ".join(probe.split()[:15])
        params = {
            "query": short_probe,
            "select": "URL,title,abstract",
            "rows": 15,
            "mailto": "research_turnitin_local@university.edu"
        }
        res = requests.get(url, params=params, timeout=6)
        if res.status_code == 200:
            data = res.json()
            for item in data.get('message', {}).get('items', []):
                p_url = item.get('URL', '')
                title_list = item.get('title', [])
                title = title_list[0] if title_list else ""
                abstract = item.get('abstract', '')
                
                # Bersihkan tag HTML dari abstrak (CrossRef sering mengirim XML/HTML tags)
                import re
                abstract = re.sub(r'<[^>]+>', '', abstract)
                
                combined_text = f"{title}. {abstract}"
                if p_url and len(combined_text) > 50:
                    urls_found.append(p_url)
                    texts_found.append(combined_text)
    except:
        pass
    return urls_found, texts_found

def fetch_ddgs(probe):
    """Mencari website publik biasa via DuckDuckGo, dengan Prioritas Situs Kampus/Jurnal"""
    urls_found = []
    try:
        from ddgs import DDGS
        ddgs = DDGS()
        short_probe = " ".join(probe.split()[:15])
        
        import random
        # Gunakan filter tambahan pada 50% probabilitas untuk memaksa mesin menemukan repositori kampus dan Garuda Ristekdikti
        if random.random() > 0.5:
            query = f'{short_probe} (jurnal OR repository OR skripsi OR site:garuda.kemdikbud.go.id)'
        else:
            query = f'{short_probe}'
            
        # Ambil 15 hasil teratas untuk disortir
        results = ddgs.text(query, max_results=15)
        
        priority_urls = []
        normal_urls = []
        
        for res in list(results):
            if 'href' in res:
                url = res['href'].lower()
                # Deteksi domain prioritas tinggi ala Turnitin (berdasarkan referensi PDF Asli)
                priority_keywords = [
                    '.ac.id', '.edu', 'jurnal', 'journal', 'ejurnal', 'repository', 
                    'repositori', 'repo.', 'eprints', 'etheses', 'dspace', '123dok', 
                    'core.ac.uk', 'scribd', 'slideshare', 'docplayer', 'doku.pub', 
                    'researchgate', 'digilib', 'scholar', 'doaj.org'
                ]
                if any(kw in url for kw in priority_keywords):
                    priority_urls.append(res['href'])
                else:
                    normal_urls.append(res['href'])
                    
        # Gabungkan: Ambil maksimal 5 situs akademik/prioritas, dan sisa slot diisi situs umum
        final_urls = priority_urls[:5]
        sisa_slot = 6 - len(final_urls)
        if sisa_slot > 0:
            final_urls.extend(normal_urls[:sisa_slot])
            
        urls_found.extend(final_urls)
        time.sleep(random.uniform(0.5, 1.5))
    except:
        pass
    return urls_found, []

def fetch_probe_multi(probe):
    """Mencari ke semua mesin secara serentak"""
    u_ss, t_ss = fetch_semantic_scholar(probe)
    u_cr, t_cr = fetch_crossref(probe)
    u_dd, _ = fetch_ddgs(probe)
    
    # Gabungkan URL yang sudah ada abstraknya
    api_urls = u_ss + u_cr
    api_texts = t_ss + t_cr
    
    return api_urls, api_texts, u_dd

def get_candidate_urls(sentences, max_probes=100, progress_cb=None):
    """
    Fungsi ini kini mengembalikan dua hal:
    1. urls (List URL web biasa untuk discrape manual)
    2. preloaded_corpus (Dict berisi teks abstrak/jurnal berbayar yang langsung didapat via API)
    """
    # Prioritaskan kalimat terpanjang karena lebih spesifik/unik (menghindari hasil generik)
    sentences_sorted = sorted(sentences, key=lambda s: len(s.split()), reverse=True)
    probes = sentences_sorted[:max_probes]
    urls = set()
    preloaded_corpus = {}
    
    print(f"[API] Meluncurkan Perplexity AI (Sonar) untuk 100 kalimat paling unik...")
    try:
        def fetch_pplx(probe):
            url_api = 'https://api.perplexity.ai/chat/completions'
            api_key = "pplx-" + "3VSlkCtWU9mFCb5CWFaf64FiPNwp36oFq7p0bUQ2Vf7X7hdh"
            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            }
            payload = {
                'model': 'sonar',
                'messages': [
                    {'role': 'system', 'content': 'Find the exact academic journal or repository source for this text. Return URLs in citations.'},
                    {'role': 'user', 'content': f'Find exact source for: {probe}'}
                ]
            }
            res = requests.post(url_api, json=payload, headers=headers, timeout=20)
            if res.status_code == 200:
                data = res.json()
                return data.get('citations', [])
            return []
            
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            for c_urls in executor.map(fetch_pplx, probes[:100]):
                for u in c_urls:
                    if u and u.startswith('http'):
                        urls.add(u)
    except Exception as e:
        print(f"[!] Perplexity API Error: {e}")

    print(f"[API] Mencari jurnal dari {len(probes)} sampel kalimat via Semantic Scholar, Crossref & DuckDuckGo...")
    
    # Kurangi worker jadi 8 agar DuckDuckGo tidak langsung memblokir, tapi tetap cukup cepat
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(fetch_probe_multi, p) for p in probes]
        total = len(futures)
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            try:
                api_urls, api_texts, ddg_urls = future.result()
                
                # Masukkan hasil API langsung ke Corpus (tanpa perlu web-scrape)
                for u, t in zip(api_urls, api_texts):
                    preloaded_corpus[u] = t
                    
                # Masukkan hasil DuckDuckGo ke antrian URL scraping
                for u in ddg_urls:
                    if u not in preloaded_corpus:
                        urls.add(u)
                        
            except Exception as e:
                pass
                
            if progress_cb:
                progress_cb(i + 1, total)
                
    print(f"[API] Berhasil menarik {len(preloaded_corpus)} abstrak jurnal dan {len(urls)} link web publik.")
    return list(urls), preloaded_corpus

def scrape_url(url):
    """Bot Crawler untuk meniru TurnitinBot (Mendukung HTML dan PDF)"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive'
        }
        res = requests.get(url, headers=headers, timeout=30, verify=False) # Naikkan timeout untuk HTML repositori lambat
        if res.status_code == 200:
            import re
            
            # Deteksi jika file adalah PDF (Banyak repositori kampus langsung mengembalikan file PDF)
            if 'application/pdf' in res.headers.get('Content-Type', '').lower() or url.lower().endswith('.pdf'):
                import fitz
                import io
                doc = fitz.open(stream=res.content, filetype="pdf")
                text = ""
                for page in doc:
                    text += page.get_text() + " "
                text = re.sub(r'\s+', ' ', text).strip()
                return url, text
            else:
                # Parsing HTML biasa (Landing Page Repositori)
                soup = BeautifulSoup(res.text, 'html.parser')
                
                # [DEEP PDF CRAWLER] Cari tombol Download PDF di halaman ini
                pdf_links = []
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    href_lower = href.lower()
                    # Deteksi link PDF dari EPrints, DSpace, OJS, dsb.
                    if href_lower.endswith('.pdf') or '/download/' in href_lower or '/bitstream/' in href_lower or '/article/view/' in href_lower:
                        if href.startswith('/'):
                            from urllib.parse import urljoin
                            href = urljoin(url, href)
                        if href not in pdf_links and href.startswith('http'):
                            pdf_links.append(href)
                
                pdf_text = ""
                if pdf_links:
                    import fitz
                    # Ambil maksimal 5 file PDF per halaman untuk efisiensi (Biasanya Bab 1-5 atau Full Text)
                    for pdf_url in pdf_links[:5]:
                        try:
                            # Repositori kampus di Indonesia seringkali sangat lambat (bisa butuh 30-60 detik untuk 1 file skripsi)
                            pdf_res = requests.get(pdf_url, headers=headers, timeout=60, verify=False)
                            # Verifikasi apakah benar-benar PDF (Magic number %PDF)
                            if 'application/pdf' in pdf_res.headers.get('Content-Type', '').lower() or pdf_res.content.startswith(b'%PDF'):
                                pdf_doc = fitz.open(stream=pdf_res.content, filetype="pdf")
                                for page in pdf_doc:
                                    pdf_text += page.get_text() + " "
                        except:
                            pass
                
                # Hapus tag yang tidak berisi konten ilmiah
                for script in soup(["script", "style", "nav", "footer", "header", "aside", "menu"]):
                    script.decompose()
                
                # Ekstrak teks HTML (abstrak) dan gabungkan dengan teks PDF (isi skripsi penuh)
                text = soup.get_text(separator=' ')
                text = text + " " + pdf_text
                text = re.sub(r'\s+', ' ', text).strip()
                return url, text
    except:
        pass
    return url, ""

def scrape_all_candidates(urls, preloaded_corpus, progress_cb=None):
    """Mengeksekusi multi-threading untuk mengunduh web, lalu digabung dengan preloaded_corpus (Jurnal API)"""
    corpus = preloaded_corpus.copy()
    if not urls:
        return corpus
        
    print(f"[Scraper] Bot Crawler mulai mengunduh {len(urls)} sumber web publik...")
    
    # Abaikan InsecureRequestWarning saat scrape blog/kampus yang SSL-nya mati
    from requests.packages.urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
    
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=40) as executor:
        futures = [executor.submit(scrape_url, u) for u in urls]
        total = len(futures)
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            try:
                url, text = future.result()
                if len(text) > 150: # Validasi panjang minimal teks
                    corpus[url] = text
            except:
                pass
            if progress_cb:
                progress_cb(i + 1, total)
                
    return corpus
