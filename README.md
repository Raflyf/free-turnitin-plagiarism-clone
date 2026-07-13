# Turnitin Clone Enterprise - Plagiarism Checker

Modul ini adalah _tools_ pengecek plagiarisme mandiri tingkat lanjut (Clone Turnitin) yang berjalan secara lokal untuk mendeteksi indeks kesamaan (plagiarisme) dari dokumen skripsi Anda dengan seluruh sumber publik maupun repositori di Internet.

## 🚀 Latest Updates (v2.0)

### ✨ New Features
- **Semantic Similarity Layer**: Deteksi parafrasa menggunakan sentence-transformers (model 'all-MiniLM-L6-v2')
- **BSI Repository Priority**: Prioritas tinggi untuk repository.bsi.ac.id dan kampus Indonesia lainnya
- **Session-Based Security**: File access dilindungi dengan ownership validation
- **Auto Encoding Detection**: Support untuk berbagai encoding file (UTF-8, Latin-1, CP1252, etc.)

### 🔒 Security Improvements
- File ID menggunakan UUID (cryptographically secure) menggantikan timestamp
- Session-based ownership validation untuk semua endpoints
- 403 Forbidden untuk unauthorized access
- Secret key management untuk Flask sessions

### 🐛 Critical Bug Fixes
- **No Double Counting**: Semantic similarity hanya menghitung kata yang BELUM terdeteksi N-Gram
- **Accurate Per-Source Statistics**: Per-source percentage sekarang benar tanpa inflasi
- **Robust Error Handling**: Better handling untuk corrupt PDFs dan encoding issues

## Arsitektur & Cara Kerja (Turnitin-style)

Sistem menggunakan ekosistem *Hybrid* skala besar dengan **2-Layer Detection**:

### Layer 1: N-Gram Exact Matching
1. **Hybrid Winnowing Fingerprinting:** Mengekstrak **50 Sampel Fingerprints** (25 kalimat terpanjang untuk jaminan penemuan URL spesifik + 25 sampel seragam/merata dari Bab 1 s/d Bab 5 untuk penyisiran area dokumen).
2. **AI Search Engine:** Mengandalkan **Perplexity AI, Google Gemini, Cohere, dan Tavily** secara paralel (*Load Balanced*) untuk mencari sumber kutipan tersembunyi.
3. **Academic Repository Crawler:** Menggunakan *ScrapingBee* & *ScraperAPI* untuk menembus proteksi Cloudflare/WAF kampus demi mengumpulkan data secara instan dari:
   - **Repository BSI** (repository.bsi.ac.id) - **PRIORITAS TERTINGGI**
   - **Garuda Kemdikbud** (Seluruh Jurnal Nasional & Kampus Indonesia)
   - **Google Scholar**
   - **OpenAlex** (250+ Juta Makalah Akademik)
   - **Semantic Scholar**
   - **Crossref**
4. **Fuzzy Search & Strict Local N-Gram:** Menembakkan kueri secara *Fuzzy (BM25)* ke mesin pencari agar toleran terhadap *typo/OCR error* teks PDF, kemudian memproses silang seluruh teks sumber yang berhasil diunduh menggunakan mesin **N-Gram Shingling Exact Match** secara lokal.

### Layer 2: Semantic Similarity (NEW!)
5. **Paraphrase Detection:** Kalimat yang TIDAK terdeteksi oleh N-Gram (< 30% match) akan dicek menggunakan **sentence-transformers** untuk mendeteksi parafrasa dengan threshold 0.75
6. **No Double Counting:** Semantic layer hanya menambah kata yang BELUM terdeteksi N-Gram, menjamin akurasi skor

### Repository Priority System
Sistem menggunakan **3-Tier Priority** untuk memaksimalkan hasil dari repository kampus:
- **Tier 1 (4 slots):** repository.bsi.ac.id, repository.umsu.ac.id, etheses.uin-malang.ac.id, ejournal.itn.ac.id, eprints.undip.ac.id
- **Tier 2 (3 slots):** Repository dan jurnal .ac.id lainnya (eprints, digilib, ejurnal, dspace)
- **Tier 3 (2 slots):** Situs akademik umum (.edu, scholar, researchgate, core.ac.uk)
- **Normal (sisa):** Situs publik non-akademik

## Cara Penggunaan (Web Interface)

Sistem telah diintegrasikan secara penuh ke dalam antarmuka Web UI yang interaktif, mewah, dan responsif.

1. Install dependencies terlebih dahulu:
```bash
pip install -r requirements.txt
```

2. Jalankan server Flask (dari root direktori `Code_Spam_Email`):
```bash
python plagiarism_checker/app/server.py
```
*(Catatan: server.py berisi logic socket.io dan UI untuk plagiarism checker khusus)*

3. Buka browser web Anda dan navigasikan ke `http://localhost:5001`.
4. Unggah file skripsi (PDF) melalui antarmuka Web UI yang tersedia.
5. Pantau *progress bar* yang secara *real-time* menampilkan:
   - Indikator antrean pencarian API (contoh: `1/100`)
   - Indikator kecepatan unduhan file target (`MB/s` atau `KB/s`)
   - Layer detection progress (N-Gram + Semantic)
6. Saat pemrosesan selesai, sistem akan menampilkan:
   - Skor Persentase Plagiarisme Total
   - Breakdown N-Gram detection vs Semantic detection
   - Metrik sumber-sumber utama (domain)
   - Opsi untuk mengunduh **Originality PDF Report** bergaya Turnitin asli

## Dependencies

```
flask>=2.3.0
PyMuPDF>=1.23.0
beautifulsoup4>=4.12.0
requests>=2.31.0
reportlab>=4.0.0
duckduckgo-search>=3.9.0
sentence-transformers>=2.7.0
chardet>=5.2.0
```

## ⚠️ Disclaimer & Limitations

### Apa yang Dijamin:
✅ Algoritma N-Gram dan Semantic Similarity bekerja dengan benar
✅ Tidak ada double counting dalam perhitungan skor
✅ Security: File access terlindungi dengan session validation
✅ Error handling robust untuk berbagai format file dan encoding

### Apa yang TIDAK Dijamin:
❌ **Skor tidak akan persis sama dengan Turnitin asli** karena:
  - Turnitin memiliki database proprietary (200+ juta dokumen berbayar)
  - Turnitin menggunakan algoritma closed-source dengan optimasi 20+ tahun
  - Sistem ini menggunakan public sources dan open repositories
  - Corpus berbeda = hasil bisa berbeda

❌ **Ketergantungan pada External APIs:**
  - API pihak ketiga (Perplexity, Gemini, DuckDuckGo) bisa rate-limited atau down
  - Network issues dapat mempengaruhi web scraping
  - Hasil bergantung pada ketersediaan sumber online

### Rekomendasi Penggunaan:
- Gunakan sebagai **pre-check** sebelum submit ke Turnitin asli
- Jangan gunakan sebagai **satu-satunya validasi**
- Hasil memberikan **indikasi** plagiarisme, bukan **bukti mutlak**
- Untuk submission resmi, tetap gunakan Turnitin kampus

## 🔧 Technical Details

### File Structure
```
plagiarism_checker/
├── app/
│   ├── server.py              # Flask server dengan session management
│   ├── engine/
│   │   ├── extractor.py       # PDF/TXT extraction dengan auto encoding
│   │   ├── shingling.py       # N-Gram + Semantic similarity logic
│   │   ├── semantic_similarity.py  # Sentence transformer model
│   │   ├── web_scraper.py     # Multi-source web crawler
│   │   └── pdf_generator.py   # Report generator
│   ├── templates/             # HTML templates
│   └── static/                # CSS, JS, assets
└── requirements.txt           # Python dependencies
```

### Security Features
- UUID-based file IDs (unpredictable)
- Session-based ownership validation
- File access control with 403 responses
- Secure secret key management
- Input validation and sanitization

### Performance Optimizations
- Parallel API calls (ThreadPoolExecutor)
- Batch processing for semantic similarity
- Efficient N-Gram set operations
- Smart caching for repeated checks

## 📊 Score Calculation

**Global Similarity Score = (Total Plagiarized Words / Total Document Words) × 100%**

Where:
- **N-Gram Layer**: Detects exact/near-exact matches (5-word sequences)
- **Semantic Layer**: Detects paraphrases (similarity score ≥ 0.75)
- **No Double Counting**: Each word counted only once, even if detected by both layers

**Per-Source Score = (Matched Words from Source / Total Document Words) × 100%**

Each source shows:
- Percentage contribution
- Number of matched words
- Detection method (N-Gram or Semantic)
- Source URL

## 🐛 Known Issues & Future Improvements

### Known Limitations:
- External API rate limits dapat membatasi jumlah pencarian
- PDF dengan banyak gambar atau format kompleks mungkin tidak ter-extract sempurna
- Semantic similarity membutuhkan RAM ~2GB untuk model loading

### Planned Improvements:
- [ ] Local document database untuk mengurangi ketergantungan API
- [ ] Support untuk file DOCX dan TXT
- [ ] Custom model fine-tuning untuk bahasa Indonesia
- [ ] Multi-language support
- [ ] Batch processing untuk multiple files

## 📝 Changelog

### v2.0 (Current)
- Added semantic similarity layer for paraphrase detection
- Fixed critical double counting bug in per-source statistics
- Implemented session-based security with UUID file IDs
- Added BSI repository priority system
- Added automatic encoding detection for TXT files
- Improved error handling across all modules

### v1.0
- Initial release with N-Gram shingling
- Web UI with real-time progress
- Multi-source web scraping
- PDF report generation

## 📄 License & Credits

This is an educational project for thesis plagiarism detection. Not affiliated with Turnitin LLC.

**Created for:** Academic integrity support
**Algorithm:** N-Gram Shingling + Semantic Similarity
**Models:** sentence-transformers (all-MiniLM-L6-v2)