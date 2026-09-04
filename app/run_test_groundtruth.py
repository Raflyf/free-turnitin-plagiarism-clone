import os, sys, time, json, re, glob
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.extractor import extract_text_auto, get_sentences
from engine.web_scraper import get_candidate_urls, scrape_all_candidates
from engine.shingling import calculate_similarity

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_documents")
os.makedirs(BASE, exist_ok=True)
FROZEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frozen_corpus")
os.makedirs(FROZEN, exist_ok=True)

# REFRESH=1  -> kumpulkan ulang korpus dari internet (lalu bekukan ke disk).
# default    -> pakai korpus beku (skor 100% reproducible, defensible).
REFRESH = os.environ.get("REFRESH", "0") == "1"


def discover_docs():
    """Auto-discover dokumen validasi di test_documents/.
    Target baseline diambil dari angka 'NN%' di nama file. Slug = nama file
    tanpa angka% & ekstensi, dipakai sbagai key korpus beku."""
    docs = []
    for path in sorted(glob.glob(os.path.join(BASE, "*"))):
        if not path.lower().endswith((".pdf", ".docx", ".txt")):
            continue
        fname = os.path.basename(path)
        m = re.search(r'(\d+)\s*%', fname)
        target = int(m.group(1)) if m else None
        slug = re.sub(r'\s*\d+\s*%', '', os.path.splitext(fname)[0]).strip()
        slug = re.sub(r'[^\w]+', '_', slug).strip('_')[:40]
        docs.append((slug, fname, target))
    return docs


import hashlib

def get_frozen_path(original_filename, doc_hash):
    matches = glob.glob(os.path.join(FROZEN, f"*{doc_hash}.json"))
    if matches:
        return matches[0]
    safe_name = re.sub(r'[^\w\-]', '_', os.path.splitext(original_filename)[0])
    safe_name = re.sub(r'_+', '_', safe_name).strip('_')[:35]
    if not safe_name:
        safe_name = "doc"
    return os.path.join(FROZEN, f"web_{safe_name}_{doc_hash}.json")

summary = []
for name, fname, target in discover_docs():
    path = os.path.join(BASE, fname)
    tgt_str = f"{target}%" if target is not None else "?"
    print(f"\n{'='*60}\n[{name}] target baseline = {tgt_str}\n{'='*60}", flush=True)
    t0 = time.time()
    doc_text, warns = extract_text_auto(path, exclude_quotes=True, exclude_biblio=True)
    doc_hash = hashlib.md5(doc_text.encode("utf-8")).hexdigest()[:16]
    frozen_path = get_frozen_path(fname, doc_hash)

    sentences = get_sentences(doc_text)
    print(f"[{name}] {len(doc_text.split())} kata, {len(sentences)} kalimat", flush=True)

    existing_corpus = {}
    if os.path.exists(frozen_path):
        try:
            with open(frozen_path, "r", encoding="utf-8") as f:
                existing_corpus = json.load(f)
        except Exception:
            existing_corpus = {}

    if not REFRESH and existing_corpus:
        corpus = existing_corpus
        print(f"[{name}] KORPUS BEKU dimuat: {len(corpus)} sumber ({os.path.basename(frozen_path)})", flush=True)
    else:
        if REFRESH:
            print(f"[{name}] REFRESH=1: Memperluas korpus ({len(existing_corpus)} sumber eksis) dengan live scraping...", flush=True)
        adaptive_probes = max(180, min(200, int(len(sentences) / 2.5)))
        print(f"[{name}] ADAPTIVE SAMPLING: {adaptive_probes} probes untuk {len(sentences)} kalimat", flush=True)
        urls, preloaded = get_candidate_urls(sentences, max_probes=adaptive_probes)
        print(f"[{name}] preloaded={len(preloaded)} scrape-urls={len(urls)}", flush=True)
        new_scraped = scrape_all_candidates(urls, preloaded)
        corpus = existing_corpus.copy()
        corpus.update(new_scraped)
        # Atomic write: tulis ke file temp dulu, lalu rename
        import secrets as _secrets
        frozen_tmp = frozen_path + ".tmp." + _secrets.token_hex(4)
        with open(frozen_tmp, "w", encoding="utf-8") as f:
            json.dump(corpus, f, ensure_ascii=False)
        os.replace(frozen_tmp, frozen_path)
        print(f"[{name}] korpus DIPERBARUI ke disk: {len(corpus)} total sumber ({os.path.basename(frozen_path)})", flush=True)

    sources, total_sim, phrases = calculate_similarity(
        doc_text, corpus, exclude_small=True, use_semantic=True, 
        semantic_threshold="auto")
    dt = time.time() - t0
    print(f"[{name}] SKOR LOKAL = {round(total_sim)}%  (target {tgt_str})  [{int(dt)}s]", flush=True)
    print(f"[{name}] TOP SUMBER:", flush=True)
    for s in sources[:8]:
        print(f"    {s['percentage']:.1f}%  {s['url'][:80]}", flush=True)
    summary.append((name, round(total_sim, 1), target, len(corpus), len(sources)))

print(f"\n===== RINGKASAN (3-Tier Auto-Thresholding) =====", flush=True)
for name, local, target, corp, nsrc in summary:
    if target is not None:
        delta = round(local - target, 1)
        print(f"  {name}: lokal={local}% target={target}% delta={delta:+}pt corpus={corp} sumber={nsrc}", flush=True)
    else:
        print(f"  {name}: lokal={local}% target=? corpus={corp} sumber={nsrc}", flush=True)
