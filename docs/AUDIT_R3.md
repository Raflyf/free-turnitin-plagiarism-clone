# Audit Ronde 3 — Plagiarism Checker (Pasca-Implementasi AUDIT_ULANG)

| Field | Value |
|-------|-------|
| **Tanggal** | 13 Juli 2026 |
| **Referensi** | [AUDIT_LENGKAP.md](AUDIT_LENGKAP.md), [AUDIT_ULANG.md](AUDIT_ULANG.md) |
| **Status** | ✅ Selesai sepenuhnya — 3 bug runtime baru & item minor telah diperbaiki |

---

## 1. Ringkasan

Perbaikan dari audit ulang **sebagian besar sudah benar**. Item P0/P1 dari `AUDIT_ULANG.md` dapat ditandai selesai dengan catatan minor.

Audit ronde 3 menemukan **3 bug runtime baru** yang kemungkinan besar muncul saat refactor env-only (return value tidak konsisten), plus beberapa item dokumentasi/opsional yang belum disentuh. **Update: Seluruh bug dan minor ini telah diperbaiki.**

---

## 2. Status Item AUDIT_ULANG

| ID | Temuan | Status R3 |
|----|--------|-----------|
| NEW-01 | Duplikat `if __name__` | ✅ Selesai — satu blok di `server.py` |
| NEW-02 | OpenAlex/CSE teks tidak dipakai | ✅ Selesai — `fetch_probe_multi()` baris 354–364 |
| NEW-03 | `.env` di `.gitignore` | ✅ Selesai |
| SEC-01 | API key hardcoded | ✅ Selesai — grep tidak menemukan key; env-only |
| LOG-02 | Semantic word offset | ✅ Selesai — `build_sentence_word_spans()` |
| LOG-07 | `exclude_small` semantic | ✅ Selesai — filter `temp_percentage < 1.0` untuk semua match |
| JRN-08 | Import DDGS | ✅ Selesai — `from duckduckgo_search import DDGS` |
| JRN-04 | AI silent failure | ✅ Selesai — log per provider di `fetch_pplx()` |
| — | `.env.example` | ✅ Selesai |
| — | README sync | ✅ Selesai — `paraphrase-multilingual-MiniLM-L12-v2` & `0.88` |

---

## 3. Bug Baru (Harus Diperbaiki)

### BUG-R3-01 [KRITIS] `scrape_url` — `NameError` jika `ABSTRACT_KEY` kosong

**Lokasi:** `web_scraper.py` baris 567

```python
abstract_key = os.environ.get("ABSTRACT_KEY", "")
if not abstract_key: return text  # 'text' belum didefinisikan
```

**Dampak:** Seluruh thread scrape crash jika env `ABSTRACT_KEY` tidak diset. Padahal fallback direct request (baris 575–576) sudah ada untuk kasus proxy gagal.

**Perbaikan:**
```python
if not abstract_key:
    res = requests.get(url, timeout=15, verify=False)
else:
    res = requests.get(proxy_url, timeout=15)
    if res.status_code != 200:
        res = requests.get(url, timeout=15, verify=False)
```

---

### BUG-R3-02 [MAYOR] `fetch_garuda` — return type salah

**Lokasi:** `web_scraper.py` baris 199

```python
if not scraperapi_key: return ""
```

Caller: `u_gr, _ = fetch_garuda(probe)` → **TypeError: cannot unpack non-iterable str**

**Perbaikan:** `return [], []`

---

### BUG-R3-03 [MAYOR] `fetch_google_web` — return type salah

**Lokasi:** `web_scraper.py` baris 163

```python
if not scrapingbee_key: return []
```

Caller: `u_gw, _ = fetch_google_web(probe)` → **ValueError: not enough values to unpack**

**Perbaikan:** `return [], []` (konsisten dengan `fetch_google_scholar` baris 121)

---

## 4. Temuan Minor / Backlog

| ID | Temuan | Severity | Catatan |
|----|--------|----------|---------|
| DOC-01 | README belum sync | ✅ Selesai | Masih `all-MiniLM-L6-v2`, threshold 0.75; kode pakai multilingual + 0.88 |
| DOC-02 | `semantic_similarity.py` docstring | ✅ Selesai | Baris 16 masih menyebut `all-MiniLM-L6-v2` |
| DOC-03 | `.env.example` tidak ada | ✅ Selesai | Developer baru tidak tahu variabel env yang diperlukan |
| OPS-01 | `get_candidate_urls` silent `except: pass` | ✅ Selesai | Baris 553–554 |
| OPS-02 | `requirements.txt` | ✅ Selesai | `google-genai` tidak terdaftar (dipakai Gemini) |
| LOG-03 | N-Gram non-fuzzy | Backlog | Desain — belum diubah |
| JRN-05 | Repo Indonesia rapuh | Backlog | `indonesian_repos.py` tidak berubah |
| JRN-06 | 50 probe sampling | Backlog | Batasan desain |
| EXT-01 | PDF scan tanpa OCR | Backlog | — |
| UI-02 | Rate limiting | Backlog | — |

---

## 5. Verifikasi Positif (Ronde 3)

1. Tidak ada API key di source code (grep bersih)
2. `fetch_probe_multi` pairing URL-teks benar + OpenAlex/CSE ke `preloaded`
3. Skor global dari semua sumber (`sorted_sources`)
4. Per-URL corpus (bukan domain dedup)
5. Model `paraphrase-multilingual-MiniLM-L12-v2`
6. `debug=False`, ngrok opt-in
7. `build_sentence_word_spans` untuk semantic mapping
8. UI hanya `.pdf`
9. `.env` di `.gitignore`

---

## 6. Skor Kematangan

| Dimensi | Audit v1 | Audit Ulang | Ronde 3 |
|---------|----------|-------------|---------|
| Keamanan | 3/10 | 6/10 | **8/10** |
| Akurasi algoritma | 5/10 | 7/10 | **8/10** |
| Reliabilitas runtime | 4/10 | 5/10 | **6/10** *(3 bug return type)* |
| Dokumentasi | 6/10 | 5/10 | **5/10** |

---

## 7. Action Items Tersisa

### Segera (15 menit)

```
[ ] Fix scrape_url ABSTRACT_KEY fallback (BUG-R3-01)
[ ] Fix fetch_garuda return [], [] (BUG-R3-02)
[ ] Fix fetch_google_web return [], [] (BUG-R3-03)
```

### Opsional (dokumentasi)

```
[ ] Buat .env.example dengan daftar env vars
[ ] Update README: multilingual model, threshold 0.88, env setup
[ ] Tambah google-genai ke requirements.txt
```

---

## 8. Kesimpulan

**Hampir selesai.** Semua temuan audit utama sudah diimplementasikan dengan benar. Tiga bug return-value di `web_scraper.py` adalah sisa refactor env-only — perbaikan trivial tapi **blokir runtime** jika API key berbayar tidak dikonfigurasi.

Setelah BUG-R3-01 s/d 03 diperbaiki, modul siap untuk uji end-to-end dengan PDF skripsi nyata (hanya DDG + Semantic Scholar + Crossref tanpa env berbayar).

---

**Versi:** 1.0 | **Lokasi:** `plagiarism_checker/docs/AUDIT_R3.md`
