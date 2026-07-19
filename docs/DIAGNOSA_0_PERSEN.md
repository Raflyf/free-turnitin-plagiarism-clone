# Diagnosa Lengkap: Plagiarism Checker Lokal Melaporkan 0% (Regresi Turnitin-Clone)

> **STATUS RESOLUSI (update setelah fix):** Akar #1 & #2 (bug agregasi `exclude_small`) SUDAH DIPERBAIKI di `shingling.py` (commit `73e7e4e`, `6ae7e96`). Filter <1% dipindah agar hanya memangkas DAFTAR TAMPILAN, bukan agregasi skor total. Hasil ground-truth setelah fix: **Rafly 0% → ~6% (target 8%)**, **Hesti 0% → ~12-14% (target 18%)**. Bug tampilan "skor >0 tapi 0 sumber" juga diperbaiki (fallback top-10 penyumbang). SISA PEKERJAAN untuk menutup gap ke target: akar #3/#4 (recall korpus — masih didominasi abstrak, sumber asli jiplakan sering gagal scrape) dan akar #5 (non-determinisme search — skor bervariasi antar-run karena `random` tanpa seed + cache). Detail di bawah tetap relevan sebagai konteks investigasi.

Sistem ini adalah clone Turnitin lokal berbahasa Indonesia yang harus melaporkan skor kemiripan dokumen skripsi mendekati Turnitin asli (ground truth: dokumen "Rafly" ~8%, dokumen "Hesti" ~18%), tetapi kini KEDUA dokumen melaporkan 0.00% (0 sumber). Investigasi lima tahap pipeline membuktikan DUA akar masalah independen yang saling menutupi: (a) BUG KODE di `calculate_similarity` — `exclude_small` membuang setiap sumber dengan kontribusi <1% SEBELUM agregasi global, sehingga bila tak ada satu sumber pun mencapai 1% maka skor total dipaksa ke 0% walau gabungan lintas sumber signifikan (terbukti lewat uji terkontrol: 30 sumber @0.3% menghasilkan 9% dengan filter mati vs 0% dengan filter hidup); dan (b) MASALAH RECALL KORPUS — 93-94% korpus hanyalah abstrak metadata API topik-terkait, sedangkan dokumen sumber asli yang benar-benar dijiplak tidak pernah masuk korpus karena kegagalan scrape (SSL/DNS mati) dan variansi search acak. Mesin matching sendiri terbukti benar secara matematis (uji terkontrol overlap yang diketahui menghasilkan 47.62%), sehingga 0% BUKAN kesalahan aritmetika shingling melainkan kombinasi filter yang salah tempat plus korpus yang tidak relevan.

## Arsitektur Pipeline

Alur pemrosesan dari PDF hingga skor akhir, beserta file kunci tiap tahap (semua path absolut, forward-slash):

1. **Input & Ekstraksi PDF**
   - File: `D:/skripsi/skripsi_spam/Code_Spam_Email/plagiarism_checker/app/engine/extractor.py`
   - Fungsi: `extract_text_from_pdf`. Mengubah PDF (`before_turnitin/Rafly FIrmansyah - Skripsi_Fix.pdf`, `Hesti_skripsi_final_before_turnitin.pdf`) menjadi teks bersih. Output: Rafly 13099 kata, Hesti 8604 kata.

2. **Akuisisi Search (retrieval kandidat sumber)**
   - File: `D:/skripsi/skripsi_spam/Code_Spam_Email/plagiarism_checker/app/engine/web_scraper.py` (fungsi `fetch_ddgs` ~baris 306-399, `fetch_semantic_scholar`, `fetch_crossref`, `fetch_doaj`, `fetch_core`, `fetch_openalex`) dan `app/engine/free_api_fallbacks.py` (`search_with_fallbacks`, `get_cache_key`).
   - Sumber hidup: DuckDuckGo (ddgs), Semantic Scholar (3 API key rotasi), Crossref, DOAJ/arXiv/CORE, ScraperAPI. MATI: Cohere web-search connector (dihapus 15 Sep 2025), Google CSE (403 untuk akun baru).
   - Menghasilkan: ~1995-2020 abstrak preloaded dari API + ~204-211 URL web hasil DDG/dork.

3. **Scrape & Pembentukan Korpus**
   - File: `web_scraper.py`, fungsi `scrape_url` (~baris 860-959). Deep-PDF-crawl bersyarat: hanya mengambil PDF penuh jika landing HTML memuat link berpola `.pdf`/`/download/`/`/bitstream/`/`/article/view/`. Dibatasi `pdf_links[:3]` per halaman, cap baca 30-40 halaman per PDF (dinaikkan dari 5 sesi ini).
   - Cache: `app/engine/.search_cache/` (166 file, ~1.2M, key = MD5(query), max_age 24 jam).

4. **Matching N-Gram (shingling)**
   - File: `D:/skripsi/skripsi_spam/Code_Spam_Email/plagiarism_checker/app/engine/shingling.py`, fungsi `calculate_similarity`, `get_ngrams` (n=5).
   - Menghitung overlap 5-gram doc vs tiap sumber; `exclude_small` (baris 212-213) membuang sumber <1%; agregasi global (baris 228-244) membentuk `is_matched_global` dan `ngram_similarity`.

5. **Matching Semantic (parafrase)**
   - File: `D:/skripsi/skripsi_spam/Code_Spam_Email/plagiarism_checker/app/engine/semantic_similarity.py` + layer semantic di `shingling.py` (baris ~408-438). GPU aktif (torch 2.6.0+cu124, CUDA True, RTX 3050). Mengecek kalimat unmatched (Rafly: 586 dari 726 sentence-span).

6. **Skor Akhir**
   - `ngram_similarity` + `semantic additional` -> Overall Index. Runner uji: `app/run_test_groundtruth.py` (memanggil `calculate_similarity(exclude_small=True, use_semantic=True)` di baris 26). Log: `app/test_gpu_run.log`.

## Gejala Terukur

| Dokumen | Total kata | Sentence-span | Korpus (brief) | Korpus (log) | Korpus (json result) | Sumber lolos | N-Gram | Semantic | Target |
|---|---|---|---|---|---|---|---|---|---|
| Rafly | 13099 | 726 (586 dicek semantic) | 2272 | 2132 | 1455 | 0 | 0.00% | 0.00% | ~8% |
| Hesti | 8604 | - | 2317 | 2156 | 1313 | 0 | 0.00% | 0.00% | ~18% |
| Hesti (sebelumnya) | 8604 | - | - | - | - | 2 | 4.5% | - | ~18% |

Catatan kunci pada angka:
- **Non-determinisme korpus terbukti**: tiga artefak dari config sama melaporkan tiga ukuran korpus berbeda (brief 2272/2317, log 2132/2156, json 1455/1313). Korpus tidak reproducible antar run.
- **Komposisi korpus**: Rafly 1995 abstrak API + 204 URL = ~93% abstrak. Hesti 2020 abstrak + 211 URL = ~94% abstrak.
- **Ambang kritis exclude_small 1%**: pada dokumen 13099 kata, 1% = 131 kata WAJIB ter-match agar satu sumber lolos. Uji sensitivitas: 6 kata=0.046%, 12 kata=0.092%, 20 kata=0.198%, 50 kata=1.008% (baru lolos), 131 kata=1.0%.
- **Overlap sumber nyata**: PDF skripsi lain 12 n-gram, landing page repository 2 n-gram, ejurnal 0 n-gram, PDF umsu-dork 7 dari 7975 n-gram (~0.09%). Semua JAUH di bawah 131 kata.
- **Kegagalan jaringan**: 95 warning scraper, 44 kegagalan DNS (`getaddrinfo`), 36 terkait `garuda.kemdikbud.go.id` (DNS DEAD, dikonfirmasi `gaierror`). DDG gagal SSL ~27% pada query dork.
- **Semantic menemukan tapi dibuang**: log memuat "Semantic check found N potential paraphrase matches" tetapi "Semantic additional detection: 0.00%" — match ADA namun gugur di filter exclude_small <1%.

## Akar Masalah Berperingkat

### 1. [TERBUKTI — likelihood HIGH] Bug agregasi: exclude_small memfilter per-sumber SEBELUM agregasi global

**Klaim**: `exclude_small` (aktif di runner uji) membuang setiap sumber dengan kontribusi <1% via `continue` di `shingling.py:212-213`, SEBELUM sumber masuk `sources_report`. Karena `sorted_sources` (baris 225), `global_overlap_ngrams` (baris 230-232), dan `is_matched_global` (baris 240-244) semuanya dibangun HANYA dari sumber yang lolos filter, maka bila tak ada satu sumber pun >=1%, set global kosong -> `total_plagiarized_words_global=0` -> `ngram_similarity=0.00%`.

**Bukti (uji terkontrol dijalankan)**: doc 2000 kata, 30 sumber masing-masing cocok 6 kata berurutan (0.3% per sumber, semua <1%), gabungan 180 kata = 9%. Hasil: `exclude_small=False` -> total **9.00%** / 30 sumber; `exclude_small=True` -> total **0.00%** / 0 sumber. Komentar kode sendiri (baris 228-229) menyatakan "Turnitin menghitung indeks total dari GABUNGAN semua kata plagiat dari SUMBER MANAPUN", tetapi implementasi baris 212 justru membuang sumber sebelum union dibentuk.

**Dampak**: efek tebing — degradasi kecil recall berubah menjadi kejatuhan ke 0% alih-alih penurunan landai. Ini penyebab langsung Rafly & Hesti = 0% karena overlap tiap sumber (0-12 n-gram = maks ~16 kata = 0.12%) selalu di bawah 1%.

### 2. [TERBUKTI — likelihood HIGH] Bug yang sama diulang di layer semantic

**Klaim**: filter `exclude_small` diterapkan LAGI pada percentage per-sumber semantic (`shingling.py:410-419`), dan `is_matched_global` hanya di-update untuk sumber semantic yang lolos (baris 430-435). Memperbaiki hanya layer N-Gram tanpa layer semantic tetap menghasilkan 0% pada mode semantic.

**Bukti**: log "Semantic found N matches" tetapi "0.00%" membuktikan match dibuang oleh filter, bukan tidak ditemukan. Total semantic dihitung ulang dari `is_matched_global` (baris 438) yang tidak pernah di-update untuk sumber <1%.

**Dampak**: Rafly mengecek 586 kalimat unmatched via GPU namun kontribusi semantic tetap 0.00%.

### 3. [TERBUKTI — likelihood HIGH] Masalah recall korpus: 93-94% korpus adalah abstrak metadata, bukan teks sumber penuh

**Klaim**: `combined_text = f"{title}. {abstract}"` di semua fetcher (`fetch_semantic_scholar:113`, `fetch_crossref:148`, `fetch_doaj:434`, `fetch_core:510`, `fetch_openalex:186`). Sumber preloaded = judul + abstrak pendek topik-terkait, BUKAN dokumen asal copy-paste.

**Bukti (ceiling matematis dijalankan)**: abstrak 150 kata bila 100% verbatim hanya 1.15% di doc 13099 kata; 300 kata=2.29%. Realistis (abstrak topik-terkait, tak disalin) overlap 5-15 n-gram = 9-19 kata = 0.069%-0.145%. Korpus preloaded topikal TIDAK relevan dengan skripsi spam-email: log memuat tari Rumeksa, hijab, C4.5 marketing, koreografi, kandang sapi — noise murni.

**Dampak**: recall dokumen sumber yang benar-benar disalin mendekati NOL. Bahkan dengan bug agregasi diperbaiki, skor tak akan mencapai target jika korpus tak memuat sumber asli.

### 4. [TERBUKTI — likelihood HIGH] Sumber asli gagal masuk korpus: SSL/DNS mati + dork tak relevan

**Klaim**: dokumen sumber asli (skripsi/jurnal Indonesia yang dijiplak) gagal di-scrape karena SSL handshake failure massal dan DNS mati; URL yang muncul dipaksa operator `site:` dork dan tidak relevan secara topik.

**Bukti**: `garuda.kemdikbud.go.id` & `download.garuda.kemdikbud.go.id` DEAD (`gaierror`), backbone banyak URL preloaded (36 kegagalan). BSI/repository jurnal `CERTIFICATE_VERIFY_FAILED` & `SSLV3_ALERT_HANDSHAKE_FAILURE`. Uji nyata: PDF umsu hasil dork (`site:repository.umsu.ac.id`, topik acak SitiRaisha) download OK (HTTP 200, 1.3MB, 8838 kata) tetapi overlap 7/7975 n-gram Hesti (~0.09%) — topik tak berhubungan. Semantic Scholar untuk probe Hesti mengembalikan 0 URL atau 5 paper EN generik. Crossref 15 hasil, 0 relevan, kadang timeout (6s terlalu ketat).

**Dampak**: korpus membesar oleh abstrak noise tetapi recall sumber relevan tetap nol.

### 5. [TERBUKTI — likelihood HIGH] Regresi 4.5% -> 0% Hesti adalah VARIANSI ACAK search, bukan bug kode baru

**Klaim**: 2 sumber yang menghasilkan 4.5% pada run lama tidak terambil pada run berikutnya karena `fetch_ddgs` (web_scraper.py:325) memilih 1 dari 4 varian query dork via `random.random()` TANPA `random.seed` (grep = 0 hasil) + cache 24 jam + host sumber DNS-mati intermiten.

**Bukti**: perubahan sesi ini (git diff HEAD) HANYA menaikkan cap baca halaman PDF (5->30/40) pada `res.content` yang SUDAH di memori (`fitz.open` stream) — mustahil menyebabkan timeout/exception jaringan baru; try/except deep-crawl (baris 924-950) utuh. Tiga run melaporkan tiga ukuran korpus berbeda. DDG gagal SSL ~27% pada query dork (4/15 run), query polos 10/10 OK.

**Dampak**: skor tidak reproducible; kalibrasi mustahil sebelum determinisme ditegakkan.

### 6. [DIBANTAH — likelihood LOW] Perubahan page-cap 5->25/30/40 menyebabkan regresi

**Bukti bantahan**: diff hanya menyentuh loop iterasi halaman atas konten PDF yang sudah di-download; tidak menyentuh timeout, retry, maupun jumlah request. Uncommitted di working tree sehingga run 4.5% kemungkinan mendahului perubahan ini. Tidak ada jalur exception baru.

### 7. [DUGAAN — likelihood MEDIUM] Cache basi/teracuni menutupi penemuan baru

**Klaim**: cache key = MD5(query) tanpa scope dokumen; hasil lama tak relevan tersaji ulang <24 jam dan mencegah penemuan sumber baru; probe identik bocor antar-dokumen.

**Bukti**: 166 file cache, satu entri berisi `whitehouse.gov/sotu`, `state.gov`, dan situs porno (`lustycinema.li`). `use_cache=True` default di `search_with_fallbacks`.

## Bug Kode vs Masalah Data

Ini pertanyaan terpenting, dan jawabannya: **KEDUANYA, dan keduanya harus diperbaiki — tetapi bug kode diperbaiki LEBIH DULU karena murah, deterministik, dan terbukti.**

**Ada bug kode nyata di `calculate_similarity` (shingling.py).** Terbukti lewat uji terkontrol yang tidak menyentuh jaringan sama sekali: `exclude_small=True` mengubah 9% (30 sumber @0.3%) menjadi 0%. Filter per-sumber diterapkan di posisi yang salah — SEBELUM agregasi global, bukan setelahnya. Turnitin mengakumulasi banyak match fragmentaris lintas ratusan sumber; kode ini justru membunuh tepat match fragmentaris itu. Bug ini juga menjelaskan efek tebing regresi Hesti (turun ke 0 alih-alih landai). Bug ini identik terulang di layer semantic. Ini adalah bug, bukan preferensi desain — komentar kode sendiri bertentangan dengan implementasinya.

**Ada juga masalah data (recall korpus) nyata.** Bahkan dengan bug agregasi diperbaiki, uji membuktikan sumber nyata hanya overlap 2-12 n-gram (0.07-0.46%). Bila sumber ASLI yang dijiplak tidak masuk korpus, tidak ada n-gram signifikan untuk diagregasi — skor akan >0% tetapi tetap jauh di bawah 8%/18%.

**Cara memisahkan tegas keduanya (eksperimen penentu)**: suntik SATU PDF skripsi sumber-nyata yang DIKETAHUI disalin Rafly/Hesti langsung ke korpus, matikan `exclude_small`, lalu ukur.
- Jika skor melonjak ke kisaran target -> masalah utama adalah recall korpus (tugas scraper), dan bug kode adalah pemberat.
- Jika skor tetap rendah walau sumber asli disuntik -> masih ada masalah di scoring/agregasi.

Urutan perbaikan yang benar: perbaiki bug agregasi (deterministik, terbukti, murah) -> tegakkan determinisme search -> baru nilai apakah recall korpus cukup.

## Yang Sudah Dicoba (Sesi Ini)

- **ddgs (DuckDuckGo)**: aktif sebagai sumber search. Hasil: query polos 10/10 OK, tapi query dork gagal SSL ~27%. Recall sumber Indonesia relevan tetap nol.
- **Rotasi Semantic Scholar (3 API key)**: aktif. Hasil: mengembalikan 0 URL atau 5 paper EN generik untuk probe Hesti — bukan skripsi Indonesia sumber jiplakan.
- **Cohere web-search connector**: MATI (dihapus Cohere 15 Sep 2025). Google CSE 403. Tidak dapat digunakan.
- **GPU aktif (torch 2.6.0+cu124, CUDA True, RTX 3050)**: layer semantic berjalan, mengecek 586 kalimat unmatched Rafly. Hasil: semantic MENEMUKAN match tapi dibuang exclude_small -> 0.00%. GPU tidak menyelesaikan masalah karena filter di hilir.
- **Deep-PDF-crawl 25/30/40 halaman (dinaikkan dari 5)**: perubahan uncommitted. Hasil: TERBUKTI INERT terhadap regresi (hanya mengubah cap baca konten di memori). Tidak memperbaiki maupun merusak.
- **Preload 1995-2020 abstrak API**: memperbesar korpus. Hasil: korpus besar tapi noise (tari/hijab/C4.5), recall relevan tetap nol. Korpus besar != korpus relevan.

Kesimpulan: tidak ada satu pun perbaikan sesi ini yang menyentuh bug agregasi `exclude_small` maupun determinisme search — dua akar terbukti. Itulah sebabnya hasil tetap 0%.

## Pertanyaan Terbuka untuk AI Lain

1. **Apakah aman memindahkan `exclude_small` dari filter pra-agregasi (shingling.py:212-213 `continue`) menjadi filter tampilan pasca-agregasi?** Apakah ada konsumen `sources_report` (server.py, UI) yang mengasumsikan daftar sudah terfilter <1%, sehingga membutuhkan flag `below_threshold` alih-alih penghapusan?
2. **Berapa floor yang benar untuk meniru Turnitin?** Turnitin melaporkan sumber dengan kontribusi <1%. Apakah floor per-sumber sebaiknya berbasis n-gram absolut (mis. minimal 3-5 n-gram overlap) alih-alih persentase, dan berapa nilai yang menghasilkan 8%/18% pada dokumen 13099/8604 kata?
3. **Di mana dokumen sumber ASLI yang dijiplak Rafly (topik spam-email) dan Hesti (topik body shape/fashion) berada?** Apakah di Garuda (DNS mati), repositori kampus (SSL gagal), atau di web terbuka? Tanpa mengetahui asal jiplakan, recall tak bisa diverifikasi.
4. **Bisakah kegagalan SSL `garuda.kemdikbud.go.id` (DNS DEAD) dan BSI (handshake failure) ditembus?** Apakah host ini benar-benar mati permanen atau butuh proxy (ScraperAPI/AbstractAPI) / resolver DNS alternatif? Ini backbone banyak URL kandidat.
5. **Apakah eksperimen penentu sudah dijalankan?** Jika PDF sumber-nyata (yang PASTI disalin) disuntik ke korpus dengan `exclude_small=False`, apakah skor melonjak ke target? Jawaban ini memisahkan tegas bug-kode vs masalah-data.
6. **Bagaimana strategi query DDG seharusnya?** Jalankan KEEMPAT varian query per probe (union) alih-alih pilih-acak-1, atau tetap pakai dork `site:`? Operator `site:` terbukti menghasilkan sumber tak relevan (overlap ~0) DAN memicu SSL failure.
7. **Apakah cache `.search_cache/` harus dinonaktifkan/dibersihkan saat kalibrasi?** Terdapat entri teracuni (whitehouse.gov, situs porno). Key MD5(query) tanpa scope dokumen berpotensi bocor antar-dokumen untuk probe identik.
8. **Apakah abstrak API sebaiknya di-demote dari "sumber skor" menjadi "kandidat retrieval"?** Yaitu: gunakan abstrak hanya untuk menemukan DOI/URL, lalu paksa deep-fetch teks penuh sebelum matching — bukan menghitung abstrak pendek sebagai sumber.

## Rekomendasi Langkah Berikut (Berperingkat)

**Prioritas 1 — Perbaiki bug agregasi (deterministik, terbukti, murah, kerjakan LEBIH DULU):**
1. Di `shingling.py:212-213`, GANTI `continue` menjadi penyimpanan flag `s['below_threshold'] = percentage < 1.0`. Masukkan SEMUA sumber dengan overlap ke `sources_report` agar `overlap_ngrams`-nya ikut ke `global_overlap_ngrams` (231-232) dan `is_matched_global`.
2. Hitung `is_matched_global` & `total_plagiarized_words_global` dari SEMUA sumber (union kata per posisi, dedup). Skor total (`ngram_similarity`) TIDAK boleh dipengaruhi filter <1%.
3. Terapkan `exclude_small` HANYA sebagai filter TAMPILAN `sorted_sources` setelah global dihitung.
4. Ulangi pola sama di layer semantic (baris 410-435): update `is_matched_global` untuk SEMUA sumber semantic, filter hanya pada daftar tampilan.
5. Jalankan ulang `run_test_groundtruth.py`. Harapan: skor naik dari 0% (belum tentu ke target, tergantung recall).

**Prioritas 2 — Tegakkan determinisme sebelum kalibrasi:**
6. Set `random.seed` tetap di awal run test. Nonaktifkan/hapus `app/engine/.search_cache/` (atau `use_cache=False`) saat kalibrasi.
7. Ganti pemilihan-acak-1-varian di `fetch_ddgs` menjadi union KEEMPAT varian query per probe.
8. Jalankan ulang 3x: jika skor stabil dan konsisten -> variansi terkonfirmasi teratasi.

**Prioritas 3 — Eksperimen penentu (memisahkan bug vs data):**
9. Suntik 1 PDF sumber-nyata yang diketahui disalin ke korpus, `exclude_small=False`, ukur. Ini menjawab pertanyaan terpenting: apakah sisa masalah adalah recall.

**Prioritas 4 — Perbaiki recall korpus (jika Prioritas 3 menunjukkan recall kurang):**
10. Demote abstrak API menjadi kandidat retrieval; paksa deep-fetch teks penuh dari DOI/URL sebelum matching.
11. Filter korpus preloaded: buang abstrak yang tidak share >=1 n-gram (n=5) dengan dokumen SEBELUM masuk perhitungan (buang noise tari/hijab/C4.5).
12. Auto-blacklist host DNS-mati (`garuda.kemdikbud.go.id`) agar tidak memakan budget waktu 700-1200s. Tembus SSL BSI via proxy. Tambah pola deteksi link PDF (`/fulltext/`, `?article=`, EPrints `/<id>/1/`), naikkan `pdf_links[:3]` bila repositori punya banyak lampiran.
13. Tambah jalur full-text Indonesia (Garuda alternatif/CORE full-text) dan perpanjang timeout Crossref 6s -> 10s.

**Catatan penutup**: bug agregasi (Prioritas 1) adalah satu-satunya perbaikan yang deterministik, terbukti lewat uji tanpa-jaringan, dan pasti menaikkan skor dari 0. Kerjakan itu dulu sebelum menyentuh scraper — jangan tuning recall di atas fondasi scoring yang bocor.