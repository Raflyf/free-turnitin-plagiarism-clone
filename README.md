# Turnitin Clone Enterprise - Plagiarism Checker

Modul ini adalah _tools_ pengecek plagiarisme mandiri tingkat lanjut (Clone Turnitin) yang berjalan secara lokal untuk mendeteksi indeks kesamaan (plagiarisme) dari dokumen skripsi Anda dengan seluruh sumber publik maupun repositori di Internet.

## Arsitektur & Cara Kerja (Turnitin-style)

Sistem kini tidak lagi menggunakan script terminal biasa, melainkan menggunakan ekosistem *Hybrid* skala besar:

1. **Hybrid Winnowing Fingerprinting:** Mengekstrak **50 Sampel Fingerprints** (25 kalimat terpanjang untuk jaminan penemuan URL spesifik + 25 sampel seragam/merata dari Bab 1 s/d Bab 5 untuk penyisiran area dokumen).
2. **AI Search Engine:** Mengandalkan **Perplexity AI, Google Gemini, Cohere, dan Tavily** secara paralel (*Load Balanced*) untuk mencari sumber kutipan tersembunyi.
3. **Academic Repository Crawler:** Menggunakan *ScrapingBee* & *ScraperAPI* untuk menembus proteksi Cloudflare/WAF kampus demi mengumpulkan data secara instan dari:
   - **Garuda Kemdikbud** (Seluruh Jurnal Nasional & Kampus Indonesia)
   - **Google Scholar**
   - **OpenAlex** (250+ Juta Makalah Akademik)
   - **Semantic Scholar**
   - **Crossref**
4. **Fuzzy Search & Strict Local N-Gram:** Menembakkan kueri secara *Fuzzy (BM25)* ke mesin pencari agar toleran terhadap *typo/OCR error* teks PDF, kemudian memproses silang seluruh teks sumber yang berhasil diunduh menggunakan mesin **N-Gram Shingling Exact Match** secara lokal. Algoritma ini meniru persis metode komputasi Turnitin untuk menghindari *False Positives* dan menghasilkan PDF Report yang identik.

## Cara Penggunaan (Web Interface)

Sistem telah diintegrasikan secara penuh ke dalam antarmuka Web UI yang interaktif, mewah, dan responsif.

1. Buka terminal dan pastikan _virtual environment_ Anda (`.venv`) aktif.
2. Jalankan server Flask (dari root direktori `Code_Spam_Email`):

```bash
python plagiarism_checker/app/server.py
```
*(Catatan: server.py berisi logic socket.io dan UI untuk plagiarism checker khusus)*

3. Buka browser web Anda dan navigasikan ke `http://localhost:5000`.
4. Unggah file skripsi (PDF) melalui antarmuka Web UI yang tersedia.
5. Pantau *progress bar* yang secara *real-time* menampilkan:
   - Indikator antrean pencarian API (contoh: `1/100`)
   - Indikator kecepatan unduhan file target (`MB/s` atau `KB/s`)
6. Saat pemrosesan selesai, sistem akan menampilkan Skor Persentase Plagiarisme, metrik sumber-sumber utama (domain), beserta opsi untuk mengunduh **Originality PDF Report** bergaya Turnitin asli.
