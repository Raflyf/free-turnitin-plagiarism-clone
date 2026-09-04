# Evaluasi dan Metodologi

Dokumen ini menjelaskan metode deteksi, cara perhitungan skor, benchmark, serta batasan dari OpenPlagiarismChecker.

## Metode Deteksi Kesamaan

### Layer 1: N-Gram Exact Matching
Dokumen dibagi menjadi urutan lima kata yang berdekatan. Urutan tersebut kemudian dibandingkan dengan teks dari sumber yang berhasil ditemukan.
```text
N-Gram Similarity = (Jumlah Kata Dokumen yang Cocok / Total Kata Dokumen) × 100%
```
Kata yang cocok digabungkan menggunakan mekanisme union sehingga bagian yang sama tidak dihitung berulang kali.

### Layer 2: Semantic Similarity
Kalimat dengan tingkat exact-match yang rendah diperiksa oleh semantic similarity layer menggunakan `paraphrase-multilingual-MiniLM-L12-v2`. Threshold semantic disesuaikan secara dinamis menggunakan fungsi *Continuous Square-Root Auto-Thresholding*:
```text
Threshold = 0.7900 + 0.0250 × √(NGram Similarity)
```
Fungsi ini dikembangkan untuk menyesuaikan sensitivitas kesamaan semantik berdasarkan tingkat kecocokan tekstual. Kata yang terdeteksi semantik hanya menambahkan kata yang belum terhitung pada layer N-Gram untuk menghindari penghitungan ganda (*double counting*).

---

## Perhitungan Skor Akhir

```text
Similarity = (Kata N-Gram Match + Kata Semantic Match) / Total Kata Dokumen × 100%
```
Setiap kata dalam dokumen hanya dapat berkontribusi maksimal satu kali terhadap skor akhir.

---

## Hasil Evaluasi Benchmark

Dataset evaluasi saat ini terdiri dari 11 dokumen akademik nyata yang telah memiliki skor kesamaan dari sistem referensi eksternal.

### 1. Core Benchmark 2026 (8 Dokumen)

| Dokumen | Skor Lokal | Target Referensi | Delta (poin) |
| :--- | :---: | :---: | :---: |
| Laila after parafrase | 3.45% | 4% | -0.55 |
| Hesti | 16.91% | 18% | -1.09 |
| Fikri | 13.95% | 14% | -0.05 |
| Rafly | 8.90% | 8% | +0.90 |
| Andyan | 22.26% | 23% | -0.74 |
| Dias Maulana | 21.20% | 23% | -1.80 |
| Melani | 18.74% | 19% | -0.26 |
| Laila before parafrase| 22.09% | 24% | -1.91 |

**Mean Absolute Error (MAE): 0.91 poin persentase.**

### 2. Opsional Baseline 2025 (3 Dokumen)

| Dokumen | Skor Lokal | Target Referensi | Delta (poin) |
| :--- | :---: | :---: | :---: |
| Muhammad Ihsan | 20.69% | 18% | +2.69 |
| Tsaura Halwa | 16.76% | 13% | +3.76 |
| Tesyar | 9.79% | 8% | +1.79 |

*Catatan: Hasil di atas mencerminkan performa pada sampel dataset saat ini. Sistem ini terus divalidasi menggunakan metode Leave-One-Out Cross-Validation (LOOCV) untuk menstabilkan parameter threshold.*

---

## Keterbatasan Sistem

1. **Hanya Mengakses Sumber Publik:** Sistem tidak dapat mereplikasi indeks privat (seperti makalah internal mahasiswa atau jurnal tertutup) yang sering dijangkau oleh platform komersial. Jika dokumen asli tidak pernah dipublikasikan secara terbuka di internet, sistem tidak dapat mendeteksinya.
2. **Kesamaan Bukan Berarti Plagiarisme:** Skor yang tinggi dapat disebabkan oleh daftar pustaka, kutipan langsung, atau metode standar. Interpretasi manual oleh pengguna atau pihak berwenang tetap diperlukan.
3. **Keterbatasan Benchmark:** Margin error (*MAE 0.91*) spesifik pada 8 dokumen *core* di atas. Akurasi dapat bervariasi bergantung pada jenis dokumen, bahasa, dan disiplin ilmu.
4. **Bukan Pengganti Layanan Institusional:** Proyek ini didesain sebagai alat eksperimen dan pemeriksaan pratinjau mandiri, bukan sebagai pengganti layanan evaluasi resmi institusi.
