def get_ngrams(text, n=5):
    """Membagi teks menjadi N-Grams (Shingling) persis seperti algoritma Turnitin"""
    import re
    text = re.sub(r'[^\w\s]', '', text) # Hapus tanda baca
    words = text.lower().split()
    ngrams = [" ".join(words[i:i+n]) for i in range(len(words)-n+1)]
    return ngrams

def get_sentences(text):
    import re
    sentences = re.split(r'(?<=[.!?]) +', text)
    return [s.strip() for s in sentences if len(s.split()) >= 5]

def calculate_similarity(doc_text, corpus, exclude_small=False):
    """Membandingkan seluruh dokumen dengan database web sementara (Scraped Corpus)"""
    # Kembalikan ke 3-Gram. Terbukti ini adalah pengaturan yang paling akurat 
    # untuk bahasa Indonesia agar hasilnya kembali menyentuh ~20% (mendekati 18%)
    N_GRAM = 3
    doc_ngrams = set(get_ngrams(doc_text, n=N_GRAM))
    
    if not doc_ngrams:
        return {}, 0.0, []

    total_ngrams = len(doc_ngrams)
    matched_ngrams_global = set()
    
    # Simpan report per URL
    sources_report = {}
    
    # Untuk highlight kalimat plagiat di laporan
    doc_sentences = get_sentences(doc_text)
    plagiarized_sentences_data = []

    for url, source_text in corpus.items():
        source_ngrams = set(get_ngrams(source_text, n=N_GRAM))
        overlap = doc_ngrams.intersection(source_ngrams)
        
        if overlap:
            match_percentage = (len(overlap) / total_ngrams) * 100
            
            if exclude_small and match_percentage < 1.0:
                continue
            
            # Jika lolos filter, baru ditambahkan ke global pool
            matched_ngrams_global.update(overlap)
            
            # Tampilkan semua sumber yang memiliki minimal 1 irisan 3-Gram
            sources_report[url] = {
                'percentage': match_percentage,
                'matched_words': int(len(overlap) * N_GRAM),
                'url': url
            }

    # Hitung total kemiripan keseluruhan (tanpa duplikasi antar sumber)
    total_similarity = (len(matched_ngrams_global) / total_ngrams) * 100
    
    # Batasi maksimal 100%
    if total_similarity > 100:
        total_similarity = 100.0

    # Urutkan sumber dari plagiat terbesar ke terkecil
    sorted_sources = sorted(
        list(sources_report.values()), 
        key=lambda x: x['percentage'], 
        reverse=True
    )

    # Mencari kalimat yang plagiat untuk ditampilkan
    # Memerlukan ID sumber agar bisa diwarnai sesuai dengan ranking
    for sentence in doc_sentences:
        s_ngrams = set(get_ngrams(sentence, n=N_GRAM))
        if not s_ngrams:
            continue
            
        # Hitung rasio irisan N-Gram kalimat ini terhadap total N-Gram plagiat global
        overlap_with_global = s_ngrams.intersection(matched_ngrams_global)
        
        # Jika minimal 30% dari N-Gram di kalimat ini terdeteksi plagiat
        if len(overlap_with_global) / len(s_ngrams) > 0.3:
            # Cari sumber mana yang paling banyak beririsan dengan kalimat ini
            best_source_id = -1
            best_overlap = 0
            for idx, source in enumerate(sorted_sources):
                url = source['url']
                if url in corpus:
                    src_ngrams = set(get_ngrams(corpus[url], n=N_GRAM))
                    overlap_len = len(s_ngrams.intersection(src_ngrams))
                    if overlap_len > best_overlap:
                        best_overlap = overlap_len
                        best_source_id = idx + 1 # 1-indexed for Turnitin colors
            
            if best_source_id != -1:
                plagiarized_sentences_data.append({
                    'text': sentence,
                    'source_id': best_source_id
                })

    return sorted_sources, total_similarity, plagiarized_sentences_data
