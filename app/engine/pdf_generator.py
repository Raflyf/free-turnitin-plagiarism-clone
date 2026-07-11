import fitz
import os
import time

def get_color_for_source(source_id):
    """
    Mengembalikan warna RGB (0-1 float) berdasarkan ID sumber.
    Format Turnitin:
    1: Merah (1.0, 0.0, 0.0)
    2: Magenta (1.0, 0.0, 1.0)
    3: Ungu Tua (0.5, 0.0, 0.5)
    4: Hijau Tosca (0.0, 0.5, 0.5)
    5: Hijau (0.0, 0.8, 0.0)
    6: Oranye (1.0, 0.5, 0.0)
    7: Cokelat (0.6, 0.3, 0.0)
    8: Biru Tua (0.0, 0.0, 0.8)
    9: Ungu Muda (0.6, 0.4, 0.8)
    10: Indigo (0.3, 0.0, 0.5)
    """
    colors = [
        (1.0, 0.0, 0.0),       # 1: Merah
        (1.0, 0.0, 1.0),       # 2: Magenta
        (0.5, 0.0, 0.5),       # 3: Ungu Tua
        (0.0, 0.5, 0.5),       # 4: Hijau Tosca
        (0.0, 0.8, 0.0),       # 5: Hijau
        (1.0, 0.5, 0.0),       # 6: Oranye
        (0.6, 0.3, 0.0),       # 7: Cokelat
        (0.0, 0.0, 0.8),       # 8: Biru Tua
        (0.6, 0.4, 0.8),       # 9: Ungu Muda
        (0.3, 0.0, 0.5)        # 10: Indigo
    ]
    # Ulangi warna jika sumber > 10
    idx = (source_id - 1) % 10
    return colors[idx]

def generate_report_pdf(original_pdf_path, output_pdf_path, data):
    """
    Membuat PDF akhir bergaya Turnitin dengan highlight kalimat
    dan halaman ORIGINALITY REPORT di bagian akhir.
    """
    doc = fitz.open(original_pdf_path)
    
    # --- DEDUPLIKASI FRASA SECARA GLOBAL ---
    # Hindari mewarnai frasa yang sama berkali-kali jika muncul di kalimat berbeda
    unique_phrases = {}
    for item in data['plagiarized_sentences']:
        txt = item['text']
        if txt not in unique_phrases:
            unique_phrases[txt] = item
            
    # --- STEP 1: Berikan Highlight pada teks di PDF asli ---
    for page in doc:
        page_text_clean = page.get_text().replace('\n', ' ').replace('\r', ' ').lower()
        
        # Simpan semua kotak warna di halaman ini untuk mencegah overlap
        highlighted_rects = []
        
        def is_overlapping(rect):
            for r in highlighted_rects:
                # Jika ada tumpang tindih sekecil 5% saja, blokir!
                if (rect & r).get_area() > 0.05 * rect.get_area():
                    return True
            return False
        
        for text, item in unique_phrases.items():
            source_id = item['source_id']
            color = get_color_for_source(source_id)
            words = text.split()
            
            if len(words) >= 3:
                chunk_first = " ".join(words[:3]).lower()
                chunk_mid = " ".join(words[len(words)//2 : len(words)//2+3]).lower()
                chunk_last = " ".join(words[-3:]).lower()
                
                if chunk_first not in page_text_clean and chunk_mid not in page_text_clean and chunk_last not in page_text_clean:
                    continue
            
            found_any = False
            first_rect = None
            
            # Coba cari seluruh kalimat dengan quads (dukung line-breaks)
            text_instances = page.search_for(text, quads=True)
            if text_instances:
                for inst in text_instances:
                    if is_overlapping(inst.rect):
                        print(f"[Anti-Overlap] Memblokir penumpukan warna pada frasa: {text[:30]}...")
                        continue
                    highlighted_rects.append(inst.rect)
                    
                    annot = page.add_highlight_annot(inst)
                    annot.set_colors(stroke=color)
                    annot.set_opacity(0.3)
                    annot.update()
                    if not first_rect:
                        first_rect = inst.rect
                if first_rect:
                    found_any = True
                
            # Jika terpotong parah antar-halaman, gunakan non-overlapping stepping window!
            if not found_any and len(words) >= 3:
                # Gunakan step=3 agar tidak ada kotak warna yang saling menindih
                for i in range(0, len(words), 3):
                    chunk = " ".join(words[i:i+3])
                    # Jika sisa < 3 kata, ambil 3 kata terakhir untuk memastikan konteks pencarian spesifik
                    if len(chunk.split()) < 3 and len(words) >= 3:
                        chunk = " ".join(words[-3:])
                        
                    insts = page.search_for(chunk, quads=True)
                    for inst in insts:
                        if is_overlapping(inst.rect):
                            print(f"[Anti-Overlap] Memblokir penumpukan warna pada potongan: {chunk[:30]}...")
                            continue
                        highlighted_rects.append(inst.rect)
                        
                        annot = page.add_highlight_annot(inst)
                        annot.set_colors(stroke=color)
                        annot.set_opacity(0.3)
                        annot.update()
                        if not first_rect:
                            first_rect = inst.rect
                            
            elif not found_any and len(words) == 2:
                chunk = " ".join(words)
                insts = page.search_for(chunk, quads=True)
                for inst in insts:
                    if is_overlapping(inst.rect):
                        print(f"[Anti-Overlap] Memblokir penumpukan warna pada 2-kata: {chunk[:30]}...")
                        continue
                    highlighted_rects.append(inst.rect)
                    
                    annot = page.add_highlight_annot(inst)
                    annot.set_colors(stroke=color)
                    annot.set_opacity(0.3)
                    annot.update()
                    if not first_rect:
                        first_rect = inst.rect
                        
            if first_rect:
                draw_badge(page, first_rect, source_id, color)

    # --- STEP 2: Buat Halaman "ORIGINALITY REPORT" di akhir ---
    report_page = doc.new_page(-1, width=595, height=842) # Ukuran A4 standar
    
    y_pos = 50
    margin_left = 50
    
    # Header: Nama File
    report_page.insert_text((margin_left, y_pos), f"{os.path.basename(original_pdf_path)}", fontsize=18, fontname="helv")
    y_pos += 30
    
    # Garis tebal
    report_page.draw_line(fitz.Point(margin_left, y_pos), fitz.Point(545, y_pos), color=(0,0,0), width=2)
    y_pos += 5
    report_page.draw_line(fitz.Point(margin_left, y_pos), fitz.Point(545, y_pos), color=(0,0,0), width=0.5)
    y_pos += 20
    
    # ORIGINALITY REPORT text
    report_page.insert_text((margin_left, y_pos), "ORIGINALITY REPORT", fontsize=12, fontname="helv")
    y_pos += 30
    
    # Garis tipis
    report_page.draw_line(fitz.Point(margin_left, y_pos), fitz.Point(545, y_pos), color=(0,0,0), width=0.5)
    y_pos += 40
    
    # Skor Kemiripan Besar
    score_text = f"{int(data['total_similarity'])}%"
    report_page.insert_text((margin_left, y_pos), score_text, fontsize=48, fontname="helv")
    y_pos += 20
    
    report_page.insert_text((margin_left, y_pos), "SIMILARITY INDEX", fontsize=10, fontname="helv")
    y_pos += 20
    
    # Garis tebal
    report_page.draw_line(fitz.Point(margin_left, y_pos), fitz.Point(545, y_pos), color=(0,0,0), width=2)
    y_pos += 20
    
    # PRIMARY SOURCES
    report_page.insert_text((margin_left, y_pos), "PRIMARY SOURCES", fontsize=10, fontname="helv")
    y_pos += 20
    
    # Daftar Sumber
    if len(data['sources']) == 0:
        report_page.insert_text((margin_left, y_pos), "Tidak ditemukan kemiripan signifikan.", fontsize=10, fontname="helv")
    else:
        for idx, source in enumerate(data['sources']):
            if y_pos > 750: # Pindah halaman baru jika penuh
                report_page = doc.new_page(-1, width=595, height=842)
                y_pos = 50
                
            source_id = idx + 1
            color = get_color_for_source(source_id)
            
            # Gambar kotak lencana sumber
            rect = fitz.Rect(margin_left, y_pos - 12, margin_left + 15, y_pos + 3)
            report_page.draw_rect(rect, color=color, fill=color)
            report_page.insert_text((margin_left + 4, y_pos), str(source_id), fontsize=10, fontname="helv", color=(1,1,1))
            
            # Format URL
            url_clean = source['url'].split('//')[-1].split('/')[0]
            if len(url_clean) > 40:
                url_clean = url_clean[:40] + "..."
                
            # Print URL
            report_page.insert_text((margin_left + 25, y_pos), url_clean, fontsize=12, fontname="helv", color=color)
            report_page.insert_text((margin_left + 25, y_pos + 12), "Internet", fontsize=8, fontname="helv", color=(0.5, 0.5, 0.5))
            
            # Print persentase di kanan
            percent_str = f"< 1%" if source['percentage'] < 1 else f"{int(source['percentage'])}%"
            stats_str = f"{source['matched_words']} words — {percent_str}"
            report_page.insert_text((380, y_pos + 5), stats_str, fontsize=12, fontname="helv")
            
            y_pos += 40
            
            # Garis pembatas tipis antar sumber
            report_page.draw_line(fitz.Point(margin_left, y_pos - 15), fitz.Point(545, y_pos - 15), color=(0.9, 0.9, 0.9), width=1)
    
    # Save the modified document
    doc.save(output_pdf_path)
    doc.close()
    return output_pdf_path

def draw_badge(page, inst, source_id, color):
    """Menggambar lencana angka superskrip di atas highlight"""
    # inst adalah fitz.Rect(x0, y0, x1, y1)
    rect = fitz.Rect(inst.x0 - 8, inst.y0 - 6, inst.x0 + 4, inst.y0 + 4)
    page.draw_rect(rect, color=color, fill=color)
    
    # Teks putih di dalam lencana
    text_x = inst.x0 - 6
    text_y = inst.y0 + 2
    if source_id >= 10:
        text_x -= 2
        
    page.insert_text((text_x, text_y), str(source_id), fontsize=8, fontname="helv", color=(1,1,1))
