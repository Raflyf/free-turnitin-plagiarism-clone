import os, sys, time, json, re, glob
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.extractor import extract_text_auto, get_sentences
from engine.web_scraper import get_candidate_urls, scrape_all_candidates
from engine.shingling import calculate_similarity

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "before_turnitin")
FROZEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frozen_corpus")
os.makedirs(FROZEN, exist_ok=True)

# REFRESH=1  -> kumpulkan ulang korpus dari internet (lalu bekukan ke disk).
# default    -> pakai korpus beku (skor 100% reproducible, defensible).
REFRESH = os.environ.get("REFRESH", "0") == "1"
# THRESHOLD -> ambang semantic (default 0.90; berprinsip, setia perilaku Turnitin).
THRESHOLD = float(os.environ.get("THRESHOLD", "0.90"))


def discover_docs():
    """Auto-discover dokumen validasi di before_turnitin/.
    Target Turnitin diambil dari angka 'NN%' di nama file. Slug = nama file
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


summary = []
for name, fname, target in discover_docs():
    path = os.path.join(BASE, fname)
    frozen_path = os.path.join(FROZEN, f"{name}.json")
    tgt_str = f"{target}%" if target is not None else "?"
    print(f"\n{'='*60}\n[{name}] target Turnitin = {tgt_str}\n{'='*60}", flush=True)
    t0 = time.time()
    doc_text, warns = extract_text_auto(path)
    sentences = get_sentences(doc_text)
    print(f"[{name}] {len(doc_text.split())} kata, {len(sentences)} kalimat", flush=True)

    if not REFRESH and os.path.exists(frozen_path):
        with open(frozen_path, "r", encoding="utf-8") as f:
            corpus = json.load(f)
        print(f"[{name}] KORPUS BEKU dimuat: {len(corpus)} sumber (deterministik)", flush=True)
    else:
        urls, preloaded = get_candidate_urls(sentences, max_probes=100)
        print(f"[{name}] preloaded={len(preloaded)} scrape-urls={len(urls)}", flush=True)
        corpus = scrape_all_candidates(urls, preloaded)
        with open(frozen_path, "w", encoding="utf-8") as f:
            json.dump(corpus, f, ensure_ascii=False)
        print(f"[{name}] korpus DIBEKUKAN ke disk: {len(corpus)} sumber", flush=True)

    sources, total_sim, phrases = calculate_similarity(
        doc_text, corpus, exclude_small=True, use_semantic=True, semantic_threshold=THRESHOLD)
    dt = time.time() - t0
    print(f"[{name}] SKOR LOKAL = {round(total_sim)}%  (target {tgt_str})  [{int(dt)}s]", flush=True)
    print(f"[{name}] TOP SUMBER:", flush=True)
    for s in sources[:8]:
        print(f"    {s['percentage']:.1f}%  {s['url'][:80]}", flush=True)
    summary.append((name, round(total_sim, 1), target, len(corpus), len(sources)))

print(f"\n===== RINGKASAN (threshold={THRESHOLD}) =====", flush=True)
for name, local, target, corp, nsrc in summary:
    if target is not None:
        delta = round(local - target, 1)
        print(f"  {name}: lokal={local}% target={target}% delta={delta:+}pt corpus={corp} sumber={nsrc}", flush=True)
    else:
        print(f"  {name}: lokal={local}% target=? corpus={corp} sumber={nsrc}", flush=True)
