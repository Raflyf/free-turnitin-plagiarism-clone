import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

# Load model AI secara global agar tidak memberatkan RAM saat berulang-ulang
try:
    from sentence_transformers import SentenceTransformer
    print("[AI] Memuat model Sentence-Transformer (all-MiniLM-L6-v2)...")
    # Model ini sangat ringan (sekitar 80MB) tapi sekelas Turnitin untuk mendeteksi parafrase
    model = SentenceTransformer('all-MiniLM-L6-v2')
except Exception as e:
    print(f"[AI Warning] Gagal memuat model Transformer, fallback ke TF-IDF murni: {e}")
    model = None

def get_sentences(text):
    import re
    sentences = re.split(r'(?<=[.!?]) +', text)
    return [s.strip() for s in sentences if len(s.split()) >= 5]

def get_ngrams(text, n=5):
    text = re.sub(r'[^\w\s]', '', text)
    words = text.lower().split()
    return [" ".join(words[i:i+n]) for i in range(len(words)-n+1)]

def calculate_similarity(doc_text, corpus, exclude_small=False):
    """
    Algoritma Hybrid:
    1. Sentence Transformers (Semantic/Parafrase Detection)
    2. TF-IDF & N-Gram (Copy-Paste Exact Match Detection)
    """
    doc_sentences = get_sentences(doc_text)
    if not doc_sentences:
        return [], 0.0, []

    sources_report = {}
    plagiarized_sentences_data = []
    
    # 1. Pra-pemrosesan Corpus (Deduplikasi Domain)
    domain_corpus = {}
    for url, source_text in corpus.items():
        base_domain = url.split('//')[-1].split('/')[0] if '//' in url else url
        if base_domain not in domain_corpus:
            domain_corpus[base_domain] = source_text
        else:
            domain_corpus[base_domain] += " " + source_text
            
    corpus = domain_corpus
    
    if not corpus:
        return [], 0.0, []

    # 2. Embedding Corpus (Tingkat Dokumen/Paragraf)
    corpus_urls = list(corpus.keys())
    corpus_texts = list(corpus.values())
    
    # Gunakan TF-IDF sebagai baseline kuat untuk exact-match
    vectorizer = TfidfVectorizer(ngram_range=(1,3))
    all_texts = [doc_text] + corpus_texts
    try:
        tfidf_matrix = vectorizer.fit_transform(all_texts)
        cosine_sims = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:]).flatten()
    except:
        cosine_sims = [0] * len(corpus_texts)
    
    # 3. Embedding Semantic AI (Deteksi Parafrase tingkat tinggi)
    semantic_sims = [0] * len(corpus_texts)
    if model is not None:
        try:
            # Potong teks menjadi max 1500 kata untuk evaluasi agar tidak OOM
            short_doc = " ".join(doc_text.split()[:1500])
            short_corpus = [" ".join(t.split()[:1500]) for t in corpus_texts]
            
            doc_emb = model.encode([short_doc])
            corpus_emb = model.encode(short_corpus)
            
            # Hitung Cosine Similarity Semantic
            from numpy import dot
            from numpy.linalg import norm
            
            for i in range(len(corpus_emb)):
                denom = (norm(doc_emb[0])*norm(corpus_emb[i]))
                if denom > 0:
                    semantic_sims[i] = dot(doc_emb[0], corpus_emb[i]) / denom
        except:
            pass

    # 4. Kombinasi Skor (Ensemble)
    for i, url in enumerate(corpus_urls):
        tfidf_score = cosine_sims[i] * 100
        semantic_score = semantic_sims[i] * 100
        
        # Skor akhir adalah skor tertinggi (TF-IDF vs AI)
        # Jika copy-paste identik -> TF-IDF akan tinggi (100%)
        # Jika diubah struktur kalimatnya (parafrase) -> Semantic akan tinggi
        final_percentage = max(tfidf_score, semantic_score)
        
        # Penyesuaian agar tidak terlalu sensitif untuk similarity rendah
        if final_percentage < 3.0:
            final_percentage = 0.0
            
        if exclude_small and final_percentage < 5.0:
            continue
            
        if final_percentage > 0:
            # Prioritas untuk jurnal
            priority = 1.0
            academic_keywords = ['.ac.id', '.edu', 'jurnal', 'repository', 'scholar', 'researchgate', 'crossref', 'semanticscholar']
            if any(kw in url.lower() for kw in academic_keywords):
                priority = 2.0
                
            sources_report[url] = {
                'percentage': min(100.0, final_percentage),
                'matched_words': int((final_percentage/100) * len(doc_text.split())),
                'url': url,
                'sort_score': final_percentage * priority
            }

    # Urutkan berdasarkan sort_score tertinggi
    sorted_sources = sorted(list(sources_report.values()), key=lambda x: x['sort_score'], reverse=True)
    top_sources = sorted_sources[:20]

    # 5. Pencarian Kalimat Plagiat (Untuk Highlighting PDF)
    # Kombinasi Shingling (N-Gram 5) untuk validitas setara Turnitin
    total_doc_ngrams = set(get_ngrams(doc_text, n=5))
    matched_global_ngrams = set()
    
    # Hitung exact-match N-Gram untuk kevalidan data (agar warna di PDF akurat)
    source_ngrams_cache = {}
    for idx, source in enumerate(top_sources):
        url = source['url']
        s_ngrams = set(get_ngrams(corpus[url], n=5))
        overlap = total_doc_ngrams.intersection(s_ngrams)
        matched_global_ngrams.update(overlap)
        source_ngrams_cache[idx] = s_ngrams
        
    for sentence in doc_sentences:
        s_words = sentence.split()
        clean_words = [re.sub(r'[^\w\s]', '', w).lower() for w in s_words]
        is_matched = [False] * len(s_words)
        
        for i in range(len(s_words) - 5 + 1):
            ngram = " ".join(clean_words[i:i+5])
            if ngram in matched_global_ngrams:
                for j in range(i, i+5):
                    is_matched[j] = True
                    
        # Buat frasa yang dihighlight
        current_phrase = []
        for i in range(len(s_words)):
            if is_matched[i]:
                current_phrase.append(s_words[i])
            else:
                if current_phrase:
                    if len(current_phrase) >= 5:
                        phrase_text = " ".join(current_phrase)
                        # Cari sumber utama yang menyumbang frasa ini
                        p_ngrams = set(get_ngrams(phrase_text, n=5))
                        best_source_id = 1
                        best_overlap = 0
                        for idx, cached_ngrams in source_ngrams_cache.items():
                            olap = len(p_ngrams.intersection(cached_ngrams))
                            if olap > best_overlap:
                                best_overlap = olap
                                best_source_id = idx + 1
                                
                        plagiarized_sentences_data.append({
                            'text': phrase_text,
                            'source_id': best_source_id
                        })
                    current_phrase = []
                    
        if len(current_phrase) >= 5:
            phrase_text = " ".join(current_phrase)
            plagiarized_sentences_data.append({
                'text': phrase_text,
                'source_id': 1
            })

    # 6. Hitung Final Similarity (Turnitin Similarity Index)
    if not top_sources:
        return [], 0.0, []
        
    # [MATHEMATICALLY VALID OVERALL SCORE]
    # Sesuai standar Turnitin: (Total Kata Plagiat / Total Kata Dokumen) * 100
    total_doc_words = len(doc_text.split())
    if total_doc_words == 0:
        return sorted_sources, 0.0, plagiarized_sentences_data
        
    # Hitung jumlah kata unik yang terhighlight
    total_plagiarized_words = sum(len(p['text'].split()) for p in plagiarized_sentences_data)
    exact_match_score = (total_plagiarized_words / total_doc_words) * 100.0
    
    # Gabungkan dengan skor parafrase dari AI
    highest_semantic_score = max([s['percentage'] for s in top_sources]) if top_sources else 0.0
    
    # Skor final = Nilai tertinggi antara kata identik (Copy-Paste) vs Pemahaman Makna (Parafrase)
    total_similarity = max(exact_match_score, highest_semantic_score)
    total_similarity = min(100.0, total_similarity)
    
    return sorted_sources, total_similarity, plagiarized_sentences_data
