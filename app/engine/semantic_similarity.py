"""
Semantic Similarity Module for Paraphrase Detection
Uses sentence-transformers to detect paraphrased content that N-Gram might miss
"""

from sentence_transformers import SentenceTransformer, util
import torch
import numpy as np

# Global model instance (loaded once for efficiency)
_model = None

def get_model():
    """
    Load and cache the sentence-transformers model.
    Using 'paraphrase-multilingual-MiniLM-L12-v2' - a lightweight but effective model for semantic similarity in Indonesian.
    """
    global _model
    if _model is None:
        print("[!] Loading Sentence-Transformer model for semantic similarity...")
        # LOG-05: Menggunakan model multilingual yang akurat untuk Bahasa Indonesia
        _model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
        print("[!] Model loaded successfully.")
    return _model

def calculate_semantic_similarity(sentence1, sentence2):
    """
    Calculate semantic similarity between two sentences.
    
    Args:
        sentence1 (str): First sentence
        sentence2 (str): Second sentence
    
    Returns:
        float: Similarity score between 0 and 1
    """
    model = get_model()
    
    # Generate embeddings
    embedding1 = model.encode(sentence1, convert_to_tensor=True)
    embedding2 = model.encode(sentence2, convert_to_tensor=True)
    
    # Calculate cosine similarity
    similarity = util.pytorch_cos_sim(embedding1, embedding2).item()
    
    return similarity

def find_semantic_matches(query_sentences, corpus_sentences, threshold=0.88):
    """
    Find semantically similar sentences from corpus that match query sentences.
    This is used as a second layer after N-Gram matching.
    
    Args:
        query_sentences (list): List of sentences from the document being checked
        corpus_sentences (dict): Dictionary mapping source URLs to their sentence lists
        threshold (float): Minimum similarity score to consider a match (0-1)
    
    Returns:
        dict: Dictionary mapping query sentence indices to matching corpus sentences
              Format: {query_idx: [(source_url, corpus_sent, similarity_score), ...]}
    """
    model = get_model()
    
    # Generate embeddings for query sentences
    print(f"[!] Generating embeddings for {len(query_sentences)} query sentences...")
    query_embeddings = model.encode(query_sentences, convert_to_tensor=True, show_progress_bar=True)
    
    semantic_matches = {}
    
    # Process each source separately
    for source_url, source_sentences in corpus_sentences.items():
        if not source_sentences:
            continue
            
        print(f"[!] Checking semantic similarity with {source_url}...")
        
        # Generate embeddings for this source's sentences
        source_embeddings = model.encode(source_sentences, convert_to_tensor=True, show_progress_bar=False)
        
        # Calculate similarity matrix
        similarity_matrix = util.pytorch_cos_sim(query_embeddings, source_embeddings)
        
        # Find matches above threshold
        for query_idx in range(len(query_sentences)):
            for source_idx in range(len(source_sentences)):
                similarity_score = similarity_matrix[query_idx][source_idx].item()
                
                if similarity_score >= threshold:
                    if query_idx not in semantic_matches:
                        semantic_matches[query_idx] = []
                    
                    semantic_matches[query_idx].append({
                        'source_url': source_url,
                        'matched_text': source_sentences[source_idx],
                        'similarity_score': similarity_score,
                        'detection_method': 'semantic'
                    })
    
    # Sort matches by similarity score (highest first)
    for query_idx in semantic_matches:
        semantic_matches[query_idx].sort(key=lambda x: x['similarity_score'], reverse=True)
    
    return semantic_matches

def batch_semantic_check(unmatched_sentences, corpus_sentences, threshold=0.88, batch_size=32):
    """
    Efficiently check semantic similarity for sentences that weren't matched by N-Gram.
    Uses batch processing for better performance.
    
    Args:
        unmatched_sentences (list): Sentences that N-Gram didn't find matches for
        corpus_sentences (dict): Dictionary mapping source URLs to their sentence lists
        threshold (float): Minimum similarity score to consider a match
        batch_size (int): Number of sentences to process at once
    
    Returns:
        dict: Semantic matches with structure similar to find_semantic_matches
    """
    if not unmatched_sentences:
        return {}
    
    model = get_model()
    
    print(f"[!] Performing semantic similarity check on {len(unmatched_sentences)} unmatched sentences...")
    
    # Generate embeddings for unmatched sentences
    query_embeddings = model.encode(unmatched_sentences, convert_to_tensor=True, 
                                   batch_size=batch_size, show_progress_bar=True)
    
    semantic_matches = {}
    
    # Process each source
    for source_url, source_sentences in corpus_sentences.items():
        if not source_sentences:
            continue
        
        # Generate embeddings for source sentences
        source_embeddings = model.encode(source_sentences, convert_to_tensor=True, 
                                        batch_size=batch_size, show_progress_bar=False)
        
        # Calculate similarity
        similarity_matrix = util.pytorch_cos_sim(query_embeddings, source_embeddings)
        
        # Find matches
        for query_idx, query_sent in enumerate(unmatched_sentences):
            max_similarity = torch.max(similarity_matrix[query_idx]).item()
            
            if max_similarity >= threshold:
                best_match_idx = torch.argmax(similarity_matrix[query_idx]).item()
                
                if query_idx not in semantic_matches:
                    semantic_matches[query_idx] = []
                
                semantic_matches[query_idx].append({
                    'source_url': source_url,
                    'matched_text': source_sentences[best_match_idx],
                    'similarity_score': max_similarity,
                    'detection_method': 'semantic',
                    'original_sentence': query_sent
                })
    
    return semantic_matches