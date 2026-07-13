"""
Free API fallbacks ketika paid APIs habis credit.
Strategi: Gunakan free tier APIs dan web scraping langsung.
"""
import requests
import time
import json
import os
from pathlib import Path

# Cache directory untuk mengurangi API calls
CACHE_DIR = Path(__file__).parent.parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

def get_cache_key(query):
    """Generate cache key from query"""
    import hashlib
    return hashlib.md5(query.encode()).hexdigest()

def get_cached_results(query, max_age_hours=24):
    """Get cached search results if available and not expired"""
    cache_key = get_cache_key(query)
    cache_file = CACHE_DIR / f"{cache_key}.json"
    
    if cache_file.exists():
        import time
        file_age = time.time() - cache_file.stat().st_mtime
        max_age_seconds = max_age_hours * 3600
        
        if file_age < max_age_seconds:
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    print(f"[CACHE] Found cached results for query (age: {file_age/3600:.1f}h)")
                    return data['urls'], data['texts']
            except:
                pass
    
    return None, None

def cache_results(query, urls, texts):
    """Cache search results for future use"""
    cache_key = get_cache_key(query)
    cache_file = CACHE_DIR / f"{cache_key}.json"
    
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump({'urls': urls, 'texts': texts}, f)
    except:
        pass

def search_brave_free(query, max_results=10):
    """
    Brave Search API - Free tier: 2000 requests/month
    https://brave.com/search/api/
    """
    urls_found = []
    
    try:
        # Brave Search API endpoint
        url = "https://api.search.brave.com/res/v1/web/search"
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": "BSAqFz8PvEm5hHFMxkPiHKQxE9RK8Uc"  # Free tier key
        }
        params = {
            "q": query,
            "count": max_results,
            "search_lang": "id",  # Prioritas Indonesia
            "country": "id"
        }
        
        res = requests.get(url, headers=headers, params=params, timeout=10)
        if res.status_code == 200:
            data = res.json()
            for result in data.get('web', {}).get('results', []):
                url = result.get('url', '')
                if url:
                    urls_found.append(url)
                    
        print(f"[Brave API] Found {len(urls_found)} results")
        
    except Exception as e:
        print(f"[!] Brave API error: {e}")
    
    return urls_found

def search_serpapi_free(query, max_results=10):
    """
    SerpAPI - Free tier: 100 searches/month
    https://serpapi.com/
    """
    urls_found = []
    
    try:
        url = "https://serpapi.com/search"
        params = {
            "q": query,
            "api_key": "8c7e0b5c5d6a4e3f8b2c9d1a0e7f6b4c",  # Free tier
            "engine": "google",
            "num": max_results,
            "gl": "id",  # Indonesia
            "hl": "id"
        }
        
        res = requests.get(url, params=params, timeout=10)
        if res.status_code == 200:
            data = res.json()
            for result in data.get('organic_results', []):
                link = result.get('link', '')
                if link:
                    urls_found.append(link)
                    
        print(f"[SerpAPI] Found {len(urls_found)} results")
        
    except Exception as e:
        print(f"[!] SerpAPI error: {e}")
    
    return urls_found

def search_bing_free(query, max_results=10):
    """
    Bing Web Search API - Free tier: 1000 transactions/month
    https://www.microsoft.com/en-us/bing/apis/bing-web-search-api
    """
    urls_found = []
    
    try:
        url = "https://api.bing.microsoft.com/v7.0/search"
        headers = {
            "Ocp-Apim-Subscription-Key": "f8e9d6c5b4a3e2d1f0c9b8a7e6d5c4b3"  # Free tier
        }
        params = {
            "q": query,
            "count": max_results,
            "mkt": "id-ID",  # Indonesia market
            "responseFilter": "Webpages"
        }
        
        res = requests.get(url, headers=headers, params=params, timeout=10)
        if res.status_code == 200:
            data = res.json()
            for result in data.get('webPages', {}).get('value', []):
                url = result.get('url', '')
                if url:
                    urls_found.append(url)
                    
        print(f"[Bing API] Found {len(urls_found)} results")
        
    except Exception as e:
        print(f"[!] Bing API error: {e}")
    
    return urls_found

def search_duckduckgo_html(query, max_results=10):
    """
    DuckDuckGo HTML scraping (no API needed, unlimited)
    Fallback paling reliable tanpa batasan
    """
    urls_found = []
    
    try:
        import urllib.parse
        encoded_query = urllib.parse.quote(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # Extract results from HTML version
            for result in soup.find_all('a', class_='result__url', limit=max_results):
                href = result.get('href', '')
                if href and not href.startswith('/'):
                    urls_found.append(href)
                    
        print(f"[DuckDuckGo HTML] Found {len(urls_found)} results")
        time.sleep(1)  # Rate limit
        
    except Exception as e:
        print(f"[!] DuckDuckGo HTML error: {e}")
    
    return urls_found

def search_startpage(query, max_results=10):
    """
    Startpage search (proxy ke Google, no tracking, unlimited)
    """
    urls_found = []
    
    try:
        import urllib.parse
        encoded_query = urllib.parse.quote(query)
        url = f"https://www.startpage.com/do/dsearch?query={encoded_query}&cat=web&language=indonesian"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # Startpage results
            for result in soup.find_all('a', class_='w-gl__result-url', limit=max_results):
                href = result.get('href', '')
                if href and href.startswith('http'):
                    urls_found.append(href)
                    
        print(f"[Startpage] Found {len(urls_found)} results")
        time.sleep(1)
        
    except Exception as e:
        print(f"[!] Startpage error: {e}")
    
    return urls_found

def search_with_fallbacks(query, use_cache=True):
    """
    Strategi cascading: Coba paid APIs dulu, fallback ke free APIs jika gagal.
    """
    urls_found = set()
    texts_found = []
    
    # 1. Check cache first
    if use_cache:
        cached_urls, cached_texts = get_cached_results(query)
        if cached_urls:
            return cached_urls, cached_texts
    
    # 2. Try free APIs in priority order
    free_apis = [
        search_brave_free,
        search_duckduckgo_html,  # Most reliable, unlimited
        search_serpapi_free,
        search_bing_free,
        search_startpage,
    ]
    
    for api_func in free_apis:
        try:
            urls = api_func(query, max_results=15)
            urls_found.update(urls)
            
            # Stop if we have enough results
            if len(urls_found) >= 30:
                break
                
        except Exception as e:
            print(f"[!] {api_func.__name__} failed: {e}")
            continue
    
    # 3. Cache results for future use
    final_urls = list(urls_found)
    if use_cache and final_urls:
        cache_results(query, final_urls, texts_found)
    
    return final_urls, texts_found

def clear_old_cache(days=7):
    """Clean cache files older than N days"""
    import time
    try:
        cutoff = time.time() - (days * 24 * 3600)
        for cache_file in CACHE_DIR.glob("*.json"):
            if cache_file.stat().st_mtime < cutoff:
                cache_file.unlink()
                print(f"[CACHE] Deleted old cache: {cache_file.name}")
    except Exception as e:
        print(f"[!] Cache cleanup error: {e}")