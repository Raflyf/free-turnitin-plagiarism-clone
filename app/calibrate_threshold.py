import os, sys, json, time
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.extractor import extract_text_from_pdf
from engine.shingling import calculate_similarity

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "before_turnitin")
FROZEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frozen_corpus")

DOCS = [
    ("Rafly", "Rafly FIrmansyah - Skripsi_Fix.pdf", 8),
    ("Hesti", "Hesti_skripsi_final_before_turnitin.pdf", 18),
]

# Threshold semantic yang diuji. Korpus BEKU -> tak ada scrape ulang, cepat.
THRESHOLDS = [0.85, 0.88, 0.90, 0.92, 0.95]

results = {}
for name, fname, target in DOCS:
    path = os.path.join(BASE, fname)
    frozen_path = os.path.join(FROZEN, f"{name}.json")
    doc_text, _ = extract_text_from_pdf(path)
    with open(frozen_path, "r", encoding="utf-8") as f:
        corpus = json.load(f)
    print(f"\n{'='*60}\n[{name}] korpus beku {len(corpus)} sumber, target {target}%\n{'='*60}", flush=True)

    # N-Gram saja (baseline tanpa semantic) sebagai referensi
    _, ng_only, _ = calculate_similarity(doc_text, corpus, exclude_small=True, use_semantic=False)
    print(f"[{name}] N-Gram saja = {ng_only:.2f}%", flush=True)

    row = {"target": target, "ngram_only": round(ng_only, 2), "sweep": {}}
    for th in THRESHOLDS:
        _, total, _ = calculate_similarity(doc_text, corpus, exclude_small=True,
                                           use_semantic=True, semantic_threshold=th)
        row["sweep"][th] = round(total, 2)
        print(f"[{name}] threshold {th} -> {total:.2f}%  (target {target}%)", flush=True)
    results[name] = row

print("\n===== TABEL KALIBRASI =====", flush=True)
print(f"{'threshold':<12}" + "".join(f"{n:<12}" for n,_,_ in DOCS), flush=True)
print(f"{'N-Gram only':<12}" + "".join(f"{results[n]['ngram_only']:<12}" for n,_,_ in DOCS), flush=True)
for th in THRESHOLDS:
    print(f"{th:<12}" + "".join(f"{results[n]['sweep'][th]:<12}" for n,_,_ in DOCS), flush=True)
print("targets:    " + "".join(f"{t:<12}" for _,_,t in DOCS), flush=True)

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration_result.json"), "w") as f:
    json.dump(results, f, indent=2)
