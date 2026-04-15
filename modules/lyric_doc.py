"""Lyric Doc PDF Generator — auto-generates formatted lyric documents."""
import os
import re
import logging
import threading

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False
    logging.warning("reportlab not installed — lyric doc generation disabled. pip install reportlab")


SECTION_PATTERNS = re.compile(
    r'^\[?(verse|chorus|bridge|pre-chorus|pre chorus|hook|outro|intro|post-chorus|interlude|refrain|coda|tag|ad[- ]?lib)\s*\d*\]?\s*:?\s*$',
    re.IGNORECASE
)

DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'lyric_docs')


def _ensure_dir():
    os.makedirs(DOCS_DIR, exist_ok=True)


def _safe_filename(title):
    """Create safe filename from song title."""
    safe = re.sub(r'[^\w\s-]', '', title).strip()
    safe = re.sub(r'[\s]+', '_', safe)
    return safe[:80] if safe else 'untitled'


def generate_lyric_pdf(title, lyrics, metadata=None):
    """Generate a formatted lyric doc PDF.

    Args:
        title: Song title
        lyrics: Raw lyrics text
        metadata: dict with optional keys: songwriter_credits, producer, artist, bpm, duration, key, genre, audio_status

    Returns:
        Relative URL path to the generated PDF, or None on failure.
    """
    if not HAS_REPORTLAB:
        logging.warning("Cannot generate lyric doc — reportlab not installed")
        return None
    if not lyrics or not lyrics.strip():
        return None

    _ensure_dir()
    metadata = metadata or {}
    filename = _safe_filename(title) + '.pdf'
    filepath = os.path.join(DOCS_DIR, filename)

    try:
        doc = SimpleDocTemplate(
            filepath,
            pagesize=letter,
            topMargin=0.75 * inch,
            bottomMargin=0.75 * inch,
            leftMargin=1 * inch,
            rightMargin=1 * inch
        )

        styles = getSampleStyleSheet()
        accent = HexColor('#d4a853')
        dark = HexColor('#1a1a1a')
        muted = HexColor('#666666')

        title_style = ParagraphStyle(
            'SongTitle', parent=styles['Title'],
            fontSize=24, leading=28, textColor=dark,
            spaceAfter=6, fontName='Helvetica-Bold'
        )
        meta_style = ParagraphStyle(
            'MetaLine', parent=styles['Normal'],
            fontSize=10, leading=14, textColor=muted,
            spaceAfter=2, fontName='Helvetica'
        )
        section_style = ParagraphStyle(
            'SectionHeader', parent=styles['Normal'],
            fontSize=11, leading=16, textColor=accent,
            spaceBefore=16, spaceAfter=4,
            fontName='Helvetica-Bold'
        )
        lyric_style = ParagraphStyle(
            'LyricLine', parent=styles['Normal'],
            fontSize=11, leading=16, textColor=dark,
            spaceAfter=1, fontName='Helvetica'
        )
        divider_style = ParagraphStyle(
            'Divider', parent=styles['Normal'],
            fontSize=8, leading=10, textColor=HexColor('#cccccc'),
            spaceBefore=8, spaceAfter=8
        )

        story = []

        # Title
        story.append(Paragraph(title, title_style))
        story.append(Spacer(1, 4))

        # Metadata block
        meta_lines = []
        if metadata.get('songwriter_credits'):
            meta_lines.append(f"Writers: {metadata['songwriter_credits']}")
        if metadata.get('producer'):
            meta_lines.append(f"Producer: {metadata['producer']}")
        if metadata.get('artist'):
            meta_lines.append(f"Artist: {metadata['artist']}")

        detail_parts = []
        if metadata.get('bpm'):
            detail_parts.append(f"BPM: {metadata['bpm']}")
        if metadata.get('duration'):
            detail_parts.append(f"Duration: {metadata['duration']}")
        if metadata.get('key'):
            detail_parts.append(f"Key: {metadata['key']}")
        if metadata.get('genre'):
            detail_parts.append(f"Genre: {metadata['genre']}")
        if detail_parts:
            meta_lines.append('  |  '.join(detail_parts))

        for line in meta_lines:
            story.append(Paragraph(line, meta_style))

        if meta_lines:
            story.append(Spacer(1, 4))
            story.append(Paragraph('_' * 60, divider_style))

        # Parse and format lyrics
        lines = lyrics.split('\n')
        for line in lines:
            stripped = line.strip()
            if not stripped:
                story.append(Spacer(1, 8))
                continue

            # Check for section headers: [VERSE], [CHORUS], etc.
            is_section = False
            if stripped.startswith('[') and ']' in stripped:
                inner = stripped[1:stripped.index(']')].strip()
                if SECTION_PATTERNS.match(f'[{inner}]'):
                    is_section = True
                    story.append(Paragraph(inner.upper(), section_style))
            elif SECTION_PATTERNS.match(stripped):
                is_section = True
                label = stripped.rstrip(':').strip('[]').strip()
                story.append(Paragraph(label.upper(), section_style))

            if not is_section:
                # Escape XML special chars for reportlab
                safe = stripped.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                story.append(Paragraph(safe, lyric_style))

        doc.build(story)
        return f'/static/lyric_docs/{filename}'

    except Exception as e:
        logging.error(f"Lyric doc generation failed for '{title}': {e}")
        return None


def generate_from_record(record, headers):
    """Generate lyric doc from a song record dict.

    Args:
        record: dict with header keys
        headers: list of header strings

    Returns:
        URL path or None
    """
    from modules.id_resolver import cleanH

    def _get(field_names):
        if isinstance(field_names, str):
            field_names = [field_names]
        for fn in field_names:
            for h in headers:
                if cleanH(h).lower() == fn.lower():
                    val = record.get(h, '')
                    if val:
                        return str(val).strip()
        return ''

    title = _get(['title'])
    lyrics = _get(['lyrics'])
    if not title or not lyrics:
        return None

    metadata = {
        'songwriter_credits': _get(['songwriter credits']),
        'producer': _get(['producer']),
        'artist': _get(['artist']),
        'bpm': _get(['bpm']),
        'duration': _get(['duration']),
        'key': _get(['key']),
        'genre': _get(['genre']),
        'audio_status': _get(['audio status']),
    }

    return generate_lyric_pdf(title, lyrics, metadata)


def auto_generate_and_link(sheets_manager, table_name, row_index, headers):
    """Generate lyric doc and write the URL back to the Lyric Doc column.
    Runs in a background thread to avoid blocking the request."""
    def _do():
        try:
            row = sheets_manager.get_row(table_name, row_index)
            record = {}
            for j, h in enumerate(headers):
                record[h] = row[j] if j < len(row) else ''

            url = generate_from_record(record, headers)
            if url:
                # Find the Lyric Doc column
                from modules.id_resolver import cleanH
                ld_col = None
                for i, h in enumerate(headers):
                    ch = cleanH(h).lower()
                    if ch in ('lyric doc', 'lyric docs', 'lyrics docs'):
                        ld_col = i
                        break
                if ld_col is not None:
                    sheets_manager.update_cell(table_name, row_index, ld_col + 1, url)
                    logging.info(f"Lyric doc generated for row {row_index}: {url}")
        except Exception as e:
            logging.error(f"Auto lyric doc failed for row {row_index}: {e}")

    thread = threading.Thread(target=_do, daemon=True)
    thread.start()
