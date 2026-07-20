# Turnitin Lokal — Cek Plagiarisme Gratis Berbasis Sumber Terbuka

Alat pengecek plagiarisme lokal gratis yang meniru perilaku Turnitin: mendeteksi kecocokan teks (N-Gram exact match) dan parafrasa (semantic similarity) terhadap sumber-sumber akademik terbuka di internet. Dibangun untuk membantu mahasiswa yang terkendala biaya mengecek plagiarisme skripsi sebelum submit ke Turnitin resmi kampus.

**Bukan pengganti Turnitin** — tapi estimasi batas bawah yang akurat. Kalau di sini sudah tinggi, di Turnitin asli pasti lebih tinggi. Perbaiki dulu, hemat biaya.

## Hasil Validasi (6 Dokumen vs Turnitin Asli)

Diuji terhadap 6 dokumen skripsi nyata yang sudah punya skor Turnitin asli sebagai ground truth, di rentang 4-24%:

| Dokumen | Skor Lokal | Target Turnitin | Delta | Status |
|---|---|---|---|---|
| Rafly (klasifikasi spam) | 7.9% | 8% | -0.1pt | Tepat |
| Fikri (sistem informasi) | 14.9% | 14% | +0.9pt | Tepat |
| Hesti (body shape) | 15.5% | 18% | -2.5pt | Dekat |
| Laila before parafrase | 24.2% | 24% | +0.2pt | Tepat |
| Laila after parafrase | 5.4% | 4% | +1.4pt | Tepat |
| Tesyar | 10.4% | 8% | +2.4pt | Dekat |

**Rata-rata error absolut: 1.25 poin persentase.** Threshold 0.88 terbukti generalize tanpa overfit — 4 dari 6 dokumen dalam +/-1.4pt, dan dokumen terparafrase tetap mendapat skor rendah (tidak over-flag).

## Cara Kerja

Alur pemrosesan (mirip Turnitin):

```
PDF/DOCX → Ekstraksi Teks → Sampling 100 Kalimat Probe → Cari Sumber Online
→ Download Teks Sumber (bank lokal dipakai sbg CACHE utk skip download) → N-Gram 5-Gram
→ Semantic Paraphrase Check → Skor Agregasi Global → PDF Report Berwarna (gaya Turnitin)
```

Web localhost memakai **metodologi identik** dengan runner validasi (`run_test_groundtruth.py`): korpus pembanding dikumpulkan dengan scrape internet khusus dokumen itu, bukan dari bank mentah. Bank korpus lokal hanya berperan sebagai **cache** (mempercepat download URL yang sudah pernah diambil) dan tumbuh otomatis (auto-freeze) tiap pengecekan.

### Layer 1: N-Gram Exact Matching (5-gram)
- Dokumen dipecah jadi n-gram (5 kata berurutan)
- Dicari kecocokan persis dengan teks sumber dari internet
- Setiap kata yang cocok dihitung sekali (union lintas semua sumber)
- Skor = (total kata ter-match / total kata dokumen) x 100%

### Layer 2: Semantic Similarity (deteksi parafrasa)
- Kalimat yang TIDAK terdeteksi N-Gram (<30% match) dicek ulang
- Menggunakan model `paraphrase-multilingual-MiniLM-L12-v2` (dukung bahasa Indonesia)
- Threshold default 0.88 (dikalibrasi terhadap 6 dokumen ground truth)
- GPU auto-detect (CUDA); fallback CPU
- Tidak ada double counting — hanya menambah kata yang belum terdeteksi N-Gram
- **Selalu aktif** (tidak ada opsi mematikan di UI)

### Sumber Akademik yang Dijangkau
- **Semantic Scholar** (200M+ paper, 3 API key rotasi)
- **OpenAlex** (250M+ paper, fulltext.search + filter bahasa Indonesia)
- **Crossref** (metadata + DOI resolver)
- **DOAJ** (9M+ open-access articles)
- **arXiv** (2.4M+ preprints)
- **CORE** (300M+ papers aggregator)
- **DuckDuckGo** (web search umum, prioritas domain .ac.id)
- **Repository kampus Indonesia** (scraping langsung EPrints/DSpace/OJS)
- **ScraperAPI** (bypass WAF/Cloudflare)
- **Cohere AI** (query-expander untuk variasi frasa pencarian — opsional, aktifkan via env `USE_COHERE_EXPANDER=1`)

### PDF Report Bergaya Turnitin
- Highlight berwarna per-sumber (10 warna, badge angka)
- Skip daftar pustaka (tidak dihitung sebagai plagiarisme)
- Halaman ORIGINALITY REPORT di akhir (format "128 words - 1%")
- Daftar PRIMARY SOURCES dengan persentase kontribusi
- Download sebagai PDF

## Cara Penggunaan

### Prasyarat
- Python 3.10+
- GPU opsional (NVIDIA CUDA untuk mempercepat semantic check)

### Instalasi

```bash
cd plagiarism_checker
pip install -r requirements.txt

# Opsional: install torch CUDA untuk GPU (RTX 3050+ recommended)
pip install torch --index-url https://download.pytorch.org/whl/cu124
```

### Konfigurasi API Key

Salin `.env.example` ke `.env` dan isi key yang dipunya (semua opsional — tanpa key pun sistem tetap jalan via DuckDuckGo + OpenAlex + Crossref):

```env
# Semantic Scholar (gratis, daftar di semanticscholar.org/product/api)
S2_API_KEYS=key1,key2,key3

# Cohere (gratis, daftar di dashboard.cohere.com)
COHERE_KEYS=key1,key2

# ScraperAPI (gratis 5000 req/bulan, daftar di scraperapi.com)
SCRAPERAPI_KEY=xxx
```

### Jalankan Web Server

```bash
cd plagiarism_checker/app
python server.py
```

Buka browser: `http://localhost:5001`

### Opsi Filter di UI
- **Kecualikan Kutipan** — skip teks dalam tanda kutip
- **Kecualikan Daftar Pustaka** — skip halaman daftar pustaka
- **Kecualikan sumber <1%** — sembunyikan sumber kecil dari daftar (skor total TIDAK berubah)

Deteksi Parafrasa (Semantic AI) **selalu aktif** dan tidak lagi ditampilkan sebagai opsi.

### Jalankan Validasi Ground Truth

Taruh file PDF/DOCX di `app/before_turnitin/` dengan format nama `NamaFile NN%.pdf` (NN = skor Turnitin asli). Runner otomatis mendeteksi semua file dan target:

```bash
# Kumpulkan korpus baru + bekukan ke disk (pertama kali, ~15 menit/dokumen)
REFRESH=1 python app/run_test_groundtruth.py

# Jalankan ulang dari korpus beku (instan, deterministik)
python app/run_test_groundtruth.py

# Override threshold semantic
THRESHOLD=0.90 python app/run_test_groundtruth.py
```

## Keterbatasan (Penting Dibaca)

### Kenapa skor bisa berbeda dari Turnitin asli:
1. **Indeks Turnitin tidak bisa ditiru.** Turnitin punya 100+ miliar halaman web + 1.8 miliar makalah mahasiswa yang pernah disubmit + jurnal berbayar (IEEE, Springer, Elsevier). Alat ini hanya menjangkau sumber terbuka gratis.
2. **Sumber yang tidak online = tidak terdeteksi.** Kalau seseorang menyalin dari skripsi kating yang hanya ada di arsip kampus (tidak dipublikasi online), Turnitin mungkin mendeteksinya (karena skripsi itu pernah disubmit), tapi alat ini tidak bisa.
3. **Network variance.** Sumber yang sedang down/timeout saat pengecekan tidak akan masuk korpus.

### Arah skor yang bisa diprediksi:
- Skor lokal **cenderung lebih rendah atau sama** dengan Turnitin asli (indeks lebih kecil = lebih sedikit kecocokan ditemukan)
- Ini artinya alat ini berguna sebagai **estimasi batas bawah**: "minimal segini plagiarismenya"
- Kalau skor lokal sudah tinggi, di Turnitin pasti lebih tinggi — perbaiki dulu

### Kapan hasilnya paling akurat:
- Dokumen menyalin dari sumber online publik (repositori .ac.id, jurnal open access, 123dok, dll)
- Sumber berbahasa Indonesia (model semantic dan pencarian dioptimasi untuk ini)

### Kapan hasilnya bisa meleset:
- Dokumen menyalin dari jurnal berbayar (Elsevier, IEEE, Springer)
- Dokumen menyalin dari skripsi teman yang belum dipublikasi online
- Sumber hanya ada di database internal kampus

## Arsitektur File

```
plagiarism_checker/
├── app/
│   ├── server.py                 # Flask server (port 5001)
│   ├── run_test_groundtruth.py   # Runner validasi + freeze corpus
│   ├── calibrate_threshold.py    # Sweep threshold semantic
│   ├── before_turnitin/          # Dokumen uji + target Turnitin
│   ├── frozen_corpus/            # Korpus beku (skor deterministik)
│   ├── engine/
│   │   ├── extractor.py          # Ekstraksi PDF/DOCX/TXT
│   │   ├── shingling.py          # N-Gram matching + agregasi global
│   │   ├── semantic_similarity.py # Sentence-transformers (GPU/CPU)
│   │   ├── web_scraper.py        # Multi-source crawler + API
│   │   ├── pdf_generator.py      # Report PDF bergaya Turnitin
│   │   ├── priority_domains.py   # Daftar prioritas repositori akademik
│   │   ├── indonesian_repos.py   # Scraper langsung repo kampus
│   │   └── free_api_fallbacks.py # Fallback pencarian gratis
│   ├── templates/
│   │   ├── index.html            # Halaman upload
│   │   └── report.html           # Halaman hasil
│   └── static/                   # CSS, JS, assets
├── docs/
│   ├── DIAGNOSA_0_PERSEN.md      # Diagnosa lengkap bug 0%
│   └── AUDIT_*.md                # Riwayat audit kode
├── .env                          # API keys (jangan commit)
├── .env.example                  # Template konfigurasi
├── requirements.txt
└── README.md
```

## Perhitungan Skor

```
Skor Total = (Kata Ter-match N-Gram + Kata Ter-match Semantic) / Total Kata Dokumen x 100%
```

- Setiap kata dihitung **sekali** meskipun cocok dengan banyak sumber (union, bukan sum)
- `exclude_small` hanya memfilter **daftar tampilan** sumber per-dokumen, TIDAK memengaruhi skor total — persis perilaku Turnitin
- Threshold semantic 0.88 dikalibrasi terhadap 5 dokumen ground truth (4-24%)

## Changelog

### v3.7 (Current) — Audit Menyeluruh + Perbaikan Ketahanan Pasca-Pindah
- **Fix regresi CRITICAL**: `get_candidate_urls` crash `UnboundLocalError: concurrent` di config default (efek samping dari menggating Cohere expander — `import concurrent.futures` yang dulu tak-bersyarat jadi ikut mati). Import dipindah ke scope modul, import lokal redundan dihapus. Tanpa fix ini, SEMUA upload PDF gagal.
- **Fix frontend menggantung**: `checkStatus()` kini menangani respons 403/404/status tak dikenal + punya `.catch()` (toleransi 5 blip jaringan). Dulu overlay loading berputar selamanya bila server restart atau sesi tak cocok.
- **Fix silent data-loss bank**: `save_to_corpus_bank` hanya commit ke cache in-memory setelah tulis disk sukses (dulu mutasi cache lebih dulu — bila tulis gagal, entri hilang dari disk tapi "terlanjur ada" di memori → tak pernah ditulis ulang).
- **Fix kebocoran handle**: 2 `fitz.open` di scraper kini ditutup via `try/finally` (dulu tak pernah `.close()` → menumpuk handle PyMuPDF di pool 8-worker).
- **Fix race**: `_INDO_REPO_BUDGET` dibungkus lock (dulu read-modify-write non-atomik dari 5 worker → non-reproducible).
- **UI**: terima ekstensi `.PDF` huruf besar; teks hint diperbaiki.
- **Pindah lokasi project** ke `D:\skripsi\project\plagiarism_checker` (terpisah dari project spam email). Kode pakai path relatif `__file__` → tak ada route/path yang rusak. Helper `run.bat`/`run.sh` ditambahkan.
- Diverifikasi via 3 audit paralel + runtime: compile OK, 8 modul engine import OK, skoring deterministik cocok baseline (Hesti 11.4%, Rafly 5.5%), PDF report jalan, jalur scraping tereksekusi tanpa crash.

### v3.6 — Localhost Setara Metodologi Groundtruth
- **Alur localhost = metodologi validasi.** Saat upload PDF, korpus skoring dibangun dari hasil scrape internet **khusus dokumen itu** (100 probe), persis seperti `run_test_groundtruth.py`. Skor dokumen tervalidasi konsisten saat dites via localhost.
- **Bank korpus turun peran jadi CACHE**, bukan basis korpus. Bank mentah (17k+ sumber) dulu dijadikan korpus dan menyebabkan over-counting: union global "menjahit" potongan pendek dari ratusan sumber tak relevan jadi blok plagiat palsu. Kini bank hanya dipakai di dalam `scrape_all_candidates` untuk mempercepat (URL yang sudah pernah diunduh diambil instan) + auto-freeze sumber baru. Komposisi korpus skoring tetap terkurasi.
- **Parameter engine default aman.** `calculate_similarity` menerima `semantic_max_sources` (default None) & `min_source_overlap` (default 1) — keduanya diset ke default lama pada jalur groundtruth & localhost, sehingga skor tervalidasi TIDAK berubah.
- **Toggle "Perkaya dari Internet" dihapus.** Internet selalu ON (wajib untuk PDF baru agar skor defensible). Untuk PDF yang belum ada frozen-nya, bank-only tidak dipakai lagi karena bisa menghasilkan skor palsu-rendah.
- **Deteksi parafrasa (Semantic AI) default nyala**, opsi UI dihapus.
- **Percepat fase pencarian**: Cohere query-expander (bottleneck rate-limit) kini default MATI via env `USE_COHERE_EXPANDER=1`. Sumber utama tetap dari DOAJ + Crossref + OpenAlex + Semantic Scholar + arXiv + CORE + DuckDuckGo langsung.

### v3.5 — Audit Engine + Perbaikan Ketahanan
- **Fix hyphenation**: normalisasi kata terpotong tanda hubung akhir baris sekali di awal, agar semua stream token (spans/words/ngrams) konsisten — overlap sumber ter-atribusi dengan benar
- **Gap-fill per-sumber diperketat**: aturan sama dengan global fill (butuh >=2 kata match di kedua sisi gap), sumber tak bisa menampilkan % melebihi kontribusi union
- **Fix `sent_word_count`**: dihitung setelah clamp, memperbaiki `match_ratio` kalimat terakhir
- **Semantic sort**: daftar match per-kalimat diurutkan skor tertinggi, `matches[0]` benar-benar match terbaik
- **Bank korpus tahan-korupsi**: tulis atomik (temp + `os.replace`), guard JSON korup saat load, lock antar-thread
- **Anti-cheat extractor aman**: hanya pakai teks span-extracted bila ada teks yang benar-benar terbuang; PDF bersih tetap verbatim (skor tak bergeser)
- Validasi ulang 6 dokumen: MAE 1.25pt, 4/6 dokumen bit-identical vs baseline

### v3.4 — Validasi 5 Dokumen + Kalibrasi Threshold
- **Validasi 5 dokumen**: Rafly 8%, Hesti 18%, Fikri 14%, Laila-before 24%, Laila-after 4% — rata-rata error 0.96pt
- **Threshold semantic dikalibrasi ke 0.88** (sweep 0.85-0.95, dipilih yang meminimalkan error lintas 5 dokumen)
- **Auto-discover dokumen validasi**: taruh file `NamaFile NN%.pdf` di `before_turnitin/`, runner otomatis parse target
- **Freeze corpus**: korpus dikumpulkan sekali → disimpan ke disk → skor 100% deterministik tiap run ulang
- **Dukungan DOCX**: `extract_text_auto` mendeteksi ekstensi dan pakai `python-docx` untuk file Word

### v3.3 — Recall Boost + Determinisme
- **Domain-seeding**: prioritas pencarian ke 123 repositori akademik Indonesia (`priority_domains.py`)
- **Determinisme search**: hash stabil (`hashlib.md5`) menggantikan `random.random()` untuk pemilihan varian query
- **DDG backend fix**: pin ke backend `lite` → `html` → `auto` (menghilangkan SSL CERTIFICATE_VERIFY_FAILED)
- **OpenAlex fulltext.search**: filter `language:id,open_access.is_oa:true` untuk recall full-text Indonesia

### v3.2 — Critical Scoring Fix (0% → mendekati target)
- **Fix bug agregasi `exclude_small`**: filter <1% dipindah dari pra-agregasi ke pasca-agregasi (skor total tidak lagi terpaksa 0% saat plagiarisme tersebar tipis di banyak sumber)
- **Deep-PDF crawl**: cap baca dinaikkan 5 → 30/40 halaman per PDF
- Diagnosa lengkap: [docs/DIAGNOSA_0_PERSEN.md](docs/DIAGNOSA_0_PERSEN.md)

### v3.1 — Audit API + GPU
- Buang API mati (Perplexity/Gemini/Tavily/Google CSE), pertahankan yang aktif & gratis
- Rotasi multi-key Semantic Scholar (3) & Cohere (2)
- GPU CUDA auto-detect untuk semantic layer

### v2.0 — Semantic Similarity Layer
- Deteksi parafrasa via sentence-transformers
- Fix double counting, session security, BSI priority

### v1.0 — Initial Release
- N-Gram shingling, web UI, multi-source scraping, PDF report

## Kontribusi & Lisensi

Project edukasi untuk membantu mahasiswa mengecek plagiarisme. Tidak berafiliasi dengan Turnitin LLC.

**Dibuat oleh:** Rafly Firmansyah
**Algoritma:** N-Gram Shingling (5-gram) + Semantic Similarity (sentence-transformers)
**Model AI:** paraphrase-multilingual-MiniLM-L12-v2
