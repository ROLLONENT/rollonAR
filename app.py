"""
ROLLON AR v35.1 — A&R Operating System
Google Sheets master. No external dependencies.
"""

import os, json, math, functools, re, logging, time, threading, secrets
from datetime import datetime, timedelta
from collections import deque
from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, session, flash, send_from_directory)

from modules.google_sheets import SheetsManager
from modules.pitch_builder import PitchBuilder
from modules.pub_splits import PubSplitCalculator
from modules.id_resolver import IDResolver, cleanH as _module_cleanH
from modules.lyric_doc import auto_generate_and_link as generate_lyric_doc

logging.basicConfig(filename='rollon.log', level=logging.WARNING,
    format='%(asctime)s %(levelname)s %(message)s')

app = Flask(__name__)

SECRET_KEY_FILE = os.path.join(os.path.dirname(__file__), '.secret_key')
if os.path.exists(SECRET_KEY_FILE):
    with open(SECRET_KEY_FILE, 'rb') as f: app.secret_key = f.read()
else:
    app.secret_key = os.urandom(32)
    with open(SECRET_KEY_FILE, 'wb') as f: f.write(app.secret_key)

app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # No static file caching

# Performance monitoring middleware
@app.before_request
def _start_timer():
    from flask import g
    g._req_start = time.time()

@app.after_request
def _log_slow(response):
    from flask import g
    elapsed = (time.time() - getattr(g, '_req_start', time.time())) * 1000
    if elapsed > 500:
        logging.warning(f"SLOW {request.method} {request.path}: {elapsed:.0f}ms")
    response.headers['X-Response-Time'] = f"{elapsed:.0f}ms"
    return response

GOOGLE_SHEET_ID = os.environ.get('ROLLON_SHEET_ID', '17b7HjbfXkV5w_Q8lRuG3Ae_7hwJ0M9F7ODVIFytBBmY')

# Load .env file if present
_env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(_env_path):
    with open(_env_path) as _ef:
        for _line in _ef:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _v = _line.split('=', 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

# Passwords: require env var or .env, prompt on first run if missing
APP_PASSWORD = os.environ.get('ROLLON_PASSWORD', '')
ASSISTANT_PASSWORD = os.environ.get('ROLLON_ASSISTANT_PW', '')
if not APP_PASSWORD:
    if os.path.exists(_env_path):
        logging.warning("ROLLON_PASSWORD not set in .env file")
    else:
        # First run: create .env with prompted or generated passwords
        _pw = secrets.token_urlsafe(12)
        _apw = secrets.token_urlsafe(8)
        with open(_env_path, 'w') as _ef:
            _ef.write(f"ROLLON_PASSWORD={_pw}\n")
            _ef.write(f"ROLLON_ASSISTANT_PW={_apw}\n")
            _ef.write("ROLLON_SMTP_USER=\nROLLON_SMTP_PASS=\n")
        APP_PASSWORD = _pw
        ASSISTANT_PASSWORD = _apw
        print(f"  Created .env with generated passwords. Admin: {_pw}  Assistant: {_apw}")

# Roles: 'admin' = full access (Celina), 'assistant' = no invoices
ROLE_PAGES = {
    'admin': ['dashboard','songs','directory','pitch','invoices','settings','submit'],
    'assistant': ['dashboard','songs','directory','pitch','settings']
}

# Simple rate limiter for public endpoints (per IP)
_submit_times = {}
_submit_lock = threading.Lock()

def _get_client_ip():
    """Get real client IP, checking X-Forwarded-For for proxy setups."""
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr

def rate_limit_check(ip=None, max_per_hour=10):
    if ip is None:
        ip = _get_client_ip()
    # Authenticated admin/assistant users bypass rate limiting
    if session.get('authenticated'):
        return True
    now = time.time()
    with _submit_lock:
        times = _submit_times.get(ip, [])
        times = [t for t in times if now - t < 3600]
        if len(times) >= max_per_hour: return False
        times.append(now)
        _submit_times[ip] = times
    return True

# Edit tokens for submission corrections (token -> {row_index, data, expires})
# Persisted to .edit_tokens.json (Fix 8)
_EDIT_TOKENS_PATH = os.path.join(os.path.dirname(__file__), '.edit_tokens.json')
_edit_tokens = {}
_edit_tokens_lock = threading.Lock()

def _load_edit_tokens():
    """Load edit tokens from disk, discard expired."""
    global _edit_tokens
    if os.path.exists(_EDIT_TOKENS_PATH):
        try:
            with open(_EDIT_TOKENS_PATH, 'r') as f:
                stored = json.load(f)
            now = time.time()
            _edit_tokens = {k: v for k, v in stored.items() if v.get('expires', 0) > now}
        except Exception as e:
            logging.warning(f"Failed to load edit tokens: {e}")
            _edit_tokens = {}

def _save_edit_tokens():
    """Persist edit tokens to disk. Thread-safe."""
    with _edit_tokens_lock:
        try:
            with open(_EDIT_TOKENS_PATH, 'w') as f:
                json.dump(_edit_tokens, f)
        except Exception as e:
            logging.warning(f"Failed to save edit tokens: {e}")

_load_edit_tokens()

# SMTP config for confirmation emails (Fix 9: no hardcoded email default)
SMTP_HOST = os.environ.get('ROLLON_SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('ROLLON_SMTP_PORT', '587'))
SMTP_USER = os.environ.get('ROLLON_SMTP_USER', '')
SMTP_PASS = os.environ.get('ROLLON_SMTP_PASS', '')
SMTP_FROM = os.environ.get('ROLLON_SMTP_FROM', SMTP_USER or 'noreply@rollonent.com')

CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), "credentials.json")
TOKEN_PATH = os.path.join(os.path.dirname(__file__), "token.json")
# Fallback: check parent folder (ROLLON AR)
if not os.path.exists(CREDENTIALS_PATH):
    parent = os.path.join(os.path.dirname(__file__), '..', 'credentials.json')
    if os.path.exists(parent):
        CREDENTIALS_PATH = parent
        # Copy to local dir for future
        import shutil; shutil.copy2(parent, os.path.join(os.path.dirname(__file__), 'credentials.json'))
if not os.path.exists(TOKEN_PATH):
    parent = os.path.join(os.path.dirname(__file__), '..', 'token.json')
    if os.path.exists(parent):
        TOKEN_PATH = parent
        import shutil; shutil.copy2(parent, os.path.join(os.path.dirname(__file__), 'token.json'))

sheets = SheetsManager(GOOGLE_SHEET_ID, CREDENTIALS_PATH, TOKEN_PATH)
pitch_builder = PitchBuilder(sheets)
split_calc = PubSplitCalculator(sheets)
resolver = IDResolver(sheets)

# Fast name-to-record lookup cache (built once, used by pill clicks)
NAME_CACHE = {}  # name_lower -> {table, row_index, route, name}
NAME_CACHE_LOCK = threading.Lock()

def build_name_cache():
    """Build reverse name lookup for instant pill navigation."""
    global NAME_CACHE
    cache = {}
    for table_name, route in [('Songs', 'songs'), ('Personnel', 'directory')]:
        try:
            data = sheets.get_all_rows(table_name)
            if not data or len(data) < 2: continue
            headers = data[0]
            nc = None
            for i, h in enumerate(headers):
                hl = cleanH(h).lower()
                if hl in ('name', 'title'): nc = i; break
            if nc is None: continue
            for i, row in enumerate(data[1:]):
                if nc < len(row) and row[nc].strip():
                    name = row[nc].strip()
                    cache[name.lower()] = {'table': table_name, 'row_index': i + 2, 'route': route, 'name': name}
        except Exception as e:
            logging.warning(f'Name cache build (primary tables): {e}')
    # Also index supporting tables for peek modals
    try:
        tabs = sheets.list_sheets()
        for table_name in tabs:
            if table_name in ('Songs', 'Personnel', 'Templates', 'Pitch Log', 'Invoices'): continue
            try:
                data = sheets.get_all_rows(table_name)
                if not data or len(data) < 2: continue
                nc = None
                for i, h in enumerate(data[0]):
                    if cleanH(h).lower() in ('name', 'title', 'company name', 'label name'): nc = i; break
                if nc is None: nc = 0  # fall back to first column
                for i, row in enumerate(data[1:]):
                    if nc < len(row) and row[nc].strip():
                        name = row[nc].strip()
                        nl = name.lower()
                        if nl not in cache:  # Songs/Personnel take priority
                            cache[nl] = {'table': table_name, 'row_index': i + 2, 'route': 'peek', 'name': name}
            except Exception as e:
                logging.warning(f'Name cache build (supporting table): {e}')
    except Exception as e:
        logging.warning(f'Name cache build (supporting tables): {e}')
    with NAME_CACHE_LOCK:
        NAME_CACHE = cache
    print(f"  Name cache: {len(cache)} entries")

# Build on startup (synchronous to avoid segfault on macOS ARM64)
build_name_cache()

TAG_COLORS = {
    'BW Collab':'#1d4ed8','EMMMA Collab':'#7c3aed','IM Collab':'#0891b2',
    'EC Offer':'#059669','Dance Pitch':'#ea580c','Pop Pitch':'#d946ef',
    'KPOP Pitch':'#f43f5e','Singer-Songwriter Pitch':'#8b5cf6',
    'Sync Pitch':'#0d9488','Writing Trip':'#ca8a04','Warm':'#2563eb',
    'Dont Pitch':'#dc2626',"Don't Mass Pitch":'#b91c1c','Need Email':'#f59e0b',
    'Blocked':'#ef4444','Bounce Back':'#f97316','Celina Relationship':'#10b981',
    'Sonia Relationship':'#6366f1','EMMMA 2025 Pitch':'#8b5cf6',
    'Artist Project':'#3b82f6','Cuts':'#22c55e','2026 Album':'#6366f1',
    'PW Tour':'#ec4899','Pitch Ready':'#10b981','Released':'#22c55e',
    'In Production':'#eab308','Single':'#3b82f6','Creative':'#8b5cf6',
    'Artist':'#ec4899','MGMT':'#f97316','Record A&R':'#3b82f6',
    'Publishing A&R':'#059669','Agent':'#ef4444','Music Supervisor':'#0891b2',
    'Sync':'#0d9488','Sync Agent':'#14b8a6',
}

CITY_LOOKUP = {}
UNDO_STACK = deque(maxlen=50)
_ID_LOCK = threading.Lock()

TIMEZONE_OFFSETS = {
    'US/Pacific':-8,'US/Mountain':-7,'US/Central':-6,'US/Eastern':-5,
    'America/Los_Angeles':-8,'America/Denver':-7,'America/Chicago':-6,
    'America/New_York':-5,'America/Toronto':-5,'America/Nashville':-6,
    'Europe/London':0,'Europe/Paris':1,'Europe/Berlin':1,
    'Europe/Stockholm':1,'Europe/Amsterdam':1,'Europe/Madrid':1,
    'Europe/Rome':1,'Europe/Oslo':1,'Europe/Copenhagen':1,
    'Europe/Helsinki':2,'Europe/Athens':2,'Europe/Istanbul':3,
    'Europe/Moscow':3,'Asia/Dubai':4,'Asia/Mumbai':5.5,
    'Asia/Bangkok':7,'Asia/Singapore':8,'Asia/Shanghai':8,
    'Asia/Seoul':9,'Asia/Tokyo':9,'Asia/Hong_Kong':8,
    'Australia/Sydney':11,'Australia/Melbourne':11,
    'Pacific/Auckland':13,'Africa/Lagos':1,'Africa/Johannesburg':2,
    'America/Sao_Paulo':-3,'America/Mexico_City':-6,
    'America/Buenos_Aires':-3,'America/Bogota':-5,
}


# ==================== CSRF PROTECTION (Fix 2) ====================
# Public paths exempt from CSRF check
_CSRF_EXEMPT_PREFIXES = ('/submit', '/api/submit-song', '/api/submit-edit', '/api/submit-load/',
                          '/p/', '/api/play-log', '/api/public/', '/login', '/static/')

@app.before_request
def _csrf_check():
    """Validate CSRF token on state-changing requests from authenticated sessions."""
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return
    # Exempt public/unauthenticated paths
    for prefix in _CSRF_EXEMPT_PREFIXES:
        if request.path.startswith(prefix):
            return
    if not session.get('authenticated'):
        return
    token = request.headers.get('X-CSRF-Token', '')
    if not token or token != session.get('csrf_token', ''):
        return jsonify({'error': 'CSRF token missing or invalid'}), 403


# ==================== FORMULA INJECTION PROTECTION (Fix 3) ====================
_DANGEROUS_PREFIXES = ('=', '+', '-', '@', '\t', '\r', '\n')

def sanitize_cell(value):
    """Prefix dangerous characters with single quote to prevent formula injection in Sheets."""
    if not isinstance(value, str):
        return value
    if value and value[0] in _DANGEROUS_PREFIXES:
        return "'" + value
    return value

def sanitize_dict(data):
    """Apply sanitize_cell to all string values in a dict."""
    if not isinstance(data, dict):
        return data
    return {k: sanitize_cell(v) if isinstance(v, str) else v for k, v in data.items()}


# ==================== MULTI-SORT (Fix 1) ====================
def parse_sort_fields(args):
    """Parse sort0_field/sort0_dir, sort1_field/sort1_dir, etc. from request args.
    Falls back to legacy sort/dir params. Returns list of (field, direction) tuples."""
    fields = []
    for i in range(5):
        field = args.get(f'sort{i}_field', '').strip()
        direction = args.get(f'sort{i}_dir', 'asc').strip()
        if field:
            fields.append((field, direction))
    # Legacy fallback: single sort/dir
    if not fields:
        legacy_field = args.get('sort', '').strip()
        legacy_dir = args.get('dir', 'asc').strip()
        if legacy_field:
            fields.append((legacy_field, legacy_dir))
    return fields

def apply_multi_sort(indexed, headers, sort_fields):
    """Apply multi-level sort using stable sort from last priority to first.
    indexed = [(row_index, row_data), ...], sort_fields = [(field, dir), ...]"""
    if not sort_fields:
        return indexed
    # Resolve field names to column indices
    resolved = []
    for field_name, direction in sort_fields:
        col_idx = None
        for j, h in enumerate(headers):
            if h == field_name or cleanH(h) == field_name or cleanH(h).lower() == field_name.lower():
                col_idx = j
                break
        if col_idx is not None:
            resolved.append((col_idx, direction))
    if not resolved:
        return indexed
    # Stable sort: apply from last to first so first sort is primary
    result = list(indexed)
    for col_idx, direction in reversed(resolved):
        result.sort(
            key=lambda t: str(t[1][col_idx]).lower() if col_idx < len(t[1]) else '',
            reverse=(direction == 'desc')
        )
    return result


# ==================== RATE LIMITER CLEANUP (Fix 10) ====================
def _cleanup_thread_func():
    """Background thread: clean stale rate limiter entries, flush playlist views, purge expired edit tokens. Runs every 60s."""
    while True:
        time.sleep(60)
        # Clean rate limiter
        now = time.time()
        with _submit_lock:
            stale_ips = [ip for ip, times in _submit_times.items() if all(now - t > 3600 for t in times)]
            for ip in stale_ips:
                del _submit_times[ip]
        # Flush playlist views (Fix 11)
        _flush_playlist_views()
        # Purge expired edit tokens (Fix 8)
        with _edit_tokens_lock:
            expired = [k for k, v in _edit_tokens.items() if v.get('expires', 0) < now]
            for k in expired:
                del _edit_tokens[k]
            if expired:
                _save_edit_tokens()


# ==================== PLAYLIST VIEW BUFFERING (Fix 11) ====================
_playlist_views = {}  # {playlist_id: pending_increment}
_playlist_views_lock = threading.Lock()

def _buffer_playlist_view(pid):
    """Buffer a view increment. Flushed to Sheets every 60s."""
    with _playlist_views_lock:
        _playlist_views[pid] = _playlist_views.get(pid, 0) + 1

def _flush_playlist_views():
    """Write buffered view counts to Sheets."""
    with _playlist_views_lock:
        pending = dict(_playlist_views)
        _playlist_views.clear()
    if not pending:
        return
    try:
        data = sheets.get_all_rows('Playlists')
        if not data or len(data) < 2:
            return
        headers = data[0]
        rows = data[1:]
        id_col = find_col(headers, 'id')
        views_col = find_col(headers, 'views')
        if id_col is None or views_col is None:
            return
        for i, row in enumerate(rows):
            if id_col < len(row):
                pid = row[id_col]
                if pid in pending:
                    current = int(row[views_col]) if views_col < len(row) and row[views_col].strip().isdigit() else 0
                    sheets.update_cell('Playlists', i + 2, views_col + 1, str(current + pending[pid]))
    except Exception as e:
        logging.warning(f"Playlist view flush error: {e}")


def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated


_CLEAN_H_RE = re.compile(r'\[✓\]\s*|\[✗\]\s*|\[\?\?\]\s*|\[∅\]\s*|\[\s*✓\]\s*')
def cleanH(h):
    return _CLEAN_H_RE.sub('', h or '').strip()

def next_system_id():
    """Generate next universal System ID (RLN-XXXXX) across all tables. Thread-safe."""
    with _ID_LOCK:
        max_num = 0
        for table_name in ['Songs', 'Personnel', 'Invoices']:
            try:
                data = sheets.get_all_rows(table_name)
                if not data or len(data) < 2: continue
                headers = data[0]
                id_col = None
                for i, h in enumerate(headers):
                    hl = cleanH(h).lower()
                    if hl in ('airtable id', 'system id'): id_col = i; break
                if id_col is None: continue
                for row in data[1:]:
                    if id_col < len(row):
                        eid = str(row[id_col]).strip()
                        for prefix in ('RLN-', 'SON-', 'PER-'):
                            if eid.startswith(prefix):
                                try: max_num = max(max_num, int(eid[len(prefix):]))
                                except ValueError: pass
            except Exception as e:
                logging.warning(f"next_system_id scan {table_name}: {e}")
                continue
        if max_num == 0: max_num = 8000  # Start after existing Airtable records
        return f"RLN-{max_num + 1:05d}"

def apply_filter(rows, col_idx, op, val):
    vl = val.lower(); result = []
    for ri, r in rows:
        cell = str(r[col_idx]).lower().strip() if col_idx < len(r) else ''
        # Split cell into individual pipe-separated values for set-based ops
        cell_parts = [p.strip() for p in cell.split('|') if p.strip()]
        m = False
        if op == 'contains': m = vl in cell
        elif op == 'does_not_contain':
            vals = [v.strip() for v in vl.split(',') if v.strip()]
            if vals:
                m = not any(any(v in cp for cp in cell_parts) for v in vals)
            else:
                m = vl not in cell
        elif op == 'contains_any':
            vals = [v.strip() for v in vl.split(',') if v.strip()]
            m = any(any(v in cp or cp in v for cp in cell_parts) for v in vals)
        elif op == 'contains_all':
            vals = [v.strip() for v in vl.split(',') if v.strip()]
            m = all(any(v in cp for cp in cell_parts) for v in vals)
        elif op == 'is': m = cell == vl or vl in cell_parts
        elif op == 'is_not': m = cell != vl and vl not in cell_parts
        elif op == 'is_empty': m = cell == ''
        elif op == 'is_not_empty': m = cell != ''
        elif op == 'starts_with': m = cell.startswith(vl)
        elif op == 'ends_with': m = cell.endswith(vl)
        elif op in ('is_before', 'is_after', 'is_on_or_before', 'is_on_or_after'):
            # Date comparison
            try:
                from datetime import datetime as dt
                # Try common date formats
                cell_date = None
                for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y', '%d/%m/%Y', '%Y-%m-%dT%H:%M'):
                    try: cell_date = dt.strptime(cell, fmt); break
                    except Exception as e: pass
                val_date = None
                for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y'):
                    try: val_date = dt.strptime(vl, fmt); break
                    except Exception as e: pass
                if cell_date and val_date:
                    if op == 'is_before': m = cell_date < val_date
                    elif op == 'is_after': m = cell_date > val_date
                    elif op == 'is_on_or_before': m = cell_date <= val_date
                    elif op == 'is_on_or_after': m = cell_date >= val_date
            except Exception as e:
                logging.warning(f'Date filter comparison: {e}')
        else: m = vl in cell
        if m: result.append((ri, r))
    return result

def find_col(headers, *terms):
    for term in terms:
        tl = term.lower()
        for i, h in enumerate(headers):
            if tl == cleanH(h).lower(): return i
        for i, h in enumerate(headers):
            if tl in cleanH(h).lower(): return i
    return None

def gv(row, headers, *terms):
    idx = find_col(headers, *terms)
    if idx is not None and idx < len(row): return str(row[idx]).strip()
    return ''

def split_tags(val):
    if not val: return []
    tags = []
    for sep in [' | ', '|', ',']:
        if sep in val:
            for p in val.split(sep):
                p = p.strip()
                if p and p not in tags: tags.append(p)
            return tags
    val = val.strip()
    if val: tags.append(val)
    return tags

def record_undo(table, row_index, field, old_value, new_value):
    UNDO_STACK.append({'table':table,'row_index':row_index,'field':field,
        'old_value':old_value,'new_value':new_value,'timestamp':datetime.now().isoformat()})


# ==================== SOFT ARCHIVE (Data Protection) ====================
ARCHIVE_SHEET = 'Archive'
_archive_lock = threading.Lock()

def _ensure_archive_sheet():
    """Create Archive sheet if it doesn't exist."""
    try:
        data = sheets.get_all_rows(ARCHIVE_SHEET)
        if data:
            return True
    except Exception:
        pass
    try:
        sheets.create_new_sheet(ARCHIVE_SHEET)
        archive_headers = ['Archived From', 'Archived Date', 'Archived By', 'Original Row', 'Original Data JSON']
        sheets._retry(lambda: sheets.service.spreadsheets().values().update(
            spreadsheetId=sheets.spreadsheet_id, range=f"'{ARCHIVE_SHEET}'!A1",
            valueInputOption='USER_ENTERED', body={'values': [archive_headers]}
        ).execute())
        sheets._invalidate_cache(ARCHIVE_SHEET)
        return True
    except Exception as e:
        logging.warning(f"Archive sheet creation failed: {e}")
        return False

def _archive_rows(sheet_name, row_indices):
    """Soft-archive rows: copy to Archive sheet, then clear originals.
    Returns number of rows archived."""
    if not row_indices:
        return 0
    with _archive_lock:
        _ensure_archive_sheet()
        try:
            headers = sheets.get_headers(sheet_name)
            archived = 0
            now = datetime.now().strftime('%Y-%m-%d %H:%M')
            user = session.get('user_name', 'System') if has_request_context() else 'System'
            archive_rows = []
            for ri in sorted(row_indices):
                if ri < 2:
                    continue
                try:
                    row = sheets.get_row(sheet_name, ri)
                    # Build archive record: source sheet, date, user, original row#, full data as JSON
                    record_dict = {}
                    for j, h in enumerate(headers):
                        val = row[j] if j < len(row) else ''
                        record_dict[cleanH(h)] = val
                    archive_rows.append([
                        sheet_name, now, user, str(ri),
                        json.dumps(record_dict, ensure_ascii=False)
                    ])
                    archived += 1
                except Exception as e:
                    logging.warning(f"Archive read row {ri} from {sheet_name}: {e}")

            # Batch append to Archive
            if archive_rows:
                sheets.batch_append(ARCHIVE_SHEET, archive_rows)

            # Now clear the originals
            col_letter = sheets._col_to_letter(len(headers))
            for ri in sorted(row_indices, reverse=True):
                if ri < 2:
                    continue
                sheets._retry(lambda ri=ri: sheets.service.spreadsheets().values().clear(
                    spreadsheetId=sheets.spreadsheet_id,
                    range=f"'{sheet_name}'!A{ri}:{col_letter}{ri}").execute())
            sheets._invalidate_cache(sheet_name)
            logging.info(f"Soft-archived {archived} rows from {sheet_name} to Archive")
            return archived
        except Exception as e:
            logging.warning(f"Archive operation failed for {sheet_name}: {e}")
            return 0

def has_request_context():
    """Check if we're inside a Flask request context."""
    try:
        _ = request.method
        return True
    except RuntimeError:
        return False

def build_city_lookup():
    global CITY_LOOKUP
    try:
        per_data = sheets.get_all_rows('Personnel')
        if per_data and len(per_data) > 1:
            ph = per_data[0]; pr = per_data[1:]
            pcity_col = find_col(ph, 'city')
            pcountry_col = find_col(ph, 'countries', 'country')
            if pcity_col is not None and pcountry_col is not None:
                for row in pr:
                    if pcity_col < len(row) and pcountry_col < len(row):
                        cv = str(row[pcity_col]).strip()
                        co = str(row[pcountry_col]).strip()
                        if cv and co:
                            CITY_LOOKUP[cv.lower()] = {'country':co,'timezone':''}
        cities_data = sheets.get_all_rows('Cities')
        if cities_data and len(cities_data) > 1:
            ch = cities_data[0]; cr = cities_data[1:]
            nc = find_col(ch, 'name'); tc = find_col(ch, 'timezone')
            if nc is not None:
                for row in cr:
                    if nc < len(row):
                        cn = str(row[nc]).strip()
                        tz = str(row[tc]).strip() if tc and tc < len(row) else ''
                        if cn:
                            ex = CITY_LOOKUP.get(cn.lower(), {})
                            CITY_LOOKUP[cn.lower()] = {'country':ex.get('country',''),'timezone':tz}
    except Exception as e:
        logging.warning(f"City lookup failed: {e}")

def run_song_automations(ri, field, new_value, headers):
    results = []
    ch = cleanH(field).lower()

    # Artist/writer "Cut" tag rules: tag the song when an associated artist gets a release date
    # Each entry: (search terms in credits, tag to apply on songs)
    _CUT_ARTISTS = [
        (['ben wylen', 'benjamin schneid'], 'BW Cut'),
        (['emmma'], 'EMMMA Cut'),
        (['isa im', 'isabella m'], 'Isa IM Cut'),
    ]

    def _check_cut_tags(row, tag_col):
        """Check if any Cut artist tags should be applied based on credits + release date."""
        ct = str(row[tag_col]).strip() if tag_col < len(row) else ''
        existing_tags = split_tags(ct)
        sc_col = find_col(headers, 'songwriter credits')
        prod_col = find_col(headers, 'producer')
        art_col = find_col(headers, 'artist')
        credits_text = ''
        for col in [sc_col, prod_col, art_col]:
            if col is not None and col < len(row):
                credits_text += ' ' + str(row[col]).lower()
        rd_col = find_col(headers, 'release date')
        has_release = False
        if rd_col is not None and rd_col < len(row) and str(row[rd_col]).strip():
            has_release = True
        added = []
        for search_terms, tag_name in _CUT_ARTISTS:
            if tag_name in existing_tags:
                continue
            if any(term in credits_text for term in search_terms) and has_release:
                existing_tags.append(tag_name)
                added.append(tag_name)
        if added:
            sheets.update_cell('Songs', ri, tag_col + 1, ' | '.join(existing_tags))
            results.extend([f'Added {t} tag' for t in added])

    # When credits or release date change, check Cut tags
    if ch in ('songwriter credits', 'producer', 'artist', 'release date'):
        tc = find_col(headers, 'tag')
        if tc is not None:
            row = sheets.get_row('Songs', ri)
            _check_cut_tags(row, tc)

    # Auto-update Audio Status to "Released" when Release Date is in the past
    if ch == 'release date' and new_value and new_value.strip():
        try:
            from datetime import datetime as dt
            rd = None
            for fmt in ('%Y-%m-%d','%m/%d/%Y','%m/%d/%y','%d/%m/%Y'):
                try: rd = dt.strptime(new_value.strip(), fmt); break
                except ValueError: pass
            if rd and rd.date() <= dt.now().date():
                sc = find_col(headers, 'audio status')
                if sc is not None:
                    row = sheets.get_row('Songs', ri)
                    current_status = str(row[sc]).strip() if sc < len(row) else ''
                    if current_status.lower() not in ('released',):
                        sheets.update_cell('Songs', ri, sc + 1, 'Released')
                        results.append('Audio Status set to Released (release date is past)')
        except Exception as e:
            logging.warning(f"Release date auto-status: {e}")
    # Recording City -> auto-fill Recording Country
    if ch == 'recording city' and new_value and new_value.strip():
        ci = CITY_LOOKUP.get(new_value.lower().strip(), None)
        if ci and ci.get('country'):
            cc = find_col(headers, 'recording country', 'country')
            if cc is not None:
                sheets.update_cell('Songs', ri, cc + 1, ci['country'])
                results.append(f"Auto-filled Recording Country: {ci['country']}")
    # Modified By -> set to logged-in user's name
    mb_col = find_col(headers, 'modified by')
    if mb_col is not None:
        user_name = session.get('user_name', 'System')
        sheets.update_cell('Songs', ri, mb_col + 1, user_name)
    return results

def run_directory_automations(ri, field, new_value, headers, old_value=''):
    results = []; ch = cleanH(field).lower()
    if ch == 'email':
        tc = find_col(headers, 'tags')
        if tc is not None:
            row = sheets.get_row('Personnel', ri)
            ct = str(row[tc]).strip() if tc < len(row) else ''
            ex = split_tags(ct)
            if new_value and new_value.strip():
                if 'Need Email' in ex:
                    ex.remove('Need Email')
                    sheets.update_cell('Personnel', ri, tc + 1, ' | '.join(ex))
                    results.append('Removed Need Email tag')
            else:
                if 'Need Email' not in ex:
                    ex.append('Need Email')
                    sheets.update_cell('Personnel', ri, tc + 1, ' | '.join(ex))
                    results.append('Added Need Email tag')
    if ch == 'city':
        ci = CITY_LOOKUP.get(new_value.lower().strip(), None) if new_value else None
        if ci and ci.get('country'):
            cc = find_col(headers, 'countries', 'country')
            if cc is not None:
                sheets.update_cell('Personnel', ri, cc + 1, ci['country'])
                results.append(f"Auto-filled country: {ci['country']}")
    return results


# ==================== AUTH ====================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        pw = request.form.get('password', '')
        if pw == APP_PASSWORD:
            session['authenticated'] = True; session['role'] = 'admin'; session['user_name'] = 'Celina Rollon'; session.permanent = True
            session['csrf_token'] = secrets.token_urlsafe(32)
            return redirect(url_for('dashboard'))
        elif pw == ASSISTANT_PASSWORD:
            session['authenticated'] = True; session['role'] = 'assistant'; session['user_name'] = 'Assistant'; session.permanent = True
            session['csrf_token'] = secrets.token_urlsafe(32)
            return redirect(url_for('dashboard'))
        flash('Incorrect password', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    try: sc = sheets.get_row_count('Songs')
    except Exception as e:
        logging.warning(f"Dashboard song count failed: {e}"); sc = 0
    try: pc = sheets.get_row_count('Personnel')
    except Exception as e:
        logging.warning(f"Dashboard personnel count failed: {e}"); pc = 0
    return render_template('dashboard.html', song_count=sc, personnel_count=pc)

_dash_cache = {'data': None, 'time': 0}

@app.route('/api/dashboard-stats')
@login_required
def api_dashboard_stats():
    import time as _time
    if _dash_cache['data'] and (_time.time() - _dash_cache['time']) < 300:
        return jsonify(_dash_cache['data'])
    result = {}
    try:
        # Songs by audio status + extra metrics
        song_rows = sheets.get_all_rows('Songs')
        if song_rows:
            sh = song_rows[0]
            si = next((i for i,h in enumerate(sh) if 'audio status' in cleanH(h).lower()), None)
            ri = next((i for i,h in enumerate(sh) if 'release date' in cleanH(h).lower()), None)
            ti = next((i for i,h in enumerate(sh) if cleanH(h).lower() == 'title'), None)
            lm = next((i for i,h in enumerate(sh) if 'last modified' in cleanH(h).lower()), None)
            if si is not None:
                statuses = {}
                for r in song_rows[1:]:
                    v = r[si].strip() if si < len(r) and r[si] else '(none)'
                    statuses[v] = statuses.get(v, 0) + 1
                result['song_statuses'] = statuses
                result['released_count'] = statuses.get('Released', 0)
            # Upcoming releases (next 60 days)
            if ri is not None:
                from datetime import datetime as dt, timedelta
                now = dt.now(); upcoming = []
                for r in song_rows[1:]:
                    if ri < len(r) and r[ri]:
                        try:
                            rd = None
                            for fmt in ('%Y-%m-%d','%m/%d/%Y','%d/%m/%Y'):
                                try: rd = dt.strptime(r[ri].strip(), fmt); break
                                except Exception as e: pass
                            if rd and now <= rd <= now + timedelta(days=60):
                                title = r[ti].strip() if ti and ti < len(r) else 'Untitled'
                                upcoming.append({'title': title, 'date': rd.strftime('%b %d'), 'days': (rd - now).days})
                        except Exception as e:
                            logging.warning(f'Upcoming release parse: {e}')
                upcoming.sort(key=lambda x: x['days'])
                result['upcoming_releases'] = upcoming[:10]
            # Recently modified songs
            if lm is not None and ti is not None:
                recent_songs = []
                for r in song_rows[1:]:
                    if lm < len(r) and r[lm]:
                        title = r[ti].strip() if ti < len(r) else ''
                        if title: recent_songs.append({'title': title, 'modified': r[lm].strip()})
                recent_songs.sort(key=lambda x: x['modified'], reverse=True)
                result['recent_songs'] = recent_songs[:8]
        # Directory by field type + contacts needing email
        per_rows = sheets.get_all_rows('Personnel')
        if per_rows:
            ph = per_rows[0]
            fi = next((i for i,h in enumerate(ph) if cleanH(h).lower() == 'field'), None)
            ei = next((i for i,h in enumerate(ph) if cleanH(h).lower() == 'email'), None)
            tgi = next((i for i,h in enumerate(ph) if cleanH(h).lower() in ('tags','tag')), None)
            if fi is not None:
                fields = {}
                for r in per_rows[1:]:
                    vals = r[fi].strip().split('|') if fi < len(r) and r[fi] else ['(none)']
                    for v in vals:
                        v = v.strip() or '(none)'
                        fields[v] = fields.get(v, 0) + 1
                result['field_types'] = fields
            # Contacts needing email
            need_email = 0
            if tgi is not None:
                for r in per_rows[1:]:
                    tags = r[tgi].strip() if tgi < len(r) else ''
                    if 'Need Email' in tags: need_email += 1
            result['need_email_count'] = need_email
            result['total_contacts'] = len(per_rows) - 1
        # Recent activity from undo stack
        recent = []
        for item in reversed(list(UNDO_STACK)):
            ts = item.get('timestamp', '')
            time_str = ''
            if ts:
                try:
                    from datetime import datetime as dt
                    t = dt.fromisoformat(ts)
                    time_str = t.strftime('%H:%M')
                except Exception as e:
                    logging.warning(f'Activity timestamp parse: {e}')
            recent.append({
                'icon': '🎵' if item.get('table') == 'Songs' else '📇',
                'text': f"{cleanH(item.get('field',''))} updated",
                'time': time_str or 'recent'
            })
            if len(recent) >= 10: break
        result['recent_activity'] = recent
    except Exception as e:
        logging.warning(f"Dashboard stats error: {e}")
    _dash_cache['data'] = result
    _dash_cache['time'] = _time.time()
    return jsonify(result)

@app.route('/api/config')
@login_required
def api_config():
    return jsonify({'tag_colors': TAG_COLORS})


# ==================== SEARCH ====================
@app.route('/api/search-record')
@login_required
def api_search_record():
    q = request.args.get('q', '').strip()
    table_filter = request.args.get('table', '').strip()
    if len(q) < 1: return jsonify({'results': []})
    ql = q.lower()
    search_tables = [('Personnel','directory'),('Songs','songs'),
        ('MGMT Companies',None),('Record Labels',None),('Publishing Company',None),
        ('Agent',None),('Agency Company',None),('Studios',None),('Cities',None),
        ('Music Sup Company',None)]
    if table_filter:
        search_tables = [(t,r) for t,r in search_tables if t.lower()==table_filter.lower() or (r and r.lower()==table_filter.lower())]
    # Two-pass search: starts-with first, then contains
    starts_results = []; contains_results = []
    for table_name, route in search_tables:
        try:
            data = sheets.get_all_rows(table_name)
            if not data or len(data) < 2: continue
            headers = data[0]; rows = data[1:]
            nc = find_col(headers, 'name', 'title')
            if nc is None: continue
            for i, row in enumerate(rows):
                if nc < len(row):
                    val = str(row[nc]).strip()
                    if not val: continue
                    vl = val.lower()
                    if vl.startswith(ql) or any(w.startswith(ql) for w in vl.split()):
                        starts_results.append({'name':val,'table':table_name,'row_index':i+2,'route':route})
                    elif ql in vl:
                        contains_results.append({'name':val,'table':table_name,'row_index':i+2,'route':route})
        except Exception as e:
            logging.warning(f'Name search table scan: {e}')
            continue
    starts_results.sort(key=lambda r: (0 if r['name'].lower().startswith(ql) else 1, r['name'].lower()))
    contains_results.sort(key=lambda r: r['name'].lower())
    results = starts_results[:15]
    if len(results) < 15:
        results.extend(contains_results[:15-len(results)])
    return jsonify({'results': results})

@app.route('/api/table-record/<table_name>/<int:row_index>')
@login_required
def api_table_record(table_name, row_index):
    """Generic endpoint to read a record from any table with ID resolution."""
    try:
        data = sheets.get_all_rows(table_name)
        if not data or len(data) < 2:
            return jsonify({'error': 'Table empty or not found'}), 404
        headers = data[0]
        rows = data[1:]
        ri_offset = row_index - 2  # row_index is 2-based (header=1)
        if ri_offset < 0 or ri_offset >= len(rows):
            return jsonify({'error': 'Row not found'}), 404
        row = rows[ri_offset]
        rec = {'_row_index': row_index, '_table': table_name}
        for j, h in enumerate(headers):
            val = row[j] if j < len(row) else ''
            # Resolve Airtable IDs to names
            rec[h] = resolver.resolve_value(h, val)
        return jsonify(rec)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== AUTOCOMPLETE ====================
@app.route('/api/autocomplete/<table>/<field>')
@login_required
def api_autocomplete(table, field):
    q = request.args.get('q', '').strip().lower()
    limit = request.args.get('limit', 20, type=int)
    tmap = {'songs':'Songs','directory':'Personnel','personnel':'Personnel',
        'cities':'Cities','mgmt':'MGMT Companies','labels':'Record Labels',
        'publishers':'Publishing Company','agents':'Agent','studios':'Studios',
        'agencies':'Agency Company','invoices':'Invoices'}
    sn = tmap.get(table.lower(), table)
    try:
        data = sheets.get_all_rows(sn)
        if not data: return jsonify({'values': []})
        headers = data[0]; rows = data[1:]
        col = find_col(headers, field)
        if col is None: return jsonify({'values':[],'error':f'Field not found'})
        vals = set()
        for row in rows:
            if col < len(row):
                for t in split_tags(str(row[col])):
                    if t and not t.startswith('rec'): vals.add(t)
        filtered = [v for v in sorted(vals) if q in v.lower()] if q else sorted(vals)
        # Sort: starts-with first, then word-starts, then alphabetical
        if q:
            filtered.sort(key=lambda v: (0 if v.lower().startswith(q) else 1, 0 if any(w.startswith(q) for w in v.lower().split()) else 1, v.lower()))
        return jsonify({'values': filtered[:limit]})
    except Exception as e:
        return jsonify({'values':[],'error':str(e)})


@app.route('/api/quick-lookup')
@login_required
def api_quick_lookup():
    """Instant name-to-record lookup with peek data (field, city, email, last outreach)."""
    name = request.args.get('name', '').strip()
    if not name: return jsonify({'error': 'No name'}), 400
    with NAME_CACHE_LOCK:
        entry = NAME_CACHE.get(name.lower())
    if not entry:
        nl = name.lower()
        with NAME_CACHE_LOCK:
            for k, v in NAME_CACHE.items():
                if k == nl or nl in k:
                    entry = v; break
    if not entry:
        return jsonify({'error': 'Not found'}), 404
    result = dict(entry)
    result['found'] = True
    # Fetch additional peek data for Personnel
    if entry.get('table') == 'Personnel':
        try:
            row = sheets.get_row('Personnel', entry['row_index'])
            per_h = sheets.get_headers('Personnel')
            fc = find_col(per_h, 'field')
            cc = find_col(per_h, 'city')
            ec = find_col(per_h, 'email')
            lc = find_col(per_h, 'last outreach')
            if fc is not None and fc < len(row): result['field'] = row[fc].strip()
            if cc is not None and cc < len(row): result['city'] = row[cc].strip()
            if ec is not None and ec < len(row): result['email'] = row[ec].strip()
            if lc is not None and lc < len(row): result['last_outreach'] = row[lc].strip()
        except Exception as e:
            logging.warning(f'Personnel detail lookup: {e}')
    return jsonify(result)


# ==================== UNDO ====================
@app.route('/api/undo', methods=['POST'])
@login_required
def api_undo():
    if not UNDO_STACK: return jsonify({'error': 'Nothing to undo'})
    entry = UNDO_STACK.pop()
    try:
        headers = sheets.get_headers(entry['table'])
        field = entry['field']
        if field not in headers:
            ci_idx = find_col(headers, cleanH(field))
            if ci_idx is not None: field = headers[ci_idx]
            else: return jsonify({'error':'Field not found'})
        ci = headers.index(field) + 1
        sheets.update_cell(entry['table'], entry['row_index'], ci, str(entry['old_value']))
        return jsonify({'success':True,'field':cleanH(field),'restored':entry['old_value'],'remaining':len(UNDO_STACK)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/history/<table>/<int:row_index>')
@login_required
def api_record_history(table, row_index):
    """Get edit history for a specific record from undo stack."""
    sn = 'Songs' if 'song' in table.lower() else 'Personnel'
    edits = [e for e in reversed(list(UNDO_STACK)) if e['row_index'] == row_index and e['table'] == sn]
    return jsonify({'edits': edits[:20]})

@app.route('/api/duplicates')
@login_required
def api_duplicates():
    """Detect potential duplicate contacts by name or email."""
    try:
        data = sheets.get_all_rows('Personnel')
        if not data or len(data) < 2: return jsonify({'duplicates': []})
        headers = data[0]; rows = data[1:]
        nc = find_col(headers, 'name'); ec = find_col(headers, 'email')
        if nc is None: return jsonify({'duplicates': []})
        # Group by normalized name
        name_groups = {}
        email_groups = {}
        for i, row in enumerate(rows):
            name = row[nc].strip().lower() if nc < len(row) else ''
            email = row[ec].strip().lower() if ec is not None and ec < len(row) else ''
            if name:
                key = ' '.join(sorted(name.split()))  # normalize word order
                name_groups.setdefault(key, []).append({'row': i+2, 'name': row[nc].strip(), 'email': email})
            if email:
                email_groups.setdefault(email, []).append({'row': i+2, 'name': row[nc].strip() if nc < len(row) else '', 'email': email})
        dupes = []
        seen = set()
        for key, entries in name_groups.items():
            if len(entries) > 1:
                ids = tuple(sorted(e['row'] for e in entries))
                if ids not in seen:
                    seen.add(ids)
                    dupes.append({'type': 'name', 'match': entries[0]['name'], 'records': entries})
        for key, entries in email_groups.items():
            if len(entries) > 1:
                ids = tuple(sorted(e['row'] for e in entries))
                if ids not in seen:
                    seen.add(ids)
                    dupes.append({'type': 'email', 'match': key, 'records': entries})
        return jsonify({'duplicates': dupes[:50], 'total': len(dupes)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== CITY SEARCH ====================
@app.route('/api/cities/search')
@login_required
def api_cities_search():
    """Dedicated city autocomplete from Cities table and Personnel city data."""
    q = request.args.get('q', '').strip().lower()
    if len(q) < 1: return jsonify({'results': []})
    results = []
    # Search Cities table first
    try:
        data = sheets.get_all_rows('Cities')
        if data and len(data) > 1:
            headers = data[0]; rows = data[1:]
            nc = find_col(headers, 'name')
            if nc is not None:
                for row in rows:
                    if nc < len(row):
                        name = str(row[nc]).strip()
                        if name and q in name.lower():
                            info = CITY_LOOKUP.get(name.lower(), {})
                            results.append({'name': name, 'country': info.get('country', ''), 'timezone': info.get('timezone', '')})
    except Exception as e:
        logging.warning(f'City search: {e}')
    # Also search from Personnel cities
    for city_name, info in CITY_LOOKUP.items():
        if q in city_name and not any(r['name'].lower() == city_name for r in results):
            results.append({'name': city_name.title(), 'country': info.get('country', ''), 'timezone': info.get('timezone', '')})
    results.sort(key=lambda r: (0 if r['name'].lower().startswith(q) else 1, r['name']))
    return jsonify({'results': results[:20]})


# ==================== SOFT ARCHIVE (replaces hard delete) ====================
@app.route('/api/bulk-delete', methods=['POST'])
@login_required
def api_bulk_delete():
    """Soft-archive rows: copies to Archive sheet, then clears originals."""
    d = request.json
    table = d.get('table', 'Personnel')
    row_indices = d.get('row_indices', [])
    hard_delete = d.get('hard_delete', False)  # Only if Captain typed DELETE
    if not row_indices: return jsonify({'error': 'No rows selected'}), 400
    sn = 'Songs' if table.lower() == 'songs' else ('Invoices' if table.lower() == 'invoices' else 'Personnel')
    try:
        if hard_delete and session.get('role') == 'admin':
            # Captain explicitly confirmed hard delete
            headers = sheets.get_headers(sn)
            col_letter = sheets._col_to_letter(len(headers))
            for ri in sorted(row_indices, reverse=True):
                if ri < 2: continue
                sheets._retry(lambda ri=ri: sheets.service.spreadsheets().values().clear(
                    spreadsheetId=sheets.spreadsheet_id,
                    range=f"'{sn}'!A{ri}:{col_letter}{ri}").execute())
            sheets._invalidate_cache(sn)
            return jsonify({'success': True, 'deleted': len(row_indices), 'method': 'hard_delete'})
        else:
            # Default: soft archive
            archived = _archive_rows(sn, row_indices)
            return jsonify({'success': True, 'deleted': archived, 'method': 'archived'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== SONGS ====================
@app.route('/songs')
@login_required
def songs(): return render_template('songs.html')

@app.route('/calendar')
@login_required
def calendar_view(): return render_template('calendar.html')

@app.route('/search')
@login_required
def search_page(): return render_template('search.html')

@app.route('/api/songs')
@login_required
def api_songs():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    search = request.args.get('search', '').strip()
    group_by = request.args.get('group', '').strip()
    adv_filters = []
    for i in range(20):
        col = request.args.get(f'f{i}_col', '').strip()
        op = request.args.get(f'f{i}_op', 'contains').strip()
        val = request.args.get(f'f{i}_val', '').strip()
        if col: adv_filters.append({'col':col,'op':op,'val':val})
    filter_mode = request.args.get('filter_mode', 'and').lower()  # 'and' or 'or'
    sort_fields = parse_sort_fields(request.args)
    try:
        data = sheets.get_all_rows('Songs')
        headers = data[0] if data else []; raw = data[1:] if len(data)>1 else []
        rows = [(i+2, r) for i, r in enumerate(raw)]
        if search:
            sl = search.lower()
            rows = [(ri,r) for ri,r in rows if any(sl in str(c).lower() for c in r)]
        if adv_filters:
            if filter_mode == 'or':
                # OR: union of all filter matches
                all_rows = rows; matched = set()
                for f in adv_filters:
                    ci = None
                    for j,h in enumerate(headers):
                        if cleanH(h).lower()==f['col'].lower() or f['col'].lower() in cleanH(h).lower():
                            ci=j; break
                    if ci is None: continue
                    for ri, r in all_rows:
                        if ri not in matched:
                            filtered = apply_filter([(ri, r)], ci, f['op'], f['val'])
                            if filtered: matched.add(ri)
                rows = [(ri, r) for ri, r in all_rows if ri in matched]
            else:
                # AND: sequential narrowing (default)
                for f in adv_filters:
                    ci = None
                    for j,h in enumerate(headers):
                        if cleanH(h).lower()==f['col'].lower() or f['col'].lower() in cleanH(h).lower():
                            ci=j; break
                    if ci is None: continue
                    rows = apply_filter(rows, ci, f['op'], f['val'])
        if sort_fields:
            rows = apply_multi_sort(rows, headers, sort_fields)
        groups = None
        if group_by:
            gi = None
            for j,h in enumerate(headers):
                if cleanH(h).lower()==group_by.lower(): gi=j; break
            if gi is not None:
                gm = {}
                for ri,r in rows:
                    gv_val = str(r[gi]).strip() if gi<len(r) else ''
                    gk = gv_val if gv_val else '(empty)'
                    gm.setdefault(gk, []).append((ri,r))
                groups = {k:len(v) for k,v in gm.items()}
        total = len(rows); tp = max(1,math.ceil(total/per_page))
        start = (page-1)*per_page; page_rows = rows[start:start+per_page]
        records = []
        for ori, row in page_rows:
            rec = {'_row_index':ori}
            for j,h in enumerate(headers):
                val = row[j] if j<len(row) else ''
                rec[h] = resolver.resolve_value(h, val)
            records.append(rec)
        result = {'headers':headers,'records':records,'page':page,'per_page':per_page,'total':total,'total_pages':tp}
        if groups: result['groups'] = groups
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/songs/update', methods=['POST'])
@login_required
def api_songs_update():
    d = request.json
    if not d or 'field' not in d or 'row_index' not in d or 'value' not in d:
        return jsonify({'error':'Missing required fields'}), 400
    ri = d['row_index']
    if not isinstance(ri, int) or ri < 2: return jsonify({'error':'Invalid row index'}), 400
    try:
        headers = sheets.get_headers('Songs')
        field = d['field']
        if field not in headers:
            # Fallback: try partial match
            ci = find_col(headers, cleanH(field))
            if ci is not None:
                field = headers[ci]
            else:
                return jsonify({'error':'Field not found'}), 400
        ci = headers.index(field)
        old_row = sheets.get_row('Songs', ri)
        old_val = old_row[ci] if ci < len(old_row) else ''
        # Batch: field value + Last Modified in single API call
        batch = [(ri, ci+1, str(d['value']))]
        lm_col = find_col(headers, 'last modified')
        if lm_col is not None and cleanH(field).lower() != 'last modified':
            now = datetime.now().strftime('%Y-%m-%d %H:%M')
            batch.append((ri, lm_col+1, now))
        mb_col = find_col(headers, 'modified by')
        if mb_col is not None:
            batch.append((ri, mb_col+1, session.get('user_name', 'System')))
        sheets.batch_update_cells('Songs', batch)
        record_undo('Songs', ri, field, old_val, d['value'])
        autos = run_song_automations(ri, field, d['value'], headers)
        # Auto-regenerate lyric doc when lyrics change
        if cleanH(field).lower() == 'lyrics' and d['value'].strip():
            try:
                generate_lyric_doc(sheets, 'Songs', ri, headers)
            except Exception as le:
                logging.warning(f"Lyric doc regen failed for row {ri}: {le}")
        return jsonify({'success':True,'automations':autos})
    except Exception as e:
        logging.exception('Songs update failed')
        return jsonify({'error': str(e)}), 500

@app.route('/api/songs/<int:row_index>/lyric-doc')
@login_required
def api_song_lyric_doc(row_index):
    """Generate or serve the lyric doc PDF for a song."""
    try:
        headers = sheets.get_headers('Songs')
        row = sheets.get_row('Songs', row_index)
        record = {}
        for j, h in enumerate(headers):
            record[h] = row[j] if j < len(row) else ''
        from modules.lyric_doc import generate_from_record
        url = generate_from_record(record, headers)
        if url:
            # Update the Lyric Doc field
            ld_col = find_col(headers, 'lyric doc', 'lyric docs', 'lyrics docs')
            if ld_col is not None:
                sheets.update_cell('Songs', row_index, ld_col + 1, url)
            filename = os.path.basename(url)
            docs_dir = os.path.join(app.static_folder, 'lyric_docs')
            return send_from_directory(docs_dir, filename, as_attachment=True,
                                       download_name=filename)
        return jsonify({'error': 'No lyrics found for this song'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/songs/<int:row_index>')
@login_required
def api_song_detail(row_index):
    try:
        headers = sheets.get_headers('Songs')
        row = sheets.get_row('Songs', row_index)
        rec = {'_row_index':row_index}
        for j,h in enumerate(headers):
            val = row[j] if j<len(row) else ''
            rec[h] = resolver.resolve_value(h, val)
        # Lookup fields: pull data from Personnel based on Songwriter Credits
        rec = resolve_song_lookups(rec, headers)
        return jsonify(rec)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def resolve_song_lookups(rec, headers):
    """Auto-populate lookup fields from linked Personnel records."""
    # Find songwriter names
    sw_col = None
    for h in headers:
        if 'songwriter credit' in cleanH(h).lower(): sw_col = h; break
    if not sw_col or not rec.get(sw_col): return rec
    writer_names = [w.strip() for w in rec[sw_col].split('|') if w.strip()]
    if not writer_names: return rec
    # Load personnel data once
    try:
        per_data = sheets.get_all_rows('Personnel')
        if not per_data or len(per_data) < 2: return rec
        ph = per_data[0]; pr = per_data[1:]
        nc = find_col(ph, 'name')
        if nc is None: return rec
        # Build lookup: name -> {field: value}
        LOOKUP_MAP = {
            'writer ipi': ['ipi', 'writer ipi', 'ipi number'],
            'pub ipi': ['pub ipi', 'publisher ipi'],
            'pro': ['pro'],
            'publishing company': ['publishing company', 'publisher'],
        }
        # Find column indices in Personnel for each lookup target
        per_cols = {}
        for lookup_name, search_terms in LOOKUP_MAP.items():
            for term in search_terms:
                idx = find_col(ph, term)
                if idx is not None:
                    per_cols[lookup_name] = idx; break
        # For each songwriter, pull their data
        lookups = {k: [] for k in LOOKUP_MAP}
        for wname in writer_names:
            wl = wname.lower().strip()
            for row in pr:
                if nc < len(row) and row[nc].strip().lower() == wl:
                    for lookup_name, col_idx in per_cols.items():
                        val = row[col_idx].strip() if col_idx < len(row) else ''
                        if val:
                            lookups[lookup_name].append(f"{wname}: {val}")
                    break
        # Write lookup values into the record (only if the song field is empty or has rec IDs)
        for lookup_name, values in lookups.items():
            if not values: continue
            # Find the matching song header
            song_h = None
            for h in headers:
                if cleanH(h).lower() == lookup_name or lookup_name in cleanH(h).lower():
                    song_h = h; break
            if song_h:
                current = rec.get(song_h, '').strip()
                # Auto-fill if empty or contains only Airtable rec IDs
                if not current or current.startswith('rec') or all(p.strip().startswith('rec') for p in current.split('|')):
                    rec[song_h] = ' | '.join(values)
                # Also add as a _lookup field for display
                rec[f'_lookup_{lookup_name}'] = ' | '.join(values)
    except Exception as e:
        logging.warning(f"Lookup resolution failed: {e}")
    return rec

@app.route('/api/songs/tags')
@login_required
def api_songs_tags():
    try:
        data = sheets.get_all_rows('Songs')
        headers = data[0] if data else []; rows = data[1:]
        tc = find_col(headers,'tag','tags'); sc = find_col(headers,'audio status'); pc = find_col(headers,'project')
        tags,statuses,projects = set(),set(),set()
        for row in rows:
            if tc is not None and tc<len(row):
                raw = str(row[tc])
                resolved = resolver.resolve_value('tags', raw) if resolver else raw
                for t in split_tags(resolved):
                    if t and not t.startswith('rec') and not t.isdigit() and len(t) > 1: tags.add(t)
            if sc is not None and sc<len(row):
                v=str(row[sc]).strip()
                if v and not v.startswith('rec') and not v.isdigit(): statuses.add(v)
            if pc is not None and pc<len(row):
                raw = str(row[pc])
                resolved = resolver.resolve_value('project', raw) if resolver else raw
                for t in split_tags(resolved):
                    if t and not t.startswith('rec') and not t.isdigit() and len(t) > 1: projects.add(t)
        all_cols = [cleanH(h) for h in headers if cleanH(h).lower() not in ['airtable id','system id']]
        return jsonify({'tags':sorted(tags),'statuses':sorted(statuses),'projects':sorted(projects),'columns':all_cols})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/songs/new', methods=['POST'])
@login_required
def api_songs_new():
    d = request.json
    try:
        headers = sheets.get_headers('Songs')
        row = ['']*len(headers)
        for key,value in d.items():
            col = find_col(headers, key)
            if col is not None: row[col] = value
        # Auto-generate System ID
        id_col = find_col(headers, 'airtable id', 'system id')
        if id_col is not None:
            row[id_col] = next_system_id()
        # Auto-set Modified By
        mb_col = find_col(headers, 'modified by')
        if mb_col is not None: row[mb_col] = session.get('user_name', 'System')
        # Auto-set Last Modified
        lm_col = find_col(headers, 'last modified')
        if lm_col is not None:
            from datetime import datetime
            row[lm_col] = datetime.now().strftime('%Y-%m-%d %H:%M')
        sheets.append_row('Songs', row)
        return jsonify({'success':True,'id':row[id_col] if id_col is not None else ''})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/backfill-ids', methods=['POST'])
@admin_required
def api_backfill_ids():
    """Backfill missing System IDs across all tables."""
    fixed = 0
    for table_name in ['Songs', 'Personnel', 'Invoices']:
        try:
            data = sheets.get_all_rows(table_name)
            if not data or len(data) < 2: continue
            headers = data[0]
            id_col = None
            for i, h in enumerate(headers):
                hl = cleanH(h).lower()
                if hl in ('airtable id', 'system id'): id_col = i; break
            if id_col is None: continue
            for ri, row in enumerate(data[1:], start=2):
                cell = str(row[id_col]).strip() if id_col < len(row) else ''
                is_valid = any(cell.startswith(p) for p in ('RLN-', 'SON-', 'PER-', 'rec'))
                if not is_valid or not cell:
                    new_id = next_system_id()
                    sheets.update_cell(table_name, ri, id_col + 1, new_id)
                    logging.info(f"Backfill ID: {table_name} row {ri} '{cell}' -> {new_id}")
                    fixed += 1
        except Exception as e:
            logging.warning(f"Backfill IDs {table_name}: {e}")
    return jsonify({'success': True, 'fixed': fixed})

@app.route('/api/fix-airtable-links', methods=['POST'])
@admin_required
def api_fix_airtable_links():
    """Scan for Airtable URLs in Lyric Doc fields and report/replace them.
    POST body: {"dry_run": true} to just scan, or {"replacements": {"old_url": "new_url"}} to fix."""
    d = request.json or {}
    dry_run = d.get('dry_run', True)
    replacements = d.get('replacements', {})
    found = []
    fixed = 0
    try:
        data = sheets.get_all_rows('Songs')
        if not data or len(data) < 2:
            return jsonify({'found': [], 'fixed': 0})
        headers = data[0]
        ld_col = find_col(headers, 'lyric doc', 'lyric docs', 'lyrics docs')
        title_col = find_col(headers, 'title')
        if ld_col is None:
            return jsonify({'error': 'No Lyric Doc column found'}), 404
        for ri, row in enumerate(data[1:], start=2):
            cell = str(row[ld_col]).strip() if ld_col < len(row) else ''
            if not cell: continue
            if 'airtable.com' in cell.lower() or cell.startswith('rec'):
                title = str(row[title_col]).strip() if title_col is not None and title_col < len(row) else ''
                entry = {'row': ri, 'title': title, 'current_url': cell}
                if not dry_run and cell in replacements:
                    new_url = replacements[cell]
                    sheets.update_cell('Songs', ri, ld_col + 1, new_url)
                    entry['new_url'] = new_url
                    fixed += 1
                found.append(entry)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'found': found, 'fixed': fixed, 'total_airtable_links': len(found)})

@app.route('/api/songs/import', methods=['POST'])
@login_required
def api_songs_import():
    d = request.json
    csv_headers = d.get('headers', [])
    csv_rows = d.get('rows', [])
    if not csv_headers or not csv_rows:
        return jsonify({'error': 'No data to import'}), 400
    try:
        sheet_headers = sheets.get_headers('Songs')
        col_map = {}
        for ci, ch in enumerate(csv_headers):
            si = find_col(sheet_headers, ch.strip())
            if si is not None: col_map[ci] = si
        if not col_map:
            return jsonify({'error': 'No matching columns found. Check that CSV headers match sheet column names.'}), 400
        # Build all rows first, then batch write
        batch_rows = []
        for csv_row in csv_rows:
            row = [''] * len(sheet_headers)
            for ci, si in col_map.items():
                if ci < len(csv_row): row[si] = str(csv_row[ci]).strip()
            if not any(cell for cell in row): continue
            batch_rows.append(row)
        if not batch_rows:
            return jsonify({'error': 'No valid rows to import'}), 400
        # Get current row count to know where to start writing
        sheets.batch_append('Songs', batch_rows)
        return jsonify({'success': True, 'imported': len(batch_rows), 'columns_matched': len(col_map), 'columns_total': len(csv_headers)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== DIRECTORY ====================
@app.route('/directory')
@login_required
def directory(): return render_template('directory.html')

@app.route('/api/directory')
@login_required
def api_directory():
    page = request.args.get('page',1,type=int)
    per_page = request.args.get('per_page',50,type=int)
    search = request.args.get('search','').strip()
    group_by = request.args.get('group','').strip()
    adv_filters = []
    for i in range(20):
        col=request.args.get(f'f{i}_col','').strip()
        op=request.args.get(f'f{i}_op','contains').strip()
        val=request.args.get(f'f{i}_val','').strip()
        if col: adv_filters.append({'col':col,'op':op,'val':val})
    filter_mode = request.args.get('filter_mode', 'and').lower()
    sort_fields = parse_sort_fields(request.args)
    try:
        data = sheets.get_all_rows('Personnel')
        headers = data[0] if data else []; raw = data[1:]
        rows = [(i+2,r) for i,r in enumerate(raw)]
        if search:
            sl=search.lower()
            rows=[(ri,r) for ri,r in rows if any(sl in str(c).lower() for c in r)]
        if adv_filters:
            if filter_mode == 'or':
                all_rows = rows; matched = set()
                for f in adv_filters:
                    ci=None
                    for j,h in enumerate(headers):
                        if cleanH(h).lower()==f['col'].lower() or f['col'].lower() in cleanH(h).lower():
                            ci=j; break
                    if ci is None: continue
                    for ri, r in all_rows:
                        if ri not in matched:
                            filtered = apply_filter([(ri, r)], ci, f['op'], f['val'])
                            if filtered: matched.add(ri)
                rows = [(ri, r) for ri, r in all_rows if ri in matched]
            else:
                for f in adv_filters:
                    ci=None
                    for j,h in enumerate(headers):
                        if cleanH(h).lower()==f['col'].lower() or f['col'].lower() in cleanH(h).lower():
                            ci=j; break
                    if ci is None: continue
                    rows = apply_filter(rows, ci, f['op'], f['val'])
        if sort_fields:
            rows = apply_multi_sort(rows, headers, sort_fields)
        groups=None
        if group_by:
            gi=None
            for j,h in enumerate(headers):
                if cleanH(h).lower()==group_by.lower(): gi=j; break
            if gi is not None:
                gm={}
                for ri,r in rows:
                    gk=str(r[gi]).strip() if gi<len(r) else ''; gk=gk if gk else '(empty)'
                    gm.setdefault(gk,[]).append((ri,r))
                groups={k:len(v) for k,v in gm.items()}
        total=len(rows); tp=max(1,math.ceil(total/per_page))
        start=(page-1)*per_page; page_rows=rows[start:start+per_page]
        records=[]
        for ori,row in page_rows:
            rec={'_row_index':ori}
            for j,h in enumerate(headers):
                val=row[j] if j<len(row) else ''
                rec[h]=resolver.resolve_value(h, val)
            records.append(rec)
        result={'headers':headers,'records':records,'page':page,'per_page':per_page,'total':total,'total_pages':tp}
        if groups: result['groups']=groups
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/directory/<int:row_index>')
@login_required
def api_person_detail(row_index):
    try:
        headers=sheets.get_headers('Personnel')
        row=sheets.get_row('Personnel',row_index)
        rec={'_row_index':row_index}
        for j,h in enumerate(headers):
            val=row[j] if j<len(row) else ''
            rec[h]=resolver.resolve_value(h, val)
        return jsonify(rec)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/directory/update', methods=['POST'])
@login_required
def api_directory_update():
    d=request.json
    if not d or 'field' not in d or 'row_index' not in d or 'value' not in d:
        return jsonify({'error':'Missing fields'}), 400
    ri=d['row_index']
    if not isinstance(ri,int) or ri<2: return jsonify({'error':'Invalid row'}), 400
    try:
        headers=sheets.get_headers('Personnel')
        field=d['field']
        if field not in headers:
            ci = find_col(headers, cleanH(field))
            if ci is not None:
                field = headers[ci]
            else:
                return jsonify({'error':'Field not found'}), 400
        ci=headers.index(field)
        old_row=sheets.get_row('Personnel',ri)
        old_val=old_row[ci] if ci<len(old_row) else ''
        sheets.update_cell('Personnel',ri,ci+1,str(d['value']))
        record_undo('Personnel',ri,field,old_val,d['value'])
        # Auto-update Last Modified
        lm_col = find_col(headers, 'last modified')
        if lm_col is not None and cleanH(field).lower() != 'last modified':
            from datetime import datetime
            now = datetime.now().strftime('%Y-%m-%d %H:%M')
            sheets.update_cell('Personnel', ri, lm_col+1, now)
        # Modified By
        mb_col = find_col(headers, 'modified by')
        if mb_col is not None:
            user_name = session.get('user_name', 'System')
            sheets.update_cell('Personnel', ri, mb_col + 1, user_name)
        autos=run_directory_automations(ri,field,d['value'],headers,old_val)
        return jsonify({'success':True,'automations':autos})
    except Exception as e:
        logging.exception('Directory update failed')
        return jsonify({'error': str(e)}), 500

@app.route('/api/directory/tags')
@login_required
def api_directory_tags():
    try:
        data=sheets.get_all_rows('Personnel')
        headers=data[0] if data else []; rows=data[1:]
        def collect(cn):
            vals=set(); idx=find_col(headers,cn)
            if idx is None: return sorted(vals)
            for row in rows:
                if idx<len(row):
                    raw = str(row[idx])
                    resolved = resolver.resolve_value(cn, raw) if resolver else raw
                    for t in split_tags(resolved):
                        # Skip Airtable IDs and pure numeric values
                        if t and not t.startswith('rec') and not t.isdigit() and len(t) > 1:
                            vals.add(t)
            return sorted(vals)
        all_cols=[cleanH(h) for h in headers if cleanH(h).lower() not in ['airtable id','system id']]
        return jsonify({'tags':collect('tags'),'cities':collect('city'),
            'fields':collect('field'),'genres':collect('genre'),
            'countries':collect('countries'),'pros':collect('pro'),
            'labels':collect('record label'),'columns':all_cols})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/directory/search-name')
@login_required
def api_directory_search_name():
    q=request.args.get('q','').strip().lower()
    if len(q)<2: return jsonify({'results':[]})
    try:
        data=sheets.get_all_rows('Personnel')
        headers=data[0] if data else []; rows=data[1:]
        nc=find_col(headers,'name'); results=[]
        if nc is not None:
            for i,row in enumerate(rows):
                if nc<len(row):
                    n=str(row[nc]).strip()
                    if q in n.lower():
                        results.append({'name':n,'row_index':i+2})
                        if len(results)>=20: break
        return jsonify({'results':results})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/directory/new', methods=['POST'])
@login_required
def api_directory_new():
    d=request.json
    try:
        headers=sheets.get_headers('Personnel')
        row=['']*len(headers)
        for key,value in d.items():
            col=find_col(headers,key)
            if col is not None: row[col]=value
        ec=find_col(headers,'email'); tc=find_col(headers,'tags')
        if ec is not None and tc is not None and not row[ec]:
            ex=split_tags(row[tc])
            if 'Need Email' not in ex: ex.append('Need Email'); row[tc]=' | '.join(ex)
        # Auto-generate System ID
        id_col = find_col(headers, 'airtable id', 'system id')
        if id_col is not None:
            row[id_col] = next_system_id()
        # Auto-set Modified By + Last Modified
        mb_col = find_col(headers, 'modified by')
        if mb_col is not None: row[mb_col] = session.get('user_name', 'System')
        lm_col = find_col(headers, 'last modified')
        if lm_col is not None:
            from datetime import datetime
            row[lm_col] = datetime.now().strftime('%Y-%m-%d %H:%M')
        sheets.append_row('Personnel',row)
        return jsonify({'success':True,'id':row[id_col] if id_col is not None else ''})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/directory/import', methods=['POST'])
@login_required
def api_directory_import():
    d = request.json
    csv_headers = d.get('headers', [])
    csv_rows = d.get('rows', [])
    if not csv_headers or not csv_rows:
        return jsonify({'error': 'No data to import'}), 400
    try:
        sheet_headers = sheets.get_headers('Personnel')
        col_map = {}
        for ci, ch in enumerate(csv_headers):
            si = find_col(sheet_headers, ch.strip())
            if si is not None: col_map[ci] = si
        if not col_map:
            return jsonify({'error': 'No matching columns found. Check CSV headers.'}), 400
        ec = find_col(sheet_headers, 'email')
        tc = find_col(sheet_headers, 'tags')
        batch_rows = []
        for csv_row in csv_rows:
            row = [''] * len(sheet_headers)
            for ci, si in col_map.items():
                if ci < len(csv_row): row[si] = str(csv_row[ci]).strip()
            if not any(cell for cell in row): continue
            if ec is not None and tc is not None and not row[ec]:
                ex = split_tags(row[tc])
                if 'Need Email' not in ex: ex.append('Need Email'); row[tc] = ' | '.join(ex)
            batch_rows.append(row)
        if not batch_rows:
            return jsonify({'error': 'No valid rows to import'}), 400
        sheets.batch_append('Personnel', batch_rows)
        return jsonify({'success': True, 'imported': len(batch_rows), 'columns_matched': len(col_map)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== BULK ====================
@app.route('/api/bulk-update', methods=['POST'])
@login_required
def api_bulk_update():
    d=request.json; table=d.get('table','Personnel'); row_indices=d.get('row_indices',[])
    action=d.get('action',''); field=d.get('field','').strip(); value=d.get('value','').strip()
    if not row_indices: return jsonify({'error':'No rows'}),400
    sn='Songs' if table.lower()=='songs' else 'Personnel'
    try:
        headers=sheets.get_headers(sn); updated=0
        if action in ('add_tag','remove_tag'):
            tc=find_col(headers,'tags','tag')
            if tc is None: return jsonify({'error':'Tags not found'}),400
            for ri in row_indices:
                row=sheets.get_row(sn,ri)
                ct=str(row[tc]).strip() if tc<len(row) else ''
                ex=[t.strip() for t in ct.split(' | ') if t.strip()] if ct else []
                ov=ct
                if action=='add_tag' and value not in ex: ex.append(value); updated+=1
                elif action=='remove_tag' and value in ex: ex.remove(value); updated+=1
                nv=' | '.join(ex); sheets.update_cell(sn,ri,tc+1,nv)
                record_undo(sn,ri,headers[tc],ov,nv)
        elif action=='set_field':
            col=find_col(headers,field)
            if col is None: return jsonify({'error':'Field not found'}),400
            # Batch all updates into one API call
            batch=[]
            for ri in row_indices:
                row=sheets.get_row(sn,ri)
                ov=str(row[col]).strip() if col<len(row) else ''
                batch.append((ri, col+1, value))
                record_undo(sn,ri,headers[col],ov,value); updated+=1
            if batch: sheets.batch_update_cells(sn, batch)
        elif action=='add_to_field':
            col=find_col(headers,field)
            if col is None: return jsonify({'error':'Field not found'}),400
            for ri in row_indices:
                row=sheets.get_row(sn,ri)
                ct=str(row[col]).strip() if col<len(row) else ''
                ex=[t.strip() for t in ct.split(' | ') if t.strip()] if ct else []
                ov=ct
                if value not in ex:
                    ex.append(value); nv=' | '.join(ex)
                    sheets.update_cell(sn,ri,col+1,nv)
                    record_undo(sn,ri,headers[col],ov,nv); updated+=1
        elif action=='remove_from_field':
            col=find_col(headers,field)
            if col is None: return jsonify({'error':'Field not found'}),400
            for ri in row_indices:
                row=sheets.get_row(sn,ri)
                ct=str(row[col]).strip() if col<len(row) else ''
                ex=[t.strip() for t in ct.split(' | ') if t.strip()] if ct else []
                ov=ct
                if value in ex:
                    ex.remove(value); nv=' | '.join(ex)
                    sheets.update_cell(sn,ri,col+1,nv)
                    record_undo(sn,ri,headers[col],ov,nv); updated+=1
        return jsonify({'success':True,'updated':updated})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/directory/bulk-tag', methods=['POST'])
@login_required
def api_directory_bulk_tag():
    d=request.json; d['table']='Personnel'
    d['action']='add_tag' if d.get('action','add')=='add' else 'remove_tag'
    d['value']=d.get('tag','')
    return api_bulk_update()


# ==================== WORKS WITH ====================
@app.route('/api/automate/works-with', methods=['POST'])
@login_required
def api_works_with():
    d=request.json; mri=d.get('master_row_index'); lnames=d.get('linked_names',[])
    if not mri or not lnames: return jsonify({'error':'Master row and names required'}),400
    try:
        headers=sheets.get_headers('Personnel')
        wwc=find_col(headers,'works with'); ec=find_col(headers,'email'); nc=find_col(headers,'name')
        cec=find_col(headers,'emails combined'); cnc=find_col(headers,'combined first names')
        tc=find_col(headers,'tags')
        mr=sheets.get_row('Personnel',mri)
        mn=str(mr[nc]).strip() if nc and nc<len(mr) else ''
        me=str(mr[ec]).strip() if ec and ec<len(mr) else ''
        cww=str(mr[wwc]).strip() if wwc and wwc<len(mr) else ''
        wl=[t.strip() for t in cww.split(' | ') if t.strip()] if cww else []
        emails=[me] if me else []; fnames=[mn.split()[0]] if mn else []
        data=sheets.get_all_rows('Personnel'); allr=data[1:] if data else []
        for ln in lnames:
            if ln not in wl: wl.append(ln)
            for i,row in enumerate(allr):
                if nc is not None and nc<len(row) and str(row[nc]).strip().lower()==ln.lower():
                    lri=i+2
                    le=str(row[ec]).strip() if ec and ec<len(row) else ''
                    if le: emails.append(le)
                    fnames.append(ln.split()[0])
                    lww=str(row[wwc]).strip() if wwc and wwc<len(row) else ''
                    ll=[t.strip() for t in lww.split(' | ') if t.strip()] if lww else []
                    if mn not in ll:
                        ll.append(mn); sheets.update_cell('Personnel',lri,wwc+1,' | '.join(ll))
                    if tc is not None:
                        lt=str(row[tc]).strip() if tc<len(row) else ''
                        tl=split_tags(lt)
                        if "Don't Mass Pitch" not in tl:
                            tl.append("Don't Mass Pitch")
                            sheets.update_cell('Personnel',lri,tc+1,' | '.join(tl))
                    break
        if wwc is not None: sheets.update_cell('Personnel',mri,wwc+1,' | '.join(wl))
        if cec is not None: sheets.update_cell('Personnel',mri,cec+1,', '.join(emails))
        if cnc is not None: sheets.update_cell('Personnel',mri,cnc+1,', '.join(fnames))
        return jsonify({'success':True,'works_with':wl,'combined_emails':emails,'combined_names':fnames})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/automate/timezone-calc', methods=['POST'])
@login_required
def api_timezone_calc():
    d=request.json; tt=d.get('target_time','11:00'); rc=d.get('city','').strip()
    stz=d.get('sender_timezone','Europe/London')
    ci=CITY_LOOKUP.get(rc.lower(),{})
    rtz=ci.get('timezone','')
    if not rtz: return jsonify({'error':f'No timezone for {rc}'})
    try:
        so=TIMEZONE_OFFSETS.get(stz,0); ro=TIMEZONE_OFFSETS.get(rtz,0)
        h,m=map(int,tt.split(':')); diff=ro-so; sh=h-diff
        da=0
        while sh<0: sh+=24; da-=1
        while sh>=24: sh-=24; da+=1
        return jsonify({'send_time':f"{int(sh):02d}:{m:02d}",'send_day_adjust':da,
            'recipient_city':rc,'note':f"Send at {int(sh):02d}:{m:02d} your time to arrive at {tt} in {rc}"})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== PUB SPLITS ====================
@app.route('/api/splits/calculate', methods=['POST'])
@login_required
def api_calculate_splits():
    try: d=request.json; return jsonify(split_calc.calculate(d.get('writers',[]),d.get('mode','equal'),d.get('vocalist')))
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/splits/lookup', methods=['POST'])
@login_required
def api_lookup_writer():
    try: return jsonify(split_calc.lookup_writer(request.json.get('name','')))
    except Exception as e: return jsonify({'error': str(e)}), 500


# ==================== PITCH ====================
# ==================== INVOICES (ADMIN ONLY) ====================
@app.route('/invoices')
@admin_required
def invoices_page(): return render_template('invoices.html')

@app.route('/api/invoices')
@admin_required
def api_invoices():
    try:
        data = sheets.get_all_rows('Invoices')
        if not data or len(data) < 1:
            # Create Invoices sheet if it doesn't exist
            try:
                sheets.service.spreadsheets().batchUpdate(
                    spreadsheetId=sheets.spreadsheet_id,
                    body={'requests': [{'addSheet': {'properties': {'title': 'Invoices'}}}]}
                ).execute()
                headers_row = ['Invoice No','Date','Client','Description','Amount','Currency','Status','Due Date','Payment Date','Category','Notes']
                sheets.service.spreadsheets().values().update(
                    spreadsheetId=sheets.spreadsheet_id, range="'Invoices'!A1",
                    valueInputOption='USER_ENTERED', body={'values': [headers_row]}
                ).execute()
                sheets._invalidate_cache('Invoices')
                return jsonify({'headers': headers_row, 'records': [], 'total': 0})
            except Exception as e:
                logging.warning(f'Invoice sheet init: {e}')
                return jsonify({'headers': [], 'records': [], 'total': 0})
        headers = data[0]; rows = data[1:]
        # Search
        search = request.args.get('search', '').strip()
        indexed = [(i+2, r) for i, r in enumerate(rows)]
        if search:
            sl = search.lower()
            indexed = [(ri, r) for ri, r in indexed if any(sl in str(c).lower() for c in r)]
        # Sort
        sort_fields = parse_sort_fields(request.args)
        if sort_fields:
            indexed = apply_multi_sort(indexed, headers, sort_fields)
        # Filters
        adv_filters = []
        for i in range(20):
            col = request.args.get(f'f{i}_col', '').strip()
            op = request.args.get(f'f{i}_op', 'contains').strip()
            val = request.args.get(f'f{i}_val', '').strip()
            if col: adv_filters.append({'col':col,'op':op,'val':val})
        for f in adv_filters:
            ci = None
            for j, h in enumerate(headers):
                if cleanH(h).lower() == f['col'].lower() or f['col'].lower() in cleanH(h).lower():
                    ci = j; break
            if ci is not None:
                indexed = apply_filter(indexed, ci, f['op'], f['val'])
        records = []
        for ori, row in indexed:
            rec = {'_row_index': ori}
            for j, h in enumerate(headers):
                rec[h] = row[j] if j < len(row) else ''
            records.append(rec)
        return jsonify({'headers': headers, 'records': records, 'total': len(records)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/invoices/<int:ri>')
@admin_required
def api_invoice_detail(ri):
    try:
        headers = sheets.get_headers('Invoices')
        row = sheets.get_row('Invoices', ri)
        rec = {'_row_index': ri}
        for j, h in enumerate(headers):
            rec[h] = row[j] if j < len(row) else ''
        return jsonify(rec)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/invoices/new', methods=['POST'])
@admin_required
def api_invoice_new():
    d = request.json
    try:
        headers = sheets.get_headers('Invoices')
        row = [''] * len(headers)
        # Auto-number if requested
        prefix = d.pop('_auto_number', '')
        if prefix:
            data = sheets.get_all_rows('Invoices')
            inv_col = find_col(headers, 'invoice no', 'invoice number', 'invoice #')
            max_num = 2613
            if data and len(data) > 1 and inv_col is not None:
                for r in data[1:]:
                    if inv_col < len(r):
                        num_str = ''.join(c for c in str(r[inv_col]) if c.isdigit())
                        if num_str:
                            try: max_num = max(max_num, int(num_str))
                            except Exception as e: pass
            inv_no = prefix + str(max_num + 1)
            d['Invoice No'] = inv_no
        # Due date auto-calc (14 days from today)
        if 'Due Date' not in d:
            d['Due Date'] = (datetime.now() + timedelta(days=14)).strftime('%Y-%m-%d')
        for key, value in d.items():
            if key.startswith('_'): continue
            col = find_col(headers, key)
            if col is not None: row[col] = value
        # Auto System ID
        id_col = find_col(headers, 'system id', 'airtable id')
        if id_col is not None: row[id_col] = next_system_id()
        sheets.append_row('Invoices', row)
        return jsonify({'success': True, 'invoice_no': d.get('Invoice No', '')})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/invoices/update', methods=['POST'])
@admin_required
def api_invoice_update():
    d = request.json
    field = d.get('field', ''); ri = d.get('row_index'); value = d.get('value', '')
    if not field or not ri: return jsonify({'error': 'Missing field or row_index'}), 400
    try:
        headers = sheets.get_headers('Invoices')
        col = find_col(headers, field)
        if col is None: return jsonify({'error': f'Field not found: {field}'}), 400
        sheets.update_cell('Invoices', ri, col + 1, value)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/invoices/mark-paid', methods=['POST'])
@admin_required
def api_invoice_mark_paid():
    d = request.json
    ri = d.get('row_index')
    if not ri: return jsonify({'error': 'Missing row_index'}), 400
    try:
        headers = sheets.get_headers('Invoices')
        status_col = find_col(headers, 'status')
        payment_col = find_col(headers, 'payment date')
        if status_col is not None:
            sheets.update_cell('Invoices', ri, status_col + 1, 'Paid')
        if payment_col is not None:
            sheets.update_cell('Invoices', ri, payment_col + 1, datetime.now().strftime('%Y-%m-%d'))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== SONG SUBMISSION (PUBLIC, NO AUTH) ====================
@app.route('/submit')
def submit_form():
    return render_template('submit.html')

@app.route('/api/submit-song', methods=['POST'])
def api_submit_song():
    if not rate_limit_check(max_per_hour=30):
        return jsonify({'error': 'Too many submissions. Please try again later.'}), 429
    d = request.json
    if not d: return jsonify({'error': 'No data'}), 400
    title = d.get('title', '').strip()
    if not title: return jsonify({'error': 'Title is required'}), 400
    submitter = d.get('submitter_name', '').strip()
    email = d.get('submitter_email', '').strip()
    if not submitter or not email: return jsonify({'error': 'Name and email required'}), 400
    try:
        headers = sheets.get_headers('Songs')
        row = [''] * len(headers)
        # Auto-format lyrics with section headers
        lyrics = d.get('lyrics', '').strip()
        if lyrics:
            lyrics = format_lyrics(lyrics)
        # Map form fields to sheet columns (sanitized against formula injection)
        field_map = sanitize_dict({
            'Title': title,
            'Songwriter Credits': d.get('songwriter_credits', ''),
            'Producer': d.get('producer', ''),
            'Artist': d.get('artist', ''),
            'Genre': d.get('genre', ''),
            'Audio Status': d.get('audio_status', 'Demo'),
            'Dropbox Link': d.get('dropbox_link', ''),
            'DISCO': d.get('disco', ''),
            'Lyrics': lyrics,
            'Tag': 'New Submission',
            'BPM': d.get('bpm', ''),
            'Duration': d.get('duration', ''),
        })
        for field_name, value in field_map.items():
            if value:
                col = find_col(headers, field_name)
                if col is not None: row[col] = value
        # Store submitter info, new people flags, and notes
        notes_parts = [f"Submitted by: {submitter} ({email})"]
        # Flag new people for admin action
        new_people = d.get('new_people', [])
        if new_people:
            notes_parts.append("NEW PEOPLE (needs admin):")
            for p in new_people:
                notes_parts.append(f"  {p.get('name','')} ({p.get('role','')}) - needs MGMT/publisher lookup")
        if d.get('notes', '').strip():
            notes_parts.append(f"Notes: {d['notes'].strip()}")
        notes_col = find_col(headers, 'outreach notes', 'notes')
        if notes_col is not None: row[notes_col] = '\n'.join(notes_parts)
        # Store vocalist
        vocalist = d.get('vocalist', '').strip()
        if vocalist:
            voc_col = find_col(headers, 'vocalist')
            if voc_col is not None: row[voc_col] = vocalist
        # Store lyric doc link
        lyricdoc = d.get('lyricdoc', '').strip()
        if lyricdoc:
            ld_col = find_col(headers, 'lyric doc', 'lyric docs', 'lyrics docs')
            if ld_col is not None: row[ld_col] = lyricdoc
        # Set Last Modified
        lm_col = find_col(headers, 'last modified')
        if lm_col is not None:
            row[lm_col] = datetime.now().strftime('%Y-%m-%d %H:%M')
        # Auto-generate System ID
        id_col = find_col(headers, 'airtable id', 'system id')
        if id_col is not None:
            row[id_col] = next_system_id()
        # Set Song Admin checklist
        admin_col = find_col(headers, 'song admin')
        if admin_col is not None:
            admin_tasks = ['[ ] Review lyrics', '[ ] Check splits', '[ ] Save to Dropbox', '[ ] Create DISCO playlist', '[ ] Confirm with writers']
            if new_people:
                for p in new_people:
                    admin_tasks.insert(0, f"[ ] Find MGMT/publisher for {p.get('name','')}")
            row[admin_col] = '\n'.join(admin_tasks)
        sheets.append_row('Songs', row)
        # Auto-create Personnel records for new people
        if new_people:
            try:
                per_headers = sheets.get_headers('Personnel')
                pn_col = find_col(per_headers, 'name')
                ptag_col = find_col(per_headers, 'tags', 'tag')
                pfield_col = find_col(per_headers, 'field')
                pid_col = find_col(per_headers, 'airtable id', 'system id')
                plm_col = find_col(per_headers, 'last modified')
                for p in new_people:
                    prow = [''] * len(per_headers)
                    if pn_col is not None: prow[pn_col] = p.get('name', '')
                    if ptag_col is not None: prow[ptag_col] = 'Needs Admin | New Submission'
                    role_map = {'writer': 'Songwriter', 'producer': 'Producer', 'vocalist': 'Artist'}
                    if pfield_col is not None: prow[pfield_col] = role_map.get(p.get('role', ''), 'Songwriter')
                    if pid_col is not None: prow[pid_col] = next_system_id()
                    if plm_col is not None: prow[plm_col] = datetime.now().strftime('%Y-%m-%d %H:%M')
                    sheets.append_row('Personnel', prow)
                    logging.info(f"Auto-created Personnel: {p.get('name','')} ({p.get('role','')})")
            except Exception as pe:
                logging.warning(f"Failed to auto-create Personnel: {pe}")
        # Rebuild name cache to include new records (synchronous)
        try: build_name_cache()
        except Exception as e:
            logging.warning(f'Name cache rebuild after submit: {e}')
        logging.info(f"Song submitted: {title} by {submitter} ({email})")
        # Auto-generate lyric doc PDF if lyrics were included
        if lyrics:
            try:
                new_row_idx = sheets.get_row_count('Songs') + 1
                generate_lyric_doc(sheets, 'Songs', new_row_idx, headers)
            except Exception as le:
                logging.warning(f"Lyric doc generation failed on submit: {le}")
        # Generate edit token (24h expiry), persisted to disk
        token = secrets.token_urlsafe(32)
        _edit_tokens[token] = {
            'row_index': sheets.get_row_count('Songs') + 1,  # last row
            'data': d,
            'title': title,
            'email': email,
            'submitter': submitter,
            'expires': time.time() + 86400  # 24 hours
        }
        _save_edit_tokens()
        # Send confirmation email (non-blocking, best effort)
        try:
            if SMTP_USER and SMTP_PASS:
                _send_confirmation_email(email, submitter, title, token, d)
        except Exception as em:
            logging.warning(f"Confirmation email failed: {em}")
        return jsonify({'success': True, 'title': title, 'new_people_created': len(new_people), 'edit_token': token})
    except Exception as e:
        logging.error(f"Submission error: {e}")
        return jsonify({'error': 'Submission failed. Please try again.'}), 500


def _send_confirmation_email(to_email, name, title, token, data):
    """Send submission confirmation with edit link."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    edit_url = f"{request.host_url}submit?edit={token}"
    # Build summary
    summary_parts = [f"Song Title: {title}"]
    if data.get('genre'): summary_parts.append(f"Genre: {data['genre']}")
    if data.get('audio_status'): summary_parts.append(f"Audio Status: {data['audio_status']}")
    if data.get('bpm'): summary_parts.append(f"BPM: {data['bpm']}")
    if data.get('duration'): summary_parts.append(f"Duration: {data['duration']}")
    if data.get('songwriter_credits'): summary_parts.append(f"Songwriters: {data['songwriter_credits']}")
    if data.get('producer'): summary_parts.append(f"Producers: {data['producer']}")
    if data.get('artist'): summary_parts.append(f"Artists: {data['artist']}")
    if data.get('vocalist'): summary_parts.append(f"Vocalists: {data['vocalist']}")
    if data.get('dropbox_link'): summary_parts.append(f"Download Link: {data['dropbox_link']}")
    if data.get('lyricdoc'): summary_parts.append(f"Lyric Doc: {data['lyricdoc']}")
    if data.get('notes'): summary_parts.append(f"Notes: {data['notes']}")
    summary = '\n'.join(summary_parts)
    html = f"""<div style="font-family:Inter,Helvetica,Arial,sans-serif;max-width:560px;margin:0 auto;color:#e8e6e3;background:#131316;padding:32px;border-radius:12px">
<div style="text-align:center;margin-bottom:24px">
<h1 style="font-family:'DM Sans',sans-serif;color:#d4a853;font-size:22px;letter-spacing:2px;margin:0">ROLLON ENT</h1>
<p style="color:#9a9a9f;font-size:12px;margin-top:4px">Song Submission Confirmation</p>
</div>
<p style="font-size:14px">Hi {name},</p>
<p style="font-size:13px;color:#9a9a9f">Your song <strong style="color:#e8e6e3">{title}</strong> has been received. Here's what we got:</p>
<div style="background:#1c1c21;border:1px solid #2a2a32;border-radius:8px;padding:16px;margin:16px 0;font-size:12px;line-height:1.8">
{'<br>'.join(f'<span style="color:#9a9a9f">{line.split(": ", 1)[0]}:</span> {line.split(": ", 1)[1] if ": " in line else ""}' for line in summary_parts)}
</div>
<p style="font-size:13px;color:#9a9a9f">Need to make changes? You have 24 hours:</p>
<div style="text-align:center;margin:20px 0">
<a href="{edit_url}" style="display:inline-block;padding:12px 28px;background:#d4a853;color:#131316;text-decoration:none;border-radius:8px;font-weight:700;font-size:13px">Edit Submission</a>
</div>
<p style="font-size:11px;color:#5a5a62;text-align:center;margin-top:24px">ROLLON ENT | celina@rollonent.com</p>
</div>"""
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f'Submission received: {title}'
    msg['From'] = SMTP_FROM
    msg['To'] = to_email
    msg['Reply-To'] = SMTP_FROM
    msg.attach(MIMEText(f"Hi {name},\n\nYour song \"{title}\" has been received.\n\n{summary}\n\nNeed to make changes? Edit within 24 hours:\n{edit_url}\n\nROLLON ENT\ncelina@rollonent.com", 'plain'))
    msg.attach(MIMEText(html, 'html'))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
    logging.info(f"Confirmation email sent to {to_email} for '{title}'")


@app.route('/api/submit-edit', methods=['POST'])
def api_submit_edit():
    """Update a previously submitted song using edit token."""
    if not rate_limit_check(max_per_hour=30):
        return jsonify({'error': 'Too many requests.'}), 429
    d = request.json
    if not d: return jsonify({'error': 'No data'}), 400
    token = d.get('edit_token', '').strip()
    if not token or token not in _edit_tokens:
        return jsonify({'error': 'Invalid or expired edit link.'}), 400
    tok = _edit_tokens[token]
    if time.time() > tok['expires']:
        del _edit_tokens[token]
        return jsonify({'error': 'Edit link has expired (24 hour limit).'}), 400
    title = d.get('title', '').strip()
    if not title: return jsonify({'error': 'Title is required'}), 400
    try:
        headers = sheets.get_headers('Songs')
        ri = tok['row_index']
        lyrics = d.get('lyrics', '').strip()
        if lyrics: lyrics = format_lyrics(lyrics)
        # Map form fields (sanitized against formula injection)
        field_map = sanitize_dict({
            'Title': title,
            'Songwriter Credits': d.get('songwriter_credits', ''),
            'Producer': d.get('producer', ''),
            'Artist': d.get('artist', ''),
            'Genre': d.get('genre', ''),
            'Audio Status': d.get('audio_status', 'Demo'),
            'Dropbox Link': d.get('dropbox_link', ''),
            'DISCO': d.get('disco', ''),
            'Lyrics': lyrics,
            'BPM': d.get('bpm', ''),
            'Duration': d.get('duration', ''),
        })
        for field_name, value in field_map.items():
            col = find_col(headers, field_name)
            if col is not None:
                sheets.update_cell('Songs', ri, col + 1, value or '')
        # Update vocalist
        vocalist = d.get('vocalist', '').strip()
        voc_col = find_col(headers, 'vocalist')
        if voc_col is not None: sheets.update_cell('Songs', ri, voc_col + 1, vocalist)
        # Update lyric doc
        lyricdoc = d.get('lyricdoc', '').strip()
        ld_col = find_col(headers, 'lyric doc', 'lyric docs', 'lyrics docs')
        if ld_col is not None: sheets.update_cell('Songs', ri, ld_col + 1, lyricdoc)
        # Update notes
        submitter = d.get('submitter_name', '').strip()
        email = d.get('submitter_email', '').strip()
        notes_parts = [f"Submitted by: {submitter} ({email})", "EDITED via confirmation link"]
        if d.get('notes', '').strip():
            notes_parts.append(f"Notes: {d['notes'].strip()}")
        notes_col = find_col(headers, 'outreach notes', 'notes')
        if notes_col is not None:
            sheets.update_cell('Songs', ri, notes_col + 1, '\n'.join(notes_parts))
        # Update Last Modified
        lm_col = find_col(headers, 'last modified')
        if lm_col is not None:
            sheets.update_cell('Songs', ri, lm_col + 1, datetime.now().strftime('%Y-%m-%d %H:%M'))
        sheets._invalidate_cache('Songs')
        # Keep token valid for remaining time (they might need another edit)
        tok['data'] = d
        logging.info(f"Song edited via token: {title} by {submitter}")
        return jsonify({'success': True, 'title': title, 'edited': True})
    except Exception as e:
        logging.error(f"Edit submission error: {e}")
        return jsonify({'error': 'Edit failed. Please try again.'}), 500


@app.route('/api/submit-load/<token>')
def api_submit_load(token):
    """Load submission data for editing."""
    if not rate_limit_check(max_per_hour=60):
        return jsonify({'error': 'Too many requests.'}), 429
    if token not in _edit_tokens:
        return jsonify({'error': 'Invalid or expired edit link.'}), 400
    tok = _edit_tokens[token]
    if time.time() > tok['expires']:
        del _edit_tokens[token]
        return jsonify({'error': 'Edit link has expired (24 hour limit).'}), 400
    d = tok['data']
    remaining = int((tok['expires'] - time.time()) / 60)
    return jsonify({'success': True, 'data': d, 'title': tok['title'], 'minutes_remaining': remaining})

def format_lyrics(text):
    """Smart lyric formatter. Detects repeated sections as chorus, pre-chorus."""
    if not text: return text
    lines = text.split('\n')
    # If already has [Section] headers, clean up duplicate labels
    has_brackets = any(l.strip().startswith('[') for l in lines)
    if has_brackets:
        cleaned = []
        skip_labels = {'verse','chorus','bridge','pre-chorus','hook','outro','intro','post-chorus'}
        for line in lines:
            s = line.strip().lower().rstrip(':')
            if s in skip_labels: continue
            cleaned.append(line)
        return '\n'.join(cleaned)
    # Check for inline labels first
    LABELS = {'verse':'VERSE','chorus':'CHORUS','bridge':'BRIDGE',
              'pre-chorus':'PRE-CHORUS','pre chorus':'PRE-CHORUS',
              'hook':'HOOK','outro':'OUTRO','intro':'INTRO'}
    has_inline = False
    for line in lines:
        s = line.strip().rstrip(':').lower()
        if s in LABELS: has_inline = True; break
    if has_inline:
        formatted = []; in_section = False; vn = 0
        for line in lines:
            s = line.strip()
            if not s: in_section = False; formatted.append(''); continue
            lc = s.rstrip(':').lower()
            if lc in LABELS:
                in_section = True
                label = LABELS[lc]
                if label == 'VERSE': vn += 1
                formatted.append(f'[{label}]')
                continue
            if not in_section:
                in_section = True; vn += 1; formatted.append(f'[VERSE]')
            formatted.append(s)
        return '\n'.join(formatted)
    # No labels: use content fingerprinting to detect repeats
    # Split into sections by blank lines
    sections = []; current = []
    for line in lines:
        if not line.strip():
            if current: sections.append(current); current = []
        else: current.append(line.strip())
    if current: sections.append(current)
    if not sections: return text
    # Create fingerprints (first line, lowercase, stripped)
    fps = []
    for sec in sections:
        fp = sec[0].lower().strip()[:30] if sec else ''
        fps.append(fp)
    # Count fingerprint occurrences
    from collections import Counter
    fp_counts = Counter(fps)
    # Most repeated = chorus candidate
    chorus_fp = None
    for fp, count in fp_counts.most_common():
        if count >= 2: chorus_fp = fp; break
    # Find pre-chorus: section that always appears before chorus
    prechorus_fp = None
    if chorus_fp:
        for i, fp in enumerate(fps):
            if fp == chorus_fp and i > 0:
                prev = fps[i-1]
                if prev != chorus_fp and fp_counts.get(prev, 0) >= 2:
                    prechorus_fp = prev; break
    # Build formatted output
    formatted = []; vn = 0; last_label = ''
    for i, sec in enumerate(sections):
        fp = fps[i]
        if chorus_fp and fp == chorus_fp:
            label = 'CHORUS'
        elif prechorus_fp and fp == prechorus_fp:
            label = 'PRE-CHORUS'
        else:
            label = 'VERSE'
        # Only add header if label changed from previous section
        if label != last_label:
            if formatted and formatted[-1] != '': formatted.append('')
            formatted.append(f'[{label}]')
        elif formatted and formatted[-1] != '':
            formatted.append('')
        for line in sec: formatted.append(line)
        last_label = label
    return '\n'.join(formatted)

@app.route('/api/public/search-names')
def api_public_search_names():
    """Public endpoint for submission form. Returns names only, no sensitive data."""
    if not rate_limit_check(max_per_hour=200):
        return jsonify({'names': []}), 429
    q = request.args.get('q', '').strip()
    if len(q) < 1: return jsonify({'names': []})
    ql = q.lower()
    with NAME_CACHE_LOCK:
        matches = [v['name'] for k, v in NAME_CACHE.items()
                   if ql in k and v['table'] == 'Personnel'][:10]
    return jsonify({'names': matches})


@app.route('/api/public/autocomplete/<table>/<field>')
def api_public_autocomplete(table, field):
    """Public autocomplete for submit form — returns unique field values, no auth required."""
    if not rate_limit_check(max_per_hour=200):
        return jsonify({'values': []}), 429
    tmap = {'songs': 'Songs', 'directory': 'Personnel', 'personnel': 'Personnel'}
    sn = tmap.get(table.lower())
    if not sn:
        return jsonify({'values': []})
    try:
        data = sheets.get_all_rows(sn)
        if not data:
            return jsonify({'values': []})
        headers = data[0]; rows = data[1:]
        col = find_col(headers, field)
        if col is None:
            return jsonify({'values': []})
        vals = set()
        for row in rows:
            if col < len(row):
                for t in split_tags(str(row[col])):
                    if t and not t.startswith('rec') and not t.isdigit() and len(t) > 1:
                        vals.add(t)
        return jsonify({'values': sorted(vals)})
    except Exception as e:
        return jsonify({'values': []})


@app.route('/pitch')
@login_required
def pitch(): return render_template('pitch.html')

@app.route('/api/pitch/contacts', methods=['POST'])
@login_required
def api_pitch_contacts():
    try: return jsonify({'contacts':pitch_builder.get_contacts_for_type(request.json.get('pitch_type',''))})
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/pitch/generate', methods=['POST'])
@login_required
def api_pitch_generate():
    d=request.json
    try: return jsonify(pitch_builder.generate_campaign(d.get('pitch_type',''),d.get('playlist_link',''),d.get('round_number','001'),d.get('bespoke_paragraph',''),d.get('contacts',[]),d.get('send_day','Tuesday'),d.get('send_time','11:00')))
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/pitch/draft-email', methods=['POST'])
@login_required
def api_pitch_draft_email():
    d=request.json
    try: return jsonify({'draft':pitch_builder.draft_email(d.get('pitch_type',''),d.get('round_number','001'),d.get('playlist_link',''))})
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/pitch/history')
@login_required
def api_pitch_history():
    contact = request.args.get('contact', '').strip()
    song = request.args.get('song', '').strip()
    try:
        history = pitch_builder.get_pitch_history(contact_name=contact or None, song_title=song or None)
        return jsonify({'history': history, 'total': len(history)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/pitch/check-duplicate', methods=['POST'])
@login_required
def api_pitch_check_duplicate():
    d = request.json
    try:
        result = pitch_builder.check_duplicates(d.get('email', ''), d.get('song', ''))
        return jsonify({'duplicate': bool(result), 'entry': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== VIEWS PERSISTENCE (Sheets-backed) ====================
def _ensure_views_sheet():
    try:
        data = sheets.get_all_rows('Views')
        if data: return True
    except Exception:
        pass
    try:
        sheets.service.spreadsheets().batchUpdate(
            spreadsheetId=sheets.spreadsheet_id,
            body={'requests': [{'addSheet': {'properties': {'title': 'Views'}}}]}
        ).execute()
        sheets.service.spreadsheets().values().update(
            spreadsheetId=sheets.spreadsheet_id, range="'Views'!A1",
            valueInputOption='USER_ENTERED', body={'values': [['Page', 'ViewData', 'Updated']]}
        ).execute()
        sheets._invalidate_cache('Views')
        return True
    except Exception as e:
        logging.warning(f"Failed to create Views sheet: {e}")
        return False

@app.route('/api/views/<page>', methods=['GET'])
@login_required
def api_views_get(page):
    """Load saved views for a page (songs, directory, pitch, invoices)."""
    try:
        if not _ensure_views_sheet(): return jsonify({})
        data = sheets.get_all_rows('Views')
        if not data or len(data) < 2: return jsonify({})
        headers = data[0]
        page_col = find_col(headers, 'page')
        data_col = find_col(headers, 'viewdata')
        if page_col is None or data_col is None: return jsonify({})
        for row in data[1:]:
            if page_col < len(row) and str(row[page_col]).strip().lower() == page.lower():
                raw = str(row[data_col]) if data_col < len(row) else '{}'
                try: return jsonify(json.loads(raw))
                except Exception: return jsonify({})
        return jsonify({})
    except Exception as e:
        logging.warning(f"Views load {page}: {e}")
        return jsonify({})

@app.route('/api/views/<page>', methods=['POST'])
@login_required
def api_views_save(page):
    """Save views for a page."""
    try:
        if not _ensure_views_sheet(): return jsonify({'error': 'Sheet error'}), 500
        view_data = json.dumps(request.json or {})
        data = sheets.get_all_rows('Views')
        headers = data[0] if data else ['Page', 'ViewData', 'Updated']
        page_col = find_col(headers, 'page')
        data_col = find_col(headers, 'viewdata')
        updated_col = find_col(headers, 'updated')
        if page_col is None: page_col = 0
        if data_col is None: data_col = 1
        # Find existing row for this page
        for ri, row in enumerate(data[1:] if data else [], start=2):
            if page_col < len(row) and str(row[page_col]).strip().lower() == page.lower():
                sheets.update_cell('Views', ri, data_col + 1, view_data)
                if updated_col is not None:
                    sheets.update_cell('Views', ri, updated_col + 1, datetime.now().strftime('%Y-%m-%d %H:%M'))
                return jsonify({'success': True})
        # New row
        new_row = [''] * max(len(headers), 3)
        new_row[page_col] = page
        new_row[data_col] = view_data
        if updated_col is not None: new_row[updated_col] = datetime.now().strftime('%Y-%m-%d %H:%M')
        sheets.append_row('Views', new_row)
        return jsonify({'success': True})
    except Exception as e:
        logging.warning(f"Views save {page}: {e}")
        return jsonify({'error': str(e)}), 500


# ==================== PLAYLISTS (DISCO replacement) ====================
import uuid as _uuid

def _ensure_playlists_sheet():
    try:
        data = sheets.get_all_rows('Playlists')
        if data: return True
    except Exception as e:
        logging.warning(f'Playlists sheet check: {e}')
    try:
        sheets.service.spreadsheets().batchUpdate(
            spreadsheetId=sheets.spreadsheet_id,
            body={'requests': [{'addSheet': {'properties': {'title': 'Playlists'}}}]}
        ).execute()
        headers = ['ID','Name','Description','Song IDs','Song Data','Created','Created By','Views','Status']
        sheets.service.spreadsheets().values().update(
            spreadsheetId=sheets.spreadsheet_id, range="'Playlists'!A1",
            valueInputOption='USER_ENTERED', body={'values': [headers]}
        ).execute()
        sheets._invalidate_cache('Playlists')
        return True
    except Exception as e:
        logging.warning(f'Playlists sheet create: {e}')
        return False

@app.route('/playlists')
@login_required
def playlists_page(): return render_template('playlists.html')

@app.route('/api/playlists')
@login_required
def api_playlists():
    try:
        if not _ensure_playlists_sheet(): return jsonify({'playlists': []})
        data = sheets.get_all_rows('Playlists')
        if not data or len(data) < 2: return jsonify({'playlists': []})
        headers = data[0]; rows = data[1:]
        playlists = []
        for i, row in enumerate(rows):
            rec = {'_row': i + 2}
            for j, h in enumerate(headers):
                rec[h] = row[j] if j < len(row) else ''
            if rec.get('ID'): playlists.append(rec)
        return jsonify({'playlists': playlists})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/playlists/create', methods=['POST'])
@login_required
def api_playlists_create():
    d = request.json
    name = d.get('name', '').strip()
    if not name: return jsonify({'error': 'Name required'}), 400
    song_ids = d.get('song_ids', [])  # list of row indices
    if not song_ids: return jsonify({'error': 'No songs selected'}), 400
    try:
        if not _ensure_playlists_sheet(): return jsonify({'error': 'Sheet error'}), 500
        # Build song data from Songs sheet
        song_headers = sheets.get_headers('Songs')
        song_data = []
        for ri in song_ids:
            try:
                row = sheets.get_row('Songs', ri)
                rec = {}
                for j, h in enumerate(song_headers):
                    val = row[j] if j < len(row) else ''
                    rec[cleanH(h)] = resolver.resolve_value(h, val) if resolver else val
                song_data.append(rec)
            except Exception as e:
                logging.warning(f'Song data fetch for playlist: {e}')
        pid = 'PLY-' + _uuid.uuid4().hex[:8].upper()
        new_row = [
            pid, name, d.get('description', ''),
            '|'.join(str(s) for s in song_ids),
            json.dumps(song_data),
            datetime.now().strftime('%Y-%m-%d %H:%M'),
            {'admin':'Captain','assistant':'Co-Pilot'}.get(session.get('role','admin'), session.get('role','admin')),
            '0', 'Active'
        ]
        sheets.append_row('Playlists', new_row)
        sheets._invalidate_cache('Playlists')
        share_url = f"/p/{pid}"
        return jsonify({'success': True, 'id': pid, 'share_url': share_url, 'songs': len(song_data)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/playlists/<pid>/delete', methods=['POST'])
@login_required
def api_playlists_delete(pid):
    """Soft-archive a playlist (moves to Archive sheet)."""
    try:
        data = sheets.get_all_rows('Playlists')
        if not data or len(data) < 2: return jsonify({'error': 'Not found'}), 404
        headers = data[0]
        id_col = find_col(headers, 'id')
        for i, row in enumerate(data[1:]):
            if id_col is not None and id_col < len(row) and row[id_col] == pid:
                ri = i + 2
                archived = _archive_rows('Playlists', [ri])
                return jsonify({'success': True, 'archived': archived})
        return jsonify({'error': 'Not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/p/<pid>')
def public_playlist(pid):
    """Public playlist page. No login required."""
    try:
        data = sheets.get_all_rows('Playlists')
        if not data or len(data) < 2: return "Playlist not found", 404
        headers = data[0]; rows = data[1:]
        id_col = find_col(headers, 'id')
        for i, row in enumerate(rows):
            if id_col is not None and id_col < len(row) and row[id_col] == pid:
                rec = {}
                for j, h in enumerate(headers):
                    rec[h] = row[j] if j < len(row) else ''
                # Increment views (buffered, flushed every 60s)
                views_col = find_col(headers, 'views')
                current_views = 0
                if views_col is not None:
                    current_views = int(rec.get('Views', '0') or '0')
                    _buffer_playlist_view(pid)
                # Parse song data
                songs = []
                try: songs = json.loads(rec.get('Song Data', '[]'))
                except Exception as e: logging.warning(f"Playlist song data parse error: {e}")
                # Count pending buffered views
                with _playlist_views_lock:
                    pending = _playlist_views.get(pid, 0)
                return render_template('playlist_public.html',
                    playlist_name=rec.get('Name', ''),
                    playlist_desc=rec.get('Description', ''),
                    songs=songs,
                    views=current_views + pending,
                    created=rec.get('Created', ''),
                    pid=pid,
                    playlist_id=pid)
        return "Playlist not found", 404
    except Exception as e:
        return f"Error: {e}", 500


# ==================== FOLLOW-UP REMINDERS ====================
@app.route('/api/follow-ups')
@login_required
def api_follow_ups():
    """Get contacts with overdue or upcoming follow-ups."""
    try:
        data = sheets.get_all_rows('Personnel')
        if not data or len(data) < 2: return jsonify({'reminders': []})
        headers = data[0]; rows = data[1:]
        lo_col = find_col(headers, 'last outreach')
        nc = find_col(headers, 'name')
        ec = find_col(headers, 'email')
        fc = find_col(headers, 'field')
        tc = find_col(headers, 'tags')
        if lo_col is None or nc is None: return jsonify({'reminders': []})
        from datetime import datetime as dt, timedelta
        now = dt.now(); reminders = []
        for i, row in enumerate(rows):
            lo = row[lo_col].strip() if lo_col < len(row) else ''
            if not lo: continue
            try:
                lo_date = None
                for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%Y-%m-%d %H:%M'):
                    try: lo_date = dt.strptime(lo.strip(), fmt); break
                    except Exception as e: pass
                if not lo_date: continue
                days_since = (now - lo_date).days
                # Flag if outreach was 14+ days ago
                if days_since >= 14:
                    name = row[nc].strip() if nc < len(row) else ''
                    email = row[ec].strip() if ec is not None and ec < len(row) else ''
                    field = row[fc].strip() if fc is not None and fc < len(row) else ''
                    tags = row[tc].strip() if tc is not None and tc < len(row) else ''
                    # Skip if tagged "Don't Pitch" or "Blocked"
                    if 'dont pitch' in tags.lower() or 'blocked' in tags.lower(): continue
                    priority = 'overdue' if days_since > 30 else 'due'
                    reminders.append({
                        'name': name, 'email': email, 'field': field,
                        'last_outreach': lo, 'days_since': days_since,
                        'priority': priority, 'row_index': i + 2
                    })
            except Exception as e:
                logging.warning(f'Outreach reminder parse: {e}')
                continue
        reminders.sort(key=lambda r: r['days_since'], reverse=True)
        return jsonify({'reminders': reminders[:50], 'total': len(reminders)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== EMAIL TEMPLATES (Google Sheets backed) ====================
def _ensure_templates_sheet():
    """Create Templates sheet if it doesn't exist."""
    try:
        data = sheets.get_all_rows('Templates')
        if data: return True
    except Exception as e:
        logging.warning(f'Templates sheet check: {e}')
    try:
        sheets.service.spreadsheets().batchUpdate(
            spreadsheetId=sheets.spreadsheet_id,
            body={'requests': [{'addSheet': {'properties': {'title': 'Templates'}}}]}
        ).execute()
        headers = ['Name', 'Type', 'Subject', 'Body', 'Last Used']
        sheets.service.spreadsheets().values().update(
            spreadsheetId=sheets.spreadsheet_id, range="'Templates'!A1",
            valueInputOption='USER_ENTERED', body={'values': [headers]}
        ).execute()
        sheets._invalidate_cache('Templates')
        return True
    except Exception as e:
        logging.warning(f'Templates sheet create: {e}')
        return False

@app.route('/api/templates')
@login_required
def api_templates():
    try:
        if not _ensure_templates_sheet(): return jsonify({'templates': {}})
        data = sheets.get_all_rows('Templates')
        if not data or len(data) < 2: return jsonify({'templates': {}})
        headers = data[0]; rows = data[1:]
        nc = find_col(headers, 'name'); sc = find_col(headers, 'subject')
        bc = find_col(headers, 'body'); tc = find_col(headers, 'type')
        templates = {}
        for row in rows:
            name = row[nc].strip() if nc is not None and nc < len(row) else ''
            if not name: continue
            templates[name] = {
                'subject': row[sc].strip() if sc is not None and sc < len(row) else '',
                'body': row[bc].strip() if bc is not None and bc < len(row) else '',
                'type': row[tc].strip() if tc is not None and tc < len(row) else ''
            }
        return jsonify({'templates': templates})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/templates/save', methods=['POST'])
@login_required
def api_templates_save():
    d = request.json
    name = d.get('name', '').strip()
    if not name: return jsonify({'error': 'Name required'}), 400
    try:
        if not _ensure_templates_sheet(): return jsonify({'error': 'Sheet error'}), 500
        data = sheets.get_all_rows('Templates')
        headers = data[0] if data else ['Name','Type','Subject','Body','Last Used']
        nc = find_col(headers, 'name')
        # Check if template exists (update) or new (append)
        existing_row = None
        if data and len(data) > 1:
            for i, row in enumerate(data[1:]):
                if nc is not None and nc < len(row) and row[nc].strip().lower() == name.lower():
                    existing_row = i + 2; break
        new_row = [name, d.get('type', ''), d.get('subject', ''), d.get('body', ''), datetime.now().strftime('%Y-%m-%d')]
        if existing_row:
            for j, val in enumerate(new_row):
                sheets.update_cell('Templates', existing_row, j + 1, val)
        else:
            sheets.append_row('Templates', new_row)
        sheets._invalidate_cache('Templates')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/templates/delete', methods=['POST'])
@login_required
def api_templates_delete():
    """Soft-archive a template (moves to Archive sheet)."""
    name = request.json.get('name', '').strip()
    if not name: return jsonify({'error': 'Name required'}), 400
    try:
        data = sheets.get_all_rows('Templates')
        if not data or len(data) < 2: return jsonify({'error': 'Not found'}), 404
        headers = data[0]; nc = find_col(headers, 'name')
        for i, row in enumerate(data[1:]):
            if nc is not None and nc < len(row) and row[nc].strip().lower() == name.lower():
                ri = i + 2
                _archive_rows('Templates', [ri])
                return jsonify({'success': True})
        return jsonify({'error': 'Not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== SETTINGS ====================
# ==================== DUPLICATE FINDER ====================
@app.route('/api/duplicates', methods=['POST'])
@login_required
def api_duplicates_v2():
    """Find duplicate records. POST body: {table, fields: [field_names], mode: exact|similar|fuzzy}"""
    d = request.json or {}
    table_name = d.get('table', 'Songs')
    field_names = d.get('fields', [])
    mode = d.get('mode', 'exact')  # exact, similar, fuzzy

    sheet_map = {'Songs': 'Songs', 'Personnel': 'Personnel', 'Directory': 'Personnel'}
    sheet = sheet_map.get(table_name, table_name)

    try:
        data = sheets.get_all_rows(sheet)
        if not data or len(data) < 2:
            return jsonify({'groups': [], 'total_dupes': 0})
        headers = data[0]; rows = data[1:]

        # Resolve field columns
        field_cols = []
        for fn in field_names:
            col = find_col(headers, fn)
            if col is not None:
                field_cols.append(col)
        if not field_cols:
            return jsonify({'error': 'No matching fields found'}), 400

        def normalize(s):
            s = s.lower().strip()
            if mode == 'fuzzy':
                # Remove common words, punctuation
                import string
                s = s.translate(str.maketrans('', '', string.punctuation))
                s = ' '.join(s.split())  # collapse whitespace
            return s

        def get_key(row):
            parts = []
            for ci in field_cols:
                val = str(row[ci]).strip() if ci < len(row) else ''
                parts.append(normalize(val))
            return '||'.join(parts)

        # Group by key
        groups = {}
        for ri, row in enumerate(rows, start=2):
            key = get_key(row)
            if not key or key == '||'.join(['' for _ in field_cols]):
                continue
            if key not in groups:
                groups[key] = []
            # Build record summary
            name_col = find_col(headers, 'title', 'name')
            rec = {'_row_index': ri}
            for j, h in enumerate(headers):
                rec[cleanH(h)] = row[j] if j < len(row) else ''
            groups[key].append(rec)

        # Filter to only groups with 2+ records
        dupe_groups = []
        for key, recs in groups.items():
            if len(recs) >= 2:
                # Use first record's name as group label
                label = recs[0].get('Title', '') or recs[0].get('Name', '') or key
                dupe_groups.append({
                    'label': label,
                    'count': len(recs),
                    'records': recs,
                    'key': key
                })

        dupe_groups.sort(key=lambda g: -g['count'])
        total = sum(g['count'] for g in dupe_groups)

        return jsonify({
            'groups': dupe_groups[:100],  # Cap at 100 groups
            'total_groups': len(dupe_groups),
            'total_dupes': total,
            'fields_checked': field_names
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/merge', methods=['POST'])
@login_required
def api_merge():
    """Merge duplicate records. Keeps winner, soft-archives losers to Archive sheet.
    POST body: {table, keep_row: int, delete_rows: [int], merged_values: {field: value}}"""
    d = request.json or {}
    table_name = d.get('table', 'Songs')
    keep_row = d.get('keep_row')
    delete_rows = d.get('delete_rows', [])
    merged_values = d.get('merged_values', {})

    sheet_map = {'Songs': 'Songs', 'Personnel': 'Personnel', 'Directory': 'Personnel'}
    sheet = sheet_map.get(table_name, table_name)

    try:
        headers = sheets.get_headers(sheet)
        # Update kept record with merged values
        for field_name, value in merged_values.items():
            col = find_col(headers, field_name)
            if col is not None:
                sheets.update_cell(sheet, keep_row, col + 1, value)

        # Soft-archive the loser rows (NOT hard delete)
        # Filter out keep_row from delete_rows to prevent archiving the winner
        actual_deletes = [ri for ri in delete_rows if ri != keep_row]
        archived = _archive_rows(sheet, actual_deletes)

        return jsonify({'success': True, 'kept': keep_row, 'deleted': archived, 'method': 'archived'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== ARCHIVE (Data Recovery) ====================
@app.route('/api/archive')
@admin_required
def api_archive():
    """List archived records, optionally filtered by source sheet."""
    source = request.args.get('source', '').strip()
    try:
        _ensure_archive_sheet()
        data = sheets.get_all_rows(ARCHIVE_SHEET)
        if not data or len(data) < 2:
            return jsonify({'records': [], 'total': 0})
        headers = data[0]
        rows = data[1:]
        records = []
        for i, row in enumerate(rows):
            rec = {'_row_index': i + 2}
            for j, h in enumerate(headers):
                rec[h] = row[j] if j < len(row) else ''
            # Skip empty rows
            if not any(v.strip() for v in row if v):
                continue
            if source and rec.get('Archived From', '') != source:
                continue
            records.append(rec)
        records.reverse()  # Newest first
        return jsonify({'records': records, 'total': len(records)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/archive/restore', methods=['POST'])
@admin_required
def api_archive_restore():
    """Restore an archived record back to its original sheet."""
    d = request.json or {}
    archive_row = d.get('row_index')
    if not archive_row:
        return jsonify({'error': 'row_index required'}), 400
    try:
        _ensure_archive_sheet()
        headers = sheets.get_headers(ARCHIVE_SHEET)
        row = sheets.get_row(ARCHIVE_SHEET, archive_row)
        source_col = find_col(headers, 'Archived From')
        data_col = find_col(headers, 'Original Data JSON')
        if source_col is None or data_col is None:
            return jsonify({'error': 'Archive format invalid'}), 400

        source_sheet = row[source_col].strip() if source_col < len(row) else ''
        data_json = row[data_col].strip() if data_col < len(row) else '{}'

        if not source_sheet:
            return jsonify({'error': 'No source sheet recorded'}), 400

        record = json.loads(data_json)
        # Rebuild row for the original sheet
        orig_headers = sheets.get_headers(source_sheet)
        new_row = [''] * len(orig_headers)
        for j, h in enumerate(orig_headers):
            ch = cleanH(h)
            if ch in record:
                new_row[j] = record[ch]

        # Append to original sheet
        sheets.append_row(source_sheet, new_row)

        # Clear the archive row
        col_letter = sheets._col_to_letter(len(headers))
        sheets._retry(lambda: sheets.service.spreadsheets().values().clear(
            spreadsheetId=sheets.spreadsheet_id,
            range=f"'{ARCHIVE_SHEET}'!A{archive_row}:{col_letter}{archive_row}").execute())
        sheets._invalidate_cache(ARCHIVE_SHEET)
        sheets._invalidate_cache(source_sheet)

        name = record.get('Name', record.get('Title', 'Record'))
        return jsonify({'success': True, 'restored': name, 'to': source_sheet})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/settings')
@login_required
def settings(): return render_template('settings.html')

@app.route('/api/tables')
@login_required
def api_tables():
    try: return jsonify({'tables':sheets.list_sheets()})
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/rename-header', methods=['POST'])
@login_required
def api_rename_header():
    """Rename a column header in a sheet (row 1 cell update)."""
    d = request.json
    table = d.get('table', '')
    old_name = d.get('old_name', '').strip()
    new_name = d.get('new_name', '').strip()
    if not table or not old_name or not new_name:
        return jsonify({'error': 'Table, old_name, and new_name required'}), 400
    # Safety: prevent renaming critical system columns
    protected = ['airtable id', 'system id', 'name', 'title']
    if cleanH(old_name).lower() in protected:
        return jsonify({'error': f'Cannot rename protected column: {cleanH(old_name)}'}), 400
    sn = 'Songs' if 'song' in table.lower() else 'Personnel'
    try:
        headers = sheets.get_headers(sn)
        if old_name not in headers:
            ci = find_col(headers, cleanH(old_name))
            if ci is not None: old_name = headers[ci]
            else: return jsonify({'error': 'Column not found'}), 400
        col_idx = headers.index(old_name) + 1
        sheets.update_cell(sn, 1, col_idx, new_name)
        sheets._invalidate_cache(sn)
        return jsonify({'success': True, 'old': old_name, 'new': new_name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/insert-column', methods=['POST'])
@login_required
def api_insert_column():
    """Insert a new column header in the sheet."""
    d = request.json
    table = d.get('table', '')
    name = d.get('name', '').strip()
    if not table or not name:
        return jsonify({'error': 'Table and name required'}), 400
    sn = 'Songs' if 'song' in table.lower() else ('Invoices' if 'invoice' in table.lower() else 'Personnel')
    try:
        headers = sheets.get_headers(sn)
        if name in headers or any(cleanH(h) == name for h in headers):
            return jsonify({'error': f'Column "{name}" already exists'}), 400
        col_idx = len(headers) + 1
        sheets.update_cell(sn, 1, col_idx, name)
        sheets._invalidate_cache(sn)
        return jsonify({'success': True, 'column': name, 'index': col_idx})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/delete-column', methods=['POST'])
@admin_required
def api_delete_column():
    """Permanently delete a column from the sheet."""
    d = request.json
    table = d.get('table', '')
    column_name = d.get('column_name', '').strip()
    if not table or not column_name:
        return jsonify({'error': 'Table and column_name required'}), 400
    sn = 'Songs' if 'song' in table.lower() else ('Invoices' if 'invoice' in table.lower() else 'Personnel')
    try:
        headers = sheets.get_headers(sn)
        # Find the column index
        col_idx = None
        for i, h in enumerate(headers):
            if h == column_name or cleanH(h) == cleanH(column_name):
                col_idx = i; break
        if col_idx is None:
            return jsonify({'error': f'Column not found: {column_name}'}), 400
        # Protect critical columns
        protected = ['airtable id', 'system id', 'title', 'name']
        if cleanH(headers[col_idx]).lower() in protected:
            return jsonify({'error': f'Cannot delete protected column: {cleanH(headers[col_idx])}'}), 400
        # Get sheet ID
        meta = sheets.service.spreadsheets().get(spreadsheetId=sheets.spreadsheet_id).execute()
        sheet_id = None
        for s in meta.get('sheets', []):
            if s['properties']['title'] == sn:
                sheet_id = s['properties']['sheetId']; break
        if sheet_id is None:
            return jsonify({'error': f'Sheet not found: {sn}'}), 400
        # Delete the column using batchUpdate
        sheets.service.spreadsheets().batchUpdate(
            spreadsheetId=sheets.spreadsheet_id,
            body={'requests': [{'deleteDimension': {'range': {
                'sheetId': sheet_id, 'dimension': 'COLUMNS',
                'startIndex': col_idx, 'endIndex': col_idx + 1
            }}}]}
        ).execute()
        sheets._invalidate_cache(sn)
        logging.info(f"Deleted column '{column_name}' (index {col_idx}) from {sn}")
        return jsonify({'success': True, 'deleted': cleanH(column_name)})
    except Exception as e:
        logging.exception('Delete column failed')
        return jsonify({'error': str(e)}), 500


@app.route('/api/resolver/rebuild', methods=['POST'])
@login_required
def api_resolver_rebuild():
    try:
        resolver.rebuild(); build_city_lookup(); build_name_cache()
        return jsonify({'success':True,'cache_size':len(resolver._cache),'cities':len(CITY_LOOKUP),'names':len(NAME_CACHE)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== PLAY LOG ====================
def _ensure_play_log_sheet():
    """Create Play Log sheet if it doesn't exist."""
    try:
        data = sheets.get_all_rows('Play Log')
        if data: return True
    except Exception as e:
        logging.warning(f'Play Log sheet check: {e}')
    try:
        sheets.create_new_sheet('Play Log')
        headers = ['Timestamp', 'Song', 'Playlist', 'Duration (s)', 'IP']
        sheets.service.spreadsheets().values().update(
            spreadsheetId=sheets.spreadsheet_id, range="'Play Log'!A1",
            valueInputOption='USER_ENTERED', body={'values': [headers]}
        ).execute()
        sheets._invalidate_cache('Play Log')
        return True
    except Exception as e:
        logging.warning(f'Play Log sheet create: {e}')
        return False

@app.route('/api/play-log', methods=['POST'])
def api_play_log():
    """Log a play event from the public playlist player."""
    if not rate_limit_check(max_per_hour=200):
        return jsonify({'error': 'Rate limited'}), 429
    d = request.json or {}
    song = d.get('song', '')
    playlist = d.get('playlist', '')
    duration = d.get('duration', 0)
    if not song: return jsonify({'error': 'Song required'}), 400
    try:
        _ensure_play_log_sheet()
        sheets.append_row('Play Log', [
            datetime.now().isoformat(),
            song,
            playlist,
            str(duration),
            _get_client_ip()
        ])
        return jsonify({'success': True})
    except Exception as e:
        logging.warning(f"Play log error: {e}")
        return jsonify({'success': True})  # Don't fail the client


# ==================== INVOICE OVERDUE SCANNER ====================
_overdue_lock = threading.Lock()

def scan_overdue_invoices():
    """Scan invoices and mark overdue ones. Runs on startup and every 60 min."""
    with _overdue_lock:
        try:
            data = sheets.get_all_rows('Invoices')
            if not data or len(data) < 2: return 0
            headers = data[0]; rows = data[1:]
            status_col = find_col(headers, 'status')
            due_col = find_col(headers, 'due date')
            if status_col is None or due_col is None: return 0
            count = 0
            for i, row in enumerate(rows):
                status = str(row[status_col]).strip() if status_col < len(row) else ''
                due_str = str(row[due_col]).strip() if due_col < len(row) else ''
                if status.lower() != 'sent' or not due_str: continue
                try:
                    due_date = None
                    for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y'):
                        try: due_date = datetime.strptime(due_str, fmt); break
                        except ValueError: pass
                    if due_date and due_date.date() < datetime.now().date():
                        sheets.update_cell('Invoices', i + 2, status_col + 1, 'Overdue')
                        count += 1
                except Exception as e:
                    logging.warning(f'Overdue invoice check: {e}')
            if count > 0:
                logging.info(f"Overdue scanner: marked {count} invoices as Overdue")
            return count
        except Exception as e:
            logging.warning(f"Overdue scanner error: {e}")
            return 0

def _overdue_timer():
    """Run overdue scanner every 60 minutes."""
    while True:
        time.sleep(3600)
        scan_overdue_invoices()


# ==================== INVOICE PDF GENERATOR ====================
INVOICE_ENTITIES = {
    'ROLLON ENT': {
        'name': 'ROLLON ENT LLC',
        'address': ['ROLLON ENT LLC', 'Los Angeles, CA', 'United States'],
        'email': 'celina@rollonent.com',
        'prefix': 'ROL'
    },
    'RESTLESS YOUTH': {
        'name': 'RESTLESS YOUTH LLC',
        'address': ['RESTLESS YOUTH LLC', 'Los Angeles, CA', 'United States'],
        'email': 'celina@rollonent.com',
        'prefix': 'RYE'
    },
    'Tyber Heart Limited': {
        'name': 'Tyber Heart Limited',
        'address': ['Tyber Heart Limited', 'London', 'United Kingdom'],
        'email': 'celina@rollonent.com',
        'prefix': 'TYB'
    }
}

@app.route('/api/invoices/pdf/<int:ri>')
@admin_required
def api_invoice_pdf(ri):
    """Generate branded PDF for an invoice."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib.colors import HexColor
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    except ImportError:
        return jsonify({'error': 'reportlab not installed. pip install reportlab'}), 500

    try:
        data = sheets.get_all_rows('Invoices')
        if not data or len(data) < 2: return jsonify({'error': 'No invoices'}), 404
        headers = data[0]
        row = sheets.get_row('Invoices', ri)
        rec = {}
        for j, h in enumerate(headers):
            rec[cleanH(h)] = row[j] if j < len(row) else ''

        entity_name = rec.get('Entity', 'ROLLON ENT')
        entity = INVOICE_ENTITIES.get(entity_name, INVOICE_ENTITIES['ROLLON ENT'])

        # Generate PDF
        os.makedirs(os.path.join(os.path.dirname(__file__), 'static', 'invoices'), exist_ok=True)
        inv_no = rec.get('Invoice No', f'INV-{ri}')
        filename = f"invoice_{inv_no.replace('/', '-')}.pdf"
        filepath = os.path.join(os.path.dirname(__file__), 'static', 'invoices', filename)

        doc = SimpleDocTemplate(filepath, pagesize=letter, topMargin=0.75*inch, bottomMargin=0.75*inch)
        styles = getSampleStyleSheet()
        accent = HexColor('#d4a853')
        dark = HexColor('#1a1a1a')
        muted = HexColor('#666666')

        title_s = ParagraphStyle('InvTitle', parent=styles['Title'], fontSize=28, textColor=dark, fontName='Helvetica-Bold', spaceAfter=4)
        entity_s = ParagraphStyle('Entity', parent=styles['Normal'], fontSize=14, textColor=accent, fontName='Helvetica-Bold', spaceAfter=2)
        addr_s = ParagraphStyle('Addr', parent=styles['Normal'], fontSize=10, textColor=muted, spaceAfter=1)
        label_s = ParagraphStyle('Label', parent=styles['Normal'], fontSize=9, textColor=muted, fontName='Helvetica-Bold')
        val_s = ParagraphStyle('Val', parent=styles['Normal'], fontSize=11, textColor=dark)
        note_s = ParagraphStyle('Note', parent=styles['Normal'], fontSize=10, textColor=muted, spaceBefore=20)

        story = []
        story.append(Paragraph('INVOICE', title_s))
        story.append(Paragraph(entity['name'], entity_s))
        for line in entity['address']:
            story.append(Paragraph(line, addr_s))
        story.append(Spacer(1, 20))

        # Invoice details table
        inv_data = [
            ['Invoice No:', inv_no],
            ['Date:', rec.get('Date', '')],
            ['Due Date:', rec.get('Due Date', '')],
            ['Status:', rec.get('Status', 'Draft')],
        ]
        t = Table(inv_data, colWidths=[100, 300])
        t.setStyle(TableStyle([
            ('FONT', (0, 0), (0, -1), 'Helvetica-Bold', 9),
            ('FONT', (1, 0), (1, -1), 'Helvetica', 11),
            ('TEXTCOLOR', (0, 0), (0, -1), muted),
            ('TEXTCOLOR', (1, 0), (1, -1), dark),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(t)
        story.append(Spacer(1, 16))

        # Bill To
        story.append(Paragraph('BILL TO', label_s))
        story.append(Paragraph(rec.get('Client', '-'), val_s))
        story.append(Spacer(1, 16))

        # Description & Amount
        desc_data = [
            ['Description', 'Amount'],
            [rec.get('Description', '-'), f"{rec.get('Currency', 'USD')} {rec.get('Amount', '0.00')}"],
        ]
        dt = Table(desc_data, colWidths=[350, 130])
        dt.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 9),
            ('FONT', (0, 1), (-1, -1), 'Helvetica', 11),
            ('TEXTCOLOR', (0, 0), (-1, 0), muted),
            ('TEXTCOLOR', (0, 1), (-1, -1), dark),
            ('LINEBELOW', (0, 0), (-1, 0), 1, HexColor('#cccccc')),
            ('LINEBELOW', (0, -1), (-1, -1), 1, accent),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ]))
        story.append(dt)
        story.append(Spacer(1, 20))

        # Total
        story.append(Paragraph(f"TOTAL: {rec.get('Currency', 'USD')} {rec.get('Amount', '0.00')}", ParagraphStyle(
            'Total', parent=styles['Normal'], fontSize=16, textColor=accent, fontName='Helvetica-Bold', alignment=2)))

        if rec.get('Notes'):
            story.append(Spacer(1, 20))
            story.append(Paragraph(f"Notes: {rec['Notes']}", note_s))

        # Category
        if rec.get('Category'):
            story.append(Paragraph(f"Category: {rec['Category']}", note_s))

        doc.build(story)
        return send_from_directory(os.path.join(os.path.dirname(__file__), 'static', 'invoices'), filename, as_attachment=True)
    except Exception as e:
        logging.exception('Invoice PDF failed')
        return jsonify({'error': str(e)}), 500


# ==================== INVOICE SEND REMINDER ====================
@app.route('/api/invoices/send-reminder', methods=['POST'])
@admin_required
def api_invoice_send_reminder():
    """Send reminder email for overdue invoice."""
    d = request.json or {}
    ri = d.get('row_index')
    if not ri: return jsonify({'error': 'row_index required'}), 400
    try:
        data = sheets.get_all_rows('Invoices')
        if not data or len(data) < 2: return jsonify({'error': 'No invoices'}), 404
        headers = data[0]
        row = sheets.get_row('Invoices', ri)
        rec = {}
        for j, h in enumerate(headers):
            rec[cleanH(h)] = row[j] if j < len(row) else ''

        client = rec.get('Client', '')
        inv_no = rec.get('Invoice No', '')
        amount = rec.get('Amount', '')
        currency = rec.get('Currency', 'USD')
        due_date = rec.get('Due Date', '')
        entity = rec.get('Entity', 'ROLLON ENT')

        # Find client email from Personnel
        client_email = ''
        if client:
            per_data = sheets.get_all_rows('Personnel')
            if per_data and len(per_data) > 1:
                per_h = per_data[0]
                nc = find_col(per_h, 'name')
                ec = find_col(per_h, 'email')
                if nc is not None and ec is not None:
                    for pr in per_data[1:]:
                        if nc < len(pr) and pr[nc].strip().lower() == client.lower():
                            client_email = pr[ec].strip() if ec < len(pr) else ''
                            break

        if not client_email:
            return jsonify({'error': f'No email found for client: {client}'}), 400

        # Send reminder via SMTP
        if not SMTP_PASS:
            return jsonify({'error': 'SMTP not configured'}), 400

        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'Payment Reminder — Invoice {inv_no}'
        msg['From'] = SMTP_FROM
        msg['To'] = client_email

        body = f"""Hi {client},

This is a friendly reminder that Invoice {inv_no} for {currency} {amount} was due on {due_date}.

Please let us know if you have any questions or need updated payment details.

Best regards,
{entity}
{SMTP_FROM}"""

        msg.attach(MIMEText(body, 'plain'))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, client_email, msg.as_string())

        return jsonify({'success': True, 'sent_to': client_email})
    except Exception as e:
        logging.exception('Invoice reminder failed')
        return jsonify({'error': str(e)}), 500


# ==================== INVOICE DUPLICATE ====================
@app.route('/api/invoices/duplicate', methods=['POST'])
@admin_required
def api_invoice_duplicate():
    """Duplicate an invoice for recurring retainers."""
    d = request.json or {}
    ri = d.get('row_index')
    if not ri: return jsonify({'error': 'row_index required'}), 400
    try:
        data = sheets.get_all_rows('Invoices')
        if not data or len(data) < 2: return jsonify({'error': 'No invoices'}), 404
        headers = data[0]
        row = sheets.get_row('Invoices', ri)
        rec = {}
        for j, h in enumerate(headers):
            rec[cleanH(h)] = row[j] if j < len(row) else ''

        # Copy key fields, new date and number
        entity = rec.get('Entity', 'ROLLON ENT')
        prefix = 'RYE' if 'restless' in entity.lower() else ('TYB' if 'tyber' in entity.lower() else 'ROL')

        # Auto-number: find highest existing number for this prefix
        no_col = find_col(headers, 'invoice no')
        max_num = 0
        if no_col is not None:
            for r in data[1:]:
                if no_col < len(r):
                    ino = str(r[no_col]).strip()
                    if ino.startswith(prefix + '-'):
                        try: max_num = max(max_num, int(ino[len(prefix)+1:]))
                        except ValueError: pass
        new_no = f"{prefix}-{max_num + 1:03d}"

        new_row = [''] * len(headers)
        for j, h in enumerate(headers):
            ch = cleanH(h).lower()
            if ch == 'invoice no': new_row[j] = new_no
            elif ch == 'date': new_row[j] = datetime.now().strftime('%Y-%m-%d')
            elif ch == 'due date': new_row[j] = (datetime.now() + timedelta(days=14)).strftime('%Y-%m-%d')
            elif ch == 'status': new_row[j] = 'Draft'
            elif ch == 'payment date': new_row[j] = ''
            elif ch in ('system id', 'airtable id'):
                new_row[j] = next_system_id()
            else:
                new_row[j] = row[j] if j < len(row) else ''

        sheets.append_row('Invoices', new_row)
        return jsonify({'success': True, 'invoice_no': new_no})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== INVOICE FOLLOW-UP FLAGS ====================
@app.route('/api/invoices/flags')
@admin_required
def api_invoice_flags():
    """Get follow-up flag status for invoices."""
    try:
        data = sheets.get_all_rows('Invoices')
        if not data or len(data) < 2: return jsonify({'flags': {}})
        headers = data[0]
        status_col = find_col(headers, 'status')
        due_col = find_col(headers, 'due date')
        no_col = find_col(headers, 'invoice no')
        if status_col is None or due_col is None: return jsonify({'flags': {}})

        flags = {}
        now = datetime.now()
        for i, row in enumerate(data[1:]):
            status = str(row[status_col]).strip().lower() if status_col < len(row) else ''
            if status not in ('sent', 'overdue'): continue
            due_str = str(row[due_col]).strip() if due_col < len(row) else ''
            if not due_str: continue
            try:
                due_date = None
                for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y'):
                    try: due_date = datetime.strptime(due_str, fmt); break
                    except ValueError: pass
                if not due_date: continue
                days_overdue = (now - due_date).days
                if days_overdue <= 0: continue
                inv_no = str(row[no_col]).strip() if no_col is not None and no_col < len(row) else str(i + 2)
                if days_overdue >= 30: color = 'red'
                elif days_overdue >= 14: color = 'orange'
                elif days_overdue >= 7: color = 'yellow'
                else: continue
                flags[inv_no] = {'days': days_overdue, 'color': color, 'row_index': i + 2}
            except Exception as e:
                logging.warning(f'Follow-up flag parse: {e}')
        return jsonify({'flags': flags})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== DISTRIBUTION SYSTEM ====================
def _ensure_dist_log():
    """Create Distribution Log sheet if it doesn't exist."""
    try:
        data = sheets.get_all_rows('Distribution Log')
        if data: return True
    except Exception as e:
        logging.warning(f'Distribution Log sheet check: {e}')
    try:
        sheets.create_new_sheet('Distribution Log')
        headers = ['Date', 'Channel', 'Recipient', 'Song Count', 'Song Titles', 'Status']
        sheets.service.spreadsheets().values().update(
            spreadsheetId=sheets.spreadsheet_id, range="'Distribution Log'!A1",
            valueInputOption='USER_ENTERED', body={'values': [headers]}
        ).execute()
        sheets._invalidate_cache('Distribution Log')
        return True
    except Exception as e:
        logging.warning(f'Distribution Log sheet create: {e}')
        return False

@app.route('/api/distribution/send', methods=['POST'])
@admin_required
def api_distribution_send():
    """Send distribution CSV (Rightsbridge, Sync, or custom channel)."""
    d = request.json or {}
    channel = d.get('channel', 'Rightsbridge')
    song_indices = d.get('song_indices', [])
    recipient_email = d.get('recipient', '')
    fields = d.get('fields', [])
    recipients = d.get('recipients', [])  # For sync: list of contact names/emails

    if not song_indices:
        return jsonify({'error': 'No songs selected'}), 400

    try:
        song_data = sheets.get_all_rows('Songs')
        if not song_data or len(song_data) < 2:
            return jsonify({'error': 'No songs data'}), 400
        headers = song_data[0]

        # Default field sets per channel
        if not fields:
            if channel == 'Rightsbridge':
                fields = ['Title', 'Artist', 'Songwriter Credits', 'Producer', 'ISRC', 'Duration', 'BPM', 'Release Date', 'Audio Status', 'Genre', 'Record Label', 'Dropbox Link']
            elif channel == 'Sync':
                fields = ['Title', 'Artist', 'Genre', 'BPM', 'Duration', 'Audio Status', 'Mood', 'Instrumentation', 'Dropbox Link', 'DISCO', 'Sync Notes', 'Songwriter Credits', 'Producer', 'ISRC']
            else:
                fields = ['Title', 'Artist', 'Genre', 'Audio Status', 'Dropbox Link']

        # Build CSV
        field_cols = []
        for fn in fields:
            col = find_col(headers, fn)
            if col is not None:
                field_cols.append((fn, col))

        csv_header = ','.join([f'"{fn}"' for fn, _ in field_cols])
        csv_rows = []
        song_titles = []
        for ri in song_indices:
            row = sheets.get_row('Songs', ri)
            vals = []
            for fn, ci in field_cols:
                v = str(row[ci]).strip() if ci < len(row) else ''
                # Convert Dropbox links to direct download
                if 'dropbox' in fn.lower() and 'dl=0' in v:
                    v = v.replace('dl=0', 'dl=1')
                vals.append('"' + v.replace('"', '""') + '"')
            csv_rows.append(','.join(vals))
            # Get title for logging
            tc = find_col(headers, 'title')
            title = str(row[tc]).strip() if tc is not None and tc < len(row) else f'Row {ri}'
            song_titles.append(title)

        csv_content = csv_header + '\n' + '\n'.join(csv_rows) + '\n\n"Generated by ROLLON AR | rollonent.com"\n'

        # Tag songs with distribution marker
        tag_col = find_col(headers, 'tag')
        date_str = datetime.now().strftime('%Y-%m-%d')
        tag_label = f"Sent to {channel} {date_str}"
        if tag_col is not None:
            updates = []
            for ri in song_indices:
                row = sheets.get_row('Songs', ri)
                existing = str(row[tag_col]).strip() if tag_col < len(row) else ''
                tags = split_tags(existing)
                if tag_label not in tags:
                    tags.append(tag_label)
                    updates.append((ri, tag_col + 1, ' | '.join(tags)))
            if updates:
                sheets.batch_update_cells('Songs', updates)

        # Log to Distribution Log
        _ensure_dist_log()
        recipient_str = recipient_email or ', '.join(recipients)
        sheets.append_row('Distribution Log', [
            date_str, channel, recipient_str,
            str(len(song_indices)),
            ' | '.join(song_titles[:20]),
            'Sent'
        ])

        # Email CSV if SMTP configured and recipient provided
        email_sent = False
        if SMTP_PASS and recipient_email:
            try:
                import smtplib
                from email.mime.text import MIMEText
                from email.mime.multipart import MIMEMultipart
                from email.mime.base import MIMEBase
                from email import encoders

                msg = MIMEMultipart()
                msg['Subject'] = f'ROLLON AR - {channel} Distribution ({len(song_indices)} songs)'
                msg['From'] = SMTP_FROM
                msg['To'] = recipient_email
                msg.attach(MIMEText(f'{channel} distribution: {len(song_indices)} songs attached.\n\nGenerated by ROLLON AR', 'plain'))

                att = MIMEBase('application', 'octet-stream')
                att.set_payload(csv_content.encode('utf-8'))
                encoders.encode_base64(att)
                att.add_header('Content-Disposition', f'attachment; filename="rollon_{channel.lower().replace(" ", "_")}_{date_str}.csv"')
                msg.attach(att)

                with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                    server.starttls()
                    server.login(SMTP_USER, SMTP_PASS)
                    server.sendmail(SMTP_FROM, recipient_email, msg.as_string())
                email_sent = True
            except Exception as e:
                logging.warning(f"Distribution email failed: {e}")

        return jsonify({
            'success': True,
            'songs': len(song_indices),
            'channel': channel,
            'tag': tag_label,
            'email_sent': email_sent,
            'csv': csv_content
        })
    except Exception as e:
        logging.exception('Distribution send failed')
        return jsonify({'error': str(e)}), 500


# ==================== SMART DEFAULTS (Intelligence) ====================
@app.route('/api/smart-defaults')
@login_required
def api_smart_defaults():
    """Get smart suggestions for a producer or writer based on historical data."""
    name = request.args.get('name', '').strip()
    if not name:
        return jsonify({'genres': [], 'cowriters': []})
    try:
        data = sheets.get_all_rows('Songs')
        if not data or len(data) < 2:
            return jsonify({'genres': [], 'cowriters': []})
        headers = data[0]
        pc = find_col(headers, 'producer')
        sc = find_col(headers, 'songwriter credits')
        gc = find_col(headers, 'genre')
        nl = name.lower()

        genres = {}
        cowriters = {}
        for row in data[1:]:
            # Check if this person is credited
            prod = str(row[pc]).strip().lower() if pc is not None and pc < len(row) else ''
            writers = str(row[sc]).strip().lower() if sc is not None and sc < len(row) else ''
            if nl not in prod and nl not in writers:
                continue
            # Collect genres
            if gc is not None and gc < len(row):
                for g in split_tags(row[gc]):
                    genres[g] = genres.get(g, 0) + 1
            # Collect co-writers
            if sc is not None and sc < len(row):
                for w in split_tags(row[sc]):
                    wl = w.strip()
                    if wl.lower() != nl:
                        cowriters[wl] = cowriters.get(wl, 0) + 1

        top_genres = sorted(genres.items(), key=lambda x: -x[1])[:5]
        top_cowriters = sorted(cowriters.items(), key=lambda x: -x[1])[:5]
        return jsonify({
            'genres': [g for g, _ in top_genres],
            'cowriters': [w for w, _ in top_cowriters]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== MORNING BRIEFING (Intelligence) ====================
@app.route('/api/briefing')
@login_required
def api_briefing():
    """Morning briefing: stale songs, follow-ups, upcoming invoices, new submissions."""
    result = {}
    try:
        now = datetime.now()

        # Stale songs (no activity in 30 days)
        song_data = sheets.get_all_rows('Songs')
        if song_data and len(song_data) > 1:
            sh = song_data[0]
            lm_col = find_col(sh, 'last modified')
            ti_col = find_col(sh, 'title')
            stale = []
            if lm_col is not None and ti_col is not None:
                for i, row in enumerate(song_data[1:]):
                    title = str(row[ti_col]).strip() if ti_col < len(row) else ''
                    lm = str(row[lm_col]).strip() if lm_col < len(row) else ''
                    if not title or not lm: continue
                    try:
                        for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%Y-%m-%dT%H:%M'):
                            try: d = datetime.strptime(lm, fmt); break
                            except Exception as e: d = None
                        if d and (now - d).days > 30:
                            stale.append({'title': title, 'days': (now - d).days, 'row_index': i + 2})
                    except Exception as e:
                        logging.warning(f'Stale song parse: {e}')
                stale.sort(key=lambda x: -x['days'])
                result['stale_songs'] = stale[:10]

        # Upcoming invoice deadlines (7 days)
        try:
            inv_data = sheets.get_all_rows('Invoices')
            if inv_data and len(inv_data) > 1:
                ih = inv_data[0]
                due_col = find_col(ih, 'due date')
                no_col = find_col(ih, 'invoice no')
                st_col = find_col(ih, 'status')
                cl_col = find_col(ih, 'client')
                am_col = find_col(ih, 'amount')
                upcoming_inv = []
                if due_col is not None:
                    for row in inv_data[1:]:
                        status = str(row[st_col]).strip().lower() if st_col is not None and st_col < len(row) else ''
                        if status in ('paid', 'draft'): continue
                        due_str = str(row[due_col]).strip() if due_col < len(row) else ''
                        if not due_str: continue
                        try:
                            due = None
                            for fmt in ('%Y-%m-%d', '%m/%d/%Y'):
                                try: due = datetime.strptime(due_str, fmt); break
                                except Exception as e: pass
                            if due and 0 <= (due - now).days <= 7:
                                inv_no = str(row[no_col]).strip() if no_col is not None and no_col < len(row) else ''
                                client = str(row[cl_col]).strip() if cl_col is not None and cl_col < len(row) else ''
                                amount = str(row[am_col]).strip() if am_col is not None and am_col < len(row) else ''
                                upcoming_inv.append({'invoice_no': inv_no, 'client': client, 'amount': amount, 'days': (due - now).days})
                        except Exception as e:
                            logging.warning(f'Upcoming invoice parse: {e}')
                result['upcoming_invoices'] = upcoming_inv
        except Exception as e:
            logging.warning(f'Upcoming invoices fetch: {e}')

        # Overdue count
        try:
            overdue_count = 0
            overdue_amount = 0
            if inv_data and len(inv_data) > 1:
                for row in inv_data[1:]:
                    status = str(row[st_col]).strip().lower() if st_col is not None and st_col < len(row) else ''
                    if status == 'overdue':
                        overdue_count += 1
                        try: overdue_amount += float(str(row[am_col]).replace(',','').replace('$','')) if am_col is not None and am_col < len(row) else 0
                        except Exception as e: pass
            result['overdue_invoices'] = {'count': overdue_count, 'amount': round(overdue_amount, 2)}
        except Exception as e:
            logging.warning(f'Overdue invoice count: {e}')

        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== SCOUT (Intelligence Engine) ====================
SCOUT_HEADERS = ['Type', 'Name', 'Genre', 'City', 'Listeners', 'Growth', 'Social',
                 'Notes', 'Tags', 'Status', 'Headliner', 'Dates', 'Cities', 'Venue',
                 'Capacity', 'Agent Contact', 'Project', 'Supervisor', 'Mood',
                 'Deadline', 'Date Added']

def _ensure_scout_sheet():
    """Create Scout Leads sheet if it doesn't exist."""
    try:
        data = sheets.get_all_rows('Scout Leads')
        if data: return True
    except Exception as e:
        logging.warning(f'Scout Leads sheet check: {e}')
    try:
        sheets.create_new_sheet('Scout Leads')
        sheets.service.spreadsheets().values().update(
            spreadsheetId=sheets.spreadsheet_id, range="'Scout Leads'!A1",
            valueInputOption='USER_ENTERED', body={'values': [SCOUT_HEADERS]}
        ).execute()
        sheets._invalidate_cache('Scout Leads')
        return True
    except Exception as e:
        logging.warning(f"Scout sheet creation failed: {e}")
        return False

@app.route('/scout')
@admin_required
def scout_page():
    return render_template('scout.html')

@app.route('/api/scout')
@admin_required
def api_scout():
    """Get all scout leads, cross-referenced with Directory."""
    _ensure_scout_sheet()
    try:
        data = sheets.get_all_rows('Scout Leads')
        if not data or len(data) < 2:
            return jsonify({'artists': [], 'tours': [], 'syncs': []})

        headers = data[0]
        rows = data[1:]

        # Build name lookup from Personnel for cross-referencing
        dir_names = set()
        try:
            per_data = sheets.get_all_rows('Personnel')
            if per_data and len(per_data) > 1:
                nc = find_col(per_data[0], 'name')
                if nc is not None:
                    for r in per_data[1:]:
                        if nc < len(r) and r[nc].strip():
                            dir_names.add(r[nc].strip().lower())
        except Exception as e:
            logging.warning(f'Directory names lookup: {e}')

        # Build music supervisor lookup for sync brief cross-referencing
        music_sups = set()
        try:
            if per_data and len(per_data) > 1:
                fc = find_col(per_data[0], 'field')
                nc2 = find_col(per_data[0], 'name')
                if fc is not None and nc2 is not None:
                    for r in per_data[1:]:
                        field_val = str(r[fc]).lower() if fc < len(r) else ''
                        if 'music supervisor' in field_val or 'sync' in field_val:
                            if nc2 < len(r) and r[nc2].strip():
                                music_sups.add(r[nc2].strip().lower())
        except Exception as e:
            logging.warning(f'Music supervisor lookup: {e}')

        artists, tours, syncs = [], [], []
        for i, row in enumerate(rows):
            rec = {}
            for j, h in enumerate(headers):
                rec[cleanH(h).lower().replace(' ', '_')] = row[j].strip() if j < len(row) else ''
            rec['row_index'] = i + 2

            name = rec.get('name', '')
            rec['in_directory'] = name.lower() in dir_names if name else False

            lead_type = rec.get('type', '').lower()

            if lead_type == 'artist':
                rec['warm_lead'] = rec['in_directory']
                artists.append(rec)
            elif lead_type == 'tour':
                # Check if headliner's agent/manager is in our Directory
                headliner = rec.get('headliner', '')
                agent = rec.get('agent_contact', '')
                rec['warm_lead'] = (headliner.lower() in dir_names or agent.lower() in dir_names) if (headliner or agent) else False
                tours.append(rec)
            elif lead_type == 'sync':
                # Check if supervisor is in our Directory
                sup = rec.get('supervisor', '')
                rec['warm_lead'] = sup.lower() in music_sups if sup else False
                syncs.append(rec)

        return jsonify({'artists': artists, 'tours': tours, 'syncs': syncs})
    except Exception as e:
        logging.warning(f"Scout API error: {e}")
        return jsonify({'artists': [], 'tours': [], 'syncs': [], 'error': str(e)})


@app.route('/api/scout/add', methods=['POST'])
@admin_required
def api_scout_add():
    """Add a new scout lead."""
    _ensure_scout_sheet()
    d = request.json or {}
    name = d.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    try:
        headers = sheets.get_headers('Scout Leads')
        row = [''] * len(headers)
        # Map incoming fields to sheet columns
        field_map = {
            'type': 'Type', 'name': 'Name', 'genre': 'Genre', 'city': 'City',
            'listeners': 'Listeners', 'growth': 'Growth', 'social': 'Social',
            'notes': 'Notes', 'tags': 'Tags', 'status': 'Status',
            'headliner': 'Headliner', 'dates': 'Dates', 'cities': 'Cities',
            'venue': 'Venue', 'capacity': 'Capacity', 'agent_contact': 'Agent Contact',
            'project': 'Project', 'supervisor': 'Supervisor', 'mood': 'Mood',
            'deadline': 'Deadline'
        }
        for json_key, sheet_col in field_map.items():
            if json_key in d and d[json_key]:
                ci = find_col(headers, sheet_col)
                if ci is not None:
                    row[ci] = str(d[json_key]).strip()
        # Set status default
        status_col = find_col(headers, 'status')
        if status_col is not None and not row[status_col]:
            row[status_col] = 'New'
        # Date added
        da_col = find_col(headers, 'date added')
        if da_col is not None:
            row[da_col] = datetime.now().strftime('%Y-%m-%d')

        sheets.append_row('Scout Leads', row)
        return jsonify({'success': True, 'name': name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/scout/update', methods=['POST'])
@admin_required
def api_scout_update():
    """Update a scout lead field."""
    d = request.json or {}
    ri = d.get('row_index')
    field = d.get('field', '')
    value = d.get('value', '')
    if not ri or not field:
        return jsonify({'error': 'row_index and field required'}), 400
    try:
        headers = sheets.get_headers('Scout Leads')
        ci = find_col(headers, field)
        if ci is None:
            return jsonify({'error': f'Field {field} not found'}), 400
        sheets.update_cell('Scout Leads', ri, ci + 1, value)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/scout/to-directory', methods=['POST'])
@admin_required
def api_scout_to_directory():
    """Convert a scout artist lead to a Personnel record."""
    d = request.json or {}
    ri = d.get('row_index')
    if not ri:
        return jsonify({'error': 'row_index required'}), 400
    try:
        scout_headers = sheets.get_headers('Scout Leads')
        row = sheets.get_row('Scout Leads', ri)
        rec = {}
        for j, h in enumerate(scout_headers):
            rec[cleanH(h).lower().replace(' ', '_')] = row[j].strip() if j < len(row) else ''

        name = rec.get('name', '')
        if not name:
            return jsonify({'error': 'No name on this lead'}), 400

        # Check for duplicates
        per_data = sheets.get_all_rows('Personnel')
        if per_data and len(per_data) > 1:
            nc = find_col(per_data[0], 'name')
            if nc is not None:
                for r in per_data[1:]:
                    if nc < len(r) and r[nc].strip().lower() == name.lower():
                        # Already exists - update status and return
                        status_col = find_col(scout_headers, 'status')
                        if status_col is not None:
                            sheets.update_cell('Scout Leads', ri, status_col + 1, 'In Directory')
                        return jsonify({'success': True, 'name': name, 'note': 'Already in Directory'})

        # Create new Personnel record
        per_headers = sheets.get_headers('Personnel')
        new_row = [''] * len(per_headers)

        # Map scout fields to Personnel fields
        nc = find_col(per_headers, 'name')
        if nc is not None: new_row[nc] = name
        gc = find_col(per_headers, 'genre')
        if gc is not None: new_row[gc] = rec.get('genre', '')
        cc = find_col(per_headers, 'city')
        if cc is not None: new_row[cc] = rec.get('city', '')
        fc = find_col(per_headers, 'field')
        if fc is not None: new_row[fc] = 'Artist'
        tc = find_col(per_headers, 'tags')
        if tc is not None:
            tags = rec.get('tags', 'Scout Target | Songwriting')
            new_row[tc] = tags

        # System ID
        id_col = find_col(per_headers, 'airtable id', 'system id')
        if id_col is not None:
            new_row[id_col] = next_system_id()
        # LinkedIn/Socials from social field
        lc = find_col(per_headers, 'linkedin/socials', 'linkedin', 'website')
        if lc is not None: new_row[lc] = rec.get('social', '')

        sheets.append_row('Personnel', new_row)
        build_name_cache()  # Rebuild so the new person appears immediately

        # Update scout lead status
        status_col = find_col(scout_headers, 'status')
        if status_col is not None:
            sheets.update_cell('Scout Leads', ri, status_col + 1, 'In Directory')

        return jsonify({'success': True, 'name': name, 'id': new_row[id_col] if id_col else ''})
    except Exception as e:
        logging.exception('Scout to directory failed')
        return jsonify({'error': str(e)}), 500


@app.route('/api/scout/count')
@admin_required
def api_scout_count():
    """Get count of new scout leads for badge."""
    try:
        data = sheets.get_all_rows('Scout Leads')
        if not data or len(data) < 2:
            return jsonify({'count': 0})
        headers = data[0]
        sc = find_col(headers, 'status')
        count = 0
        for row in data[1:]:
            status = str(row[sc]).strip().lower() if sc is not None and sc < len(row) else 'new'
            if status == 'new':
                count += 1
        return jsonify({'count': count})
    except Exception as e:
        logging.warning(f'Scout leads count: {e}')
        return jsonify({'count': 0})


@app.errorhandler(404)
def not_found(e): return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e): return render_template('500.html'), 500

if __name__ == '__main__':
    print("Building ID resolver cache...")
    try: resolver.rebuild(); print(f"  Cached {len(resolver._cache)} record IDs")
    except Exception as e: print(f"  Warning: {e}")
    print("Building city lookup...")
    try: build_city_lookup(); print(f"  Loaded {len(CITY_LOOKUP)} cities")
    except Exception as e: print(f"  Warning: {e}")
    print("Building name cache...")
    try: build_name_cache()
    except Exception as e: print(f"  Warning: {e}")

    print("Scanning overdue invoices...")
    try:
        overdue_count = scan_overdue_invoices()
        print(f"  Marked {overdue_count} invoices as overdue")
    except Exception as e: print(f"  Warning: {e}")

    # Start overdue scanner background thread
    overdue_thread = threading.Thread(target=_overdue_timer, daemon=True)
    overdue_thread.start()

    # Start cleanup thread (rate limiter, playlist views, edit tokens)
    cleanup_thread = threading.Thread(target=_cleanup_thread_func, daemon=True)
    cleanup_thread.start()

    # Lazy rebuild: if resolver has 0 entries, retry on first request
    @app.before_request
    def _lazy_rebuild():
        if len(resolver._cache) == 0:
            try:
                resolver.rebuild()
                build_city_lookup()
                build_name_cache()
                print(f"  Lazy rebuild: {len(resolver._cache)} IDs, {len(CITY_LOOKUP)} cities, {len(NAME_CACHE)} names")
            except Exception as e:
                logging.warning(f"Lazy rebuild failed: {e}")
        # Remove this hook after first successful rebuild
        if len(resolver._cache) > 0:
            app.before_request_funcs[None] = [f for f in app.before_request_funcs.get(None, []) if f != _lazy_rebuild]

    # Fix 7: Use gunicorn if available, fall back to Flask dev server
    try:
        import gunicorn
        print("Starting with gunicorn (1 worker, 4 threads)...")
        import subprocess, sys
        subprocess.Popen([sys.executable, '-m', 'gunicorn', '-w', '1', '--threads', '4',
                         '-b', '0.0.0.0:5001', 'app:app'])
    except ImportError:
        print("gunicorn not installed, using Flask dev server (pip install gunicorn for production)")
        app.run(host='0.0.0.0', port=5001, threaded=True)
