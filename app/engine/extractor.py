import fitz
import re

def detect_manipulation(text):
    """Mendeteksi trik mahasiswa untuk mencurangi Turnitin"""
    warnings = []
    # 1. Deteksi Zero-Width Characters (diselipkan antar huruf agar kata tidak terbaca)
    zero_width_chars = re.findall(r'[\u200B-\u200D\uFEFF]', text)
    if len(zero_width_chars) > 20:
        warnings.append("⚠️ MANIPULASI TERDETEKSI: Ditemukan karakter tak terlihat (Zero-Width Space) yang digunakan untuk mengelabui sistem.")
    
    # 2. Deteksi huruf Cyrillic Homoglyphs (Huruf Rusia yang terlihat seperti huruf A, E, O latin)
    # Ini sangat umum digunakan untuk memutus N-Gram
    cyrillic_chars = re.findall(r'[асеорху]', text.lower())
    if len(cyrillic_chars) > 30:
        warnings.append("⚠️ MANIPULASI TERDETEKSI: Ditemukan penggunaan huruf Cyrillic (Rusia) ilegal yang menyamar sebagai abjad Latin.")
        
    return warnings

def extract_text_from_pdf(filepath, exclude_quotes=True, exclude_biblio=True):
    text = ""
    try:
        doc = fitz.open(filepath)
        for page in doc:
            text += page.get_text() + " "
        doc.close()
    except Exception as e:
        print(f"Error reading PDF: {e}")
        
    manipulation_warnings = detect_manipulation(text)
    
    cleaned_text = clean_text(text, exclude_quotes, exclude_biblio)
    
    # Bersihkan Zero-width chars dari teks agar tetap bisa di-cek similarity-nya
    cleaned_text = re.sub(r'[\u200B-\u200D\uFEFF]', '', cleaned_text)
    # Normalkan huruf Cyrillic kembali ke Latin agar usahanya sia-sia
    cyrillic_to_latin = str.maketrans('асеорху', 'aceopxy')
    cleaned_text = cleaned_text.translate(cyrillic_to_latin)
    
    return cleaned_text, manipulation_warnings

def clean_text(text, exclude_quotes=True, exclude_biblio=True):
    text = re.sub(r'\s+', ' ', text).strip()
    
    # [1] Exclude Front Matter (Cover, Pengesahan, Daftar Isi) - Turnitin Behavior
    # Mencari kemunculan pertama BAB I, BAB 1, atau PENDAHULUAN (dengan batas wajar di awal)
    first_bab_idx = -1
    upper_text = text.upper()
    
    # Cari indeks terkecil dari BAB 1, BAB I, atau PENDAHULUAN
    idx_1 = upper_text.find('BAB I ')
    idx_2 = upper_text.find('BAB 1 ')
    idx_3 = upper_text.find('PENDAHULUAN')
    
    valid_indices = [idx for idx in [idx_1, idx_2, idx_3] if idx != -1 and idx < len(text) * 0.3]
    if valid_indices:
        first_bab_idx = min(valid_indices)
        text = text[first_bab_idx:]
    
    # [2] Exclude Bibliography
    if exclude_biblio:
        last_idx = max(text.upper().rfind('DAFTAR PUSTAKA'), text.upper().rfind('REFERENCES'))
        if last_idx > len(text) * 0.5:
            text = text[:last_idx]
    
    # [3] Exclude Quotes
    if exclude_quotes:
        text = re.sub(r'["“”].*?["“”]', '', text)
    
    return text

def get_sentences(text):
    sentences = re.split(r'(?<=[.!?]) +', text)
    return [s.strip() for s in sentences if len(s.split()) >= 5]
