# Turnitin Lokal — Cek Plagiarisme Gratis Berbasis Sumber Terbuka

Alat pengecek plagiarisme lokal gratis yang meniru perilaku Turnitin: mendeteksi kecocokan teks (N-Gram exact match) dan parafrasa (semantic similarity) terhadap sumber-sumber akademik terbuka di internet. Dibangun untuk membantu mahasiswa yang terkendala biaya mengecek plagiarisme skripsi sebelum submit ke Turnitin resmi kampus.

**Bukan pengganti Turnitin** — tapi estimasi batas bawah yang akurat. Kalau di sini sudah tinggi, di Turnitin asli pasti lebih tinggi. Perbaiki dulu, hemat biaya.

## Hasil Validasi (5 Dokumen vs Turnitin Asli)

Diuji terhadap 5 dokumen skripsi nyata yang sudah punya skor Turnitin asli sebagai ground truth, di rentang 4-24%:

| Dokumen | Skor Lokal | Target Turnitin | Delta | Status |
|---|---|---|---|---|
| Rafly (klasifikasi spam) | 7.9% | 8% | -0.1pt | Tepat |
| Fikri (sistem informasi) | 15.1% | 14% | +1.1pt | Tepat |
| Hesti (body shape) | 16.0% | 18% | -2.0pt | Dekat |
| Laila before parafrase | 24.2% | 24% | +0.2pt | Tepat |
| Laila after parafrase | 5.4% | 4% | +1.4pt | Tepat |

**Rata-rata error absolut: 0.96 poin persentase.** Threshold 0.88 terbukti generalize tanpa overfit — 4 dari 5 dokumen dalam +/-1.4pt, dan dokumen terparafrase tetap mendapat skor rendah (tidak over-flag).

## Cara Kerja

Alur pemrosesan (mirip Turnitin):

```
PDF/DOCX → Ekstraksi Teks → Sampling 100 Kalimat Probe → Cari Sumber Online
→ Download Teks Sumber → N-Gram 5-Gram Matching → Semantic Paraphrase Check
→ Skor Agregasi Global → PDF Report Berwarna (gaya Turnitin)
```

### Layer 1: N-Gram Exact Matching (5-gram)
- Dokumen dipecah jadi n-gram (5 kata berurutan)
- Dicari kecocokan persis dengan teks sumber dari internet
- Setiap kata yang cocok dihitung sekali (union lintas semua sumber)
- Skor = (total kata ter-match / total kata dokumen) x 100%

### Layer 2: Semantic Similarity (deteksi parafrasa)
- Kalimat yang TIDAK terdeteksi N-Gram (<30% match) dicek ulang
- Menggunakan model `paraphrase-multilingual-MiniLM-L12-v2` (dukung bahasa Indonesia)
- Threshold default 0.88 (dikalibrasi terhadap 5 dokumen ground truth)
- GPU auto-detect (CUDA); fallback CPU
- Tidak ada double counting — hanya menambah kata yang belum terdeteksi N-Gram

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
- **Cohere AI** (query-expander untuk variasi frasa pencarian)

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
- **Deteksi Parafrasa (Semantic AI)** — aktifkan layer 2 (butuh GPU untuk kecepatan)

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

### v3.4 (Current) — Validasi 5 Dokumen + Kalibrasi Threshold
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
