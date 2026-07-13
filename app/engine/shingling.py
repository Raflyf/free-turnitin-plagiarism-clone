import re
from .semantic_similarity import batch_semantic_check

def get_sentences(text):
    sentences = re.split(r'(?<=[.!?]) +', text)
    return [s.strip() for s in sentences if len(s.split()) >= 3]

def get_ngrams(text, n=5):
    """
    Menghasilkan N-Grams dari teks.
    Turnitin default menggunakan threshold 5 kata berurutan.
    """
    # 1. OPTIMALISASI PRE-PROCESSING: Gabungkan kata yang terpisah oleh tanda hubung (hyphen) di akhir baris
    text = re.sub(r'-\s+', '', text)
    # 2. Hapus semua tanda baca kecuali karakter alfanumerik dan spasi
    text = re.sub(r'[^\w\s]', '', text)
    words = text.lower().split()
    return [" ".join(words[i:i+n]) for i in range(len(words)-n+1)]

def get_shingles(text, n=5):
    return set(get_ngrams(text, n))

def calculate_similarity(doc_text, corpus, exclude_small=False, use_semantic=True, semantic_threshold=0.75):
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
    """
    doc_sentences = get_sentences(doc_text)
    if not doc_sentences:
        return [], 0.0, []

    doc_words = doc_text.split()
    total_doc_words = len(doc_words)
    if total_doc_words == 0:
        return [], 0.0, []

    # 1. Pra-pemrosesan Corpus (Deduplikasi Domain)
    domain_corpus = {}
    for url, source_text in corpus.items():
        base_domain = url.split('//')[-1].split('/')[0] if '//' in url else url
        if base_domain not in domain_corpus:
            domain_corpus[base_domain] = source_text
        else:
            domain_corpus[base_domain] += " " + source_text

    if not domain_corpus:
        return [], 0.0, []

    total_doc_ngrams = set(get_ngrams(doc_text, n=5))
    
    sources_report = {}
    
    # 2. Hitung Kemiripan per Sumber secara Matematis Akurat
    for domain, source_text in domain_corpus.items():
        s_ngrams = set(get_ngrams(source_text, n=5))
        overlap_ngrams = total_doc_ngrams.intersection(s_ngrams)
        
        if not overlap_ngrams:
            continue
            
        # Hitung persis berapa kata di doc_text yang tersusun dari overlap_ngrams sumber INI
        clean_doc_words = [re.sub(r'[^\w\s]', '', w).lower() for w in doc_words]
        is_matched_source = [False] * len(doc_words)
        
        for i in range(len(doc_words) - 5 + 1):
            ngram = " ".join(clean_doc_words[i:i+5])
            if ngram in overlap_ngrams:
                for j in range(5):
                    is_matched_source[i+j] = True
                    
        # Gap Filling untuk Sumber (Meniru blok Turnitin)
        for i in range(len(is_matched_source) - 3):
            if is_matched_source[i] and not is_matched_source[i+1]:
                # Cari True terdekat dalam jarak 3 kata
                for gap in range(2, 4):
                    if i + gap < len(is_matched_source) and is_matched_source[i+gap]:
                        for fill in range(1, gap):
                            is_matched_source[i+fill] = True
                        break
                    
        matched_word_count = sum(is_matched_source)
        percentage = (matched_word_count / total_doc_words) * 100.0
        
        if exclude_small and percentage < 1.0:
            continue
            
        if percentage > 0:
            sources_report[domain] = {
                'percentage': float(percentage),
                'matched_words': int(matched_word_count),
                'url': domain,
                'sort_score': float(percentage),
                'overlap_ngrams': overlap_ngrams # Simpan untuk agregasi global nanti
            }

    # Urutkan berdasarkan persentase tertinggi
    sorted_sources = sorted(list(sources_report.values()), key=lambda x: x['sort_score'], reverse=True)
    top_sources = sorted_sources[:20] # Ambil 20 sumber teratas
    
    # 3. Agregasi Keseluruhan (Overall Similarity Index)
    # Turnitin menghitung indeks total dari GABUNGAN semua kata yang plagiat dari SUMBER MANAPUN.
    global_overlap_ngrams = set()
    for s in top_sources:
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

    # Global Gap Filling: Sorot 1-3 kata yang terselip di antara frasa plagiat
    for i in range(len(is_matched_global) - 3):
        if is_matched_global[i] and not is_matched_global[i+1]:
            for gap in range(2, 4):
                if i + gap < len(is_matched_global) and is_matched_global[i+gap]:
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
        print(f"[!] Threshold: {semantic_threshold}, Total sentences: {len(doc_sentences)}")
        
        # Identifikasi kalimat yang TIDAK terdeteksi oleh N-Gram
        unmatched_sentences = []
        unmatched_indices = []
        
        sentence_word_positions = []  # Track posisi kata untuk setiap kalimat
        current_pos = 0
        
        for sent_idx, sentence in enumerate(doc_sentences):
            sent_words = sentence.split()
            sent_word_count = len(sent_words)
            
            # Cek apakah kalimat ini sebagian besar belum terdeteksi oleh N-Gram
            sent_start = current_pos
            sent_end = current_pos + sent_word_count
            
            if sent_end > len(is_matched_global):
                sent_end = len(is_matched_global)
            
            matched_in_sentence = sum(is_matched_global[sent_start:sent_end])
            match_ratio = matched_in_sentence / sent_word_count if sent_word_count > 0 else 0
            
            sentence_word_positions.append((sent_start, sent_end))
            
            # Jika kurang dari 30% kata di kalimat ini terdeteksi N-Gram, cek semantic
            if match_ratio < 0.3 and sent_word_count >= 5:
                unmatched_sentences.append(sentence)
                unmatched_indices.append(sent_idx)
            
            current_pos += sent_word_count
        
        print(f"[!] Found {len(unmatched_sentences)} unmatched sentences for semantic check")
        
        if unmatched_sentences:
            # Siapkan corpus dalam format yang diperlukan semantic_similarity
            corpus_by_sentence = {}
            for url, source_text in corpus.items():
                corpus_by_sentence[url] = get_sentences(source_text)
            
            # Jalankan batch semantic check
            semantic_results = batch_semantic_check(
                unmatched_sentences, 
                corpus_by_sentence, 
                threshold=semantic_threshold
            )
            
            print(f"[!] Semantic check found {len(semantic_results)} potential paraphrase matches")
            
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
                    
                    # Update global match status untuk kalimat ini
                    # PENTING: Hanya hitung kata yang BELUM terdeteksi N-Gram (no double counting)
                    sent_start, sent_end = sentence_word_positions[actual_sent_idx]
                    newly_detected_words = 0
                    
                    for word_idx in range(sent_start, sent_end):
                        if word_idx < len(is_matched_global):
                            if not is_matched_global[word_idx]:  # Hanya hitung yang BELUM terdeteksi
                                newly_detected_words += 1
                                is_matched_global[word_idx] = True
                    
                    # Hitung HANYA kata tambahan yang terdeteksi oleh semantic (no double counting)
                    semantic_plagiarized_words += newly_detected_words
                    
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
            
            # Recalculate total similarity dengan semantic results
            total_plagiarized_words_global = sum(is_matched_global)
            
            # Sort ulang sources dengan semantic results
            sorted_sources = sorted(list(sources_report.values()), key=lambda x: x['sort_score'], reverse=True)
            top_sources = sorted_sources[:20]
    
    total_similarity = float((total_plagiarized_words_global / total_doc_words) * 100.0)
    
    print(f"\n[!] ===== DETECTION SUMMARY =====")
    print(f"[!] N-Gram similarity: {ngram_similarity:.2f}%")
    print(f"[!] Semantic additional detection: {(semantic_plagiarized_words / total_doc_words * 100):.2f}%")
    print(f"[!] Total similarity (combined): {total_similarity:.2f}%")
    
    return sorted_sources, total_similarity, plagiarized_sentences_data
