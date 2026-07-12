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
    
    if exclude_biblio:
        last_idx = max(text.upper().rfind('DAFTAR PUSTAKA'), text.upper().rfind('REFERENCES'))
        if last_idx > len(text) * 0.5:
            text = text[:last_idx]
    
    if exclude_quotes:
        text = re.sub(r'["“”].*?["“”]', '', text)
    
    return text

def get_sentences(text):
    sentences = re.split(r'(?<=[.!?]) +', text)
    return [s.strip() for s in sentences if len(s.split()) >= 5]
