"""Bandingkan threshold pada SEMUA korpus beku (instan, tanpa scrape).
Dipakai untuk memilih threshold final yang paling valid vs target Turnitin.
Auto-discover dokumen & target dari nama file di before_turnitin/, cocokkan
dengan korpus beku via slug yang sama seperti run_test_groundtruth.py."""
import os, sys, json, re, glob
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.extractor import extract_text_auto
from engine.shingling import calculate_similarity

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "before_turnitin")
FROZEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frozen_corpus")

THRESHOLDS = [float(x) for x in os.environ.get("THRESHOLDS", "0.88,0.90").split(",")]


def discover():
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


rows = []
for slug, fname, target in discover():
    frozen_path = os.path.join(FROZEN, f"{slug}.json")
    if not os.path.exists(frozen_path):
        print(f"[SKIP] {slug}: korpus beku belum ada", flush=True)
        continue
    doc_text, _ = extract_text_auto(os.path.join(BASE, fname))
    with open(frozen_path, "r", encoding="utf-8") as f:
        corpus = json.load(f)
    scores = {}
    for th in THRESHOLDS:
        _, total, _ = calculate_similarity(doc_text, corpus, exclude_small=True,
                                           use_semantic=True, semantic_threshold=th)
        scores[th] = round(total, 1)
    rows.append((slug[:24], target, scores))
    print(f"[{slug[:24]:24}] target={target}% " +
          " ".join(f"th{th}={scores[th]}%" for th in THRESHOLDS), flush=True)

print("\n===== TABEL PERBANDINGAN =====", flush=True)
hdr = f"{'dokumen':<26}{'target':<8}" + "".join(f"{'th'+str(th):<10}" for th in THRESHOLDS) + "best"
print(hdr, flush=True)
mae = {th: 0.0 for th in THRESHOLDS}
for slug, target, scores in rows:
    if target is None:
        continue
    best_th = min(THRESHOLDS, key=lambda t: abs(scores[t] - target))
    line = f"{slug:<26}{str(target)+'%':<8}"
    for th in THRESHOLDS:
        d = scores[th] - target
        line += f"{str(scores[th])+f'({d:+.0f})':<10}"
        mae[th] += abs(d)
    line += f"th{best_th}"
    print(line, flush=True)
n = sum(1 for _, t, _ in rows if t is not None)
print(f"\nMAE (rata-rata |delta|) untuk {n} dokumen:", flush=True)
for th in THRESHOLDS:
    print(f"  threshold {th}: MAE = {mae[th]/n:.2f} pt", flush=True)
best_overall = min(THRESHOLDS, key=lambda t: mae[t])
print(f"\n>>> THRESHOLD TERBAIK (MAE terkecil): {best_overall}", flush=True)
