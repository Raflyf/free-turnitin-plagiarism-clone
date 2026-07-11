import fitz
import re

def extract_text_from_pdf(filepath, exclude_quotes=True, exclude_biblio=True):
    text = ""
    try:
        doc = fitz.open(filepath)
        for page in doc:
            text += page.get_text() + " "
        doc.close()
    except Exception as e:
        print(f"Error reading PDF: {e}")
    return clean_text(text, exclude_quotes, exclude_biblio)

def clean_text(text, exclude_quotes=True, exclude_biblio=True):
    # Bersihkan spasi dan enter (newline) DULU!
    # PyMuPDF sering membaca teks sebagai "DAFTAR\nPUSTAKA" atau "DAFTAR  PUSTAKA"
    text = re.sub(r'\s+', ' ', text).strip()
    
    if exclude_biblio:
        # Gunakan pencarian dari belakang (rfind) untuk mencari bab Daftar Pustaka sebenarnya
        last_idx = max(text.upper().rfind('DAFTAR PUSTAKA'), text.upper().rfind('REFERENCES'))
        
        # Pastikan ia berada di paruh akhir dokumen untuk menghindari false positive di Daftar Isi
        if last_idx > len(text) * 0.5:
            text = text[:last_idx]
    
    if exclude_quotes:
        # Hilangkan kutipan langsung ("...")
        text = re.sub(r'".*?"', '', text)
    
    return text

def get_sentences(text):
    sentences = re.split(r'(?<=[.!?]) +', text)
    return [s.strip() for s in sentences if len(s.split()) >= 5]
