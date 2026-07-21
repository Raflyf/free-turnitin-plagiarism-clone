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
            
    import re
    # --- STEP 1: Berikan Highlight pada teks di PDF asli ---
    biblio_started = False
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        
        # Baca teks halaman dan bersihkan spasinya untuk deteksi Daftar Pustaka
        page_text_clean = page.get_text().replace('\n', ' ').replace('\r', ' ').lower()
        page_text_nospace = re.sub(r'\s+', ' ', page_text_clean).strip()
        
        # Jika halaman berada di paruh akhir dokumen dan mengandung "daftar pustaka", hentikan highlight
        if page_num >= len(doc) * 0.5:
            if "daftar pustaka" in page_text_nospace or "references" in page_text_nospace:
                biblio_started = True
                
        if biblio_started:
            continue
            
        # Simpan semua kotak warna di halaman ini untuk mencegah overlap
        highlighted_rects = []
        blocked_overlaps_count = 0
        
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
            
            if len(words) >= 5:
                chunk_first = " ".join(words[:5]).lower()
                chunk_mid = " ".join(words[len(words)//2 : len(words)//2+5]).lower()
                chunk_last = " ".join(words[-5:]).lower()
                
                if chunk_first not in page_text_clean and chunk_mid not in page_text_clean and chunk_last not in page_text_clean:
                    continue
            
            found_any = False
            first_rect = None
            
            # Coba cari seluruh kalimat dengan quads (dukung line-breaks)
            text_instances = page.search_for(text, quads=True)
            if text_instances:
                for inst in text_instances:
                    if is_overlapping(inst.rect):
                        blocked_overlaps_count += 1
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
            if not found_any and len(words) >= 5:
                # Gunakan step=5 agar tidak ada kotak warna yang saling menindih
                for i in range(0, len(words), 5):
                    chunk = " ".join(words[i:i+5])
                    # Jika sisa < 5 kata, ambil 5 kata terakhir untuk memastikan konteks pencarian spesifik
                    if len(chunk.split()) < 5 and len(words) >= 5:
                        chunk = " ".join(words[-5:])
                        
                    insts = page.search_for(chunk, quads=True)
                    for inst in insts:
                        if is_overlapping(inst.rect):
                            blocked_overlaps_count += 1
                            continue
                        highlighted_rects.append(inst.rect)
                        
                        annot = page.add_highlight_annot(inst)
                        annot.set_colors(stroke=color)
                        annot.set_opacity(0.3)
                        annot.update()
                        if not first_rect:
                            first_rect = inst.rect
                            
            elif not found_any and len(words) >= 2:
                chunk = " ".join(words)
                insts = page.search_for(chunk, quads=True)
                for inst in insts:
                    if is_overlapping(inst.rect):
                        blocked_overlaps_count += 1
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
                
        if blocked_overlaps_count > 0:
            print(f"[Anti-Overlap] Blokir {blocked_overlaps_count} penumpukan warna di Halaman {page_num + 1}")

    # --- STEP 1.5: Highlight teks tersembunyi (hidden spans) dengan warna berbeda ---
    # Warna: hitam transparan, agar mencolok dan berbeda dari warna plagiarisme
    hidden_spans = data.get('hidden_spans', [])
    if hidden_spans:
        for page_index, bbox in hidden_spans:
            if page_index < len(doc):
                page = doc[page_index]
                rect = fitz.Rect(bbox)
                
                # Perbesar area bbox jika ukurannya terlalu kecil (karena font mungil)
                # agar highlight tetap terlihat jelas oleh mata manusia
                if rect.height < 5:
                    rect.y0 = rect.y1 - 5
                if rect.width < 5:
                    rect.x1 = rect.x0 + 5
                
                annot = page.add_highlight_annot(rect)
                annot.set_colors(stroke=(0.2, 0.2, 0.2))  # Abu-abu sangat gelap
                annot.set_opacity(0.8)
                annot.set_info(content="TEKS TERSEMBUNYI (MANIPULASI)", title="Sistem Plagiarisme")
                annot.update()

    # --- STEP 2: Buat Halaman "ORIGINALITY REPORT" di akhir ---
    report_page = doc.new_page(-1, width=595, height=842) # Ukuran A4 standar
    
    y_pos = 50
    margin_left = 50
    max_text_width = 490  # 595 - 50 - 55 (margin kiri + kanan)
    
    # Header: Nama File. Utamakan nama asli upload (data['filename']); path fisik
    # memakai UUID (mis. 94ae2154-...pdf) sehingga tak informatif di report.
    display_name = data.get('filename') or os.path.splitext(os.path.basename(original_pdf_path))[0]
    if not display_name.lower().endswith('.pdf'):
        display_name += '.pdf'
    report_page.insert_text((margin_left, y_pos), display_name, fontsize=18, fontname="helv")
    y_pos += 30
    
    # --- Peringatan manipulasi (text-wrapped agar tidak terpotong) ---
    if 'manipulation_warnings' in data and data['manipulation_warnings']:
        report_page.insert_text((margin_left, y_pos), "MANIPULASI TEKS TERDETEKSI:", fontsize=12, fontname="hebo", color=(1.0, 0.0, 0.0))
        y_pos += 20
        for warning in data['manipulation_warnings']:
            # Text-wrap: potong teks panjang ke beberapa baris agar muat di halaman
            words = warning.split()
            line = ""
            for word in words:
                test_line = f"{line} {word}".strip()
                # Estimasi kasar: ~5.5px per karakter pada fontsize 9
                if len(test_line) * 5.5 > max_text_width:
                    report_page.insert_text((margin_left + 10, y_pos), "-- " + line, fontsize=9, fontname="helv", color=(0.8, 0.0, 0.0))
                    y_pos += 13
                    line = word
                else:
                    line = test_line
            if line:
                report_page.insert_text((margin_left + 10, y_pos), "-- " + line, fontsize=9, fontname="helv", color=(0.8, 0.0, 0.0))
                y_pos += 13
        y_pos += 10
        
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
    
    # --- Skor Kemiripan Utama (hidden text dibuang = skor jujur) ---
    score_text = f"{int(data['total_similarity'])}%"
    report_page.insert_text((margin_left, y_pos), score_text, fontsize=48, fontname="helv")
    y_pos += 20
    
    report_page.insert_text((margin_left, y_pos), "SIMILARITY INDEX", fontsize=10, fontname="helv")
    y_pos += 8
    report_page.insert_text((margin_left, y_pos), "(Skor asli - teks tersembunyi telah dibuang)", fontsize=8, fontname="helv", color=(0.4, 0.4, 0.4))
    y_pos += 20
    
    # --- Skor Kedua: "Fooled" (jika hidden text lolos) ---
    fooled_sim = data.get('fooled_similarity')
    if fooled_sim is not None:
        # Kotak info abu-abu muda
        info_rect = fitz.Rect(margin_left, y_pos - 5, 545, y_pos + 55)
        report_page.draw_rect(info_rect, color=(0.7, 0.7, 0.7), fill=(0.95, 0.95, 0.95), width=0.5)
        y_pos += 10
        
        fooled_text = f"{fooled_sim}%"
        report_page.insert_text((margin_left + 10, y_pos), fooled_text, fontsize=28, fontname="helv", color=(0.5, 0.5, 0.5))
        y_pos += 15
        report_page.insert_text((margin_left + 10, y_pos), "SKOR JIKA HIDDEN TEXT LOLOS (seperti Turnitin asli)", fontsize=9, fontname="helv", color=(0.5, 0.5, 0.5))
        y_pos += 13
        report_page.insert_text((margin_left + 10, y_pos), "Teks tersembunyi menggelembungkan jumlah kata sehingga persentase turun.", fontsize=8, fontname="helv", color=(0.6, 0.6, 0.6))
        y_pos += 25
    
    y_pos += 5
    
    # Garis tebal
    report_page.draw_line(fitz.Point(margin_left, y_pos), fitz.Point(545, y_pos), color=(0,0,0), width=2)
    y_pos += 20
    
    # PRIMARY SOURCES
    report_page.insert_text((margin_left, y_pos), "PRIMARY SOURCES", fontsize=10, fontname="helv")
    y_pos += 20
    
    # Daftar Sumber
    # Dedup per-DOMAIN untuk tampilan: banyak URL berbeda (mis. doi.org/xxx, doi.org/yyy)
    # menciut ke domain yang sama -> tampil berulang. Sumber sudah terurut % desc, jadi
    # menyimpan kemunculan PERTAMA tiap domain = menahan yang kontribusinya tertinggi.
    # Ini murni tampilan; skor total (union kata) dihitung terpisah & tidak berubah.
    seen_domains = set()
    unique_sources = []
    for source in data['sources']:
        domain = source['url'].split('//')[-1].split('/')[0]
        if domain in seen_domains:
            continue
        seen_domains.add(domain)
        unique_sources.append((domain, source))

    if len(unique_sources) == 0:
        report_page.insert_text((margin_left, y_pos), "Tidak ditemukan kemiripan signifikan.", fontsize=10, fontname="helv")
    else:
        for idx, (url_clean, source) in enumerate(unique_sources):
            if y_pos > 750: # Pindah halaman baru jika penuh
                report_page = doc.new_page(-1, width=595, height=842)
                y_pos = 50

            source_id = idx + 1
            color = get_color_for_source(source_id)

            # Gambar kotak lencana sumber. Lebar menyesuaikan jumlah digit: angka 3-digit
            # ("100") lebih lebar dari kotak tetap -> digit terakhir jatuh di luar kotak
            # berwarna = teks putih di atas latar putih (tak terlihat, tampak seperti "10").
            badge_w = 15 + max(0, len(str(source_id)) - 2) * 7
            rect = fitz.Rect(margin_left, y_pos - 12, margin_left + badge_w, y_pos + 3)
            report_page.draw_rect(rect, color=color, fill=color)
            report_page.insert_text((margin_left + 4, y_pos), str(source_id), fontsize=10, fontname="helv", color=(1,1,1))

            # Format URL (domain sudah diekstrak saat dedup di atas)
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
    # Lebar kotak menyesuaikan jumlah digit: angka 2-3 digit (10, 100) lebih lebar
    # dari 1 digit. Tanpa ini, digit terakhir jatuh di luar kotak -> teks putih di
    # atas latar putih = tak terlihat (mis. "100" tampak seperti "10").
    n_digits = len(str(source_id))
    extra_w = (n_digits - 1) * 4
    rect = fitz.Rect(inst.x0 - 8, inst.y0 - 6, inst.x0 + 4 + extra_w, inst.y0 + 4)
    page.draw_rect(rect, color=color, fill=color)

    # Teks putih di dalam lencana
    text_x = inst.x0 - 6
    text_y = inst.y0 + 2
    page.insert_text((text_x, text_y), str(source_id), fontsize=8, fontname="helv", color=(1,1,1))
