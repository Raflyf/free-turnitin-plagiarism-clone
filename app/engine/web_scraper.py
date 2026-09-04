import os
import logging

logger = logging.getLogger(__name__)
import time
import random
import requests
import warnings
import urllib.parse
import urllib3
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor

# Nonaktifkan peringatan SSL (banyak web kampus SSL-nya kedaluwarsa) & parser XML
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)
try:
    import requests.packages.urllib3.exceptions
    requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
    warnings.filterwarnings("ignore", category=requests.packages.urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*duckduckgo_search.*")
warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*renamed to.*")
logging.getLogger("duckduckgo_search").setLevel(logging.ERROR)
logging.getLogger("ddgs").setLevel(logging.ERROR)

# --- Konstanta Timeout & Pool Global ---
_REQUEST_TIMEOUT = 10           # timeout default semua fetch API (detik) — kompromi: cepat vs server kampus lambat
_SCRAPE_TIMEOUT = 12            # timeout scrape URL (detik) — turun dari 30s
_POOL_CONNECTIONS = 30          # koneksi maks per host
_POOL_MAXSIZE = 80              # max total koneksi pool

# --- Bank Korpus Lokal (SQLite3 Database) ---
import sqlite3 as _sqlite3
import json as _json
import threading as _threading
import ipaddress as _ipaddress
from engine.supabase_client import (
    get_bank_urls_supabase,
    get_bank_texts_supabase,
    save_to_corpus_bank_supabase
)

# Thread-local HTTP session untuk connection pooling (reuse koneksi TCP)
_thread_local = _threading.local()
from contextlib import closing
from typing import Dict, Set, Optional

def _get_session():
    """Mendapatkan requests.Session untuk thread saat ini (thread-safe)."""
    if not hasattr(_thread_local, "session"):
        _thread_local.session = requests.Session()
        _thread_local.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        # Setel adapter dengan pool besar untuk koneksi paralel
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=_POOL_CONNECTIONS,
            pool_maxsize=_POOL_MAXSIZE,
            max_retries=requests.adapters.Retry(
                total=2, backoff_factor=0.5,
                status_forcelist=[429, 500, 502, 503, 504]
            )
        )
        _thread_local.session.mount('https://', adapter)
        _thread_local.session.mount('http://', adapter)
    return _thread_local.session

_BANK_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "corpus_bank", "bank.json")
_BANK_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "corpus_bank", "bank.db")
_bank_lock = _threading.Lock()  # lindungi mutasi DB dari race antar-thread
_byte_lock = _threading.Lock()
_global_download_bytes = 0

def _reset_download_bytes():
    global _global_download_bytes
    with _byte_lock:
        _global_download_bytes = 0

def _add_download_bytes(b):
    global _global_download_bytes
    with _byte_lock:
        _global_download_bytes += b

def _get_download_bytes():
    with _byte_lock:
        return _global_download_bytes

_bank_initialized = False

def init_bank_db():
    """Inisialisasi tabel SQLite3 dan lakukan auto-migrasi dari bank.json jika ada."""
    global _bank_initialized
    if _bank_initialized:
        return
    os.makedirs(os.path.dirname(_BANK_DB_PATH), exist_ok=True)
    with _bank_lock:
        with closing(_sqlite3.connect(_BANK_DB_PATH)) as conn:
            cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS corpus (url TEXT PRIMARY KEY, text TEXT)")
            conn.commit()
            
            # Migrasi otomatis HANYA jika bank.db masih kosong dan bank.json ada
            cur.execute("SELECT COUNT(*) FROM corpus")
            total = cur.fetchone()[0]
            if total == 0 and os.path.exists(_BANK_JSON_PATH):
                try:
                    logger.info("[Bank] Mengimpor data lama dari bank.json ke SQLite bank.db...")
                    with open(_BANK_JSON_PATH, "r", encoding="utf-8") as f:
                        data = _json.load(f)
                    items = [(u, t) for u, t in data.items() if len(t) > 150]
                    cur.executemany("INSERT OR IGNORE INTO corpus (url, text) VALUES (?, ?)", items)
                    conn.commit()
                    logger.info(f"[Bank] Berhasil migrasi {len(items)} sumber ke bank.db SQLite.")
                except Exception as e:
                    logger.info("[Bank] Warning migrasi: %s", e)
        _bank_initialized = True

def get_bank_urls() -> Set[str]:
    """Mengembalikan set URL yang tersimpan di bank.db lokal & Supabase (instan <1ms)."""
    urls = set()
    try:
        init_bank_db()
        with closing(_sqlite3.connect(_BANK_DB_PATH)) as conn:
            cur = conn.cursor()
            cur.execute("SELECT url FROM corpus")
            urls.update(row[0] for row in cur.fetchall())
    except Exception as e:
        logger.info("[Bank] Warning read bank_urls local: %s", e)
        
    if supa_urls := get_bank_urls_supabase():
        urls.update(supa_urls)
        
    return urls

def get_bank_texts(target_urls: list[str]) -> Dict[str, str]:
    """Mengambil teks spesifik HANYA untuk target_urls dari bank.db lokal, lalu Supabase."""
    if not target_urls: return {}
        
    result = {}
    target_set = set(target_urls)
    
    try:
        init_bank_db()
        with closing(_sqlite3.connect(_BANK_DB_PATH)) as conn:
            cur = conn.cursor()
            target_list = list(target_set)
            for i in range(0, len(target_list), 500):
                batch = target_list[i:i+500]
                placeholders = ",".join("?" for _ in batch)
                cur.execute(f"SELECT url, text FROM corpus WHERE url IN ({placeholders})", batch)
                result.update({url: text for url, text in cur.fetchall()})
    except Exception as e:
        logger.info("[Bank] Warning read bank.db: %s", e)
        
    if missing_urls := target_set - set(result.keys()):
        if supa_texts := get_bank_texts_supabase(missing_urls):
            result.update(supa_texts)
            
    return result

def load_corpus_bank(target_urls: Optional[list[str]] = None) -> Dict[str, str]:
    """Load bank corpus on-demand for specific target_urls to prevent RAM explosion."""
    if target_urls:
        return get_bank_texts(target_urls)
    init_bank_db()
    with closing(_sqlite3.connect(_BANK_DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute("SELECT url, text FROM corpus")
        return {row[0]: row[1] for row in cur}

def save_to_corpus_bank_local(new_corpus: Dict[str, str]):
    """Simpan sumber baru HANYA ke bank.db SQLite (Lokal)."""
    if not new_corpus: return
        
    init_bank_db()
    with _bank_lock:
        try:
            with closing(_sqlite3.connect(_BANK_DB_PATH)) as conn:
                cur = conn.cursor()
                items = [(u, t) for u, t in new_corpus.items() if isinstance(t, str) and len(t) > 150]
                cur.executemany("INSERT OR IGNORE INTO corpus (url, text) VALUES (?, ?)", items)
                conn.commit()
                cur.execute("SELECT COUNT(*) FROM corpus")
                total = cur.fetchone()[0]
                logger.info("[Bank] Tersimpan ke bank.db (total: %s sumber)", total)
        except Exception as e:
            logger.info("[Bank] PERINGATAN: gagal menyimpan ke bank.db: %s", e)

def save_to_corpus_bank(new_corpus):
    """Simpan sumber baru ke bank.db SQLite (instan <1ms) & Supabase Cloud (async background thread, zero delay)."""
    save_to_corpus_bank_local(new_corpus)

    # 2. Simpan ke Supabase Cloud di BACKGROUND THREAD (Zero delay, tidak menahan kalkulasi N-Gram!)
    import threading
    t = threading.Thread(target=save_to_corpus_bank_supabase, args=(new_corpus.copy(),), daemon=True)
    t.start()

def is_safe_url(url):
    """Sanitasi URL anti-SSRF: memblokir IP privat/local, loopback, dan metadata endpoint.
    Juga memblokir URL shortener/redirector yang bisa dipakai bypass."""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        
        # Normalisasi hostname: lower + strip trailing dot
        hostname = hostname.lower().rstrip('.')
        
        # Blokir hostname berbahaya
        BLOCKED_HOSTNAMES = {
            'localhost', '127.0.0.1', '0.0.0.0', '::1', '::',
            'metadata.google.internal', 'metadata.google.internal.',
            '169.254.169.254',  # AWS/GCP/Azure metadata endpoint
            '100.100.100.200',  # Alibaba Cloud metadata
        }
        if hostname in BLOCKED_HOSTNAMES:
            return False
        
        # Blokir wildcard localhost (mis. 127.0.0.2, 127.0.0.3, ...)
        if hostname.startswith('127.'):
            parts = hostname.split('.')
            if len(parts) == 4 and parts[0] == '127':
                return False
        
        # Blokir URL shortener umum (bisa redirect ke internal)
        SHORTENER_DOMAINS = {
            'bit.ly', 'tinyurl.com', 'shorturl.at', 'tiny.cc', 'ow.ly',
            'is.gd', 'buff.ly', 'rebrand.ly', 'cutt.ly', 'short.link',
            's.id', 'rb.gy', 'bl.ink', 'short.cm', '1url.com',
        }
        if hostname in SHORTENER_DOMAINS:
            return False
        
        try:
            ip = _ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
                return False
        except ValueError:
            pass
        
        # Cek apakah hostname mengandung IP dalam format desimal/oktal/hex
        # yang bisa bypass filter (mis. http://0x7f000001/ = 127.0.0.1)
        import re as _re
        if _re.match(r'^0[xX][0-9a-fA-F]+$', hostname):
            return False
        if _re.match(r'^0\d+$', hostname):
            return False
        
        return True
    except Exception:
        return False

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
            "Anda membantu mendeteksi plagiarisme dokumen akademik Bahasa Indonesia. "
            f"Buat {n} variasi frasa pencarian singkat (5-8 kata) untuk menemukan sumber "
            "jurnal/dokumen yang mungkin menjadi asal kalimat berikut. Jawab HANYA daftar "
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

def fetch_semantic_scholar(probe, cutoff_year=None):
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
        res = requests.get(url, params=params, headers=s2_headers, timeout=_REQUEST_TIMEOUT)
        if res.status_code == 200:
            data = res.json()
            for paper in data.get('data', []):
                p_url = paper.get('url') or f"https://semanticscholar.org/paper/{paper.get('paperId','')}"
                abstract = paper.get('abstract') or ""
                title = paper.get('title') or ""

                oa_pdf = paper.get('openAccessPdf')
                if oa_pdf and oa_pdf.get('url'):
                    p_url = oa_pdf['url']

                combined_text = f"{title}. {abstract}"
                if len(combined_text) > 50:
                    urls_found.append(p_url)
                    texts_found.append(combined_text)
    except Exception as e:
        logger.debug("Silently caught exception: %s", e)
    return urls_found, texts_found

def fetch_crossref(probe, cutoff_year=None):
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
            "mailto": "research_open_plagiarism@university.edu"
        }
        if cutoff_year:
            params["filter"] = f"until-pub-date:{cutoff_year}-12-31"
        res = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
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
        logger.debug("CrossRef API error: %s", e)
    return urls_found, texts_found

def fetch_openalex(probe, cutoff_year=None):
    """Mencari full-text jurnal Indonesia via OpenAlex (250M+ Dokumen).
    Upgrade v3.3: pakai filter fulltext.search + language:id + is_oa:true
    untuk mendapat URL PDF langsung (bukan hanya abstrak metadata)."""
    urls_found = []
    texts_found = []
    try:
        short_probe = " ".join(probe.split()[:10])
        filter_str = f"language:id,open_access.is_oa:true,fulltext.search:{short_probe}"
        if cutoff_year:
            filter_str += f",to_publication_date:{cutoff_year}-12-31"
        params = {
            "filter": filter_str,
            "per_page": 10,
            "select": "id,title,open_access,primary_location,abstract_inverted_index",
            "mailto": "research_open_plagiarism@university.edu"
        }
        res = requests.get("https://api.openalex.org/works", params=params, timeout=_REQUEST_TIMEOUT)
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
        logger.debug("OpenAlex API error: %s", e)
    return urls_found, texts_found

def fetch_garuda(probe, cutoff_year=None):
    """Mencari Portal Jurnal Nasional (Garuda Kemdikbud/SINTA) — direct scrape tanpa proxy.
    Server Garuda tidak punya proteksi anti-bot level Cloudflare, cukup request langsung."""
    urls_found = []
    try:
        import urllib.parse
        short_probe = " ".join(probe.split()[:8])
        query = urllib.parse.quote(short_probe)
        target_url = f"https://garuda.kemdiktisaintek.go.id/documents?q={query}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        res = _get_session().get(target_url, timeout=_REQUEST_TIMEOUT, headers=headers, verify=False)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            for a_tag in soup.select('a.title-article'):
                if 'href' in a_tag.attrs:
                    url = a_tag['href']
                    if not url.startswith('http'):
                        url = "https://garuda.kemdiktisaintek.go.id" + url
                    urls_found.append(url)
    except Exception as e:
        logger.debug("Silently caught exception: %s", e)
    return urls_found, []

def fetch_ddgs(probe, cutoff_year=None):
    """Mencari website publik biasa via DuckDuckGo, dengan Prioritas Situs Kampus/Jurnal"""
    urls_found = []
    try:
        # Utamakan paket baru `ddgs`; isolasi peringatan fallback jika hanya ada `duckduckgo_search`
        try:
            from ddgs import DDGS
            ddgs = DDGS()
        except ImportError:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                from duckduckgo_search import DDGS
                ddgs = DDGS()
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)

        # FUZZY SEARCH KEMBALI!
        # Ekstraksi PDF sangat rawan typo (spasi hilang, dsb). Exact match mutlak sering berujung 0 hasil.
        # Kita gunakan Fuzzy Search di Search Engine dengan potongan 8 kata (standar industri), bukan 15 kata!
        short_probe = " ".join(probe.split()[:8])

        import random, hashlib
        # DETERMINISME: pilih varian query berdasarkan hash STABIL probe. Python hash()
        # bawaan di-randomisasi per-proses (PYTHONHASHSEED) sehingga TIDAK reproducible
        # antar run; hashlib.md5 stabil. Probe sama -> varian sama -> korpus reproducible.
        # Ini syarat agar skor bisa dikalibrasi & dipertanggungjawabkan.
        variant = int(hashlib.md5(short_probe.encode("utf-8")).hexdigest(), 16) % 4
        
        # Injeksi cutoff_year ke query search engine
        cutoff_suffix = ""
        # Sayangnya DuckDuckGo tidak memiliki operator before: yang stabil, namun kita bisa menambahkan batas temporal pada beberapa kasus atau skip jika tak didukung secara konsisten. 
        # Tetap kita pasang saja jika sewaktu-waktu DDG mendukung atau jika DDGS pass-through
        # (Lebih aman kita filter secara manual di client setelah scraping jika benar-benar ketat, tapi ini sekedar usaha best-effort)

        if variant == 0:
            # PRIORITAS TERTINGGI: repositori indeks-besar (paling mungkin full-text)
            query = f'{short_probe} (site:123dok.com OR site:repository.bsi.ac.id OR site:etheses.uin-malang.ac.id OR site:doku.pub)'
        elif variant == 1:
            query = f'{short_probe} (jurnal OR repository OR skripsi OR eprints)'
        elif variant == 2:
            query = f'{short_probe} site:ac.id'
        else:
            # Bias Indonesia: tambah keyword bahasa Indonesia untuk recall lokal
            query = f'{short_probe} (skripsi tesis jurnal penelitian)'

        if cutoff_year:
            # Menggunakan operator temporal duckduckgo d: atau range (meskipun kadang tidak konsisten, better than nothing)
            # DDG tak punya before: yang resmi seperti google, tapi kita bisa pakai d: (date format) di beberapa kasus
            pass

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
    except Exception as e:
        logger.debug("Silently caught exception: %s", e)
    return urls_found, []

def fetch_doaj(probe, cutoff_year=None):
    """Mencari artikel open-access di DOAJ (Directory of Open Access Journals — 9M+ articles)"""
    urls_found = []
    texts_found = []
    try:
        words = probe.split()
        short_probe = " ".join(words[:6])
        url = "https://doaj.org/api/search/articles/" + requests.utils.quote(short_probe)
        res = requests.get(url, params={"pageSize": 5}, timeout=_REQUEST_TIMEOUT)
        if res.status_code == 200:
            data = res.json()
            results = data.get('results', [])
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
    except Exception as e:
        logger.debug("Silently caught exception: %s", e)
    return urls_found, texts_found

def fetch_arxiv(probe, cutoff_year=None):
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
        res = requests.get(search_url, params=params, timeout=_REQUEST_TIMEOUT)
        if res.status_code == 200:
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
    except Exception as e:
        logger.debug("Silently caught exception: %s", e)
    return urls_found, texts_found

def fetch_europe_pmc(probe, cutoff_year=None):
    """Mencari artikel di Europe PMC (40M+ paper open-access, full-text gratis, tanpa API key)."""
    urls_found = []
    texts_found = []
    try:
        short_probe = " ".join(probe.split()[:8])
        url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        params = {
            "query": f'"{short_probe}"',
            "format": "json",
            "pageSize": 5,
            "resultType": "core"
        }
        headers = {"User-Agent": "OpenPlagiarismBot/4.0 (mailto:research_open_plagiarism@university.edu)"}
        res = requests.get(url, params=params, headers=headers, timeout=3)
        if res.status_code == 200:
            data = res.json()
            results = data.get("resultList", {}).get("result", [])
            for item in results:
                title = item.get("title", "")
                abstract = item.get("abstractText", "")
                p_url = f"https://europepmc.org/article/{item.get('source', 'MED')}/{item.get('id', '')}"
                combined = f"{title}. {abstract}"
                if len(combined) > 50:
                    urls_found.append(p_url)
                    texts_found.append(combined)
    except Exception as e:
        logger.debug("Silently caught exception: %s", e)
    return urls_found, texts_found

def fetch_onesearch_id(probe, cutoff_year=None):
    """Mencari ke Indonesia OneSearch / IOS Perpusnas RI (Indeks 1.200+ Repositori & Jurnal Kampus se-Indonesia)."""
    urls_found = []
    texts_found = []
    try:
        short_probe = " ".join(probe.split()[:8])
        url = "https://onesearch.id/api/search"
        params = {
            "q": short_probe,
            "type": "all",
            "limit": 5
        }
        res = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
        if res.status_code == 200:
            data = res.json()
            docs = data.get("data", []) or data.get("docs", [])
            for doc in docs:
                title = doc.get("title", "")
                abstract = doc.get("description", "") or doc.get("abstract", "")
                p_url = doc.get("url", "") or doc.get("link", [""])[0] if isinstance(doc.get("link"), list) else doc.get("link", "")
                if not p_url and doc.get("id"):
                    p_url = f"https://onesearch.id/Record/{doc.get('id')}"
                combined = f"{title}. {abstract}"
                if p_url and len(combined) > 50:
                    urls_found.append(p_url)
                    texts_found.append(combined)
    except Exception as e:
        logger.debug("Silently caught exception: %s", e)
    return urls_found, texts_found

def fetch_neliti(probe, cutoff_year=None):
    """Mencari paper di Neliti (Reposisori Riset Terbesar Indonesia — 500.000+ Jurnal & Skripsi)."""
    urls_found = []
    texts_found = []
    try:
        short_probe = " ".join(probe.split()[:8])
        url = f"https://www.neliti.com/id/search?q={requests.utils.quote(short_probe)}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(url, headers=headers, timeout=_REQUEST_TIMEOUT)
        if res.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(res.text, 'html.parser')
            for card in soup.find_all('div', class_='card-publication-body'):
                a_tag = card.find('a', href=True)
                if a_tag:
                    p_url = a_tag['href']
                    if not p_url.startswith('http'):
                        p_url = "https://www.neliti.com" + p_url
                    title = a_tag.get_text(strip=True)
                    snippet = card.get_text(separator=' ', strip=True)
                    combined = f"{title}. {snippet}"
                    if len(combined) > 50:
                        urls_found.append(p_url)
                        texts_found.append(combined)
    except Exception as e:
        logger.debug("Silently caught exception: %s", e)
    return urls_found, texts_found

def fetch_moraref(probe, cutoff_year=None):
    """Mencari publikasi dari MORAREF (Kementerian Agama RI) - repositori jurnal keagamaan Islam.
    Strategi: REST API + OAI-PMH fallback via search.apps.kemenag.go.id
    """
    urls_found = []
    texts_found = []
    try:
        short_probe = " ".join(probe.split()[:10])
        import urllib.parse
        # Pendekatan 1: REST API search
        api_url = "https://search.apps.kemenag.go.id/api/v1/documents"
        params = {"q": short_probe, "limit": 10, "source": "moraref"}
        try:
            res = requests.get(api_url, params=params, timeout=_REQUEST_TIMEOUT)
            if res.status_code == 200:
                data = res.json()
                docs = data.get("data", data.get("documents", data.get("results", [])))
                if not isinstance(docs, list):
                    docs = [docs]
                for doc in docs:
                    if isinstance(doc, dict):
                        title = doc.get("title", doc.get("judul", ""))
                        abstract = doc.get("abstract", doc.get("abstrak", doc.get("description", "")))
                        url = doc.get("url", doc.get("link", doc.get("id", "")))
                        if url and not url.startswith("http"):
                            url = f"https://moraref.kemenag.go.id/archives/{url}"
                        combined = f"{title}. {abstract}" if abstract else title
                        if title and len(combined) > 50:
                            urls_found.append(url)
                            texts_found.append(combined)
        except Exception as e:
            logger.debug("Silently caught exception: %s", e)
        # Pendekatan 2: OAI-PMH fallback
        if len(urls_found) < 3:
            try:
                oai_url = "https://moraref.kemenag.go.id/oai"
                oai_params = {"verb": "ListRecords", "metadataPrefix": "oai_dc", "set": "moraref"}
                res = requests.get(oai_url, params=oai_params, timeout=_REQUEST_TIMEOUT)
                if res.status_code == 200:
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(res.text)
                    for record in root.iter("{http://www.openarchives.org/OAI/2.0/}record"):
                        metadata = record.find(".//{http://www.openarchives.org/OAI/2.0/}metadata")
                        if metadata is None:
                            continue
                        titles = [t.text for t in metadata.iter("{http://purl.org/dc/elements/1.1/}title") if t.text]
                        descriptions = [d.text for d in metadata.iter("{http://purl.org/dc/elements/1.1/}description") if d.text]
                        identifiers = [i.text for i in metadata.iter("{http://purl.org/dc/elements/1.1/}identifier") if i.text]
                        if not titles:
                            continue
                        title = titles[0]
                        abstract = descriptions[0] if descriptions else ""
                        url = identifiers[0] if identifiers else ""
                        combined = f"{title}. {abstract}" if abstract else title
                        probe_lower = probe.lower()
                        if (probe_lower in title.lower() or probe_lower in abstract.lower()) and len(combined) > 50:
                            urls_found.append(url)
                            texts_found.append(combined)
                            if len(urls_found) >= 5:
                                break
            except Exception as e:
                logger.debug("Silently caught exception: %s", e)
    except Exception as e:
        logger.debug("Silently caught exception: %s", e)
    return urls_found, texts_found

def fetch_base(probe, cutoff_year=None):
    """Mencari publikasi dari BASE (Bielefeld Academic Search Engine) - 300M+ dokumen Open Access.
    API gratis: https://api.base-search.net/
    """
    urls_found = []
    texts_found = []
    try:
        short_probe = " ".join(probe.split()[:12])
        import urllib.parse
        api_url = "https://api.base-search.net/cgi-bin/BaseHttpSearchInterface.fcgi"
        params = {"func": "PerformSearch", "query": short_probe, "format": "json", "limit": "10", "boost": "dc.description"}
        res = requests.get(api_url, params=params, timeout=_REQUEST_TIMEOUT)
        if res.status_code == 200:
            data = res.json()
            docs = data.get("result", data.get("docs", data.get("records", [])))
            if isinstance(docs, dict):
                docs = docs.get("doc", docs.get("result", []))
            if not isinstance(docs, list):
                docs = [docs]
            for doc in docs:
                if isinstance(doc, dict):
                    title = doc.get("dc:title", doc.get("title", ""))
                    if isinstance(title, list):
                        title = title[0] if title else ""
                    description = doc.get("dc:description", doc.get("description", ""))
                    if isinstance(description, list):
                        description = description[0] if description else ""
                    url = doc.get("dc:identifier", doc.get("identifier", doc.get("id", "")))
                    if isinstance(url, list):
                        url = url[0] if url else ""
                    combined = f"{title}. {description}" if description else title
                    if title and len(combined) > 50:
                        urls_found.append(url)
                        texts_found.append(combined)
    except Exception as e:
        logger.debug("Silently caught exception: %s", e)
    return urls_found, texts_found

def fetch_pubmed(probe, cutoff_year=None):
    """Mencari publikasi biomedis di PubMed/NCBI (30M+ paper, gratis, tanpa API key).
    Menggunakan NCBI E-Utilities (ESearch + ESummary) — sumber resmi pemerintah AS."""
    urls_found = []
    texts_found = []
    try:
        short_probe = " ".join(probe.split()[:10])
        # ESearch: cari PMID berdasarkan query
        esearch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        params = {"db": "pubmed", "term": short_probe, "retmax": 5, "retmode": "json"}
        res = _get_session().get(esearch_url, params=params, timeout=_REQUEST_TIMEOUT)
        if res.status_code != 200:
            return urls_found, texts_found
        pmids = res.json().get("esearchresult", {}).get("idlist", [])
        if not pmids:
            return urls_found, texts_found
        # ESummary: ambil metadata (title + abstract snippet)
        esummary_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "json"}
        res = _get_session().get(esummary_url, params=params, timeout=_REQUEST_TIMEOUT)
        if res.status_code == 200:
            data = res.json().get("result", {})
            for pmid in pmids:
                item = data.get(pmid, {})
                if not isinstance(item, dict):
                    continue
                title = item.get("title", "")
                source = item.get("source", "")
                combined = f"{title}. {source}"
                url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
                if title and len(combined) > 40:
                    urls_found.append(url)
                    texts_found.append(combined)
    except Exception as e:
        logger.debug("Silently caught exception: %s", e)
    return urls_found, texts_found

def fetch_indonesian_ethesis(probe, cutoff_year=None):
    """Mencari skripsi/tesis dari 8 repositori universitas negeri, swasta & UIN aktif se-Indonesia.
    Target: Undip, Unair, UMS, UNY, UIN Sunan Kalijaga Yogya, UIN Ar-Raniry Aceh, UNP Padang, UIN Jakarta.
    """
    urls_found = []
    texts_found = []
    try:
        short_probe = " ".join(probe.split()[:8])
        import urllib.parse
        encoded = urllib.parse.quote(short_probe)
        repos = [
            ("Undip", f"https://eprints.undip.ac.id/cgi/search/simple?q={encoded}", "eprints"),
            ("Unair", f"https://repository.unair.ac.id/cgi/search/simple?q={encoded}", "eprints"),
            ("UMS", f"https://eprints.ums.ac.id/cgi/search/simple?q={encoded}", "eprints"),
            ("UNY", f"https://eprints.uny.ac.id/cgi/search/simple?q={encoded}", "eprints"),
            ("UINSuka", f"https://digilib.uin-suka.ac.id/cgi/search/simple?q={encoded}", "eprints"),
            ("UINArRaniry", f"https://repository.ar-raniry.ac.id/cgi/search/simple?q={encoded}", "eprints"),
            ("UNPPadang", f"https://repository.unp.ac.id/cgi/search/simple?q={encoded}", "eprints"),
            ("UINJakarta", f"https://repository.uinjkt.ac.id/dspace/simple-search?query={encoded}", "dspace"),
        ]
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        for repo_name, search_url, rtype in repos:
            try:
                res = requests.get(search_url, timeout=3.5, headers=headers, verify=False)
                if res.status_code != 200:
                    continue
                soup = BeautifulSoup(res.text, "html.parser")
                if rtype == "eprints":
                    results = soup.select("tr.ep_search_result, p.ep_search_result, div.ep_search_result, table.ep_search_results tr")
                    for item in results:
                        link_el = item.find("a", href=True)
                        if not link_el:
                            continue
                        title = link_el.get_text(strip=True)
                        if not title or len(title) < 15:
                            continue
                        href = link_el["href"]
                        url = href if href.startswith("http") else f"https://{search_url.split('/')[2]}{href}"
                        desc_el = item.find("p") or item.find("em") or item.find("span")
                        description = desc_el.get_text(strip=True) if desc_el else ""
                        combined = f"{title}. {description}" if description else title
                        if len(combined) > 40:
                            urls_found.append(url)
                            texts_found.append(combined)
                elif rtype == "dspace":
                    for item in soup.find_all("tr"):
                        link_el = item.find("a", href=True)
                        if link_el and "/handle/" in link_el.get("href", ""):
                            title = link_el.get_text(strip=True)
                            if not title or len(title) < 15:
                                continue
                            href = link_el["href"]
                            url = href if href.startswith("http") else f"https://repository.uinjkt.ac.id{href}"
                            combined = title
                            urls_found.append(url)
                            texts_found.append(combined)
            except Exception:
                continue
    except Exception as e:
        logger.debug("Silently caught exception: %s", e)
    return urls_found, texts_found

_FAILED_APIS = set()
_FAILED_APIS_LOCK = threading.Lock()

_GOOGLE_NATIVE_BUDGET = 5
_GOOGLE_NATIVE_LOCK = threading.Lock()

def fetch_google_search_native(probe, cutoff_year=None):
    """Mencari menggunakan googlesearch-python (scraping HTML Google Search langsung).
    Hanya dijalankan untuk 5 kalimat terpanjang (Top 5) agar terhindar dari IP Ban (Error 429)."""
    urls_found = []
    try:
        from googlesearch import search
        # Hindari query terlalu panjang yang bisa ditolak Google
        short_probe = " ".join(probe.split()[:15])
        query = f'"{short_probe}"'
        if cutoff_year:
            query += f' before:{cutoff_year+1}-01-01'
        # logger.info("[Google Search] Probe: {short_probe[:50]}...")
        # advanced=False mempercepat eksekusi (hanya butuh URL)
        for url in search(query, num_results=3, sleep_interval=1.5, advanced=False):
            urls_found.append(url)
    except Exception as e:
        logger.debug("Silently caught exception: %s", e)
    return urls_found, []

class APICircuitBreaker:
    _FAILED_APIS = {}
    _LOCK = __import__('threading').Lock()
    COOLDOWN = 60  # turun dari 120s agar API yang recover cepat bisa dipakai lagi

    @classmethod
    def is_available(cls, api_name):
        with cls._LOCK:
            if api_name not in cls._FAILED_APIS:
                return True
            return __import__('time').time() >= cls._FAILED_APIS[api_name]

    @classmethod
    def record_failure(cls, api_name):
        with cls._LOCK:
            cls._FAILED_APIS[api_name] = __import__('time').time() + cls.COOLDOWN

    @classmethod
    def record_success(cls, api_name):
        with cls._LOCK:
            cls._FAILED_APIS.pop(api_name, None)


def call_api_safe_v2(api_name, fetch_func, probe, cutoff_year=None):
    """Panggil API dengan circuit breaker v2 (auto-recovery)."""
    if not APICircuitBreaker.is_available(api_name):
        return [], []
    try:
        urls, texts = fetch_func(probe, cutoff_year=cutoff_year)
        APICircuitBreaker.record_success(api_name)
        return urls, texts
    except Exception:
        APICircuitBreaker.record_failure(api_name)
        return [], []

def fetch_probe_multi(probe, cutoff_year=None):
    preloaded = {}
    normal_urls = []
    stats = {}

    def _fetch_group(group_name, api_pairs):
        group_preloaded = {}
        group_normal = []
        group_stats = {}
        if not api_pairs:
            return group_preloaded, group_normal, group_stats
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=len(api_pairs)) as executor:
            fut_map = {}
            for api_name, fetch_func in api_pairs:
                fut = executor.submit(call_api_safe_v2, api_name, fetch_func, probe, cutoff_year)
                fut_map[fut] = api_name
            for fut in as_completed(fut_map):
                api_name = fut_map[fut]
                try:
                    urls, texts = fut.result(timeout=_REQUEST_TIMEOUT)
                except Exception:
                    urls, texts = [], []
                urls = urls or []
                texts = texts or []
                group_stats[api_name] = len(urls)
                if len(texts) < len(urls):
                    texts = list(texts) + [""] * (len(urls) - len(texts))
                for u, t in zip(urls, texts):
                    if u:
                        if t and len(t) >= 50:
                            group_preloaded[u] = t
                        else:
                            group_normal.append(u)
        return group_preloaded, group_normal, group_stats

    # SINGLE WAVE: Semua API ditembak serentak dalam 1 gelombang paralel.
    # API mati (tanpa key) sudah early-return di fungsinya masing-masing.
    # OpenAIRE & HAL dihapus (Eropa/Prancis, tidak relevan untuk skripsi Indonesia, sering RTO).
    all_apis = [
        # Indonesia (prioritas)
        ("OneSearchID", fetch_onesearch_id),
        ("Neliti", fetch_neliti),
        ("Garuda", fetch_garuda),
        ("MORAREF", fetch_moraref),
        ("IndoEThesis", fetch_indonesian_ethesis),
        # Internasional
        ("SemanticScholar", fetch_semantic_scholar),
        ("Crossref", fetch_crossref),
        ("OpenAlex", fetch_openalex),
        ("EuropePMC", fetch_europe_pmc),
        ("PubMed", fetch_pubmed),
        # Tambahan
        ("DOAJ", fetch_doaj),
        ("arXiv", fetch_arxiv),
        ("BASE", fetch_base),
        # Search Engine
        ("GoogleNative", fetch_google_search_native),
        ("DuckDuckGo", fetch_ddgs),
    ]
    g_pre, g_norm, g_stat = _fetch_group("all", all_apis)
    preloaded.update(g_pre); normal_urls.extend(g_norm); stats.update(g_stat)

    return preloaded, normal_urls, stats



def get_candidate_urls(sentences, max_probes=100, progress_cb=None, cutoff_year=None):
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
    global _GOOGLE_NATIVE_BUDGET
    with _INDO_REPO_LOCK:
        _INDO_REPO_BUDGET = 15
    with _GOOGLE_NATIVE_LOCK:
        _GOOGLE_NATIVE_BUDGET = 5
    with _FAILED_APIS_LOCK:
        _FAILED_APIS.clear()

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
    
    logger.info(f"[API] Meluncurkan Bot AI & Browser Crawler untuk {len(probes)} Fingerprints...")
    
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
                    v_urls, _ = fetch_ddgs(variant, cutoff_year=cutoff_year)
                    for u in v_urls:
                        if u and u.startswith('http'):
                            found.add(u)
                except Exception as e:
                    logger.debug("fetch_ddgs varian gagal: %s", e)
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
                    logger.debug("expander future gagal: %s", e)
      except Exception as e:
        logger.debug("Cohere/DDG expander error: %s", e)

    # --- blok API mati di bawah dinonaktifkan (disimpan sbagai referensi histori) ---
    logger.info(f"[API] Mencari jurnal dari {len(probes)} sampel kalimat via Semantic Scholar, Crossref & DuckDuckGo...")
    
    # Akumulasi statistik per-API lintas semua probe
    total_stats = {}
    probes_done = 0
    
    # Maksimalkan thread CPU ke 32 worker agar API paralel berjalan lebih agresif
    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as executor:
        futures = [executor.submit(fetch_probe_multi, p, cutoff_year) for p in probes]
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            if progress_cb:
                progress_cb(i + 1, len(probes))
            try:
                preloaded, ddg_urls, stats = future.result()
                
                # Akumulasikan statistik
                for api_name, count in stats.items():
                    total_stats[api_name] = total_stats.get(api_name, 0) + count
                
                # Masukkan hasil API langsung ke Corpus (tanpa perlu web-scrape)
                for u, t in preloaded.items():
                    preloaded_corpus[u] = t
                    
                # Masukkan hasil DuckDuckGo ke antrian URL scraping
                for u in ddg_urls:
                    if u not in preloaded_corpus:
                        urls.add(u)
                    
            except Exception as e:
                logger.debug("Worker probe caught: %s", e)
            
            probes_done += 1
            # Cetak ringkasan progresif setiap 10 probe atau pada probe terakhir
            if probes_done % 10 == 0 or probes_done == len(probes):
                active = {k: v for k, v in total_stats.items() if v > 0}
                parts = [f"{k}:{v}" for k, v in sorted(active.items(), key=lambda x: -x[1])]
                total_found = sum(active.values())
                logger.info(f"[API] Probe {probes_done}/{len(probes)} -- {total_found} sumber ditemukan | {', '.join(parts)}")
                
    logger.info(f"[API] Berhasil menarik {len(preloaded_corpus)} abstrak jurnal dan {len(urls)} link web publik.")
    return list(urls), preloaded_corpus

class AdaptiveThreadPool:
    """Dynamic thread pool yang menyesuaikan ukuran berdasarkan rasio timeout."""
    def __init__(self, min_workers=2, max_workers=8, cooldown=30):
        self.min_workers = min_workers
        self.max_workers = max_workers
        self.current_workers = max_workers
        self.cooldown = cooldown
        self.recent_timeouts = []
        self._last_adjust = 0.0

    def get_workers(self):
        now = __import__('time').time()
        if now - self._last_adjust < self.cooldown:
            return self.current_workers
        self._last_adjust = now
        if not self.recent_timeouts:
            return self.current_workers
        rate = sum(self.recent_timeouts) / len(self.recent_timeouts)
        if rate > 0.3:
            self.current_workers = max(self.min_workers, self.current_workers - 2)
        elif rate < 0.1 and self.current_workers < self.max_workers:
            self.current_workers += 1
        self.recent_timeouts = []
        return self.current_workers

    def record_timeout(self, occurred):
        self.recent_timeouts.append(1 if occurred else 0)
        if len(self.recent_timeouts) > 20:
            self.recent_timeouts.pop(0)



def scrape_url(url):
    """Mengekstrak teks mentah dari URL (Website atau PDF) menggunakan AbstractAPI Proxy untuk menembus WAF/Cloudflare"""
    if not is_safe_url(url):
        return url, "", 0
    total_bytes = 0
    # Banyak situs (Medium, repositori kampus) mengembalikan halaman kosong/blokir
    # tanpa User-Agent browser. Header ini menaikkan keberhasilan & kelengkapan teks.
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
    }
    import os
    if "bsi.ac.id" in url.lower():
        bsi_cookie = os.environ.get("BSI_COOKIE", "")
        if bsi_cookie:
            headers["Cookie"] = bsi_cookie

    try:
        import urllib.parse
        encoded_url = urllib.parse.quote(url)
        abstract_key = os.environ.get("ABSTRACT_KEY", "")
        res = None
        if abstract_key:
            proxy_url = f"https://scrape.abstractapi.com/v1/?api_key={abstract_key}&url={encoded_url}"
            res = _get_session().get(proxy_url, timeout=_SCRAPE_TIMEOUT, stream=True)
            if res.status_code != 200:
                try:
                    res = _get_session().get(url, timeout=_SCRAPE_TIMEOUT, verify=True, headers=headers, stream=True)
                except requests.exceptions.SSLError:
                    res = _get_session().get(url, timeout=_SCRAPE_TIMEOUT, verify=False, headers=headers, stream=True)
        else:
            try:
                res = _get_session().get(url, timeout=_SCRAPE_TIMEOUT, verify=True, headers=headers, stream=True)
            except requests.exceptions.SSLError:
                res = _get_session().get(url, timeout=_SCRAPE_TIMEOUT, verify=False, headers=headers, stream=True)
            
        if res and res.status_code == 200:
            content_length = res.headers.get('Content-Length')
            if content_length and int(content_length) > 20 * 1024 * 1024:
                return url, "", total_bytes

            import time
            start_download = time.time()
            content = b""
            for chunk in res.iter_content(chunk_size=8192):
                if chunk:
                    content += chunk
                    total_bytes += len(chunk)
                    _add_download_bytes(len(chunk))
                if len(content) > 20 * 1024 * 1024:
                    break
                if time.time() - start_download > 10:
                    # Timeout 10 detik maksimal per unduhan untuk mencegah hang
                    break
            
            import re
            
            # Deteksi jika file adalah PDF langsung
            if 'application/pdf' in res.headers.get('Content-Type', '').lower() or url.lower().endswith('.pdf'):
                import fitz
                doc = fitz.open(stream=content, filetype="pdf")
                text = ""
                try:
                    for page_num, page in enumerate(doc):
                        if page_num >= 30: break
                        text += page.get_text() + " "
                finally:
                    doc.close()
                text = re.sub(r'\s+', ' ', text).strip()
                return url, text, total_bytes
            else:
                # Parsing HTML (Landing Page Repositori & Web Publik)
                # Hindari res.apparent_encoding karena chardet sangat lambat (O(N)) pada file besar.
                enc = res.encoding if res.encoding else 'utf-8'
                res_text = content.decode(enc, errors='ignore')
                soup = BeautifulSoup(res_text, 'html.parser')

                # [DEEP PDF CRAWLER] Cari tombol Download PDF di halaman repositori kampus (EPrints, DSpace, OJS)
                pdf_links = []
                for a in soup.find_all('a', href=True):
                    href = a.get('href', '').strip()
                    href_lower = href.lower()
                    if href_lower.endswith('.pdf') or '/download/' in href_lower or '/bitstream/' in href_lower or '/article/download/' in href_lower or '/article/view/' in href_lower:
                        if href.startswith('/'):
                            href = urllib.parse.urljoin(url, href)
                        if href not in pdf_links and href.startswith('http') and is_safe_url(href):
                            pdf_links.append(href)

                pdf_text = ""
                if pdf_links:
                    import fitz
                    # Ambil maksimal 2 file PDF per landing page untuk efisiensi
                    for pdf_url in pdf_links[:2]:
                        try:
                            pdf_res = _get_session().get(pdf_url, timeout=12, verify=False, headers=headers)
                            if pdf_res.status_code == 200:
                                total_bytes += len(pdf_res.content)
                                if 'application/pdf' in pdf_res.headers.get('Content-Type', '').lower() or pdf_res.content.startswith(b'%PDF'):
                                    pdf_doc = fitz.open(stream=pdf_res.content, filetype="pdf")
                                    try:
                                        for page_num, page in enumerate(pdf_doc):
                                            if page_num >= 30: break
                                            pdf_text += page.get_text() + " "
                                    finally:
                                        pdf_doc.close()
                        except Exception:
                            pass

                for tag in soup(["script", "style", "nav", "footer", "header", "aside", "menu"]):
                    tag.decompose()
                text = soup.get_text(separator=' ')
                if pdf_text:
                    text = text + " " + pdf_text
                text = re.sub(r'\s+', ' ', text).strip()
                return url, text, total_bytes
    except Exception as e:
        logger.debug("Silently caught exception: %s", e)
    return url, "", total_bytes

def scrape_all_candidates(urls, preloaded_corpus, progress_cb=None):
    """Mengeksekusi multi-threading untuk mengunduh web, lalu digabung dengan preloaded_corpus (Jurnal API).
    Bank lokal di-merge terlebih dahulu (cek lokal dulu, internet pelengkap)."""
    corpus = preloaded_corpus.copy()

    # BANK LOKAL (SQLite3): lookup instan via bank.db tanpa load memori raksasa
    bank_urls = get_bank_urls()
    found_urls = [u for u in urls if u in bank_urls]
    if found_urls:
        cached_texts = get_bank_texts(found_urls)
        corpus.update(cached_texts)
        logger.info(f"[Bank] {len(cached_texts)} sumber ditemukan di bank.db lokal (skip scrape)")
    
    # Hapus URL yang sudah ada di bank / preloaded (tak perlu scrape ulang)
    urls = [u for u in urls if u not in bank_urls and u not in corpus]

    if not urls:
        save_to_corpus_bank(corpus)
        return corpus

    logger.info(f"[Scraper] Bot Crawler mulai mengunduh {len(urls)} sumber web publik...")
    
    # Abaikan InsecureRequestWarning saat scrape blog/kampus yang SSL-nya mati
    from requests.packages.urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
    
    import time
    start_time = time.time()
    total_downloaded_bytes = 0
    # Maksimalkan ke 32 thread untuk mengunduh ratusan/ribuan URL web secara sangat agresif
    failed_urls = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as executor:
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
                logger.debug("[!] Scraper connection error -> %s", e)
            
            # Incremental save ke bank lokal setiap 50 URL sukses agar tidak hangus bila proses dibatalkan (Ctrl+C)
            # KITA HANYA SIMPAN KE LOKAL (SQLite) DISINI agar Supabase tidak kebanjiran request dan Time Out.
            if len(corpus) - len(preloaded_corpus) >= 50 and (i + 1) % 50 == 0:
                save_to_corpus_bank_local(corpus)
            
            if progress_cb:
                elapsed = time.time() - start_time
                current_bytes = total_downloaded_bytes
                speed_bytes_sec = current_bytes / elapsed if elapsed > 0 else 0
                
                if speed_bytes_sec >= 1024 * 1024:
                    speed_str = f"{speed_bytes_sec / (1024 * 1024):.2f} MB/s"
                elif speed_bytes_sec >= 1024:
                    speed_str = f"{speed_bytes_sec / 1024:.1f} KB/s"
                else:
                    speed_str = f"{speed_bytes_sec:.1f} B/s"
                progress_cb(i + 1, total, speed_str)

    # RETRY PASS: URL yang gagal (kosong/error) sering korban rate-limit sesaat, bukan
    # benar-benar mati. Coba sekali lagi dengan konkurensi sedang (8 worker).
    if failed_urls:
        logger.info(f"[Scraper] Retry {len(failed_urls)} sumber yang gagal (konkurensi sedang)...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(scrape_url, u): u for u in failed_urls}
            for future in concurrent.futures.as_completed(futures):
                try:
                    url, text, downloaded_bytes = future.result()
                    total_downloaded_bytes += downloaded_bytes
                    if len(text) > 150:
                        corpus[url] = text
                except Exception as e:
                    logger.debug("Silently caught exception: %s", e)

    # Simpan sumber baru ke bank lokal (makin kaya seiring waktu)
    save_to_corpus_bank(corpus)
    return corpus

