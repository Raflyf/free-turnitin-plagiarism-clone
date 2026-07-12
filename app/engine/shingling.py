import re

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

def calculate_similarity(doc_text, corpus, exclude_small=False):
    """
    Algoritma Turnitin Asli (Rabin-Karp / N-Gram Exact Match).
    Tidak menggunakan Cosine Similarity / AI Topic Matching agar tidak terjadi False Positives.
    Skor dihitung 100% mutlak berdasarkan rasio kata yang benar-benar overlap (plagiat).
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

    # Total Kata Plagiat Global
    total_plagiarized_words_global = sum(is_matched_global)
    total_similarity = float((total_plagiarized_words_global / total_doc_words) * 100.0)
    
    return sorted_sources, total_similarity, plagiarized_sentences_data
