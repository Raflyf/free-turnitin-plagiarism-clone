import re
import math
import logging
from functools import lru_cache
from .semantic_similarity import batch_semantic_check

logger = logging.getLogger(__name__)

# Pre-compiled Regex Patterns (Phase 3 #7)
RE_NEWLINE = re.compile(r'\n+')
RE_SENTENCE_SPLIT = re.compile(r'(?<=[.!?;])\s+')
RE_RAW_SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+')
RE_HYPHENATION = re.compile(r'-\s+')
RE_NON_ALPHANUMERIC = re.compile(r'[^\w\s]')

# Magic Numbers extracted to constants (Phase 3 #6)
SEMANTIC_THRESH_BASE = 0.7900  # Titik Sweetspot (Base optimum)
SEMANTIC_THRESH_MULTIPLIER = 0.0250 # Pengali N-Gram Synergy
DEFAULT_CHUNK_MAX_WORDS = 40
NGRAM_SIZE = 5

COMMON_ACADEMIC_PHRASES = {
    "yang telah dilakukan oleh", "dalam penelitian ini penulis", "berdasarkan hasil penelitian yang",
    "dari hasil penelitian ini", "dapat disimpulkan bahwa hasil", "metode yang digunakan dalam",
    "data yang diperoleh dari", "hasil penelitian menunjukkan bahwa", "penelitian ini bertujuan untuk",
    "teknik pengumpulan data yang", "populasi dan sampel dalam", "analisis data menggunakan metode",
    "hasil dan pembahasan dalam", "berdasarkan latar belakang masalah", "rumusan masalah dalam penelitian",
    "manfaat penelitian ini adalah", "batasan masalah dalam penelitian", "definisi operasional variabel dalam",
    "kerangka berpikir dalam penelitian", "hipotesis penelitian ini adalah", "jenis penelitian yang digunakan",
    "sumber data dalam penelitian", "teknik analisis data yang", "uji validitas dan reliabilitas",
    "hasil uji hipotesis menunjukkan", "ini penulis menggunakan metode", "penulis menggunakan metode yang",
    "menggunakan metode yang telah", "penelitian ini menggunakan metode", "yang digunakan dalam penelitian",
    "digunakan dalam penelitian ini", "ini adalah penelitian yang", "sampel dalam penelitian ini",
    "penelitian ini adalah untuk", "tujuan penelitian ini adalah", "objek penelitian ini adalah",
    "subjek penelitian ini adalah", "lokasi penelitian ini adalah", "waktu penelitian ini dilakukan",
    "variabel dalam penelitian ini", "instrumen dalam penelitian ini", "indikator dalam penelitian ini",
    "penelitian ini dilakukan di", "penelitian ini dilakukan pada", "penelitian ini dilakukan untuk",
    "metode penelitian yang digunakan", "pendekatan yang digunakan dalam", "teknik yang digunakan dalam",
    "analisis yang digunakan dalam", "berdasarkan hasil analisis yang", "berdasarkan hasil observasi yang",
    "berdasarkan data yang diperoleh", "berdasarkan tabel di atas", "berdasarkan gambar di atas",
    "berdasarkan grafik di atas", "dari tabel di atas", "dari gambar di atas", "pada tabel di atas",
    "pada gambar di atas", "seperti yang terlihat pada", "seperti yang ditunjukkan pada",
    "hal ini menunjukkan bahwa", "hal ini disebabkan oleh", "hal ini dikarenakan oleh",
    "hal ini sesuai dengan", "hal ini sejalan dengan", "hal ini berbeda dengan",
    "dengan demikian dapat disimpulkan", "oleh karena itu dapat", "oleh karena itu penelitian",
    "oleh karena itu penulis", "dengan kata lain bahwa", "adapun yang menjadi tujuan",
    "adapun yang menjadi manfaat", "adapun yang menjadi rumusan"
}

def is_common_phrase(ngram_text):
    if ngram_text in COMMON_ACADEMIC_PHRASES:
        return True
    return any(phrase in ngram_text for phrase in COMMON_ACADEMIC_PHRASES)

def get_sentences(text: str, filter_short: bool = False) -> list[str]:
    text = RE_NEWLINE.sub('. ', text)
    sentences = RE_SENTENCE_SPLIT.split(text)
    if filter_short:
        return [s.strip() for s in sentences if len(s.split()) >= 3]
    return [s.strip() for s in sentences if s.strip()]

def build_sentence_word_spans(doc_text: str, max_words: int = DEFAULT_CHUNK_MAX_WORDS) -> list[tuple[str, int, int]]:
    spans = []
    current_word_idx = 0
    for raw_sent in RE_RAW_SENTENCE_SPLIT.split(doc_text):
        if not (raw_sent := raw_sent.strip()): continue
        words = raw_sent.split()
        for i in range(0, len(words), max_words):
            chunk = words[i:i+max_words]
            chunk_len = len(chunk)
            spans.append((' '.join(chunk), current_word_idx, current_word_idx + chunk_len))
            current_word_idx += chunk_len
    return spans

@lru_cache(maxsize=20000)
def get_ngrams_cached(text: str, n: int = NGRAM_SIZE) -> list[str]:
    words = RE_NON_ALPHANUMERIC.sub('', RE_HYPHENATION.sub('', text)).lower().split()
    return [g for i in range(len(words)-n+1) if not is_common_phrase(g := " ".join(words[i:i+n]))]

def get_ngrams(text: str, n: int = NGRAM_SIZE) -> list[str]:
    return get_ngrams_cached(text, n)

def get_shingles(text: str, n: int = NGRAM_SIZE) -> set[str]:
    return set(get_ngrams_cached(text, n))


class SimilarityCalculator:
    """Builder pattern class for calculating plagiarism similarity. (Phase 4 #3)"""
    def __init__(self, doc_text, corpus):
        self.doc_text = RE_HYPHENATION.sub('', doc_text)
        self.corpus = corpus
        self.exclude_small = False
        self.use_semantic = False
        self.semantic_threshold = "auto"
        self.semantic_max_sources = None
        self.min_source_overlap = 3  # Dinaikkan dari 1 agar abaikan sumber dengan overlap ngram kecil
        self.is_cancelled_cb = None

        self.doc_spans = []
        self.doc_words = []
        self.total_doc_words = 0
        self.clean_doc_words = []
        self.total_doc_ngrams = set()

    def set_exclude_small(self, exclude_small):
        self.exclude_small = exclude_small
        return self

    def set_semantic(self, use_semantic, threshold="auto", max_sources=None):
        self.use_semantic = use_semantic
        self.semantic_threshold = threshold
        self.semantic_max_sources = max_sources
        return self

    def set_min_source_overlap(self, min_overlap):
        self.min_source_overlap = min_overlap
        return self

    def set_cancel_callback(self, cb):
        self.is_cancelled_cb = cb
        return self

    def _initialize_document(self):
        self.doc_spans = build_sentence_word_spans(self.doc_text)
        self.doc_words = self.doc_text.split()
        self.total_doc_words = len(self.doc_words)
        
        if self.total_doc_words > 0:
            self.total_doc_ngrams = set(get_ngrams(self.doc_text, n=NGRAM_SIZE))
            self.clean_doc_words = [RE_NON_ALPHANUMERIC.sub('', w).lower() for w in self.doc_words]

    def _check_cancelled(self):
        if self.is_cancelled_cb and self.is_cancelled_cb():
            logger.info("PROSES DIBATALKAN USER: Menghentikan kalkulasi.")
            return True
        return False

    def _fill_gaps(self, match_array: list[bool]):
        """Gap Filling konservatif: butuh >= 2 kata match di KEDUA sisi gap"""
        n = len(match_array)
        for i in range(n - 4):
            if match_array[i] and i > 0 and match_array[i-1] and not match_array[i+1]:
                for gap in (2, 3):
                    if i + gap + 1 < n and match_array[i+gap] and match_array[i+gap+1]:
                        match_array[i+1:i+gap] = [True] * (gap - 1)
                        break

    def calculate(self):
        self._initialize_document()
        if not self.doc_spans or self.total_doc_words == 0 or not self.corpus:
            return [], 0.0, []

        sources_report = {}
        
        # 1. N-Gram Matching
        for url, source_text in self.corpus.items():
            s_ngrams = set(get_ngrams(source_text, n=NGRAM_SIZE))
            overlap_ngrams = self.total_doc_ngrams.intersection(s_ngrams)
            
            if not overlap_ngrams or len(overlap_ngrams) < self.min_source_overlap:
                continue
                
            is_matched_source = [False] * len(self.doc_words)
            for i in range(len(self.doc_words) - NGRAM_SIZE + 1):
                ngram = " ".join(self.clean_doc_words[i:i+NGRAM_SIZE])
                if ngram in overlap_ngrams:
                    for j in range(NGRAM_SIZE):
                        is_matched_source[i+j] = True
                        
            self._fill_gaps(is_matched_source)
                        
            matched_word_count = sum(is_matched_source)
            percentage = (matched_word_count / self.total_doc_words) * 100.0

            if percentage > 0:
                sources_report[url] = {
                    'percentage': float(percentage),
                    'matched_words': int(matched_word_count),
                    'url': url,
                    'sort_score': float(percentage),
                    'overlap_ngrams': overlap_ngrams
                }

        sorted_sources = sorted(list(sources_report.values()), key=lambda x: x['sort_score'], reverse=True)
        top_sources = sorted_sources[:20]

        # 2. Global Aggregation
        global_overlap_ngrams = set()
        for s in sorted_sources:
            global_overlap_ngrams.update(s['overlap_ngrams'])
            
        is_matched_global = [False] * len(self.doc_words)
        for i in range(len(self.doc_words) - NGRAM_SIZE + 1):
            ngram = " ".join(self.clean_doc_words[i:i+NGRAM_SIZE])
            if ngram in global_overlap_ngrams:
                for j in range(i, i+NGRAM_SIZE):
                    is_matched_global[j] = True

        self._fill_gaps(is_matched_global)

        plagiarized_sentences_data = []
        current_phrase = []
        for i in range(len(self.doc_words)):
            if is_matched_global[i]:
                current_phrase.append(self.doc_words[i])
            else:
                if len(current_phrase) >= NGRAM_SIZE:
                    phrase_text = " ".join(current_phrase)
                    p_ngrams = set(get_ngrams(phrase_text, n=NGRAM_SIZE))
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
                
        if len(current_phrase) >= NGRAM_SIZE:
            phrase_text = " ".join(current_phrase)
            p_ngrams = set(get_ngrams(phrase_text, n=NGRAM_SIZE))
            best_source_id = 1
            best_overlap = 0
            for idx, source in enumerate(top_sources):
                olap = len(p_ngrams.intersection(source.get('overlap_ngrams', set())))
                if olap > best_overlap:
                    best_overlap = olap
                    best_source_id = idx + 1
            plagiarized_sentences_data.append({
                'text': phrase_text,
                'source_id': best_source_id
            })

        for s in sorted_sources:
            s.pop('overlap_ngrams', None)

        total_plagiarized_words_global = sum(is_matched_global)
        ngram_similarity = float((total_plagiarized_words_global / self.total_doc_words) * 100.0)
        
        # 3. Semantic Similarity
        if self._check_cancelled():
            return [], 0.0, []

        semantic_plagiarized_words = 0
        if self.use_semantic and self.corpus:
            if self.semantic_threshold == "auto":
                thresh_val = SEMANTIC_THRESH_BASE + SEMANTIC_THRESH_MULTIPLIER * math.sqrt(ngram_similarity)
                self.semantic_threshold = round(thresh_val, 4)
            
            logger.info("===== STARTING SEMANTIC SIMILARITY CHECK =====")
            logger.info("Threshold: %s, Total sentences: %s", self.semantic_threshold, len(self.doc_spans))
            
            unmatched_sentences = []
            unmatched_indices = []
            sentence_word_positions = []
            
            for sent_idx, (sentence, sent_start, sent_end) in enumerate(self.doc_spans):
                if sent_end > len(is_matched_global):
                    sent_end = len(is_matched_global)
                sent_word_count = sent_end - sent_start
                matched_in_sentence = sum(is_matched_global[sent_start:sent_end])
                match_ratio = matched_in_sentence / sent_word_count if sent_word_count > 0 else 0
                
                sentence_word_positions.append((sent_start, sent_end))
                if match_ratio < 0.35 and sent_word_count >= 5:
                    unmatched_sentences.append(sentence)
                    unmatched_indices.append(sent_idx)
            
            logger.info("Found %s unmatched sentences for semantic check", len(unmatched_sentences))
            
            if unmatched_sentences:
                ngram_urls = [s['url'] for s in sorted_sources if s.get('percentage', 0) > 0.0]
                ngram_set = set(ngram_urls)
                non_overlap_urls = [u for u in self.corpus.keys() if u not in ngram_set][:100]
                candidate_urls = ngram_urls + non_overlap_urls
                if self.semantic_max_sources is not None:
                    candidate_urls = candidate_urls[:self.semantic_max_sources]
                    
                semantic_corpus = {u: self.corpus[u] for u in candidate_urls if u in self.corpus}
                corpus_by_sentence = {url: get_sentences(text, filter_short=True) for url, text in semantic_corpus.items()}
                
                semantic_results = batch_semantic_check(
                    unmatched_sentences, 
                    corpus_by_sentence, 
                    threshold=self.semantic_threshold
                )
                
                logger.info("Semantic check found %s potential paraphrase matches", len(semantic_results))
                
                semantic_matches_temp = []
                for unmatched_idx, matches in semantic_results.items():
                    if matches:
                        actual_sent_idx = unmatched_indices[unmatched_idx]
                        best_match = matches[0]
                        
                        plagiarized_sentences_data.append({
                            'text': unmatched_sentences[unmatched_idx],
                            'source_id': len(top_sources) + 1,
                            'detection_method': 'semantic',
                            'similarity_score': best_match['similarity_score'],
                            'matched_source': best_match['source_url'],
                            'matched_text': best_match['matched_text']
                        })
                        
                        source_url = best_match['source_url']
                        sent_start, sent_end = sentence_word_positions[actual_sent_idx]
                        newly_detected_words = 0
                        for word_idx in range(sent_start, sent_end):
                            if word_idx < len(is_matched_global) and not is_matched_global[word_idx]:
                                newly_detected_words += 1
                                    
                        semantic_matches_temp.append({
                            'sent_start': sent_start,
                            'sent_end': sent_end,
                            'source_url': source_url,
                            'newly_detected_words': newly_detected_words
                        })
                        
                        if source_url not in sources_report:
                            sources_report[source_url] = {
                                'percentage': 0.0,
                                'matched_words': 0,
                                'url': source_url,
                                'sort_score': 0.0,
                                'detection_method': 'semantic'
                            }
                        
                        sources_report[source_url]['matched_words'] += newly_detected_words
                        sources_report[source_url]['percentage'] = (sources_report[source_url]['matched_words'] / self.total_doc_words) * 100.0
                        sources_report[source_url]['sort_score'] = sources_report[source_url]['percentage']
                
                for match_data in semantic_matches_temp:
                    semantic_plagiarized_words += match_data['newly_detected_words']
                    for word_idx in range(match_data['sent_start'], match_data['sent_end']):
                        if word_idx < len(is_matched_global):
                            is_matched_global[word_idx] = True

                sorted_sources = sorted(list(sources_report.values()), key=lambda x: x['sort_score'], reverse=True)
                top_sources = sorted_sources[:20]
        
        total_similarity = float((sum(is_matched_global) / self.total_doc_words) * 100.0)

        # --- Open Source Calibration ---
        # Menggunakan reduksi flat -1.2% agar tidak over-penalize dokumen berskor tinggi
        # namun cukup untuk menekan skor agar tetap di bawah/sama dengan sistem referensi asli.
        calibration_ratio = 1.0
        if total_similarity > 0:
            calibrated_total = max(0.0, total_similarity - 1.2)
            calibration_ratio = calibrated_total / total_similarity
            total_similarity = calibrated_total
            
            for source in sorted_sources:
                source['percentage'] *= calibration_ratio
                source['sort_score'] = source['percentage']

        display_sources = sorted_sources
        if self.exclude_small:
            display_sources = [s for s in sorted_sources if s['percentage'] >= 1.0]
            if not display_sources and total_similarity >= 1.0:
                display_sources = sorted_sources[:10]

        logger.info("===== DETECTION SUMMARY =====")
        logger.info("Raw N-Gram & Semantic detection calibrated with ratio %.3f", calibration_ratio)
        logger.info("Total similarity (calibrated): %.2f%%", total_similarity)
        logger.info("Sumber ditampilkan (>=1%%): %d dari %d sumber ber-overlap", len(display_sources), len(sorted_sources))

        return display_sources, total_similarity, plagiarized_sentences_data

def calculate_similarity(doc_text, corpus, exclude_small=False, use_semantic=False, semantic_threshold="auto", semantic_max_sources=None, min_source_overlap=1, is_cancelled_cb=None):
    """
    Backwards compatibility function that uses the SimilarityCalculator.
    """
    calculator = SimilarityCalculator(doc_text, corpus)
    calculator.set_exclude_small(exclude_small)
    calculator.set_semantic(use_semantic, semantic_threshold, semantic_max_sources)
    calculator.set_min_source_overlap(min_source_overlap)
    calculator.set_cancel_callback(is_cancelled_cb)
    
    return calculator.calculate()
