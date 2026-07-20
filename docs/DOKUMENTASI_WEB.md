# Dokumentasi Web App — Turnitin Lokal

Dokumen ini merangkum arsitektur, alur kerja, dan changelog konseptual aplikasi web
(localhost) pengecek plagiarisme. Dibaca bersama [README.md](../README.md).

## 1. Tujuan

Menyediakan pengecek plagiarisme lokal gratis yang meniru perilaku Turnitin untuk
membantu mahasiswa mengecek skripsi sebelum submit ke Turnitin resmi. Skor diusahakan
se-valid mungkin terhadap Turnitin asli (validasi 6 dokumen: MAE 1.25pt).

## 2. Arsitektur Berkas

```
app/
├── server.py                 # Flask server (port 5001), orkestrasi process_document
├── run_test_groundtruth.py   # Runner validasi + freeze corpus (acuan metodologi)
├── compare_threshold.py      # Bandingkan threshold pada korpus beku
├── engine/
│   ├── extractor.py          # Ekstraksi PDF/DOCX/TXT + anti-manipulasi
│   ├── shingling.py          # N-Gram matching + agregasi global union + semantic orchestration
│   ├── semantic_similarity.py# sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2)
│   ├── web_scraper.py        # Multi-source crawler + API + bank korpus (cache)
│   └── pdf_generator.py      # Report PDF bergaya Turnitin (highlight per-sumber)
├── corpus_bank/bank.json     # Bank korpus (CACHE URL->teks, tumbuh tiap pemakaian)
├── frozen_corpus/*.json      # Korpus beku per-dokumen validasi (skor deterministik)
├── templates/index.html      # Halaman upload
└── templates/report.html     # Halaman hasil
```

## 3. Alur Pemrosesan (process_document)

Localhost memakai **metodologi identik dengan groundtruth** (`run_test_groundtruth.py`)
agar skor konsisten dan dapat dipertanggungjawabkan:

1. **Ekstraksi teks** (`extract_text_from_pdf`) — buang front-matter, daftar pustaka,
   kutipan (opsional); deteksi manipulasi (zero-width, Cyrillic homoglyph, tiny-font).
2. **Cari kandidat sumber** (`get_candidate_urls`, 100 probe) — scrape internet KHUSUS
   dokumen ini via Semantic Scholar, Crossref, OpenAlex, DOAJ, arXiv, CORE, DuckDuckGo,
   repositori kampus Indonesia.
3. **Unduh isi sumber** (`scrape_all_candidates`) — download multi-thread. **Bank korpus
   dipakai sebagai CACHE**: URL yang sudah pernah diunduh diambil instan (skip download);
   sumber baru otomatis disimpan ke bank (auto-freeze). Bank mempercepat tanpa mengubah
   komposisi korpus.
4. **Skoring** (`calculate_similarity`, parameter default identik groundtruth):
   - Layer 1 N-Gram 5-gram exact match + gap-filling konservatif + union global.
   - Layer 2 Semantic (selalu nyala) untuk kalimat yang lolos N-Gram (<30% match).
   - Skor = (kata ter-match union / total kata) × 100%.
5. **PDF report** (`generate_report_pdf`) — highlight berwarna per-sumber ala Turnitin,
   halaman ORIGINALITY REPORT, daftar PRIMARY SOURCES.

## 4. Peran Bank Korpus (PENTING)

Bank **bukan** basis korpus skoring. Bank adalah **cache + auto-freeze**:

- **Cache**: `scrape_all_candidates` cek bank dulu; URL yang sudah ada di bank tidak
  di-download ulang (hemat waktu, hindari rate-limit).
- **Auto-freeze**: sumber baru hasil scrape otomatis ditambah ke bank (tulis atomik
  temp+`os.replace`, guard JSON korup, lock antar-thread). Bank makin kaya tiap dipakai.

Alasan bank TIDAK dijadikan basis korpus: bank mentah (17k+ sumber lintas bidang) berisi
banyak frasa umum yang overlap tipis; union global akan "menjahit" potongan pendek dari
ratusan sumber tak relevan menjadi blok plagiat palsu → skor menggelembung (over-counting).
Dengan korpus terkurasi per-dokumen (hasil probe), skor setara metodologi groundtruth.

## 5. Endpoint

| Route | Fungsi |
|---|---|
| `GET /` | Halaman upload |
| `POST /upload` | Terima PDF, mulai thread `process_document`, kembalikan `file_id` |
| `GET /status/<file_id>` | Progress realtime (validasi kepemilikan via session) |
| `GET /report/<file_id>` | Halaman hasil HTML |
| `GET /download/<file_id>` | Unduh PDF report |

Keamanan: `file_id` UUID kripto-aman, ownership divalidasi via `session_id`, `debug=False`
(cegah RCE Werkzeug), `MAX_CONTENT_LENGTH` 16MB.

## 6. Opsi Filter UI

- **Kecualikan Kutipan** — skip teks dalam tanda kutip.
- **Kecualikan Daftar Pustaka** — skip halaman daftar pustaka.
- **Kecualikan sumber <1%** — sembunyikan sumber kecil dari DAFTAR TAMPILAN (skor total
  TIDAK berubah, persis perilaku Turnitin).
- **Deteksi Parafrasa (Semantic AI)** — SELALU NYALA, tidak lagi ditampilkan sebagai opsi.

## 7. Konfigurasi (env)

- `INTERNET_MAX_PROBES` (default 100) — jumlah kalimat-probe pencarian; sama dengan
  groundtruth agar skor setara. Turunkan bila ingin lebih cepat (mengorbankan recall).
- `USE_COHERE_EXPANDER` (default 0=MATI) — Cohere query-expander→DDG adalah bottleneck
  utama (rate-limit). Nyalakan hanya bila butuh recall ekstra.

## 8. Changelog Konseptual

### v3.7 — Audit Hardening (pasca-pindah folder)
Audit menyeluruh 3-jalur (engine, server/web, scraper/API) + verifikasi runtime.
- **FIX CRITICAL — regresi `UnboundLocalError: concurrent`**: efek samping dari mematikan
  Cohere expander (v3.6). `import concurrent.futures` yang tersisa hanya di blok bersyarat
  membuat `concurrent` jadi variabel lokal → `get_candidate_urls` crash di config default
  (setiap upload gagal). Diperbaiki: import dipindah ke scope modul, import lokal redundan dihapus.
- **FIX HIGH — frontend menggantung**: `checkStatus()` kini menangani respons
  `not_found`/403/undefined + `.catch()` (toleransi 5 blip jaringan). Sebelumnya overlay
  loading berputar selamanya saat server restart atau sesi tak cocok.
- **FIX HIGH — bank kehilangan data diam-diam**: `save_to_corpus_bank` kini commit ke
  cache HANYA setelah tulis disk sukses (dulu mutasi cache dulu → gagal tulis = entri hilang permanen).
- **FIX MEDIUM**: 2 `fitz.open` tanpa `.close()` (kebocoran handle saat scraping paralel);
  race pada `_INDO_REPO_BUDGET` dibungkus lock (reproducibility).
- **FIX LOW**: ekstensi `.PDF` huruf besar diterima; teks hint UI diperbaiki.
- Diverifikasi BENAR (tak diubah): semua fix engine v3.5, default parameter aman, guard
  div-by-zero, semua `requests` bertimeout, tak ada rekursi crawler. Temuan kalibrasi
  (whole-chunk semantic, punctuation non-ASCII, `is_common_phrase`) TIDAK disentuh demi
  menjaga skor tervalidasi MAE 1.25pt.

### v3.6 — Metodologi Localhost = Groundtruth
- **Localhost memakai metodologi identik groundtruth**: korpus skoring = hasil scrape
  khusus dokumen (terkurasi), BUKAN bank mentah. Menghilangkan over-counting di akarnya.
- **Bank turun peran jadi cache + auto-freeze** (mempercepat, tumbuh, tidak jadi basis skor).
- **Semantic (deteksi parafrasa) selalu nyala** — toggle UI dihapus.
- **Toggle "Perkaya dari Internet" dihapus** — internet selalu ON (wajib untuk PDF baru).
- **Percepatan (C)**: Cohere expander default MATI (`USE_COHERE_EXPANDER`); sumber utama
  tetap dari DOAJ/Crossref/OpenAlex/Semantic Scholar/arXiv/CORE/DDG.
- Parameter engine `semantic_max_sources`/`min_source_overlap` tetap ada dengan default
  aman (None/1 = perilaku lama) — TIDAK dipakai jalur web maupun groundtruth, sehingga
  skor tervalidasi tidak berubah.

### v3.5 — Audit Engine + Perbaikan Ketahanan
- Fix hyphenation, gap-fill per-sumber diperketat, fix `sent_word_count`, semantic sort,
  bank tahan-korupsi (tulis atomik), anti-cheat extractor aman. Validasi 6 dokumen: MAE 1.25pt.

### v3.4 — Validasi + Kalibrasi Threshold 0.88
- Validasi dokumen, freeze corpus (deterministik), auto-discover dokumen, dukungan DOCX.

### v3.1–v3.3 — Audit API, GPU, recall boost, fix agregasi exclude_small
- Lihat [README.md](../README.md) untuk detail.

## 9. Keterbatasan

- **PDF baru wajib scrape internet** (~10-15 menit). Bank hanya mempercepat bagian yang
  sudah pernah diambil.
- **Indeks tak sebesar Turnitin** — hanya sumber terbuka gratis (bukan jurnal berbayar
  IEEE/Springer/Elsevier, bukan arsip kampus internal, bukan repositori paper mahasiswa).
- Skor cenderung ≤ Turnitin asli → berguna sebagai **estimasi batas bawah**.
