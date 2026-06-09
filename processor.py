import pdfplumber, pikepdf, re, io
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

SZ = 11.04

def setup_fonts():
    candidates_reg  = ['/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf',
                       '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf']
    candidates_bold = ['/usr/share/fonts/truetype/crosextra/Carlito-Bold.ttf',
                       '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf']
    reg  = next((p for p in candidates_reg  if os.path.exists(p)), None)
    bold = next((p for p in candidates_bold if os.path.exists(p)), None)
    if reg:
        pdfmetrics.registerFont(TTFont('Body',     reg))
        pdfmetrics.registerFont(TTFont('BodyBold', bold or reg))
        return 'Body', 'BodyBold'
    return 'Helvetica', 'Helvetica-Bold'

FONT_REG, FONT_BOLD = setup_fonts()

def is_blank_candidate_page(text):
    t = text.strip()
    return (bool(re.search(r'Candidate:\s*,', t)) and
            not re.search(r'Candidate:\s+\w+\s+\w+', t) and
            'The candidate highlights are provided below' in t)

def is_stray_content_page(text):
    t = text.strip()
    return len(t) < 30 and bool(re.match(r'^[\(\d\)\s\-\.]+$', t))

def group_by_line(words, tol=2):
    lines = {}
    for w in words:
        k = round(w['top'] / tol) * tol
        lines.setdefault(k, []).append(w)
    return {k: sorted(v, key=lambda x: x['x0']) for k, v in sorted(lines.items())}

def find_home_y_in_stream(stream_text):
    for m in re.finditer(r'BT\b.*?\bET', stream_text, re.DOTALL):
        b = m.group(0)
        if 'ome:' in b or 'H)3(o)' in b or '(Home' in b or 'ome' in b:
            tms = re.findall(r'[\d\.\-]+ [\d\.\-]+ [\d\.\-]+ [\d\.\-]+ ([\d\.\-]+) ([\d\.\-]+) Tm', b)
            if tms:
                return float(tms[0][1])
    return None

def remove_bt_at_y(stream_text, y_value, tolerance=5.0):
    def should_remove(block):
        tms = re.findall(r'[\d\.\-]+ [\d\.\-]+ [\d\.\-]+ [\d\.\-]+ [\d\.\-]+ ([\d\.\-]+) Tm', block)
        return any(abs(float(y) - y_value) <= tolerance for y in tms)
    return re.sub(r'BT\b.*?\bET', lambda m: '' if should_remove(m.group(0)) else m.group(0), stream_text, flags=re.DOTALL)

def remove_bt_below_y(stream_text, y_threshold):
    def should_remove(block):
        tms = re.findall(r'[\d\.\-]+ [\d\.\-]+ [\d\.\-]+ [\d\.\-]+ [\d\.\-]+ ([\d\.\-]+) Tm', block)
        return any(float(y) < y_threshold for y in tms)
    return re.sub(r'BT\b.*?\bET', lambda m: '' if should_remove(m.group(0)) else m.group(0), stream_text, flags=re.DOTALL)

def make_text_overlay(width, height, entries):
    packet = io.BytesIO()
    c = rl_canvas.Canvas(packet, pagesize=(width, height))
    for x, y, txt, bold in entries:
        if txt:
            c.setFillColorRGB(0, 0, 0)
            c.setFont(FONT_BOLD if bold else FONT_REG, SZ)
            c.drawString(x, y, txt)
    c.save()
    packet.seek(0)
    return PdfReader(packet).pages[0]

def process_cover(pdf_bytes, plumb_page, stray_phone, h, w):
    words = plumb_page.extract_words()
    chars = plumb_page.chars
    lines = group_by_line(words)

    rto_top = if_you_top = thank_top = sincerely_top = None
    name_text = account_text = email_text = None
    last_content_bot = 0

    for top, lw in lines.items():
        txt = ' '.join(x['text'] for x in lw).strip()
        if re.match(r'^No RTO|^RTO', txt):    rto_top = top
        if txt.startswith('If you have any'): if_you_top = top
        if txt.startswith('Thank you'):       thank_top = top
        if 'Sincerely' in txt:               sincerely_top = top
        if 'hosthealthcare.com' in txt:      email_text = txt.strip()

    found_name = False
    if sincerely_top:
        for top, lw in lines.items():
            if top <= sincerely_top + 5: continue
            txt = ' '.join(x['text'] for x in lw).strip()
            if not txt: continue
            if not found_name:     name_text = txt;    found_name = True
            elif not account_text: account_text = txt; break

    if rto_top:
        for top, lw in lines.items():
            if top >= rto_top - 5: continue
            txt = ' '.join(x['text'] for x in lw).strip()
            if txt:
                bot = max(c['bottom'] for c in chars if abs(c['top'] - top) < 4)
                last_content_bot = max(last_content_bot, bot)

    footer_pdf_y_threshold = h - rto_top + 8 if rto_top else 260
    avail_start = last_content_bot + 14
    extra = ((h - 36.0) - avail_start) - 175.0
    new_rto_plumb = avail_start + min(max(extra * 0.35, 0), 28)

    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        page = pdf.pages[0]
        contents = page['/Contents']
        if isinstance(contents, pikepdf.Array):
            raw = b''.join(s.read_bytes() for s in contents)
        else:
            raw = contents.read_bytes()
        stream_text = raw.decode('latin-1')
        home_y = find_home_y_in_stream(stream_text)
        if home_y:
            stream_text = remove_bt_at_y(stream_text, home_y, tolerance=5.0)
        stream_text = remove_bt_below_y(stream_text, footer_pdf_y_threshold)
        page['/Contents'] = pikepdf.Stream(pdf, stream_text.encode('latin-1'))
        tmp = io.BytesIO()
        pdf.save(tmp)
        tmp.seek(0)

    reader   = PdfReader(tmp)
    page_obj = reader.pages[0]

    def rl_y(offset):
        return h - (new_rto_plumb + offset) - SZ + 2

    rto_txt   = (rto_top    and ' '.join(x['text'] for x in lines[round(rto_top)]).strip())    or 'No RTO needed'
    if_txt    = (if_you_top and ' '.join(x['text'] for x in lines[round(if_you_top)]).strip()) or 'If you have any questions, please feel free to contact me.'
    thank_txt = (thank_top  and ' '.join(x['text'] for x in lines[round(thank_top)]).strip())  or 'Thank you for considering this candidate.'

    entries = [
        (72, rl_y(0),     rto_txt,                          False),
        (72, rl_y(23.6),  if_txt,                           False),
        (72, rl_y(46.1),  thank_txt,                        False),
        (72, rl_y(80.4),  'Sincerely,',                     False),
        (72, rl_y(101.9), name_text    or '',                True),
        (72, rl_y(123.2), account_text or 'Account Manager', False),
        (72, rl_y(144.7), email_text   or '',                False),
    ]
    if stray_phone:
        entries.append((72, rl_y(158.0), stray_phone, False))

    overlay = make_text_overlay(w, h, [(x,y,t,b) for x,y,t,b in entries if t])
    page_obj.merge_page(overlay)
    return page_obj

def process_profile(input_buf):
    """Accept file-like object or bytes, return processed PDF bytes."""
    if isinstance(input_buf, (bytes, bytearray)):
        pdf_bytes = bytes(input_buf)
    else:
        pdf_bytes = input_buf.read()

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages_text  = [p.extract_text() or '' for p in pdf.pages]
        plumb_pages = list(pdf.pages)
        dims        = [(float(p.width), float(p.height)) for p in pdf.pages]

    reader = PdfReader(io.BytesIO(pdf_bytes))
    stray_phone = None
    skip = set()

    for i, txt in enumerate(pages_text):
        if is_stray_content_page(txt):
            stray_phone = txt.strip(); skip.add(i)
        elif is_blank_candidate_page(txt):
            skip.add(i)

    # Extract cover page bytes separately for pikepdf
    cover_writer = PdfWriter()
    cover_writer.add_page(reader.pages[0])
    cover_buf = io.BytesIO()
    cover_writer.write(cover_buf)
    cover_bytes = cover_buf.getvalue()

    writer = PdfWriter()
    for i in range(len(reader.pages)):
        if i in skip: continue
        w, h = dims[i]
        if i == 0:
            page = process_cover(cover_bytes, plumb_pages[i], stray_phone, h, w)
        else:
            page = reader.pages[i]
        writer.add_page(page)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
