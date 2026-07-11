import time
import random
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
from ddgs import DDGS

def fetch_probe(probe):
    """Mencari satu probe ke DuckDuckGo"""
    urls_found = []
    try:
        ddgs = DDGS()
        short_probe = " ".join(probe.split()[:15])
        results = ddgs.text(f'{short_probe}', max_results=8)
        for res in list(results):
            if 'href' in res and not res['href'].endswith('.pdf'): 
                urls_found.append(res['href'])
        # Jeda lebih singkat karena sudah disebar ke beberapa thread
        time.sleep(random.uniform(0.5, 1.5))
    except Exception as e:
        pass
    return urls_found

def get_candidate_urls(sentences, max_probes=120):
    """Mencari kandidat URL jurnal/referensi menggunakan sampel kalimat"""
    probes = random.sample(sentences, min(len(sentences), max_probes))
    urls = set()
    
    print(f"Mencari kandidat URL dari {len(probes)} sampel kalimat (Multi-Threading Cepat)...")
    
    # Gunakan 8 pekerja paralel untuk mencari di mesin pencari.
    # Waktu akan terpangkas drastis dari ~5 menit menjadi kurang dari 1 menit
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = executor.map(fetch_probe, probes)
        for res_urls in results:
            urls.update(res_urls)
            
    print(f"Berhasil mengumpulkan {len(urls)} kandidat URL.")
    return list(urls)

def scrape_url(url):
    """Mengunduh konten teks dari suatu URL (Mirip crawler bot Turnitin)"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
        }
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            # Ambil semua teks dari tag paragraf
            paragraphs = soup.find_all(['p', 'div', 'span'])
            text = " ".join([p.get_text() for p in paragraphs])
            # Bersihkan teks
            import re
            text = re.sub(r'\s+', ' ', text).strip()
            return url, text
    except:
        pass
    return url, ""

def scrape_all_candidates(urls):
    """Mengeksekusi multi-threading untuk mendownload isi artikel dari web"""
    corpus = {}
    print(f"Mengunduh isi dari {len(urls)} sumber web secara paralel...")
    
    with ThreadPoolExecutor(max_workers=40) as executor:
        results = executor.map(scrape_url, urls)
        for url, text in results:
            if len(text) > 100: # Hanya simpan web yang memiliki konten valid
                corpus[url] = text
                
    return corpus
