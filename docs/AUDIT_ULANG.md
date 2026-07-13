# Audit Ulang — Plagiarism Checker (Pasca-Perbaikan)

| Field | Value |
|-------|-------|
| **Tanggal** | 13 Juli 2026 |
| **Referensi** | [AUDIT_LENGKAP.md](AUDIT_LENGKAP.md) v1.0 |
| **Tujuan** | Verifikasi perbaikan P0–P2 dan identifikasi temuan yang masih terlewat |

---

## 1. Ringkasan Eksekutif

Sebagian besar temuan **kritis (P0)** dan beberapa temuan **mayor (P1–P2)** sudah ditangani dengan benar. Kualitas kode meningkat signifikan dibanding audit pertama.

Namun audit ulang menemukan:

- **3 temuan baru** (bug regresi / efek samping perbaikan)
- **4 temuan lama** yang hanya diperbaiki **sebagian**
- **8+ temuan backlog** yang memang belum disentuh (sesuai rencana P3)

**Status keseluruhan:** Layak untuk pre-check internal, **belum** layak produksi tanpa menyelesaikan sisa P0 parsial dan 3 temuan baru.

---

## 2. Matriks Status Perbaikan

Legenda: ✅ Selesai | ⚠️ Sebagian | ❌ Belum | 🆕 Temuan Baru

### 2.1 P0 — Kritis (Audit Pertama)

| ID | Temuan | Status | Bukti / Catatan |
|----|--------|--------|-----------------|
| SEC-01 | API key hardcoded | ⚠️ | `os.environ.get()` dipakai, tapi **semua key masih ada sebagai default fallback** di `web_scraper.py` & `free_api_fallbacks.py` |
| JRN-01 | URL–teks zip misalignment | ✅ | `fetch_probe_multi()` kini pairing per-sumber: `zip(u_ss,t_ss)`, `zip(u_cr,t_cr)`, `zip(u_repo,t_repo)` |
| LOG-01 | Skor global hanya top-20 | ✅ | `global_overlap_ngrams` iterasi `sorted_sources` (semua), bukan `top_sources` |
| LOG-02 | Semantic word offset | ⚠️ | `get_sentences()` di `shingling.py` diseragamkan; mapping posisi kata masih `current_pos += len(sent.split())` tanpa offset karakter |

### 2.2 P1 — Minggu Ini

| ID | Temuan | Status | Bukti / Catatan |
|----|--------|--------|-----------------|
| SEC-02 | `debug=True` | ✅ | `debug=False` di `server.py` baris 276 |
| SEC-03 | Ngrok auto-expose | ✅ | Hanya aktif jika `USE_NGROK=true` |
| JRN-04 | Silent API failure | ⚠️ | Academic API sudah log error; AI layer (`fetch_pplx`) masih `except: pass` |
| JRN-08 | OpenAlex tanpa teks | ⚠️ | Abstrak direkonstruksi di `fetch_openalex()`, tapi **teks tidak dimasukkan ke preloaded** (lihat JRN-12) |

### 2.3 P2 — Sprint Berikutnya

| ID | Temuan | Status | Bukti / Catatan |
|----|--------|--------|-----------------|
| LOG-04 | Dedup per domain | ✅ | Dihapus; perhitungan per URL penuh di `shingling.py` |
| LOG-05 | Model EN untuk BI | ✅ | `paraphrase-multilingual-MiniLM-L12-v2` |
| LOG-06 | Threshold semantic | ✅ | Dinaikkan ke `0.88` (perlu validasi empiris) |
| LOG-07 | `exclude_small` semantic | ⚠️ | Hanya filter sumber **baru** <1%; sumber existing tidak difilter ulang |
| JRN-08 | Import DDGS inkonsisten | ❌ | `web_scraper.py` → `from ddgs import DDGS`; `free_api_fallbacks.py` → `from duckduckgo_search import DDGS` |
| UI-01 | DOCX vs PDF | ✅ | `index.html` → `accept=".pdf"` |
| LOG-03 | Non-fuzzy N-Gram | ❌ | Belum diubah (backlog desain) |
| JRN-05 | Repo Indonesia rapuh | ❌ | `indonesian_repos.py` tidak berubah |

---

## 3. Temuan Baru (Pasca-Perbaikan)

### NEW-01 [MAYOR] `server.py` — Duplikasi Blok `if __name__`

**Lokasi:** `server.py` baris 197–221 dan 223–276

Dua blok `if __name__ == '__main__':` identik berurutan. Blok pertama (197–221) dead code — tidak memanggil `signal.signal()` maupun `app.run()`.

**Dampak:** Kebingungan maintenance; risiko edit salah blok.

**Perbaikan:** Hapus blok pertama (baris 197–221).

---

### NEW-02 [MAYOR] OpenAlex & Google CSE — Teks Abstrak Tidak Dipakai

**Lokasi:** `web_scraper.py` `fetch_probe_multi()` baris 342–349

```python
for u, t in zip(u_ss, t_ss): preloaded[u] = t
for u, t in zip(u_cr, t_cr): preloaded[u] = t
for u, t in zip(u_repo, t_repo): preloaded[u] = t
# u_oa, t_oa TIDAK ditambahkan
# t_fallback TIDAK ditambahkan
normal_urls = u_gs + u_gw + u_gr + u_dd + u_fallback + u_oa
```

`fetch_openalex()` sudah merekonstruksi abstrak, dan `search_with_fallbacks()` mengembalikan `texts_found` (title+snippet), tapi keduanya **dibuang**. URL masuk antrian scrape yang sering gagal.

**Dampak:** Coverage jurnal turun dibanding potensi API; regresi logis setelah fix JRN-01.

**Perbaikan:**
```python
for u, t in zip(u_oa, t_oa):
    if t and len(t) > 50:
        preloaded[u] = t
for u, t in zip(u_fallback, t_fallback):
    if t and len(t) > 50:
        preloaded[u] = t
# Hanya URL tanpa teks yang masuk normal_urls
```

---

### NEW-03 [MODERAT] `.gitignore` — `.env` Belum Diabaikan

**Lokasi:** `plagiarism_checker/.gitignore`

Hanya berisi `.venv/`, `__pycache__/`, `uploads/`, `reports/`. File `.env` bisa ter-commit tidak sengaja.

**Perbaikan:** Tambahkan `.env`, `.env.local`, `*.env`.

---

## 4. Temuan Lama yang Masih Terlewat

### SEC-01 (Sisa) — Default Fallback Key Masih di Kode

Meski sudah pakai `os.environ.get()`, pola berikut masih berbahaya:

```python
os.environ.get("SCRAPINGBEE_KEY", "YOUR_SCRAPINGBEE_KEY_HERE")
os.environ.get("PERPLEXITY_KEY", "YOUR_PERPLEXITY_KEY_HERE")
os.environ.get('GOOGLE_API_KEYS', 'YOUR_GOOGLE_KEY_HERE')
```

**Rekomendasi:** Hapus default fallback; fail fast jika env tidak diset. Sediakan `.env.example` tanpa nilai asli.

---

### LOG-02 (Sisa) — Mapping Kalimat Semantic Masih Approximate

**Lokasi:** `shingling.py` baris 182–206

Masalah inti belum diselesaikan:
- `doc_words = doc_text.split()` vs kalimat dari `re.split(r'(?<=[.!?])\s+', text)`
- Tidak ada mapping berbasis offset karakter ke indeks kata
- Kalimat tanpa `.` di akhir (umum di skripsi) digabung jadi satu blok panjang

**Dampak:** Semantic layer bisa salah menandai posisi kata pada dokumen dengan format non-standar.

**Perbaikan ideal:** Fungsi `build_sentence_word_spans(doc_text)` yang return `(start_idx, end_idx)` per kalimat dari posisi karakter.

---

### LOG-07 (Sisa) — `exclude_small` Semantic Tidak Lengkap

**Lokasi:** `shingling.py` baris 254–255

```python
if exclude_small and source_url not in sources_report and temp_percentage < 1.0:
    continue
```

Hanya men-skip sumber semantic **baru** dengan kontribusi <1%. Jika sumber sudah ada dari N-Gram, semantic match kecil tetap ditambahkan.

---

### JRN-04 (Sisa) — AI Search Layer Masih Silent

**Lokasi:** `web_scraper.py` `fetch_pplx()` — Perplexity, Gemini, Cohere, Tavily semua `except Exception: pass`.

Academic API sudah diperbaiki dengan `print(f"[!] Warning: ...")`.

---

### Dokumentasi Belum Diupdate

| File | Masalah |
|------|---------|
| `README.md` | Masih menyebut `all-MiniLM-L6-v2`, threshold `0.75`, API key hardcoded |
| `AUDIT_LENGKAP.md` | Belum ada status pasca-perbaikan |
| `SETUP_GOOGLE_API.md` | Masih contoh hardcode key di code |

---

## 5. Backlog yang Belum Disentuh (Expected)

Temuan berikut **belum diharapkan** diperbaiki pada iterasi ini — tetap valid sebagai keterbatasan:

| ID | Temuan | Prioritas |
|----|--------|-----------|
| LOG-03 | N-Gram non-fuzzy lokal | P3 |
| JRN-05 | Selector repo Indonesia rapuh | P2 |
| JRN-06 | Sampling 50 probe (~2–5% dokumen) | Desain |
| JRN-07 | Scrape max 5 halaman PDF | P3 |
| EXT-01 | PDF scan tanpa OCR | P3 |
| EXT-02 | Deteksi manipulasi sempit | P3 |
| EXT-03 | `clean_text` front matter rapuh | P3 |
| UI-02 | Tidak ada rate limiting upload | P3 |
| SEC-04 | `verify=False` di scrape | P3 |
| SEC-05 | Cleanup uploads/reports | P3 |

---

## 6. Verifikasi Positif (Yang Sudah Benar)

Perbaikan berikut **diverifikasi benar** di kode:

1. **JRN-01** — Pairing URL-teks per API source, bukan zip global
2. **LOG-01** — `for s in sorted_sources` (bukan `top_sources[:20]`)
3. **LOG-04** — Per-URL corpus, domain dedup dihapus
4. **LOG-05** — Model multilingual aktif
5. **LOG-12** — No double counting semantic tetap benar
6. **SEC-02** — `debug=False`
7. **SEC-03** — Ngrok opt-in via env
8. **UI-01** — UI hanya terima PDF
9. **OpenAlex** — Rekonstruksi `abstract_inverted_index` sudah diimplementasi (tinggal dipakai di preloaded)
10. **Error logging** — Academic fetch functions log exception

---

## 7. Skor Kematangan (Perkiraan)

| Dimensi | Audit v1.0 | Audit Ulang | Delta |
|---------|------------|-------------|-------|
| Keamanan | 3/10 | 6/10 | +3 |
| Akurasi algoritma | 5/10 | 7/10 | +2 |
| Reliabilitas API/jurnal | 4/10 | 5/10 | +1 |
| Maintainability | 5/10 | 6/10 | +1 |
| Dokumentasi | 6/10 | 5/10 | -1 (belum sync) |

---

## 8. Action Items Tersisa (Prioritas)

### Segera (≤ 1 jam)

| # | Aksi | File |
|---|------|------|
| 1 | Hapus duplikat `if __name__` | `server.py` |
| 2 | Masukkan `u_oa`/`t_fallback` ke `preloaded` | `web_scraper.py` |
| 3 | Tambah `.env` ke `.gitignore` | `.gitignore` |
| 4 | Hapus default API key fallback | `web_scraper.py`, `free_api_fallbacks.py` |
| 5 | Buat `.env.example` | root `plagiarism_checker/` |

### Minggu ini

| # | Aksi | File |
|---|------|------|
| 6 | `build_sentence_word_spans()` untuk semantic | `shingling.py` |
| 7 | Seragamkan `from duckduckgo_search import DDGS` | `web_scraper.py` |
| 8 | Log error di `fetch_pplx()` | `web_scraper.py` |
| 9 | Update README (model, threshold, env setup) | `README.md` |

### Backlog

| # | Aksi |
|---|------|
| 10 | Uji & perbaiki selector `indonesian_repos.py` |
| 11 | Rate limiting Flask-Limiter |
| 12 | OCR fallback PDF scan |

---

## 9. Checklist Verifikasi Pasca-Fix Round 2

```
[ ] server.py — satu blok __main__ saja
[ ] OpenAlex abstract masuk preloaded_corpus (bukan hanya scrape queue)
[ ] Google CSE snippet masuk preloaded_corpus
[ ] Tidak ada string API key di grep source (hanya .env.example)
[ ] .env di .gitignore
[ ] DDGS import konsisten
[ ] README menyebut multilingual model + threshold 0.88
[ ] Upload PDF known-plagiarism → skor > 0 dengan sumber URL benar
```

---

## 10. Kesimpulan

Perbaikan Anda **on track** — 6 dari 9 item P0/P1/P2 utama sudah selesai atau hampir selesai. Yang paling mendesak sekarang:

1. **NEW-02** — jangan buang teks OpenAlex/CSE setelah susah memperbaiki zip
2. **SEC-01 sisa** — hapus fallback key (env-only)
3. **NEW-01** — bersihkan duplikat `server.py`

Setelah 5 action item "Segera" di atas, modul siap untuk uji end-to-end dengan PDF skripsi nyata.

---

**Versi dokumen:** 1.0  
**Lokasi:** `plagiarism_checker/docs/AUDIT_ULANG.md`  
**Dokumen terkait:** [AUDIT_LENGKAP.md](AUDIT_LENGKAP.md)
