import re

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
    # Konsep "N-Gram 3.55" (Weighted Average: 45% dari N-Gram 3 dan 55% dari N-Gram 4)
    # Bobot: (3 * 0.45) + (4 * 0.55) = 1.35 + 2.2 = 3.55
    N_GRAM = 3
    doc_ngrams_3 = set(get_ngrams(doc_text, n=3))
    doc_ngrams_4 = set(get_ngrams(doc_text, n=4))
    
    if not doc_ngrams_3:
        return {}, 0.0, []

    total_ngrams_3 = len(doc_ngrams_3)
    total_ngrams_4 = len(doc_ngrams_4)
    
    matched_ngrams_global_3 = set()
    matched_ngrams_global_4 = set()
    
    # Simpan report per URL
    sources_report = {}
    
    # Untuk highlight kalimat plagiat di laporan
    doc_sentences = get_sentences(doc_text)
    plagiarized_sentences_data = []

    # Gabungkan teks dari artikel yang berasal dari domain yang sama (Deduplikasi)
    # Agar di laporan PDF tidak muncul banyak "medium.com" secara berulang
    domain_corpus = {}
    for url, source_text in corpus.items():
        base_domain = url.split('//')[-1].split('/')[0]
        if base_domain not in domain_corpus:
            domain_corpus[base_domain] = source_text
        else:
            domain_corpus[base_domain] += " " + source_text
            
    corpus = domain_corpus # Timpa corpus asli dengan corpus hasil gabungan domain

    for url, source_text in corpus.items():
        source_ngrams_3 = set(get_ngrams(source_text, n=3))
        source_ngrams_4 = set(get_ngrams(source_text, n=4))
        
        overlap_3 = doc_ngrams_3.intersection(source_ngrams_3)
        overlap_4 = doc_ngrams_4.intersection(source_ngrams_4)
        
        if overlap_3 or overlap_4:
            pct_3 = (len(overlap_3) / total_ngrams_3) * 100 if total_ngrams_3 else 0
            pct_4 = (len(overlap_4) / total_ngrams_4) * 100 if total_ngrams_4 else 0
            
            # "N-Gram 3.55" menggunakan pembobotan 45% (3) dan 55% (4)
            match_percentage = (pct_3 * 0.45) + (pct_4 * 0.55)
            
            if exclude_small and match_percentage < 1.0:
                continue
            
            # Jika lolos filter, baru ditambahkan ke global pool
            matched_ngrams_global_3.update(overlap_3)
            matched_ngrams_global_4.update(overlap_4)
            
            # Berikan prioritas (Priority Multiplier) untuk situs akademik/jurnal/repositori
            priority = 1.0
            academic_keywords = ['.ac.id', '.edu', 'jurnal', 'repository', 'scholar', 'researchgate', '123dok', 'scribd.com', 'core.ac.uk', 'digilib', 'eprints']
            if any(kw in url.lower() for kw in academic_keywords):
                priority = 5.0  # Boost 5x lipat agar web kampus selalu berada di Ranking Atas
                
            # Tampilkan semua sumber yang memiliki minimal 1 irisan N-Gram
            # Untuk jumlah matched words, kita ambil rata-ratanya juga
            words_3 = len(overlap_3) * 3
            words_4 = len(overlap_4) * 4
            sources_report[url] = {
                'percentage': match_percentage,
                'matched_words': int((words_3 * 0.45) + (words_4 * 0.55)),
                'url': url,
                'sort_score': match_percentage * priority
            }

    # Hitung total kemiripan keseluruhan (tanpa duplikasi antar sumber)
    total_sim_3 = (len(matched_ngrams_global_3) / total_ngrams_3) * 100 if total_ngrams_3 else 0
    total_sim_4 = (len(matched_ngrams_global_4) / total_ngrams_4) * 100 if total_ngrams_4 else 0
    total_similarity = (total_sim_3 * 0.45) + (total_sim_4 * 0.55)
    
    # Batasi maksimal 100%
    if total_similarity > 100:
        total_similarity = 100.0
        
    # Set matched_ngrams_global kembali ke N-Gram 3 agar highlighting di PDF bisa berfungsi maksimal
    matched_ngrams_global = matched_ngrams_global_3

    # Urutkan sumber berdasarkan kombinasi kecocokan dan tingkat prioritas akademis
    sorted_sources = sorted(
        list(sources_report.values()), 
        key=lambda x: x['sort_score'], 
        reverse=True
    )

    # Mencari kalimat yang plagiat untuk ditampilkan
    # Memerlukan ID sumber agar bisa diwarnai sesuai dengan ranking
    
    # PRECOMPUTE: Hitung N-Gram sumber SEKALI SAJA di awal
    top_sources = sorted_sources[:20]
    source_ngrams_cache = {}
    for idx, source in enumerate(top_sources):
        url = source['url']
        if url in corpus:
            source_ngrams_cache[idx] = set(get_ngrams(corpus[url], n=N_GRAM))
    
    for sentence in doc_sentences:
        s_words = sentence.split() # Pertahankan tanda baca asli untuk PDF
        clean_words = [re.sub(r'[^\w\s]', '', w).lower() for w in s_words]
        
        is_matched = [False] * len(s_words)
        
        # Tandai kata mana saja yang masuk dalam 5-Gram plagiat
        for i in range(len(s_words) - N_GRAM + 1):
            ngram = " ".join(clean_words[i:i+N_GRAM])
            if ngram in matched_ngrams_global:
                for j in range(i, i+N_GRAM):
                    is_matched[j] = True
                    
        # Kumpulkan potongan frasa (potongan berurutan yang bernilai True)
        phrases = []
        current_phrase = []
        for i in range(len(s_words)):
            if is_matched[i]:
                current_phrase.append(s_words[i])
            else:
                if current_phrase:
                    phrases.append(" ".join(current_phrase))
                    current_phrase = []
        if current_phrase:
            phrases.append(" ".join(current_phrase))
            
        # Simpan setiap potongan frasa ke daftar highlight
        for phrase in phrases:
            # Gunakan N-Gram dari potongan frasa ini untuk mencari sumber terkuatnya
            p_ngrams = set(get_ngrams(phrase, n=N_GRAM))
            best_source_id = -1
            best_overlap = 0
            
            for idx, cached_ngrams in source_ngrams_cache.items():
                overlap_len = len(p_ngrams.intersection(cached_ngrams))
                if overlap_len > best_overlap:
                    best_overlap = overlap_len
                    best_source_id = idx + 1
                    
            # Jika tidak ada yang cocok (biasanya karena panjang kata < N_GRAM), kita pakai fallback source 1
            if best_source_id == -1 and len(source_ngrams_cache) > 0:
                best_source_id = 1
                
            if best_source_id != -1:
                plagiarized_sentences_data.append({
                    'text': phrase,
                    'source_id': best_source_id
                })

    return sorted_sources, total_similarity, plagiarized_sentences_data
