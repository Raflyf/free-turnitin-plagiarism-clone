import os
import time
import random
import requests
import warnings
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor

# Sembunyikan peringatan jika situs web yang di-scrape berupa XML/RSS
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# --- Bank Korpus Lokal (mirip database Turnitin) ---
import json as _json

import threading as _threading

_BANK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "corpus_bank", "bank.json")
_bank_cache = None
_bank_lock = _threading.Lock()  # lindungi mutasi cache + tulis file dari race antar-thread

def load_corpus_bank():
    """Load bank korpus lokal (cache in-memory setelah load pertama).

    Bila bank.json korup (mis. terputus saat proses lain crash saat menulis), JANGAN
    membuat seluruh pengecekan gagal: beri peringatan dan perlakukan bank sebagai kosong."""
    global _bank_cache
    if _bank_cache is not None:
        return _bank_cache
    if os.path.exists(_BANK_PATH):
        try:
            with open(_BANK_PATH, "r", encoding="utf-8") as f:
                _bank_cache = _json.load(f)
            print(f"[Bank] Loaded {len(_bank_cache)} sumber dari bank lokal")
        except (ValueError, OSError) as e:
            print(f"[Bank] PERINGATAN: gagal membaca bank ({e}); memakai bank kosong")
            _bank_cache = {}
    else:
        _bank_cache = {}
    return _bank_cache

def save_to_corpus_bank(new_corpus):
    """Tambahkan sumber baru ke bank (append-only, tidak menghapus yang sudah ada).

    Penulisan ATOMIK: tulis ke file sementara lalu os.replace, agar bank.json tak pernah
    setengah-tertulis walau proses mati di tengah jalan. Dijaga lock agar aman multi-thread."""
    global _bank_cache
    with _bank_lock:
        current = load_corpus_bank()
        # Bangun kandidat di dict TERPISAH; cache in-memory (_bank_cache) baru di-commit
        # SETELAH tulis disk sukses. Kalau tidak, kegagalan tulis meninggalkan sumber di
        # memori tapi tak pernah di disk -> panggilan berikut menganggapnya sudah ada
        # (added=0) sehingga tak pernah ditulis ulang (kehilangan data diam-diam).
        merged = dict(current)
        added = 0
        for url, text in new_corpus.items():
            if url not in merged and len(text) > 150:
                merged[url] = text
                added += 1
        if added > 0:
            os.makedirs(os.path.dirname(_BANK_PATH), exist_ok=True)
            tmp_path = _BANK_PATH + ".tmp"
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    _json.dump(merged, f, ensure_ascii=False)
                os.replace(tmp_path, _BANK_PATH)  # atomic pada satu filesystem
            except OSError as e:
                print(f"[Bank] PERINGATAN: gagal menyimpan bank ({e}); cache in-memory tak diubah, akan dicoba lagi")
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                return
            _bank_cache = merged  # commit ke cache HANYA setelah disk sukses
            print(f"[Bank] +{added} sumber baru disimpan (total: {len(merged)})")

# --- Rotasi API Key (round-robin) untuk backup & mengurangi rate-limit 429 ---
import itertools, threading

def _load_keys(*env_names):
    """Kumpulkan key dari beberapa env var (comma-separated), buang duplikat & kosong."""
    seen, keys = set(), []
    for name in env_names:
        for k in os.environ.get(name, "").split(","):
            k = k.strip()
            if k and k not in seen:
                seen.add(k)
                keys.append(k)
    return keys

_s2_lock = threading.Lock()
_s2_cycle = None

def _next_s2_key():
    """Ambil S2 key berikutnya secara round-robin (thread-safe). None bila tak ada key."""
    global _s2_cycle
    with _s2_lock:
        if _s2_cycle is None:
            keys = _load_keys("S2_API_KEYS", "S2_API_KEY")
            _s2_cycle = itertools.cycle(keys) if keys else itertools.cycle([None])
        return next(_s2_cycle)

_cohere_lock = threading.Lock()
_cohere_cycle = None

def _next_cohere_key():
    """Ambil Cohere key berikutnya secara round-robin (thread-safe). None bila tak ada key."""
    global _cohere_cycle
    with _cohere_lock:
        if _cohere_cycle is None:
            keys = _load_keys("COHERE_KEYS", "COHERE_KEY")
            _cohere_cycle = itertools.cycle(keys) if keys else itertools.cycle([None])
        return next(_cohere_cycle)

def cohere_expand_queries(probe, n=3):
    """Pakai Cohere chat (command-a) sebagai query-expander: hasilkan variasi frasa
    pencarian akademik Indonesia untuk 1 probe. Connector web-search Cohere sudah
    dihapus (15 Sep 2025), jadi Cohere TIDAK dipakai mencari URL langsung; variasi
    ini diumpankan ke DuckDuckGo yang masih berfungsi. Return list frasa (bisa kosong)."""
    key = _next_cohere_key()
    if not key:
        return []
    try:
        prompt = (
            "Anda membantu mendeteksi plagiarisme skripsi Bahasa Indonesia. "
            f"Buat {n} variasi frasa pencarian singkat (5-8 kata) untuk menemukan sumber "
            "jurnal/skripsi yang mungkin menjadi asal kalimat berikut. Jawab HANYA daftar "
            "frasa, satu per baris, tanpa nomor atau penjelasan.\n\n"
            f"Kalimat: {probe}"
        )
        res = requests.post(
            "https://api.cohere.ai/v2/chat",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "command-a-03-2025",
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.3},
            timeout=20,
        )
        if res.status_code != 200:
            return []
        data = res.json()
        # v2 chat: message.content adalah list blok {type:'text', text:...}
        text = ""
        for block in data.get("message", {}).get("content", []):
            if block.get("type") == "text":
                text += block.get("text", "")
        lines = [ln.strip(" -*0123456789.\t") for ln in text.splitlines()]
        return [ln for ln in lines if len(ln.split()) >= 3][:n]
    except Exception:
        return []

# Budget global: jumlah probe yang boleh menyisir repo Indonesia (lambat karena throttling
# server kampus). Di-reset tiap run di get_candidate_urls(). Melindungi dari 75x hit.
# Lock: decrement dijalankan oleh banyak worker paralel -> tanpa lock, read-modify-write
# bisa balapan (jumlah crawl non-deterministik). Lock membuat konsumsi budget deterministik.
_INDO_REPO_BUDGET = 15
_INDO_REPO_LOCK = threading.Lock()

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
            "fields": "title,abstract,url,openAccessPdf"
        }
        s2_key = _next_s2_key()
        s2_headers = {"x-api-key": s2_key} if s2_key else {}
        res = requests.get(url, params=params, headers=s2_headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            for paper in data.get('data', []):
                p_url = paper.get('url') or f"https://semanticscholar.org/paper/{paper.get('paperId','')}"
                abstract = paper.get('abstract') or ""
                title = paper.get('title') or ""

                # Prioritaskan URL PDF langsung (full-text, bukan abstrak)
                oa_pdf = paper.get('openAccessPdf')
                if oa_pdf and oa_pdf.get('url'):
                    p_url = oa_pdf['url']

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
    """Mencari full-text jurnal Indonesia via OpenAlex (250M+ Dokumen).
    Upgrade v3.3: pakai filter fulltext.search + language:id + is_oa:true
    untuk mendapat URL PDF langsung (bukan hanya abstrak metadata)."""
    urls_found = []
    texts_found = []
    try:
        short_probe = " ".join(probe.split()[:10])
        params = {
            "filter": f"language:id,open_access.is_oa:true,fulltext.search:{short_probe}",
            "per_page": 10,
            "select": "id,title,open_access,primary_location,abstract_inverted_index",
            "mailto": "research_turnitin_local@university.edu"
        }
        res = requests.get("https://api.openalex.org/works", params=params, timeout=10)
        if res.status_code == 200:
            data = res.json()
            for work in data.get("results", []):
                title = work.get('title') or ""
                loc = work.get('primary_location') or {}
                pdf_url = (work.get('open_access') or {}).get('oa_url') or \
                          (loc.get('pdf_url')) or \
                          (loc.get('landing_page_url'))
                if not pdf_url:
                    continue
                urls_found.append(pdf_url)
                abstract = work.get('abstract_inverted_index')
                abstract_text = ""
                if abstract:
                    word_index = []
                    for word, positions in abstract.items():
                        for pos in positions:
                            word_index.append((pos, word))
                    word_index.sort(key=lambda x: x[0])
                    abstract_text = " ".join([w[1] for w in word_index])
                texts_found.append((title + " " + abstract_text).strip())
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
        
        import hashlib
        # Potong jadi 8 kata saja. 15 kata terlalu spesifik untuk search engine dan berujung 0 hasil
        short_probe = " ".join(probe.split()[:8])
        # DETERMINISME: varian query dari hash stabil probe (bukan random tanpa seed).
        variant = int(hashlib.md5(short_probe.encode("utf-8")).hexdigest(), 16) % 3
        if variant == 0:
            query = urllib.parse.quote(f'{short_probe} site:ac.id')
        elif variant == 1:
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
        # Potong jadi 8 kata saja. 15 kata terlalu spesifik
        short_probe = " ".join(probe.split()[:8])
        query = urllib.parse.quote(short_probe)
        # Domain lama garuda.kemdikbud.go.id MATI (ConnectionError) sejak migrasi
        # Kemdikbud -> Kemdiktisaintek. Domain baru garuda.kemdiktisaintek.go.id hidup
        # (HTTP 200), selector a.title-article & path /documents tetap sama.
        target_url = f"https://garuda.kemdiktisaintek.go.id/documents?q={query}"
        
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
                        url = "https://garuda.kemdiktisaintek.go.id" + url
                    urls_found.append(url)
    except Exception as e:
        print(f"[!] Warning: API/Scraper error -> {e}")
    return urls_found, []

def fetch_ddgs(probe):
    """Mencari website publik biasa via DuckDuckGo, dengan Prioritas Situs Kampus/Jurnal"""
    urls_found = []
    try:
        # Library duckduckgo_search lama (<=8.x) sudah mati (return 0). Utamakan paket
        # baru `ddgs`; fallback ke nama lama hanya bila paket baru tidak terpasang.
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        ddgs = DDGS()

        # FUZZY SEARCH KEMBALI!
        # Ekstraksi PDF sangat rawan typo (spasi hilang, dsb). Exact match mutlak sering berujung 0 hasil.
        # Kita gunakan Fuzzy Search di Search Engine dengan potongan 8 kata (standar Turnitin), bukan 15 kata!
        short_probe = " ".join(probe.split()[:8])

        import random, hashlib
        # DETERMINISME: pilih varian query berdasarkan hash STABIL probe. Python hash()
        # bawaan di-randomisasi per-proses (PYTHONHASHSEED) sehingga TIDAK reproducible
        # antar run; hashlib.md5 stabil. Probe sama -> varian sama -> korpus reproducible.
        # Ini syarat agar skor bisa dikalibrasi & dipertanggungjawabkan.
        variant = int(hashlib.md5(short_probe.encode("utf-8")).hexdigest(), 16) % 4
        if variant == 0:
            # PRIORITAS TERTINGGI: repositori indeks-besar (paling mungkin full-text)
            query = f'{short_probe} (site:123dok.com OR site:repository.bsi.ac.id OR site:etheses.uin-malang.ac.id OR site:doku.pub)'
        elif variant == 1:
            query = f'{short_probe} (jurnal OR repository OR skripsi OR eprints)'
        elif variant == 2:
            query = f'{short_probe} site:ac.id'
        else:
            query = short_probe

        # Ambil 25 hasil teratas untuk disortir dengan prioritas domain.
        # Backend 'auto' sering rotasi ke endpoint html.duckduckgo.com yang cert-nya
        # mismatch saat rate-limited (SSL CERTIFICATE_VERIFY_FAILED) -> 0 hasil & recall
        # hilang. Pin ke 'lite' (paling stabil), fallback berurutan bila kosong/gagal.
        results = []
        for backend in ("lite", "html", "auto"):
            try:
                results = ddgs.text(query, max_results=25, backend=backend)
                if results:
                    break
            except Exception:
                continue

        # SISTEM PRIORITAS via priority_domains.domain_priority (repositori akademik
        # Indonesia diutamakan). Skor tetap dari overlap nyata; ini hanya urutan crawl.
        try:
            from .priority_domains import domain_priority
        except ImportError:
            from priority_domains import domain_priority

        scored = []
        for res in list(results):
            if 'href' in res and res['href'].startswith('http'):
                scored.append((domain_priority(res['href']), res['href']))

        # Urutkan prioritas tertinggi dulu; ambil 12 teratas (naik dari 10 demi recall).
        scored.sort(key=lambda x: x[0], reverse=True)
        urls_found.extend([u for _, u in scored[:12]])
        time.sleep(random.uniform(0.5, 1.5))
    except Exception as e:
        print(f"[!] Warning: API/Scraper error -> {e}")
    return urls_found, []

def fetch_doaj(probe):
    """Mencari artikel open-access di DOAJ (Directory of Open Access Journals — 9M+ articles)"""
    urls_found = []
    texts_found = []
    try:
        # DOAJ path-search bersifat phrase-match ketat. Probe panjang -> 0 hasil.
        # Gunakan query pendek (6 kata) agar mendapat kandidat, lalu turunkan bila kosong.
        words = probe.split()
        for n_words in (6, 4):
            short_probe = " ".join(words[:n_words])
            url = "https://doaj.org/api/search/articles/" + requests.utils.quote(short_probe)
            res = requests.get(url, params={"pageSize": 5}, timeout=8)
            if res.status_code != 200:
                continue
            data = res.json()
            results = data.get('results', [])
            if not results:
                continue
            for item in results:
                bibjson = item.get('bibjson', {})
                title = bibjson.get('title', '')
                abstract = bibjson.get('abstract', '')
                links = bibjson.get('link', [])
                p_url = ''
                for lnk in links:
                    if lnk.get('type') == 'fulltext':
                        p_url = lnk.get('url', '')
                        break
                if not p_url:
                    for ident in bibjson.get('identifier', []):
                        if ident.get('type') == 'doi':
                            p_url = f"https://doi.org/{ident.get('id', '')}"
                            break
                combined = f"{title}. {abstract}"
                if p_url and len(combined) > 50:
                    urls_found.append(p_url)
                    texts_found.append(combined)
            if urls_found:
                break
    except Exception as e:
        # DOAJ sering lambat/timeout & dipanggil per-probe -> cetak sekali per proses saja.
        if not getattr(fetch_doaj, "_warned", False):
            print(f"[!] DOAJ API lambat/timeout (pesan ini hanya sekali): {e}")
            fetch_doaj._warned = True
    return urls_found, texts_found

def fetch_arxiv(probe):
    """Mencari preprint di arXiv (2.4M+ papers, gratis tanpa API key). English STEM only."""
    urls_found = []
    texts_found = []
    try:
        import urllib.parse
        import re as _re
        short_probe = " ".join(probe.split()[:10])
        search_url = "http://export.arxiv.org/api/query"
        params = {
            "search_query": f"all:{urllib.parse.quote(short_probe)}",
            "start": 0,
            "max_results": 3
        }
        res = requests.get(search_url, params=params, timeout=8)
        if res.status_code == 200:
            # Parse Atom feed via regex (hindari dependency lxml/xml parser)
            entries = _re.findall(r'<entry>(.*?)</entry>', res.text, _re.S)
            for entry in entries:
                t_match = _re.search(r'<title>(.*?)</title>', entry, _re.S)
                s_match = _re.search(r'<summary>(.*?)</summary>', entry, _re.S)
                id_match = _re.search(r'<id>(.*?)</id>', entry, _re.S)
                if t_match and s_match and id_match:
                    title = _re.sub(r'\s+', ' ', t_match.group(1)).strip()
                    summary = _re.sub(r'\s+', ' ', s_match.group(1)).strip()
                    link = id_match.group(1).strip()
                    combined = f"{title}. {summary}"
                    if len(combined) > 50:
                        urls_found.append(link)
                        texts_found.append(combined)
        time.sleep(0.5)
    except Exception as e:
        print(f"[!] arXiv API error: {e}")
    return urls_found, texts_found

def fetch_core(probe):
    """Mencari paper di CORE.ac.uk (300M+ papers). Butuh CORE_API_KEY (v3 Bearer token)."""
    urls_found = []
    texts_found = []
    import os
    core_key = os.environ.get("CORE_API_KEY", "")
    if not core_key:
        # Tanpa API key, CORE v3 konsisten timeout/401. Skip cepat agar tidak memblokir pipeline.
        return urls_found, texts_found
    try:
        short_probe = " ".join(probe.split()[:12])
        url = "https://api.core.ac.uk/v3/search/works"
        params = {"q": short_probe, "limit": 5}
        headers = {"Accept": "application/json", "Authorization": f"Bearer {core_key}"}
        res = requests.get(url, params=params, headers=headers, timeout=8)
        if res.status_code == 200:
            data = res.json()
            for item in data.get('results', []):
                title = item.get('title', '')
                abstract = item.get('abstract', '') or ''
                p_url = ''
                for lnk in item.get('links', []):
                    if lnk.get('type') == 'download':
                        p_url = lnk.get('url', '')
                        break
                if not p_url:
                    p_url = item.get('downloadUrl') or item.get('sourceFulltextUrls', [''])[0] if item.get('sourceFulltextUrls') else ''
                if not p_url:
                    doi = item.get('doi', '')
                    if doi:
                        p_url = f"https://doi.org/{doi}"
                combined = f"{title}. {abstract}"
                if p_url and len(combined) > 50:
                    urls_found.append(p_url)
                    texts_found.append(combined)
    except Exception as e:
        print(f"[!] CORE API error: {e}")
    return urls_found, texts_found

def fetch_probe_multi(probe):
    """Mencari ke semua mesin secara serentak dengan free API fallbacks"""

    # 1. Try academic APIs first (free, unlimited)
    u_ss, t_ss = fetch_semantic_scholar(probe)
    u_cr, t_cr = fetch_crossref(probe)
    u_oa, t_oa = fetch_openalex(probe)

    # 1b. Additional free academic APIs
    u_doaj, t_doaj = fetch_doaj(probe)
    u_arxiv, t_arxiv = fetch_arxiv(probe)
    u_core, t_core = fetch_core(probe)
    
    # 2. Try paid APIs (may fail if credit exhausted)
    u_gs, _ = fetch_google_scholar(probe)
    u_gw, _ = fetch_google_web(probe)
    u_gr, _ = fetch_garuda(probe)
    
    # 3. Try DuckDuckGo (free, unlimited)
    u_dd, _ = fetch_ddgs(probe)
    
    # 4. Direct search Indonesian repositories (no API limits, TAPI lambat: BSI ~15s/req).
    # Dibatasi global agar tidak jalan 75x (=375 request kampus). Hanya probe paling awal
    # (kalimat terpanjang/paling spesifik) yang menyisir repo lokal; sisanya sudah tercakup
    # API akademik + DDG. Repo tetap disisir menyeluruh via get_candidate_urls terpisah.
    u_repo, t_repo = [], []
    global _INDO_REPO_BUDGET
    # Klaim budget secara atomik (5 worker paralel): tanpa lock, read-modify-write bisa
    # ras -> jumlah crawl repo non-deterministik antar-run.
    _claim_repo = False
    with _INDO_REPO_LOCK:
        if _INDO_REPO_BUDGET > 0:
            _INDO_REPO_BUDGET -= 1
            _claim_repo = True
    if _claim_repo:
        try:
            from .indonesian_repos import search_all_indonesian_repos
            u_repo, t_repo = search_all_indonesian_repos(probe, max_repos=3, results_per_repo=2)
        except Exception as e:
            print(f"[!] Indonesian repos module error: {e}")
    
    # 5. NEW: Free API fallbacks with caching (jika paid APIs gagal)
    u_fallback, t_fallback = [], []
    try:
        from .free_api_fallbacks import search_with_fallbacks
        u_fallback, t_fallback = search_with_fallbacks(probe, use_cache=True)
    except Exception as e:
        print(f"[!] Free API fallbacks error: {e}")
    
    # Gabungkan URL yang sudah ada abstraknya menjadi dictionary
    preloaded = {}
    for u, t in zip(u_ss, t_ss): preloaded[u] = t
    for u, t in zip(u_cr, t_cr): preloaded[u] = t
    for u, t in zip(u_repo, t_repo): preloaded[u] = t
    for u, t in zip(u_doaj, t_doaj): preloaded[u] = t
    for u, t in zip(u_arxiv, t_arxiv): preloaded[u] = t
    for u, t in zip(u_core, t_core): preloaded[u] = t
    
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

def get_candidate_urls(sentences, max_probes=100, progress_cb=None):
    """
    Fungsi ini kini mengembalikan dua hal:
    1. urls (List URL web biasa untuk discrape manual)
    2. preloaded_corpus (Dict berisi teks abstrak/jurnal berbayar yang langsung didapat via API)

    Strategi sampling 3-tier (75 probe):
    - Tier 1 (33%): Kalimat terpanjang (high-specificity, likely unique content)
    - Tier 2 (33%): Kalimat medium-length (balanced coverage)
    - Tier 3 (34%): Uniform sampling across document (ensures all chapters covered)
    """
    # Reset budget penyisiran repo Indonesia untuk run ini (probe Tier-1 didahulukan).
    # Dikunci agar konsisten dgn decrement ber-lock di fetch_probe_multi.
    global _INDO_REPO_BUDGET
    with _INDO_REPO_LOCK:
        _INDO_REPO_BUDGET = 15

    valid_sentences = [s for s in sentences if len(s.split()) >= 8]
    if len(valid_sentences) <= max_probes:
        probes = valid_sentences
    else:
        tier1_count = max_probes // 3
        tier2_count = max_probes // 3
        tier3_count = max_probes - tier1_count - tier2_count

        sorted_by_len = sorted(valid_sentences, key=lambda s: len(s.split()), reverse=True)

        tier1 = sorted_by_len[:tier1_count]

        mid_start = len(sorted_by_len) // 4
        mid_end = len(sorted_by_len) * 3 // 4
        mid_candidates = [s for s in sorted_by_len[mid_start:mid_end] if s not in tier1]
        if len(mid_candidates) >= tier2_count:
            step = len(mid_candidates) / tier2_count
            tier2 = [mid_candidates[int(i * step)] for i in range(tier2_count)]
        else:
            tier2 = mid_candidates

        used = set(id(s) for s in tier1 + tier2)
        uniform_candidates = [s for s in valid_sentences if id(s) not in used]
        if len(uniform_candidates) >= tier3_count:
            step = len(uniform_candidates) / tier3_count
            tier3 = [uniform_candidates[int(i * step)] for i in range(tier3_count)]
        else:
            tier3 = uniform_candidates

        probes = (tier1 + tier2 + tier3)[:max_probes]
        
    urls = set()
    preloaded_corpus = {}
    
    print(f"[API] Meluncurkan Bot AI & Browser Crawler untuk {len(probes)} Fingerprints...")
    
    # USE_COHERE_EXPANDER (default "0"=MATI): blok Cohere->DDG ini bottleneck utama
    # (Cohere trial 1 req/detik + 3 varian/probe x DDG yg sering kena rate-limit 429).
    # Sumber utama tetap datang dari DOAJ/Crossref/OpenAlex/Semantic Scholar + DDG
    # langsung di fase kedua (fetch_probe_multi). Nyalakan hanya bila butuh recall ekstra.
    if os.environ.get("USE_COHERE_EXPANDER", "0") == "1":
      try:
        # ========================================================================
        # COHERE QUERY-EXPANDER -> DUCKDUCKGO
        # Perplexity/Gemini/Tavily quota habis & Google CSE ditutup permanen.
        # Cohere web-search connector juga dihapus (15 Sep 2025). Yang tersisa &
        # gratis: Cohere chat (command-a) sebagai peng-EKSPAN query. Tiap probe
        # kita minta variasi frasa, lalu variasi itu dicari via DuckDuckGo (fetch_ddgs).
        # Ini menambah recall sumber tanpa bergantung pada API yang sudah mati.
        # ========================================================================
        def fetch_expanded(args):
            idx, probe = args
            found = set()
            for variant in cohere_expand_queries(probe, n=3):
                try:
                    v_urls, _ = fetch_ddgs(variant)
                    for u in v_urls:
                        if u and u.startswith('http'):
                            found.add(u)
                except Exception as e:
                    print(f"[!] fetch_ddgs varian gagal: {e}")
            return list(found)

        # max_workers=2: hormati Cohere trial 1 req/detik + hindari DDG rate-limit
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures_exp = {executor.submit(fetch_expanded, (i, p)): i for i, p in enumerate(probes)}
            for i, future in enumerate(concurrent.futures.as_completed(futures_exp)):
                if progress_cb:
                    progress_cb(futures_exp[future] + 1, len(probes) + len(probes))
                try:
                    for u in future.result():
                        urls.add(u)
                except Exception as e:
                    print(f"[!] expander future gagal: {e}")
      except Exception as e:
        print(f"[!] Cohere/DDG expander error: {e}")

    # --- blok API mati di bawah dinonaktifkan (disimpan sbagai referensi histori) ---
    if False:
        def fetch_pplx(args):
            idx, probe = args
            combined_urls = set()

            # 1. PERPLEXITY AI
            import time
            for attempt in range(3):
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
                        break # Sukses, keluar dari loop retry
                    elif res.status_code == 429: # Rate Limit
                        time.sleep(2 ** attempt) # Exponential backoff: 1s, 2s, 4s
                    else:
                        break # Error lain, hentikan retry
                except Exception as e:
                    if attempt == 2:
                        print(f"[!] Perplexity API Error: {e}")

            # 2. GEMINI AI GROUNDING (Sistem Load Balancer dengan Auto-Failover)
            import os
            gemini_env = os.environ.get("GEMINI_KEYS", "")
            if gemini_env:
                gemini_keys = gemini_env.split(',')
                for offset in range(len(gemini_keys)):
                    try:
                        # Coba key saat ini, jika gagal (429), maju ke key berikutnya (offset)
                        key_index = (idx + offset) % len(gemini_keys)
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
                        break # Sukses, keluar dari loop failover
                    except Exception as e:
                        if "429" in str(e) or "quota" in str(e).lower():
                            continue # Coba key berikutnya di iterasi loop
                        if offset == len(gemini_keys) - 1:
                            print(f"[!] Gemini API Error: {e}")
                
            # 3. COHERE AI GROUNDING
            for attempt in range(3):
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
                        break
                    elif res.status_code == 429:
                        time.sleep(2 ** attempt)
                    else:
                        break
                except Exception as e:
                    if attempt == 2:
                        print(f"[!] Cohere API Error: {e}")
                
            # 4. TAVILY AI SEARCH
            for attempt in range(3):
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
                        break
                    elif res.status_code == 429:
                        time.sleep(2 ** attempt)
                    else:
                        break
                except Exception as e:
                    if attempt == 2:
                        print(f"[!] Tavily API Error: {e}")
                
            return list(combined_urls)

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
                except Exception as e:
                    print(f"[!] pplx future gagal: {e}")
    # --- akhir blok API mati ---

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
    # Banyak situs (Medium, repositori kampus) mengembalikan halaman kosong/blokir
    # tanpa User-Agent browser. Header ini menaikkan keberhasilan & kelengkapan teks.
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
    }
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
                res = requests.get(url, timeout=20, verify=False, headers=headers)
        else:
            res = requests.get(url, timeout=20, verify=False, headers=headers)
            
        if res.status_code == 200:
            total_bytes += len(res.content)
            import re
            
            # Deteksi jika file adalah PDF (Banyak repositori kampus langsung mengembalikan file PDF)
            if 'application/pdf' in res.headers.get('Content-Type', '').lower() or url.lower().endswith('.pdf'):
                import fitz
                import io
                doc = fitz.open(stream=res.content, filetype="pdf")
                text = ""
                # Direct-PDF: baca hingga 40 halaman (lebih tinggi dari deep-crawl karena
                # link langsung = kandidat sumber utama), tapi tetap dibatasi agar tidak
                # nyangkut di PDF ratusan halaman.
                try:
                    for page_num, page in enumerate(doc):
                        if page_num >= 40: break
                        text += page.get_text() + " "
                finally:
                    doc.close()  # lepas handle PyMuPDF (mencegah leak di pool multi-thread)
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
                            # Gunakan AbstractAPI lagi untuk mendownload PDF jika dilindungi Cloudflare.
                            # Skip proxy jika tidak ada key (mencegah request sia-sia yang selalu gagal).
                            if abstract_key:
                                encoded_pdf = urllib.parse.quote(pdf_url)
                                proxy_pdf = f"https://scrape.abstractapi.com/v1/?api_key={abstract_key}&url={encoded_pdf}"
                                pdf_res = requests.get(proxy_pdf, timeout=15)
                                if pdf_res.status_code != 200:
                                    pdf_res = requests.get(pdf_url, timeout=20, verify=False, headers=headers)
                            else:
                                pdf_res = requests.get(pdf_url, timeout=20, verify=False, headers=headers)
                                
                            if pdf_res.status_code == 200:
                                total_bytes += len(pdf_res.content)
                            
                            # Verifikasi apakah benar-benar PDF (Magic number %PDF)
                            if 'application/pdf' in pdf_res.headers.get('Content-Type', '').lower() or pdf_res.content.startswith(b'%PDF'):
                                pdf_doc = fitz.open(stream=pdf_res.content, filetype="pdf")
                                # Baca hingga 30 halaman per PDF. Skripsi 60-100 halaman: 5 halaman
                                # (versi lama) hanya menangkap cover+abstrak, sehingga isi Bab 2-4
                                # yang paling sering diplagiat TIDAK ikut terindeks -> overlap 0.
                                # Cap 30 halaman menyeimbangkan cakupan vs risiko nyangkut di PDF 300 hal.
                                try:
                                    for page_num, page in enumerate(pdf_doc):
                                        if page_num >= 30: break
                                        pdf_text += page.get_text() + " "
                                finally:
                                    pdf_doc.close()  # lepas handle PyMuPDF (hindari leak di pool multi-thread)
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
    """Mengeksekusi multi-threading untuk mengunduh web, lalu digabung dengan preloaded_corpus (Jurnal API).
    Bank lokal di-merge terlebih dahulu (cek lokal dulu, internet pelengkap)."""
    corpus = preloaded_corpus.copy()

    # BANK LOKAL: merge sumber yang sudah pernah di-scrape sebelumnya (instan).
    bank = load_corpus_bank()
    bank_hits = 0
    for url in list(urls):
        if url in bank:
            corpus[url] = bank[url]
            bank_hits += 1
    # Hapus URL yang sudah ada di bank (tak perlu scrape ulang)
    urls = [u for u in urls if u not in bank and u not in corpus]
    if bank_hits:
        print(f"[Bank] {bank_hits} sumber ditemukan di bank lokal (skip scrape)")

    if not urls:
        save_to_corpus_bank(corpus)
        return corpus

    print(f"[Scraper] Bot Crawler mulai mengunduh {len(urls)} sumber web publik...")
    
    # Abaikan InsecureRequestWarning saat scrape blog/kampus yang SSL-nya mati
    from requests.packages.urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
    
    import time
    start_time = time.time()
    total_downloaded_bytes = 0
    # max_workers=8: 40 koneksi HTTPS serentak dari 1 IP memicu rate-limit server,
    # SSL handshake gagal, dan connection-pool jenuh (banyak sumber relevan gagal
    # download meski solo-nya sukses). 8 worker jauh lebih andal walau sedikit lambat.
    failed_urls = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(scrape_url, u): u for u in urls}
        total = len(futures)
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            try:
                url, text, downloaded_bytes = future.result()
                total_downloaded_bytes += downloaded_bytes
                if len(text) > 150: # Validasi panjang minimal teks
                    corpus[url] = text
                else:
                    failed_urls.append(futures[future])
            except Exception as e:
                failed_urls.append(futures[future])
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

    # RETRY PASS: URL yang gagal (kosong/error) sering korban rate-limit sesaat, bukan
    # benar-benar mati. Coba sekali lagi dengan konkurensi sangat rendah (4 worker).
    if failed_urls:
        print(f"[Scraper] Retry {len(failed_urls)} sumber yang gagal (konkurensi rendah)...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(scrape_url, u): u for u in failed_urls}
            for future in concurrent.futures.as_completed(futures):
                try:
                    url, text, downloaded_bytes = future.result()
                    total_downloaded_bytes += downloaded_bytes
                    if len(text) > 150:
                        corpus[url] = text
                except Exception:
                    pass

    # Simpan sumber baru ke bank lokal (makin kaya seiring waktu)
    save_to_corpus_bank(corpus)
    return corpus
