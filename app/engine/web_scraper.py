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
    except Exception as e:
        print(f"[!] Warning: API/Scraper error -> {e}")
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
    except Exception as e:
        print(f"[!] Warning: API/Scraper error -> {e}")
    return urls_found, texts_found

def fetch_openalex(probe):
    """Mencari metadata jurnal via OpenAlex (Repositori Terbesar Dunia - 250 Juta+ Dokumen)"""
    urls_found = []
    texts_found = []
    try:
        url = "https://api.openalex.org/works"
        short_probe = " ".join(probe.split()[:15])
        params = {
            "search": short_probe,
            "per_page": 5,
            "mailto": "research_turnitin_local@university.edu"
        }
        res = requests.get(url, params=params, timeout=6)
        if res.status_code == 200:
            data = res.json()
            for work in data.get("results", []):
                p_url = work.get('doi') or work.get('id')
                abstract = work.get('abstract_inverted_index')
                title = work.get('title') or ""
                if p_url:
                    urls_found.append(p_url)
                    abstract_text = ""
                    if abstract:
                        word_index = []
                        for word, positions in abstract.items():
                            for pos in positions:
                                word_index.append((pos, word))
                        word_index.sort(key=lambda x: x[0])
                        abstract_text = " ".join([w[1] for w in word_index])
                    
                    combined_text = title + " " + abstract_text
                    texts_found.append(combined_text.strip())
    except Exception as e:
        print(f"[!] OpenAlex API error: {e}")
    return urls_found, texts_found

def fetch_google_scholar(probe):
    """Mencari repositori jurnal dari Google Scholar via ScrapingBee Proxy (Bypass CAPTCHA)"""
    urls_found = []
    try:
        import urllib.parse
        short_probe = " ".join(probe.split()[:15])
        query = urllib.parse.quote(short_probe)
        target_url = f"https://scholar.google.com/scholar?q={query}"
        
        import os
        scrapingbee_key = os.environ.get("SCRAPINGBEE_KEY", "")
        if not scrapingbee_key: return [], []
        api_url = "https://app.scrapingbee.com/api/v1/"
        params = {
            "api_key": scrapingbee_key,
            "url": target_url,
            "render_js": "false",
            "premium_proxy": "true",
            "country_code": "id"
        }
        res = requests.get(api_url, params=params, timeout=15)
        if res.status_code == 200:
            html = res.text
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')
            for h3 in soup.find_all('h3', class_='gs_rt'):
                a_tag = h3.find('a')
                if a_tag and 'href' in a_tag.attrs:
                    urls_found.append(a_tag['href'])
    except Exception as e:
        print(f"[!] Warning: API/Scraper error -> {e}")
    return urls_found, []

def fetch_google_web(probe):
    """Mencari website publik & repositori dari Google Search biasa via ScrapingBee Proxy (Bypass CAPTCHA)"""
    urls_found = []
    try:
        import urllib.parse
        short_probe = " ".join(probe.split()[:15])
        
        import random
        rand_val = random.random()
        if rand_val < 0.33:
            query = urllib.parse.quote(f'{short_probe} site:ac.id')
        elif rand_val < 0.66:
            query = urllib.parse.quote(f'{short_probe} filetype:pdf')
        else:
            query = urllib.parse.quote(short_probe)
            
        target_url = f"https://www.google.com/search?q={query}"
        
        import os
        scrapingbee_key = os.environ.get("SCRAPINGBEE_KEY", "")
        if not scrapingbee_key: return [], []
        api_url = "https://app.scrapingbee.com/api/v1/"
        params = {
            "api_key": scrapingbee_key,
            "url": target_url,
            "render_js": "false",
            "premium_proxy": "true",
            "country_code": "id"
        }
        res = requests.get(api_url, params=params, timeout=15)
        if res.status_code == 200:
            html = res.text
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')
            # Ekstrak SEMUA link karena struktur Google berubah-ubah
            for a_tag in soup.find_all('a'):
                if 'href' in a_tag.attrs:
                    link = a_tag['href']
                    # Filter link valid (hindari link internal Google seperti accounts.google.com, dll)
                    if link.startswith('http') and 'google.com' not in link and 'google.co.id' not in link:
                        urls_found.append(link)
    except Exception as e:
        print(f"[!] Warning: API/Scraper error -> {e}")
    return urls_found, []

def fetch_garuda(probe):
    """Mencari Portal Jurnal Nasional (Garuda Kemdikbud/SINTA) via ScraperAPI Proxy"""
    urls_found = []
    try:
        import urllib.parse
        short_probe = " ".join(probe.split()[:15])
        query = urllib.parse.quote(short_probe)
        target_url = f"https://garuda.kemdikbud.go.id/documents?q={query}"
        
        import os
        scraperapi_key = os.environ.get("SCRAPERAPI_KEY", "")
        if not scraperapi_key: return [], []
        api_url = "https://api.scraperapi.com/"
        params = {
            "api_key": scraperapi_key,
            "url": target_url,
            "render": "false"
        }
        res = requests.get(api_url, params=params, timeout=15)
        if res.status_code == 200:
            html = res.text
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')
            for a_tag in soup.select('a.title-article'):
                if 'href' in a_tag.attrs:
                    url = a_tag['href']
                    if not url.startswith('http'):
                        url = "https://garuda.kemdikbud.go.id" + url
                    urls_found.append(url)
    except Exception as e:
        print(f"[!] Warning: API/Scraper error -> {e}")
    return urls_found, []

def fetch_ddgs(probe):
    """Mencari website publik biasa via DuckDuckGo, dengan Prioritas Situs Kampus/Jurnal"""
    urls_found = []
    try:
        from duckduckgo_search import DDGS
        ddgs = DDGS()
        
        # FUZZY SEARCH KEMBALI!
        # Ekstraksi PDF sangat rawan typo (spasi hilang, dsb). Exact match mutlak sering berujung 0 hasil.
        # Kita gunakan Fuzzy Search di Search Engine, dan Exact Match di N-Gram Lokal!
        short_probe = " ".join(probe.split()[:15])
        
        import random
        # 4 Variasi Dorking DuckDuckGo dengan Prioritas BSI
        rand_val = random.random()
        if rand_val < 0.25:
            # PRIORITAS TERTINGGI: Repository BSI dan kampus Indonesia
            query = f'{short_probe} (site:repository.bsi.ac.id OR site:ejurnal.seminar-id.com OR site:repository.umsu.ac.id OR site:etheses.uin-malang.ac.id)'
        elif rand_val < 0.50:
            query = f'{short_probe} (jurnal OR repository OR skripsi OR site:garuda.kemdikbud.go.id)'
        elif rand_val < 0.75:
            query = f'{short_probe} site:ac.id'
        else:
            query = short_probe
            
        # Ambil 20 hasil teratas untuk disortir dengan prioritas
        results = ddgs.text(query, max_results=20)
        
        # SISTEM PRIORITAS BERTINGKAT (semakin tinggi semakin prioritas)
        tier1_urls = []  # BSI dan kampus prioritas
        tier2_urls = []  # Repositori dan jurnal akademik Indonesia
        tier3_urls = []  # Situs akademik umum
        normal_urls = []  # Situs non-akademik
        
        for res in list(results):
            if 'href' in res:
                url = res['href'].lower()
                
                # TIER 1: Repository BSI dan kampus prioritas Indonesia
                tier1_keywords = [
                    'repository.bsi.ac.id', 'ejurnal.seminar-id.com', 
                    'repository.umsu.ac.id', 'etheses.uin-malang.ac.id',
                    'ejournal.itn.ac.id', 'eprints.undip.ac.id',
                    'repository.uinjkt.ac.id', 'eprints.uns.ac.id'
                ]
                if any(kw in url for kw in tier1_keywords):
                    tier1_urls.append(res['href'])
                    continue
                
                # TIER 2: Repositori dan jurnal akademik Indonesia
                tier2_keywords = [
                    'repository', 'repositori', 'eprints', 'etheses', 
                    'digilib', 'ejurnal', 'jurnal', 'dspace',
                    'garuda.kemdikbud.go.id', 'sinta.kemdikbud.go.id'
                ]
                if any(kw in url for kw in tier2_keywords) and '.ac.id' in url:
                    tier2_urls.append(res['href'])
                    continue
                
                # TIER 3: Situs akademik umum
                tier3_keywords = [
                    '.ac.id', '.edu', 'scholar', 'researchgate', 
                    'core.ac.uk', 'doaj.org', '123dok', 'scribd'
                ]
                if any(kw in url for kw in tier3_keywords):
                    tier3_urls.append(res['href'])
                else:
                    normal_urls.append(res['href'])
        
        # Gabungkan dengan prioritas: Tier1 (max 4) -> Tier2 (max 3) -> Tier3 (max 2) -> Normal (sisa)
        final_urls = tier1_urls[:4]
        remaining = 10 - len(final_urls)
        
        if remaining > 0:
            final_urls.extend(tier2_urls[:min(3, remaining)])
            remaining = 10 - len(final_urls)
        
        if remaining > 0:
            final_urls.extend(tier3_urls[:min(2, remaining)])
            remaining = 10 - len(final_urls)
        
        if remaining > 0:
            final_urls.extend(normal_urls[:remaining])
            
        urls_found.extend(final_urls)
        time.sleep(random.uniform(0.5, 1.5))
    except Exception as e:
        print(f"[!] Warning: API/Scraper error -> {e}")
    return urls_found, []

def fetch_probe_multi(probe):
    """Mencari ke semua mesin secara serentak dengan free API fallbacks"""
    
    # 1. Try academic APIs first (free, unlimited)
    u_ss, t_ss = fetch_semantic_scholar(probe)
    u_cr, t_cr = fetch_crossref(probe)
    u_oa, t_oa = fetch_openalex(probe)
    
    # 2. Try paid APIs (may fail if credit exhausted)
    u_gs, _ = fetch_google_scholar(probe)
    u_gw, _ = fetch_google_web(probe)
    u_gr, _ = fetch_garuda(probe)
    
    # 3. Try DuckDuckGo (free, unlimited)
    u_dd, _ = fetch_ddgs(probe)
    
    # 4. NEW: Direct search Indonesian repositories (no API limits!)
    u_repo, t_repo = [], []
    try:
        from .indonesian_repos import search_all_indonesian_repos
        u_repo, t_repo = search_all_indonesian_repos(probe, max_repos=5, results_per_repo=2)
        print(f"[INDO REPOS] Found {len(u_repo)} URLs from Indonesian repositories")
    except Exception as e:
        print(f"[!] Indonesian repos module error: {e}")
    
    # 5. NEW: Free API fallbacks with caching (jika paid APIs gagal)
    u_fallback, t_fallback = [], []
    try:
        from .free_api_fallbacks import search_with_fallbacks
        u_fallback, t_fallback = search_with_fallbacks(probe, use_cache=True)
        print(f"[FREE APIs] Found {len(u_fallback)} URLs from free API fallbacks")
    except Exception as e:
        print(f"[!] Free API fallbacks error: {e}")
    
    # Gabungkan URL yang sudah ada abstraknya menjadi dictionary
    preloaded = {}
    for u, t in zip(u_ss, t_ss): preloaded[u] = t
    for u, t in zip(u_cr, t_cr): preloaded[u] = t
    for u, t in zip(u_repo, t_repo): preloaded[u] = t
    
    # OpenAlex dan Fallback CSE sering punya snippet/teks yang layak
    normal_urls = u_gs + u_gw + u_gr + u_dd
    
    for u, t in zip(u_oa, t_oa):
        if t and len(t) > 50:
            preloaded[u] = t
        else:
            normal_urls.append(u)
            
    for u, t in zip(u_fallback, t_fallback):
        if t and len(t) > 50:
            preloaded[u] = t
        else:
            normal_urls.append(u)
    
    return preloaded, normal_urls

def get_candidate_urls(sentences, max_probes=50, progress_cb=None):
    """
    Fungsi ini kini mengembalikan dua hal:
    1. urls (List URL web biasa untuk discrape manual)
    2. preloaded_corpus (Dict berisi teks abstrak/jurnal berbayar yang langsung didapat via API)
    """
    # Hibrida Algoritma: 
    # 1. Separuh Fingerprint dari kalimat terpanjang (Mencegah pencarian gagal karena kalimat umum)
    # 2. Separuh Fingerprint Uniform Sampling (Memastikan Bab 1 s/d Bab 5 tersisir rata layaknya Turnitin)
    valid_sentences = [s for s in sentences if len(s.split()) >= 8]
    if len(valid_sentences) <= max_probes:
        probes = valid_sentences
    else:
        # Ambil 50% Terpanjang
        half = max_probes // 2
        longest = sorted(valid_sentences, key=lambda s: len(s.split()), reverse=True)[:half]
        
        # Ambil sisanya secara merata, JANGAN sertakan yang sudah masuk di 'longest'
        remaining_needed = max_probes - len(longest)
        uniform_candidates = [s for s in valid_sentences if s not in longest]
        
        if remaining_needed > 0 and uniform_candidates:
            step = len(uniform_candidates) / remaining_needed
            uniform = [uniform_candidates[int(i * step)] for i in range(remaining_needed)]
        else:
            uniform = []
            
        # Gabungkan tanpa takut duplikat
        probes = (longest + uniform)[:max_probes]
        
    urls = set()
    preloaded_corpus = {}
    
    print(f"[API] Meluncurkan Bot AI & Browser Crawler untuk {len(probes)} Fingerprints...")
    
    try:
        def fetch_pplx(args):
            idx, probe = args
            combined_urls = set()
            
            # 1. PERPLEXITY AI
            try:
                url_api = 'https://api.perplexity.ai/chat/completions'
                import os
                api_key = os.environ.get("PERPLEXITY_KEY", "")
                if not api_key: raise Exception("No PERPLEXITY_KEY")
                headers = {
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json'
                }
                payload = {
                    'model': 'sonar',
                    'messages': [
                        {'role': 'system', 'content': 'Find the exact academic journal or repository source for this text. Return URLs in citations.'},
                        {'role': 'user', 'content': f'Find exact source for: {probe}. Prioritize repository.bsi.ac.id, ejurnal.seminar-id.com, repository.umsu.ac.id, etheses.uin-malang.ac.id, ejournal.itn.ac.id, and PDF files.'}
                    ]
                }
                res = requests.post(url_api, json=payload, headers=headers, timeout=20)
                if res.status_code == 200:
                    data = res.json()
                    for u in data.get('citations', []):
                        combined_urls.add(u)
            except Exception as e:
                print(f"[!] Perplexity API Error: {e}")
                
            # 2. GEMINI AI GROUNDING (Sistem Load Balancer - 15 RPM per Key)
            try:
                import os
                gemini_env = os.environ.get("GEMINI_KEYS", "")
                if not gemini_env: raise Exception("No GEMINI_KEYS")
                gemini_keys = gemini_env.split(',')
                
                # Hanya jalankan jika kita punya cukup kapasitas key untuk index ini
                if idx < (len(gemini_keys) * 15):
                    # Gunakan distribusi ROUND-ROBIN agar 3 thread paralel selalu menggunakan Key yang berbeda
                    # Ini mencegah 1 Key dibombardir oleh 3 request di detik yang sama (mencegah error 429)
                    key_index = idx % len(gemini_keys)
                    from google import genai
                    from google.genai import types
                    
                    client = genai.Client(api_key=gemini_keys[key_index])
                    response = client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=f'Find the exact URL source for this text: {probe}. Prioritize repository.bsi.ac.id, ejurnal.seminar-id.com, repository.umsu.ac.id, etheses.uin-malang.ac.id, ejournal.itn.ac.id, or site:ac.id',
                        config=types.GenerateContentConfig(
                            tools=[{'google_search': {}}],
                            temperature=0.0
                        )
                    )
                    if response.candidates:
                        for cand in response.candidates:
                            if cand.grounding_metadata and cand.grounding_metadata.grounding_chunks:
                                for chunk in cand.grounding_metadata.grounding_chunks:
                                    if chunk.web and chunk.web.uri:
                                        combined_urls.add(chunk.web.uri)
            except Exception as e:
                print(f"[!] Gemini API Error: {e}")
                
            # 3. COHERE AI GROUNDING
            try:
                import os
                cohere_key = os.environ.get("COHERE_KEY", "")
                if not cohere_key: raise Exception("No COHERE_KEY")
                cohere_url = "https://api.cohere.ai/v1/chat"
                headers = {
                    "Authorization": f"Bearer {cohere_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "message": f'Find the exact URL source for: "{probe}". Focus on repository.bsi.ac.id, ejurnal.seminar-id.com, repository.umsu.ac.id, etheses.uin-malang.ac.id, ejournal.itn.ac.id',
                    "model": "command-r-plus",
                    "connectors": [{"id": "web-search"}],
                    "temperature": 0.0
                }
                res = requests.post(cohere_url, json=payload, headers=headers, timeout=20)
                if res.status_code == 200:
                    data = res.json()
                    if 'documents' in data:
                        for doc in data['documents']:
                            if 'url' in doc:
                                combined_urls.add(doc['url'])
            except Exception as e:
                print(f"[!] Cohere API Error: {e}")
                
            # 4. TAVILY AI SEARCH
            try:
                import os
                tavily_key = os.environ.get("TAVILY_KEY", "")
                if not tavily_key: raise Exception("No TAVILY_KEY")
                tavily_url = "https://api.tavily.com/search"
                payload = {
                    "api_key": tavily_key,
                    "query": f'"{probe}" site:ac.id OR ext:pdf',
                    "search_depth": "basic",
                    "max_results": 5
                }
                res = requests.post(tavily_url, json=payload, timeout=20)
                if res.status_code == 200:
                    data = res.json()
                    if 'results' in data:
                        for result in data['results']:
                            if 'url' in result:
                                combined_urls.add(result['url'])
            except Exception as e:
                print(f"[!] Tavily API Error: {e}")
                
            return list(combined_urls)
            
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures_pplx = {executor.submit(fetch_pplx, (i, p)): i for i, p in enumerate(probes)}
            for i, future in enumerate(concurrent.futures.as_completed(futures_pplx)):
                if progress_cb:
                    progress_cb(futures_pplx[future] + 1, len(probes) + len(probes))
                try:
                    c_urls = future.result()
                    for u in c_urls:
                        if u and u.startswith('http'):
                            urls.add(u)
                except Exception:
                    pass
    except Exception as e:
        print(f"[!] Perplexity API Error: {e}")

    print(f"[API] Mencari jurnal dari {len(probes)} sampel kalimat via Semantic Scholar, Crossref & DuckDuckGo...")
    
    # Gunakan max_workers=5 agar ScrapingBee dan ScraperAPI tidak menolak request karena melanggar batas concurrency Free Tier
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(fetch_probe_multi, p) for p in probes]
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            if progress_cb:
                # Tambahkan offset progres dari Perplexity (100 kalimat)
                progress_cb(min(100, len(probes)) + i + 1, min(100, len(probes)) + len(probes))
            try:
                preloaded, ddg_urls = future.result()
                
                # Masukkan hasil API langsung ke Corpus (tanpa perlu web-scrape)
                for u, t in preloaded.items():
                    preloaded_corpus[u] = t
                    
                # Masukkan hasil DuckDuckGo ke antrian URL scraping
                for u in ddg_urls:
                    if u not in preloaded_corpus:
                        urls.add(u)
                        
            except Exception as e:
                print(f"[!] Peringatan di get_candidate_urls worker: {e}")
                
    print(f"[API] Berhasil menarik {len(preloaded_corpus)} abstrak jurnal dan {len(urls)} link web publik.")
    return list(urls), preloaded_corpus

def scrape_url(url):
    """Mengekstrak teks mentah dari URL (Website atau PDF) menggunakan AbstractAPI Proxy untuk menembus WAF/Cloudflare"""
    total_bytes = 0
    try:
        import urllib.parse
        import os
        encoded_url = urllib.parse.quote(url)
        abstract_key = os.environ.get("ABSTRACT_KEY", "")
        if abstract_key:
            proxy_url = f"https://scrape.abstractapi.com/v1/?api_key={abstract_key}&url={encoded_url}"
            
            # Naikkan timeout agar proses scrape web lambat (misal repositori kampus) tidak langsung gagal,
            # tapi cukup agresif (15 detik) untuk mencegah sistem tersedak.
            res = requests.get(proxy_url, timeout=15)
            
            # FALLBACK: Jika API Proxy habis limit (429) atau gagal (401), coba unduh langsung tanpa proxy!
            if res.status_code != 200:
                res = requests.get(url, timeout=15, verify=False)
        else:
            res = requests.get(url, timeout=15, verify=False)
            
        if res.status_code == 200:
            total_bytes += len(res.content)
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
                return url, text, total_bytes
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
                    # Ambil MAKSIMAL 3 file PDF per halaman untuk mencegah server tersedak (Hanging Process)
                    for pdf_url in pdf_links[:3]:
                        try:
                            # Gunakan AbstractAPI lagi untuk mendownload PDF jika dilindungi Cloudflare
                            encoded_pdf = urllib.parse.quote(pdf_url)
                            proxy_pdf = f"https://scrape.abstractapi.com/v1/?api_key={abstract_key}&url={encoded_pdf}"
                            
                            # Timeout sangat ketat (10 detik) untuk PDF. Jika server terlalu lemot, lewati!
                            pdf_res = requests.get(proxy_pdf, timeout=10)
                            
                            if pdf_res.status_code != 200:
                                pdf_res = requests.get(pdf_url, timeout=10, verify=False)
                                
                            if pdf_res.status_code == 200:
                                total_bytes += len(pdf_res.content)
                            
                            # Verifikasi apakah benar-benar PDF (Magic number %PDF)
                            if 'application/pdf' in pdf_res.headers.get('Content-Type', '').lower() or pdf_res.content.startswith(b'%PDF'):
                                pdf_doc = fitz.open(stream=pdf_res.content, filetype="pdf")
                                # Hanya baca 5 halaman awal per PDF (Mencegah mesin nyangkut di PDF 300 halaman)
                                for page_num, page in enumerate(pdf_doc):
                                    if page_num >= 5: break
                                    pdf_text += page.get_text() + " "
                        except Exception as e:
                            print(f"[!] Warning: API/Scraper error -> {e}")
                
                # Hapus tag yang tidak berisi konten ilmiah
                for script in soup(["script", "style", "nav", "footer", "header", "aside", "menu"]):
                    script.decompose()
                
                # Ekstrak teks HTML (abstrak) dan gabungkan dengan teks PDF (isi skripsi penuh)
                text = soup.get_text(separator=' ')
                text = text + " " + pdf_text
                text = re.sub(r'\s+', ' ', text).strip()
                return url, text, total_bytes
    except Exception as e:
        print(f"[!] Warning: API/Scraper error -> {e}")
    return url, "", total_bytes

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
    import time
    start_time = time.time()
    total_downloaded_bytes = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=40) as executor:
        futures = [executor.submit(scrape_url, u) for u in urls]
        total = len(futures)
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            try:
                url, text, downloaded_bytes = future.result()
                total_downloaded_bytes += downloaded_bytes
                if len(text) > 150: # Validasi panjang minimal teks
                    corpus[url] = text
            except Exception as e:
                print(f"[!] Warning: API/Scraper error -> {e}")
            
            if progress_cb:
                elapsed = time.time() - start_time
                speed_mbps = (total_downloaded_bytes / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                if speed_mbps < 1.0:
                    speed_kbps = (total_downloaded_bytes / 1024) / elapsed if elapsed > 0 else 0
                    speed_str = f"{speed_kbps:.1f} KB/s"
                else:
                    speed_str = f"{speed_mbps:.2f} MB/s"
                progress_cb(i + 1, total, speed_str)
                
    return corpus
