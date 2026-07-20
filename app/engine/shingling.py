import re
from .semantic_similarity import batch_semantic_check

# Frasa umum akademik Indonesia yang BUKAN plagiarisme (boilerplate phrases)
# Filter ini mencegah false positive pada kalimat generik
COMMON_ACADEMIC_PHRASES = {
    "yang telah dilakukan oleh",
    "dalam penelitian ini penulis",
    "berdasarkan hasil penelitian yang",
    "dari hasil penelitian ini",
    "dapat disimpulkan bahwa hasil",
    "metode yang digunakan dalam",
    "data yang diperoleh dari",
    "hasil penelitian menunjukkan bahwa",
    "penelitian ini bertujuan untuk",
    "teknik pengumpulan data yang",
    "populasi dan sampel dalam",
    "analisis data menggunakan metode",
    "hasil dan pembahasan dalam",
    "berdasarkan latar belakang masalah",
    "rumusan masalah dalam penelitian",
    "manfaat penelitian ini adalah",
    "batasan masalah dalam penelitian",
    "definisi operasional variabel dalam",
    "kerangka berpikir dalam penelitian",
    "hipotesis penelitian ini adalah",
    "jenis penelitian yang digunakan",
    "sumber data dalam penelitian",
    "teknik analisis data yang",
    "uji validitas dan reliabilitas",
    "hasil uji hipotesis menunjukkan",
    "ini penulis menggunakan metode",
    "penulis menggunakan metode yang",
    "menggunakan metode yang telah",
    "penelitian ini menggunakan metode",
    "yang digunakan dalam penelitian",
    "digunakan dalam penelitian ini",
    "ini adalah penelitian yang",
    "sampel dalam penelitian ini",
    "penelitian ini adalah untuk",
    "tujuan penelitian ini adalah",
    "objek penelitian ini adalah",
    "subjek penelitian ini adalah",
    "lokasi penelitian ini adalah",
    "waktu penelitian ini dilakukan",
    "variabel dalam penelitian ini",
    "instrumen dalam penelitian ini",
    "indikator dalam penelitian ini",
    "penelitian ini dilakukan di",
    "penelitian ini dilakukan pada",
    "penelitian ini dilakukan untuk",
    "metode penelitian yang digunakan",
    "pendekatan yang digunakan dalam",
    "teknik yang digunakan dalam",
    "analisis yang digunakan dalam",
    "berdasarkan hasil analisis yang",
    "berdasarkan hasil observasi yang",
    "berdasarkan data yang diperoleh",
    "berdasarkan tabel di atas",
    "berdasarkan gambar di atas",
    "berdasarkan grafik di atas",
    "dari tabel di atas",
    "dari gambar di atas",
    "pada tabel di atas",
    "pada gambar di atas",
    "seperti yang terlihat pada",
    "seperti yang ditunjukkan pada",
    "hal ini menunjukkan bahwa",
    "hal ini disebabkan oleh",
    "hal ini dikarenakan oleh",
    "hal ini sesuai dengan",
    "hal ini sejalan dengan",
    "hal ini berbeda dengan",
    "dengan demikian dapat disimpulkan",
    "oleh karena itu dapat",
    "oleh karena itu penelitian",
    "oleh karena itu penulis",
    "dengan kata lain bahwa",
    "adapun yang menjadi tujuan",
    "adapun yang menjadi manfaat",
    "adapun yang menjadi rumusan",
}

def is_common_phrase(ngram_text):
    """Cek apakah n-gram adalah frasa umum akademik (bukan plagiarisme)"""
    for phrase in COMMON_ACADEMIC_PHRASES:
        if phrase in ngram_text or ngram_text in phrase:
            return True
    return False

def get_sentences(text, filter_short=False):
    # Improved: handle kalimat tanpa titik yang dipisah newline atau semicolon
    text = re.sub(r'\n+', '. ', text)
    sentences = re.split(r'(?<=[.!?;])\s+', text)
    if filter_short:
        return [s.strip() for s in sentences if len(s.split()) >= 3]
    return [s.strip() for s in sentences if s.strip()]

def build_sentence_word_spans(doc_text, max_words=40):
    """
    LOG-02: Memetakan kalimat ke indeks kata (word offsets) dengan presisi.
    Jika kalimat tidak memiliki titik dan sangat panjang, akan dipecah otomatis 
    agar Semantic AI tidak terkena limit token.
    Returns: list of (chunk_text, start_idx, end_idx)
    """
    doc_words = doc_text.split()
    spans = []
    
    sentences_raw = re.split(r'(?<=[.!?])\s+', doc_text)
    current_word_idx = 0
    
    for raw_sent in sentences_raw:
        raw_sent = raw_sent.strip()
        if not raw_sent: continue
        
        words_in_sent = raw_sent.split()
        for i in range(0, len(words_in_sent), max_words):
            chunk_words = words_in_sent[i:i+max_words]
            chunk_len = len(chunk_words)
            chunk_text = ' '.join(chunk_words)
            
            start_idx = current_word_idx
            end_idx = current_word_idx + chunk_len
            
            spans.append((chunk_text, start_idx, end_idx))
            current_word_idx += chunk_len
            
    return spans

def get_ngrams(text, n=5):
    """
    Menghasilkan N-Grams dari teks.
    Turnitin default menggunakan threshold 5 kata berurutan.
    """
    text = re.sub(r'-\s+', '', text)
    text = re.sub(r'[^\w\s]', '', text)
    words = text.lower().split()
    ngrams = []
    for i in range(len(words)-n+1):
        gram = " ".join(words[i:i+n])
        if not is_common_phrase(gram):
            ngrams.append(gram)
    return ngrams

def get_shingles(text, n=5):
    return set(get_ngrams(text, n))

def calculate_similarity(doc_text, corpus, exclude_small=False, use_semantic=False, semantic_threshold=0.88, semantic_max_sources=None, min_source_overlap=1):
    """
    Algoritma Turnitin Asli (Rabin-Karp / N-Gram Exact Match) + Semantic Similarity.

    Layer 1: N-Gram exact matching untuk deteksi copy-paste langsung
    Layer 2: Semantic similarity untuk deteksi parafrasa (opsional)

    Args:
        doc_text: Teks dokumen yang akan dicek
        corpus: Dictionary mapping URL ke teks sumber
        exclude_small: Exclude sumber dengan persentase < 1%
        use_semantic: Aktifkan layer semantic similarity untuk deteksi parafrasa
        semantic_threshold: Minimum similarity score (0-1) untuk semantic matching
        semantic_max_sources: Batasi layer semantic hanya ke N sumber ber-overlap N-Gram
            teratas. None (default) = tanpa batas (semua sumber ber-overlap dicek), agar
            perilaku validasi groundtruth TIDAK berubah. Alur web bank-first mengisi angka
            (mis. 500) supaya semantic tidak meng-encode ulang 15.967 sumber -> tetap cepat.
    """
    # FIX hyphenation: get_ngrams() menyatukan kata terpotong tanda hubung di akhir
    # baris ("peng-\n eluaran" -> "pengeluaran"), tapi doc_words/clean_doc_words dulu
    # tidak, sehingga n-gram yang cocok di sumber tak pernah ter-atribusi ke kata dokumen.
    # Normalisasi SEKALI di sini agar SEMUA stream token (spans, words, ngrams) konsisten.
    doc_text = re.sub(r'-\s+', '', doc_text)

    doc_spans = build_sentence_word_spans(doc_text)
    if not doc_spans:
        return [], 0.0, []

    doc_words = doc_text.split()
    total_doc_words = len(doc_words)
    if total_doc_words == 0:
        return [], 0.0, []

    if not corpus:
        return [], 0.0, []

    total_doc_ngrams = set(get_ngrams(doc_text, n=5))
    
    sources_report = {}
    
    # 2. Hitung Kemiripan per Sumber secara Matematis Akurat
    for url, source_text in corpus.items():
        s_ngrams = set(get_ngrams(source_text, n=5))
        overlap_ngrams = total_doc_ngrams.intersection(s_ngrams)
        
        if not overlap_ngrams:
            continue

        # min_source_overlap: buang sumber yang overlap-nya sangat tipis SEBELUM union global.
        # Default=1 -> identik perilaku lama (sumber overlap 0 sudah dibuang di atas). Dinaikkan
        # HANYA untuk jalur bank/web (korpus mentah besar) guna mencegah union global "menjahit"
        # potongan pendek dari ratusan sumber tak relevan jadi blok plagiat palsu. Groundtruth
        # (frozen, terkurasi) memakai default -> skor tervalidasi tidak berubah.
        if len(overlap_ngrams) < min_source_overlap:
            continue
            
        # Hitung persis berapa kata di doc_text yang tersusun dari overlap_ngrams sumber INI
        clean_doc_words = [re.sub(r'[^\w\s]', '', w).lower() for w in doc_words]
        is_matched_source = [False] * len(doc_words)
        
        for i in range(len(doc_words) - 5 + 1):
            ngram = " ".join(clean_doc_words[i:i+5])
            if ngram in overlap_ngrams:
                for j in range(5):
                    is_matched_source[i+j] = True
                    
        # Gap Filling konservatif: aturan SAMA dengan global fill (butuh >= 2 kata match
        # di KEDUA sisi gap). Dulu blok ini hanya cek sisi kiri, sehingga sebuah sumber
        # bisa menampilkan % lebih besar daripada kontribusinya ke union global.
        for i in range(len(is_matched_source) - 4):
            if is_matched_source[i] and i > 0 and is_matched_source[i-1] and not is_matched_source[i+1]:
                for gap in range(2, 4):
                    if i + gap < len(is_matched_source) and is_matched_source[i+gap]:
                        if i + gap + 1 < len(is_matched_source) and is_matched_source[i+gap+1]:
                            for fill in range(1, gap):
                                is_matched_source[i+fill] = True
                        break
                    
        matched_word_count = sum(is_matched_source)
        percentage = (matched_word_count / total_doc_words) * 100.0

        # PENTING: JANGAN buang sumber <1% di sini. Turnitin menghitung skor total dari
        # GABUNGAN (union) kata ter-match lintas SEMUA sumber, lalu memfilter <1% hanya
        # pada DAFTAR TAMPILAN. Membuang di sini (sebelum agregasi) memaksa skor total ke
        # 0% saat plagiarisme tersebar tipis di banyak sumber (masing-masing <1%).
        if percentage > 0:
            sources_report[url] = {
                'percentage': float(percentage),
                'matched_words': int(matched_word_count),
                'url': url,
                'sort_score': float(percentage),
                'overlap_ngrams': overlap_ngrams # Simpan untuk agregasi global nanti
            }

    # Urutkan berdasarkan persentase tertinggi
    sorted_sources = sorted(list(sources_report.values()), key=lambda x: x['sort_score'], reverse=True)
    top_sources = sorted_sources[:20] # Ambil 20 sumber teratas

    # 3. Agregasi Keseluruhan (Overall Similarity Index)
    # Turnitin menghitung indeks total dari GABUNGAN semua kata yang plagiat dari SUMBER MANAPUN.
    # Agregasi dari SELURUH sumber ber-overlap (bukan hanya yang lolos filter tampilan).
    global_overlap_ngrams = set()
    for s in sorted_sources:
        global_overlap_ngrams.update(s['overlap_ngrams'])
        
    plagiarized_sentences_data = []
    
    clean_doc_words = [re.sub(r'[^\w\s]', '', w).lower() for w in doc_words]
    is_matched_global = [False] * len(doc_words)
    
    # Tandai seluruh array kata dokumen
    for i in range(len(doc_words) - 5 + 1):
        ngram = " ".join(clean_doc_words[i:i+5])
        if ngram in global_overlap_ngrams:
            for j in range(i, i+5):
                is_matched_global[j] = True

    # Global Gap Filling (konservatif): hanya fill gap jika kedua sisi >= 2 kata match
    for i in range(len(is_matched_global) - 4):
        if is_matched_global[i] and i > 0 and is_matched_global[i-1] and not is_matched_global[i+1]:
            for gap in range(2, 4):
                if i + gap < len(is_matched_global) and is_matched_global[i+gap]:
                    if i + gap + 1 < len(is_matched_global) and is_matched_global[i+gap+1]:
                        for fill in range(1, gap):
                            is_matched_global[i+fill] = True
                    break

    # Bangun kalimat yang di-highlight berdasarkan is_matched_global
    current_phrase = []
    for i in range(len(doc_words)):
        if is_matched_global[i]:
            current_phrase.append(doc_words[i])
        else:
            if current_phrase:
                if len(current_phrase) >= 5:
                    phrase_text = " ".join(current_phrase)
                    
                    # Cari sumber utama yang menyumbang frasa ini untuk pewarnaan
                    p_ngrams = set(get_ngrams(phrase_text, n=5))
                    best_source_id = 1
                    best_overlap = 0
                    for idx, source in enumerate(top_sources):
                        olap = len(p_ngrams.intersection(source['overlap_ngrams']))
                        if olap > best_overlap:
                            best_overlap = olap
                            best_source_id = idx + 1
                            
                    plagiarized_sentences_data.append({
                        'text': phrase_text,
                        'source_id': best_source_id
                    })
                current_phrase = []
                
    if current_phrase and len(current_phrase) >= 5:
        phrase_text = " ".join(current_phrase)
        plagiarized_sentences_data.append({
            'text': phrase_text,
            'source_id': 1
        })

    # Hapus field set dari JSON response
    for s in sorted_sources:
        s.pop('overlap_ngrams', None)

    # Total Kata Plagiat Global (dari N-Gram)
    total_plagiarized_words_global = sum(is_matched_global)
    ngram_similarity = float((total_plagiarized_words_global / total_doc_words) * 100.0)
    
    # ========== LAYER 2: SEMANTIC SIMILARITY (Deteksi Parafrasa) ==========
    semantic_matches = {}
    semantic_plagiarized_words = 0
    
    if use_semantic and corpus:
        print("\n[!] ===== STARTING SEMANTIC SIMILARITY CHECK =====")
        print(f"[!] Threshold: {semantic_threshold}, Total sentences: {len(doc_spans)}")
        
        # Identifikasi kalimat yang TIDAK terdeteksi oleh N-Gram
        unmatched_sentences = []
        unmatched_indices = []
        
        sentence_word_positions = []  # Track posisi kata untuk setiap kalimat
        
        for sent_idx, (sentence, sent_start, sent_end) in enumerate(doc_spans):
            # Clamp DULU sebelum menghitung jumlah kata: kalau tidak, sent_word_count
            # terlalu besar untuk kalimat terakhir -> match_ratio mengecil keliru.
            if sent_end > len(is_matched_global):
                sent_end = len(is_matched_global)

            sent_word_count = sent_end - sent_start

            matched_in_sentence = sum(is_matched_global[sent_start:sent_end])
            match_ratio = matched_in_sentence / sent_word_count if sent_word_count > 0 else 0
            
            sentence_word_positions.append((sent_start, sent_end))
            
            # Jika kurang dari 30% kata di kalimat ini terdeteksi N-Gram, cek semantic
            if match_ratio < 0.3 and sent_word_count >= 5:
                unmatched_sentences.append(sentence)
                unmatched_indices.append(sent_idx)
        
        print(f"[!] Found {len(unmatched_sentences)} unmatched sentences for semantic check")
        
        if unmatched_sentences:
            # Tentukan sumber mana yang diumpankan ke semantic. Secara default SEMUA sumber
            # di corpus (perilaku groundtruth). Bila semantic_max_sources diisi (alur web
            # bank-first), batasi ke N sumber ber-overlap N-Gram teratas -> semantic tak
            # perlu meng-encode ulang belasan ribu sumber, jadi tetap dalam anggaran waktu.
            if semantic_max_sources is not None:
                candidate_urls = [s['url'] for s in sorted_sources[:semantic_max_sources]]
                semantic_corpus = {u: corpus[u] for u in candidate_urls if u in corpus}
                print(f"[!] Semantic dibatasi ke top-{len(semantic_corpus)} sumber ber-overlap (dari {len(corpus)} total)")
            else:
                semantic_corpus = corpus

            # Siapkan corpus dalam format yang diperlukan semantic_similarity
            corpus_by_sentence = {}
            for url, source_text in semantic_corpus.items():
                corpus_by_sentence[url] = get_sentences(source_text, filter_short=True)
            
            # Jalankan batch semantic check
            semantic_results = batch_semantic_check(
                unmatched_sentences, 
                corpus_by_sentence, 
                threshold=semantic_threshold
            )
            
            print(f"[!] Semantic check found {len(semantic_results)} potential paraphrase matches")
            
            # Menyimpan mapping (sent_start, sent_end) ke source URL agar bisa di-filter nanti
            semantic_matches_temp = []
            
            # Proses hasil semantic similarity
            for unmatched_idx, matches in semantic_results.items():
                if matches:
                    actual_sent_idx = unmatched_indices[unmatched_idx]
                    best_match = matches[0]  # Ambil match terbaik
                    
                    # Tambahkan ke plagiarized_sentences_data dengan marker khusus
                    plagiarized_sentences_data.append({
                        'text': unmatched_sentences[unmatched_idx],
                        'source_id': len(top_sources) + 1,  # ID khusus untuk semantic
                        'detection_method': 'semantic',
                        'similarity_score': best_match['similarity_score'],
                        'matched_source': best_match['source_url'],
                        'matched_text': best_match['matched_text']
                    })
                    
                    # LOG-07: Terapkan exclude_small pada hasil semantic
                    source_url = best_match['source_url']
                    
                    sent_start, sent_end = sentence_word_positions[actual_sent_idx]
                    newly_detected_words = 0
                    
                    for word_idx in range(sent_start, sent_end):
                        if word_idx < len(is_matched_global):
                            if not is_matched_global[word_idx]:
                                newly_detected_words += 1
                                
                    # KITA TIDAK LAGI MEMBUANG PER-KALIMAT.
                    # Kumpulkan dulu semuanya ke sumber URL tersebut.
                    
                    # Update is_matched_global sementara (nanti jika sumbernya <1% akan kita bersihkan)
                    # KITA TIDAK LANGSUNG UPDATE is_matched_global di sini!
                    # Simpan dulu koordinat match-nya.
                    semantic_matches_temp.append({
                        'sent_start': sent_start,
                        'sent_end': sent_end,
                        'source_url': source_url,
                        'newly_detected_words': newly_detected_words
                    })
                    
                    # Update sources_report dengan info semantic
                    # PENTING: Hanya hitung kata yang BARU terdeteksi (newly_detected_words), bukan seluruh kalimat
                    source_url = best_match['source_url']
                    if source_url not in sources_report:
                        # Buat entry baru untuk sumber yang terdeteksi via semantic
                        sources_report[source_url] = {
                            'percentage': 0.0,
                            'matched_words': 0,
                            'url': source_url,
                            'sort_score': 0.0,
                            'detection_method': 'semantic'
                        }
                    
                    # Update statistik sumber - HANYA tambahkan kata yang baru terdeteksi (no double counting)
                    sources_report[source_url]['matched_words'] += newly_detected_words
                    sources_report[source_url]['percentage'] = (
                        sources_report[source_url]['matched_words'] / total_doc_words
                    ) * 100.0
                    sources_report[source_url]['sort_score'] = sources_report[source_url]['percentage']
            
            # === AGREGASI GLOBAL SEMANTIC (union lintas SEMUA sumber) ===
            # PENTING: skor total = union kata ter-match dari sumber MANAPUN, seperti
            # Turnitin. exclude_small TIDAK boleh membuang kontribusi ke is_matched_global;
            # ia hanya memangkas DAFTAR TAMPILAN per-sumber (lihat filter di bawah).
            for match_data in semantic_matches_temp:
                semantic_plagiarized_words += match_data['newly_detected_words']
                for word_idx in range(match_data['sent_start'], match_data['sent_end']):
                    if word_idx < len(is_matched_global):
                        is_matched_global[word_idx] = True

            # Recalculate total similarity (union penuh, tidak terpengaruh exclude_small)
            total_plagiarized_words_global = sum(is_matched_global)

            # Sort ulang sources dengan semantic results.
            # PENTING: JANGAN timpa sources_report menjadi hanya >=1% di sini. Daftar
            # penuh harus bertahan agar filter tampilan + fallback di akhir fungsi punya
            # sumber untuk ditampilkan (jika tidak, "14% tapi 0 sumber" tampak seperti bug).
            sorted_sources = sorted(list(sources_report.values()), key=lambda x: x['sort_score'], reverse=True)
            top_sources = sorted_sources[:20]
    
    # Hitung ulang total similarity secara global
    # (Bila kita benar-benar drop words, sum(is_matched_global) akan turun)
    total_similarity = float((sum(is_matched_global) / total_doc_words) * 100.0)

    # FILTER TAMPILAN (bukan agregasi): daftar sumber yang dikembalikan hanya memuat
    # sumber >=1% agar tabel bersih. Ini dilakukan SETELAH total_similarity dihitung,
    # jadi TIDAK memengaruhi skor total (yang tetap dari union penuh is_matched_global).
    display_sources = sorted_sources
    if exclude_small:
        display_sources = [s for s in sorted_sources if s['percentage'] >= 1.0]
        # FALLBACK: jika filter >=1% mengosongkan daftar padahal skor total signifikan
        # (plagiarisme tersebar tipis di banyak sumber), tampilkan 10 penyumbang terbesar
        # agar user tetap melihat asal skor. Tanpa ini, "9% tapi 0 sumber" tampak seperti bug.
        if not display_sources and total_similarity >= 1.0:
            display_sources = sorted_sources[:10]

    print(f"\n[!] ===== DETECTION SUMMARY =====")
    print(f"[!] N-Gram similarity: {ngram_similarity:.2f}%")
    print(f"[!] Semantic additional detection: {(semantic_plagiarized_words / total_doc_words * 100):.2f}%")
    print(f"[!] Total similarity (combined): {total_similarity:.2f}%")
    print(f"[!] Sumber ditampilkan (>=1%): {len(display_sources)} dari {len(sorted_sources)} sumber ber-overlap")

    return display_sources, total_similarity, plagiarized_sentences_data
