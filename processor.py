"""
Complete Profile Processor - Final v3
Strategy: 
- Find the full signature block across pages 1 and 2
- Remove all signature content from page 1 stream
- Redraw signature cleanly at bottom of page 1
- Delete page 2 (overflow) and blank template page
- Remove Home: field
"""
import pdfplumber, pikepdf, re, io
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

SZ     = 11.04
LH     = 15.5   # line height for signature block
MARGIN = 36.0   # bottom margin

def setup_fonts():
    reg  = next((p for p in [
        '/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    ] if os.path.exists(p)), None)
    bold = next((p for p in [
        '/usr/share/fonts/truetype/crosextra/Carlito-Bold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
    ] if os.path.exists(p)), None)
    if reg:
        pdfmetrics.registerFont(TTFont('Body',     reg))
        pdfmetrics.registerFont(TTFont('BodyBold', bold or reg))
        return 'Body', 'BodyBold'
    return 'Helvetica', 'Helvetica-Bold'

FONT_REG, FONT_BOLD = setup_fonts()

# ── Signature block definition ────────────────────────────────────────────────
# These are the known lines of the signature block in order.
# We'll detect which ones are present and reconstruct them cleanly.
SIG_KEYWORDS = [
    'thank you for considering',
    'sincerely',
    'account manager',
    'hosthealthcare.com',
    '964-0497',
    '858',
    'if you have any questions',
    'no rto',
    'rto needed',
]

def is_blank_candidate_page(text):
    t = text.strip()
    return (bool(re.search(r'Candidate:\s*,', t)) and
            not re.search(r'Candidate:\s+\w+\s+\w+', t) and
            'The candidate highlights are provided below' in t)

def is_overflow_page(text):
    t = text.strip().lower()
    return (len(t) < 400 and
            any(kw in t for kw in ['sincerely', 'thank you for considering',
                                    'account manager', 'hosthealthcare', '964-0497']))

def extract_lines(plumb_page):
    """Extract text lines using char positions."""
    chars = plumb_page.chars
    if not chars:
        return []
    lines = {}
    for c in chars:
        if not c['text'].strip():
            continue
        lines.setdefault(round(c['top']), []).append(c)
    result = []
    for top in sorted(lines.keys()):
        lc = sorted(lines[top], key=lambda x: x['x0'])
        text = ''
        prev_x1 = None
        for c in lc:
            if prev_x1 is not None and c['x0'] - prev_x1 > 2:
                text += ' '
            text += c['text']
            prev_x1 = c['x1']
        text = text.strip()
        if text:
            result.append((top, text))
    return result

def is_sig_line(txt):
    """Is this text part of the signature block?"""
    t = txt.lower()
    return any(kw in t for kw in SIG_KEYWORDS) or bool(re.match(r'^\(\d{3}\)', txt))

def find_sig_start_y(lines):
    """Find the top position where signature block starts on a page."""
    for i, (top, txt) in enumerate(lines):
        if is_sig_line(txt):
            # Also include 'The Candidate has requested...' line before it
            if i > 0 and 'requested' in lines[i-1][1].lower():
                return lines[i-1][0]
            return top
    return None

def find_home_y_in_stream(stream_text):
    for m in re.finditer(r'BT\b.*?\bET', stream_text, re.DOTALL):
        b = m.group(0)
        if 'ome:' in b or 'H)3(o)' in b or '(Home' in b or ('ome' in b and 'Tm' in b):
            tms = re.findall(r'[\d\.\-]+ [\d\.\-]+ [\d\.\-]+ [\d\.\-]+ ([\d\.\-]+) ([\d\.\-]+) Tm', b)
            if tms:
                y = float(tms[0][1])
                if 490 <= y <= 620:
                    return y
    return None

def remove_bt_at_y(stream_text, y_value, tolerance=5.0):
    def check(block):
        tms = re.findall(r'[\d\.\-]+ [\d\.\-]+ [\d\.\-]+ [\d\.\-]+ [\d\.\-]+ ([\d\.\-]+) Tm', block)
        return any(abs(float(y) - y_value) <= tolerance for y in tms)
    return re.sub(r'BT\b.*?\bET', lambda m: '' if check(m.group(0)) else m.group(0), stream_text, flags=re.DOTALL)

def remove_bt_below_pdf_y(stream_text, pdf_y_threshold):
    """Remove BT blocks whose y position is BELOW threshold (in PDF coords = less than threshold)."""
    def check(block):
        tms = re.findall(r'[\d\.\-]+ [\d\.\-]+ [\d\.\-]+ [\d\.\-]+ [\d\.\-]+ ([\d\.\-]+) Tm', block)
        return any(float(y) < pdf_y_threshold for y in tms)
    return re.sub(r'BT\b.*?\bET', lambda m: '' if check(m.group(0)) else m.group(0), stream_text, flags=re.DOTALL)

def make_overlay(page_w, page_h, entries):
    """entries: (x, rl_y, text, bold)"""
    packet = io.BytesIO()
    c = rl_canvas.Canvas(packet, pagesize=(page_w, page_h))
    for x, y, txt, bold in entries:
        if txt and txt.strip():
            c.setFillColorRGB(0, 0, 0)
            c.setFont(FONT_BOLD if bold else FONT_REG, SZ)
            c.drawString(x, y, txt)
    c.save()
    packet.seek(0)
    return PdfReader(packet).pages[0]

def collect_full_signature(lines_p1, lines_p2):
    """
    Collect ALL signature lines from both pages in order.
    Returns list of (text, is_bold) tuples.
    """
    all_sig = []
    
    # From page 1: collect everything from sig_start onward
    sig_start = find_sig_start_y(lines_p1)
    if sig_start is not None:
        for top, txt in lines_p1:
            if top >= sig_start:
                all_sig.append(txt)
    
    # From page 2: collect everything
    for top, txt in lines_p2:
        # Avoid duplicates
        if txt not in all_sig:
            all_sig.append(txt)
    
    # Now annotate bold — only the recruiter name (Tuyet Vu) is bold
    result = []
    for txt in all_sig:
        t = txt.lower()
        is_bold = (not any(kw in t for kw in [
            'thank', 'sincerely', 'account', 'hosthealthcare', '858', '964',
            'if you', 'no rto', 'rto', 'requested', 'candidate', 'questions'
        ]) and len(txt.split()) <= 4 and txt[0].isupper())
        result.append((txt, is_bold))
    
    return result

def process_cover(pdf_bytes, plumb_page1, plumb_page2, page_h, page_w):
    lines_p1 = extract_lines(plumb_page1)
    lines_p2 = extract_lines(plumb_page2) if plumb_page2 else []

    # ── Collect full signature block ──────────────────────────────────────────
    sig_lines = collect_full_signature(lines_p1, lines_p2)

    # ── Find last NON-signature line on page 1 ────────────────────────────────
    sig_start_top = find_sig_start_y(lines_p1)
    last_content_top = 0
    for top, txt in lines_p1:
        if sig_start_top and top >= sig_start_top:
            break
        last_content_top = top

    last_content_bot = last_content_top + SZ + 2

    # ── Remove Home: and entire signature from stream ─────────────────────────
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        page = pdf.pages[0]
        contents = page['/Contents']
        raw = b''.join(s.read_bytes() for s in contents) if isinstance(contents, pikepdf.Array) else contents.read_bytes()
        stream = raw.decode('latin-1')

        # Remove Home:
        home_y = find_home_y_in_stream(stream)
        if home_y:
            stream = remove_bt_at_y(stream, home_y, tolerance=5.0)

        # Remove signature block from page 1 stream
        # sig_start_top in plumber coords -> pdf_y = page_h - sig_start_top
        if sig_start_top:
            sig_pdf_y = page_h - sig_start_top + 5
            stream = remove_bt_below_pdf_y(stream, sig_pdf_y)

        page['/Contents'] = pikepdf.Stream(pdf, stream.encode('latin-1'))
        tmp = io.BytesIO()
        pdf.save(tmp)
        tmp.seek(0)

    reader   = PdfReader(tmp)
    page_obj = reader.pages[0]

    # ── Redraw signature cleanly ──────────────────────────────────────────────
    if not sig_lines:
        return page_obj

    num_lines     = len(sig_lines)
    total_sig_h   = num_lines * LH
    available     = (page_h - MARGIN) - last_content_bot
    gap_before    = min(available - total_sig_h, 22)  # max 22pt gap before sig
    gap_before    = max(gap_before, 6)                # min 6pt gap

    start_plumb = last_content_bot + gap_before

    # If still doesn't fit, reduce line height
    if start_plumb + total_sig_h > page_h - MARGIN:
        available_for_sig = (page_h - MARGIN) - start_plumb
        effective_lh = available_for_sig / num_lines
    else:
        effective_lh = LH

    entries = []
    for i, (txt, bold) in enumerate(sig_lines):
        plumb_y = start_plumb + (i * effective_lh)
        rl_y    = page_h - plumb_y - SZ + 2
        entries.append((72, rl_y, txt, bold))

    overlay  = make_overlay(page_w, page_h, entries)
    page_obj.merge_page(overlay)
    return page_obj


def process_profile(input_buf):
    if isinstance(input_buf, (bytes, bytearray)):
        pdf_bytes = bytes(input_buf)
    else:
        pdf_bytes = input_buf.read()

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages_text  = [p.extract_text() or '' for p in pdf.pages]
        plumb_pages = list(pdf.pages)
        dims        = [(float(p.width), float(p.height)) for p in pdf.pages]

    reader = PdfReader(io.BytesIO(pdf_bytes))
    skip   = set()

    overflow_idx = None
    for i in range(1, min(4, len(pages_text))):
        if is_overflow_page(pages_text[i]):
            overflow_idx = i
            skip.add(i)
            break

    for i, txt in enumerate(pages_text):
        if is_blank_candidate_page(txt):
            skip.add(i)

    cover_writer = PdfWriter()
    cover_writer.add_page(reader.pages[0])
    cover_buf = io.BytesIO()
    cover_writer.write(cover_buf)
    cover_bytes = cover_buf.getvalue()

    plumb_page2 = plumb_pages[overflow_idx] if overflow_idx is not None else None
    page_w, page_h = dims[0]

    writer = PdfWriter()
    for i in range(len(reader.pages)):
        if i in skip:
            continue
        if i == 0:
            page = process_cover(cover_bytes, plumb_pages[0], plumb_page2, page_h, page_w)
        else:
            page = reader.pages[i]
        writer.add_page(page)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


if __name__ == '__main__':
    import sys
    inp      = sys.argv[1] if len(sys.argv) > 1 else '/mnt/user-data/uploads/Complete_Profile_New.pdf'
    out_path = sys.argv[2] if len(sys.argv) > 2 else '/mnt/user-data/outputs/Complete_Profile_Processed.pdf'
    with open(inp, 'rb') as f:
        result = process_profile(f.read())
    with open(out_path, 'wb') as f:
        f.write(result)
    print(f"Done: {out_path}")
