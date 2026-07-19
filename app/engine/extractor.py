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
    """Extract text from PDF with robust error handling"""
    text = ""
    try:
        doc = fitz.open(filepath)
        for page in doc:
            text += page.get_text() + " "
        doc.close()
        
        if not text.strip():
            raise Exception("PDF appears to be empty or contains only images")
            
    except Exception as e:
        raise Exception(f"Failed to extract PDF: {str(e)}")
        
    manipulation_warnings = detect_manipulation(text)
    
    cleaned_text = clean_text(text, exclude_quotes, exclude_biblio)
    
    # Bersihkan Zero-width chars dari teks agar tetap bisa di-cek similarity-nya
    cleaned_text = re.sub(r'[\u200B-\u200D\uFEFF]', '', cleaned_text)
    # Normalkan huruf Cyrillic kembali ke Latin agar usahanya sia-sia
    cyrillic_to_latin = str.maketrans('асеорху', 'aceopxy')
    cleaned_text = cleaned_text.translate(cyrillic_to_latin)
    
    return cleaned_text, manipulation_warnings

def extract_text_from_docx(docx_path, exclude_quotes=True, exclude_biblio=True):
    """Extract text from .docx (Word). Dipakai untuk dokumen sumber asli (bukan PDF hasil Turnitin)."""
    from docx import Document
    doc = Document(docx_path)
    text = " ".join(p.text for p in doc.paragraphs if p.text)
    # Sertakan teks dari tabel (banyak skripsi menaruh konten di tabel)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text:
                    text += " " + cell.text
    if not text.strip():
        raise Exception("DOCX appears to be empty")

    manipulation_warnings = detect_manipulation(text)
    cleaned_text = clean_text(text, exclude_quotes, exclude_biblio)
    cleaned_text = re.sub(r'[​-‍﻿]', '', cleaned_text)
    cyrillic_to_latin = str.maketrans('асеорху', 'aceopxy')
    cleaned_text = cleaned_text.translate(cyrillic_to_latin)
    return cleaned_text, manipulation_warnings


def extract_text_auto(filepath, exclude_quotes=True, exclude_biblio=True):
    """Deteksi ekstensi lalu ekstrak (.pdf/.docx/.txt). Satu pintu untuk semua format."""
    low = filepath.lower()
    if low.endswith(".docx"):
        return extract_text_from_docx(filepath, exclude_quotes, exclude_biblio)
    if low.endswith(".txt"):
        return extract_text_from_txt(filepath), []
    return extract_text_from_pdf(filepath, exclude_quotes, exclude_biblio)


def extract_text_from_txt(txt_path):
    """Extract text from TXT with automatic encoding detection"""
    try:
        import chardet
        
        # Detect encoding
        with open(txt_path, 'rb') as f:
            raw_data = f.read()
        
        if not raw_data:
            raise Exception("File is empty")
        
        detected = chardet.detect(raw_data)
        encoding = detected['encoding'] or 'utf-8'
        
        # Try detected encoding with fallbacks
        encodings_to_try = [encoding, 'utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
        
        for enc in encodings_to_try:
            try:
                return raw_data.decode(enc)
            except (UnicodeDecodeError, AttributeError):
                continue
        
        # Last resort: decode with errors='replace'
        return raw_data.decode('utf-8', errors='replace')
        
    except Exception as e:
        raise Exception(f"Failed to extract TXT: {str(e)}")

def clean_text(text, exclude_quotes=True, exclude_biblio=True):
    text = re.sub(r'\s+', ' ', text).strip()

    # [1] Exclude Front Matter (Cover, Pengesahan, Daftar Isi) - Turnitin Behavior
    # PENTING: "BAB I" pertama biasanya muncul di DAFTAR ISI (diikuti dot-leader "....." dan
    # nomor halaman), BUKAN heading bab asli. Kita cari kemunculan yang diikuti KONTEN nyata,
    # bukan titik-titik daftar isi.
    upper_text = text.upper()

    # Pola heading bab asli: "BAB I" / "BAB 1" diikuti KONTEN nyata, bukan dot-leader
    # daftar isi. Cari SEMUA kemunculan lalu ambil yang bukan bagian daftar isi.
    chosen_idx = -1
    for m in re.finditer(r'BAB\s+(?:I|1)\b', upper_text):
        idx = m.start()
        # Ambil 40 karakter setelah match untuk cek apakah ini entri daftar isi
        tail = text[m.end():m.end() + 40]
        # Entri daftar isi: didominasi titik-titik atau langsung angka halaman
        dot_ratio = tail.count('.') / max(len(tail), 1)
        is_toc_entry = dot_ratio > 0.3 or bool(re.match(r'[\s\.]*\d{1,3}\s*$', tail[:15]))
        if not is_toc_entry:
            chosen_idx = idx
            break

    # Fallback: jika semua kemunculan tampak seperti TOC, pakai kemunculan terakhir di 40%
    # awal dokumen (heading asli selalu setelah daftar isi).
    if chosen_idx == -1:
        candidates = [m.start() for m in re.finditer(r'BAB\s+(?:I|1)\b', upper_text)
                      if m.start() < len(text) * 0.4]
        if candidates:
            chosen_idx = candidates[-1]

    if chosen_idx != -1 and chosen_idx < len(text) * 0.4:
        text = text[chosen_idx:]

    # [2] Exclude Bibliography
    if exclude_biblio:
        last_idx = max(text.upper().rfind('DAFTAR PUSTAKA'), text.upper().rfind('REFERENCES'))
        if last_idx > len(text) * 0.5:
            text = text[:last_idx]

    # [3] Exclude Quotes
    if exclude_quotes:
        text = re.sub(r'["""].*?["""]', '', text)

    return text

def get_sentences(text):
    text = re.sub(r'\n+', '. ', text)
    sentences = re.split(r'(?<=[.!?;])\s+', text)
    return [s.strip() for s in sentences if len(s.split()) >= 5]