"""
ROLLON AR v37.3 - A&R Operating System (Airtable parity rebuild)
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
from modules.scout_engine import (ScoutDiscovery, get_roster_artists, get_artist_profile,
    get_artist_songs, find_warm_connections as scout_warm_connections)
from modules.relationships import RelationshipsEngine, LINK_TYPES as RELATIONSHIP_LINK_TYPES
from modules.timezone_map import (resolve_timezone as tz_resolve,
    parse_iso as tz_parse_iso, to_la_from_sheet as tz_to_la,
    to_zone_wall_clock as tz_to_zone, LA as TZ_LA,
    CITY_IANA_MAP, COUNTRY_DEFAULT_TZ)

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
relationships = RelationshipsEngine(sheets)

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
    # Refresh endpoint is CSRF-exempt but still requires authentication;
    # it hands back a fresh token for the client to retry a failed request.
    if request.path == '/api/csrf/refresh':
        return
    token = request.headers.get('X-CSRF-Token', '')
    if not token or token != session.get('csrf_token', ''):
        return jsonify({'error': 'CSRF token missing or invalid'}), 403


@app.route('/api/csrf/refresh', methods=['POST', 'GET'])
def api_csrf_refresh():
    """Return a fresh CSRF token for the authenticated session.
    Called by the client-side fetch wrapper when a prior request fails
    with 403 because the token in window was stale (e.g. session was
    refreshed in another tab). Replies with 401 when the user is logged
    out so the client can redirect to /login."""
    if not session.get('authenticated'):
        return jsonify({'error': 'not authenticated'}), 401
    import secrets as _secrets
    session['csrf_token'] = _secrets.token_urlsafe(32)
    return jsonify({'csrf_token': session['csrf_token']})


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

# v37.3: strip ALL bracket markers including [USE], [LU], [Sync] so "Combined
# First Names [USE]" resolves as "Combined First Names".
_CLEAN_H_FULL_RE = re.compile(r'\[\s*[✓✗∅?]+\s*\]\s*|\[USE\]\s*|\[LU\]\s*|\[Sync\]\s*')
def cleanH_full(h):
    return _CLEAN_H_FULL_RE.sub('', h or '').strip()

# v37.3: filter column aliases — user-typed name -> sheet header (case insensitive)
COLUMN_ALIASES = {
    'country': 'Countries',
    'manager': 'MGMT Rep',
    'a&r rep': 'Record Label A&R',
    'ar rep': 'Record Label A&R',
    'first name': 'Combined First Names',
    'email address': 'Email',
    'emails': 'Email',
    'role': 'Field',
}

# v37.3: value aliases per column (country codes -> full names for smoke tests)
COUNTRY_ALIASES = {
    'uk': 'united kingdom',
    'gb': 'united kingdom',
    'us': 'united states',
    'usa': 'united states',
    'eng': 'united kingdom',
}
VALUE_ALIASES = {
    'countries': COUNTRY_ALIASES,
    'country': COUNTRY_ALIASES,
}

_MULTI_SPLIT_RE = re.compile(r'[|,;]')

def _split_multi_cell(cell):
    """v37.3: split a cell value on [|,;] with optional whitespace, trim each
    piece, lowercase. Used for multi-value matching."""
    if not cell:
        return []
    return [p.strip().lower() for p in _MULTI_SPLIT_RE.split(str(cell)) if p.strip()]

def _apply_value_aliases(col_name, values):
    """If the column has a value alias map (e.g. country codes), map each
    filter value through it. Case insensitive."""
    if not col_name:
        return values
    aliases = VALUE_ALIASES.get(col_name.lower()) or VALUE_ALIASES.get(cleanH_full(col_name).lower())
    if not aliases:
        return values
    return [aliases.get(v.lower(), v) for v in values]

def resolve_filter_col(headers, col_name):
    """v37.3: resolve a user-typed column name to a sheet header index.
    Honours COLUMN_ALIASES. Returns (idx, canonical_name) or (None, '')."""
    if not col_name:
        return None, ''
    raw = col_name.strip()
    # Apply alias
    canonical = COLUMN_ALIASES.get(raw.lower(), raw)
    cn = canonical.lower()
    # Pass 1: exact cleanH match
    for j, h in enumerate(headers):
        if cleanH(h).lower() == cn:
            return j, cleanH(h)
    # Pass 2: full cleanH_full match (strips [USE]/[LU]/[Sync])
    for j, h in enumerate(headers):
        if cleanH_full(h).lower() == cn:
            return j, cleanH_full(h)
    # Pass 3: substring
    for j, h in enumerate(headers):
        if cn in cleanH(h).lower() or cn in cleanH_full(h).lower():
            return j, cleanH(h)
    return None, ''

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

def _parse_filter_date(s):
    if not s:
        return None
    s = str(s).strip()
    for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y', '%d/%m/%Y',
                '%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S',
                '%d/%m/%Y %H:%M:%S', '%m/%d/%Y %H:%M:%S',
                '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None

def apply_filter(rows, col_idx, op, val, col_name=''):
    """v37.3: type-aware filter with Airtable-parity operators.

    Multi-value cells (pipe, comma, or semicolon separated) match
    per-piece after trim+lowercase. Linked Airtable record IDs are
    resolved to human names before comparison. Value aliases (e.g. UK
    -> United Kingdom) apply when col_name is recognised."""
    result = []
    raw_val = (val or '').strip()
    vl = raw_val.lower()
    filter_vals_raw = [v.strip() for v in raw_val.split(',') if v.strip()]
    aliased = _apply_value_aliases(col_name, filter_vals_raw) if col_name else filter_vals_raw
    filter_vals = [f.lower() for f in aliased]
    primary = filter_vals[0] if filter_vals else vl

    for ri, r in rows:
        raw = str(r[col_idx]) if col_idx < len(r) else ''
        try:
            resolved = resolver.resolve_value('', raw) if raw else raw
        except Exception:
            resolved = raw
        cell = str(resolved).strip()
        cell_l = cell.lower()
        parts = _split_multi_cell(cell_l)
        m = False
        if op == 'is_empty':
            m = not cell_l
        elif op == 'is_not_empty':
            m = bool(cell_l)
        elif op == 'contains':
            m = (any(fv in cell_l for fv in filter_vals) if filter_vals else (vl in cell_l)) if (filter_vals or vl) else True
        elif op == 'does_not_contain':
            if filter_vals:
                m = not any(any(fv == p or fv in p for p in parts) for fv in filter_vals)
            else:
                m = vl not in cell_l
        elif op in ('has_any_of', 'contains_any', 'is_any_of'):
            m = any(fv == p or fv in p for p in parts for fv in filter_vals)
        elif op in ('has_all_of', 'contains_all'):
            m = bool(filter_vals) and all(any(fv == p or fv in p for p in parts) for fv in filter_vals)
        elif op in ('has_none_of', 'is_none_of'):
            m = not any(fv == p or fv in p for p in parts for fv in filter_vals)
        elif op == 'has_any_links':
            m = bool(cell_l)
        elif op == 'has_no_links':
            m = not bool(cell_l)
        elif op == 'is':
            if filter_vals:
                m = any(fv == cell_l for fv in filter_vals) or any(fv == p for p in parts for fv in filter_vals)
            else:
                m = cell_l == vl
        elif op == 'is_not':
            if filter_vals:
                m = not (any(fv == cell_l for fv in filter_vals) or any(fv == p for p in parts for fv in filter_vals))
            else:
                m = cell_l != vl
        elif op == 'starts_with':
            m = cell_l.startswith(primary)
        elif op == 'ends_with':
            m = cell_l.endswith(primary)
        elif op in ('equals',):
            try:
                m = float(cell_l) == float(primary)
            except Exception:
                m = cell_l == primary
        elif op in ('not_equals', 'ne'):
            try:
                m = float(cell_l) != float(primary)
            except Exception:
                m = cell_l != primary
        elif op in ('greater_than', 'gt'):
            try:
                m = float(cell_l) > float(primary)
            except Exception:
                m = False
        elif op in ('less_than', 'lt'):
            try:
                m = float(cell_l) < float(primary)
            except Exception:
                m = False
        elif op == 'gte':
            try:
                m = float(cell_l) >= float(primary)
            except Exception:
                m = False
        elif op == 'lte':
            try:
                m = float(cell_l) <= float(primary)
            except Exception:
                m = False
        elif op in ('is_before', 'before', 'is_after', 'after',
                    'is_on_or_before', 'is_on_or_after', 'between',
                    'within_last', 'more_than_n_days_ago'):
            cd = _parse_filter_date(cell)
            if op in ('within_last', 'more_than_n_days_ago'):
                try:
                    n_days = int(float(primary))
                except Exception:
                    n_days = 0
                if cd and n_days:
                    delta = (datetime.now() - cd).days
                    if op == 'within_last':
                        m = 0 <= delta <= n_days
                    else:
                        m = delta > n_days
            elif op == 'between':
                bounds = [_parse_filter_date(v) for v in filter_vals_raw]
                bounds = [b for b in bounds if b]
                if cd and len(bounds) == 2:
                    lo, hi = sorted(bounds)
                    m = lo <= cd <= hi
            else:
                vd = _parse_filter_date(primary)
                if cd and vd:
                    if op in ('is_before', 'before'):
                        m = cd < vd
                    elif op in ('is_after', 'after'):
                        m = cd > vd
                    elif op == 'is_on_or_before':
                        m = cd <= vd
                    elif op == 'is_on_or_after':
                        m = cd >= vd
        else:
            # Unknown op: default to contains semantics
            m = any(fv in cell_l for fv in filter_vals) if filter_vals else (vl in cell_l)
        if m:
            result.append((ri, r))
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
def _search_records_impl(q, table_filter='', limit=15):
    """Shared search logic used by /api/search-record and /api/global-search."""
    if len(q or '') < 1:
        return []
    ql = q.lower()
    search_tables = [('Personnel','directory'),('Songs','songs'),
        ('MGMT Companies',None),('Record Labels',None),('Publishing Company',None),
        ('Agent',None),('Agency Company',None),('Studios',None),('Cities',None),
        ('Music Sup Company',None)]
    if table_filter:
        tf = table_filter.lower()
        search_tables = [(t,r) for t,r in search_tables
                         if t.lower()==tf or (r and r.lower()==tf)]
    starts_results = []; contains_results = []
    for table_name, route in search_tables:
        try:
            data = sheets.get_all_rows(table_name)
            if not data or len(data) < 2:
                continue
            headers = data[0]; rows = data[1:]
            nc = find_col(headers, 'name', 'title')
            if nc is None:
                continue
            for i, row in enumerate(rows):
                if nc < len(row):
                    val = str(row[nc]).strip()
                    if not val:
                        continue
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
    results = starts_results[:limit]
    if len(results) < limit:
        results.extend(contains_results[:limit-len(results)])
    return results

@app.route('/api/search-record')
@login_required
def api_search_record():
    q = request.args.get('q', '').strip()
    table_filter = request.args.get('table', '').strip()
    return jsonify({'results': _search_records_impl(q, table_filter)})

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
        col, _cname = resolve_filter_col(headers, field)
        if col is None:
            col = find_col(headers, field)
        if col is None: return jsonify({'values':[],'error':f'Field not found'})
        vals = set()
        for row in rows:
            if col < len(row):
                raw_cell = str(row[col])
                # Resolve linked record IDs (recXXX) to human names
                try:
                    resolved = resolver.resolve_value('', raw_cell) if raw_cell else raw_cell
                except Exception:
                    resolved = raw_cell
                for t in _MULTI_SPLIT_RE.split(str(resolved)):
                    t = t.strip()
                    if t and not t.startswith('rec'):
                        vals.add(t)
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
                    ci, cname = resolve_filter_col(headers, f['col'])
                    if ci is None: continue
                    for ri, r in all_rows:
                        if ri not in matched:
                            filtered = apply_filter([(ri, r)], ci, f['op'], f['val'], cname)
                            if filtered: matched.add(ri)
                rows = [(ri, r) for ri, r in all_rows if ri in matched]
            else:
                # AND: sequential narrowing (default)
                for f in adv_filters:
                    ci, cname = resolve_filter_col(headers, f['col'])
                    if ci is None: continue
                    rows = apply_filter(rows, ci, f['op'], f['val'], cname)
        if sort_fields:
            rows = apply_multi_sort(rows, headers, sort_fields)
        groups = None
        if group_by:
            gi, _gn = resolve_filter_col(headers, group_by)
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
        # v37.3: the Personnel sheet has trailing empty rows left over from the
        # Airtable migration. Exclude any row without an Airtable ID or Name
        # so "Clear all filters" shows the real contact count (~5305).
        name_col_idx = find_col(headers, 'Name')
        id_col_idx = find_col(headers, 'Airtable ID')
        def _is_real_contact(r):
            # v37.3: a real Personnel contact has an Airtable-style rec ID.
            # Rows without one are legacy brand partnerships / import remnants.
            if id_col_idx is not None and id_col_idx < len(r):
                aid = str(r[id_col_idx]).strip()
                if aid.startswith('rec') and len(aid) > 10:
                    return True
            return False
        rows = [(i+2, r) for i, r in enumerate(raw) if _is_real_contact(r)]
        if search:
            sl=search.lower()
            rows=[(ri,r) for ri,r in rows if any(sl in str(c).lower() for c in r)]
        if adv_filters:
            if filter_mode == 'or':
                all_rows = rows; matched = set()
                for f in adv_filters:
                    ci, cname = resolve_filter_col(headers, f['col'])
                    if ci is None: continue
                    for ri, r in all_rows:
                        if ri not in matched:
                            filtered = apply_filter([(ri, r)], ci, f['op'], f['val'], cname)
                            if filtered: matched.add(ri)
                rows = [(ri, r) for ri, r in all_rows if ri in matched]
            else:
                for f in adv_filters:
                    ci, cname = resolve_filter_col(headers, f['col'])
                    if ci is None: continue
                    rows = apply_filter(rows, ci, f['op'], f['val'], cname)
        if sort_fields:
            rows = apply_multi_sort(rows, headers, sort_fields)
        groups=None
        if group_by:
            gi, _gn = resolve_filter_col(headers, group_by)
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


# ==================== MAIL MERGE EXPORT (v36) ====================
# Builds a Google Sheet formatted for Mail Merge with Attachments (Digital
# Inspiration, Amit Agarwal) - the tool Celina runs inside Gmail.
# Scheduled Date column is emitted in America/Los_Angeles to match the
# [Use] Date Time LA to Send Email convention in the Personnel sheet.

PITCH_FOLDER_NAME = 'ROLLON AR Pitches'
MAIL_MERGE_HEADERS = ['First Name', 'Email Address', 'Scheduled Date', 'File Attachments', 'Mail Merge Status']

def _timezone_for_city(city, country=''):
    """v36: resolve IANA zone via modules.timezone_map (90+ city map +
    Cities.Timezone aliases + country default)."""
    if not city and not country:
        return ''
    return tz_resolve(city, country, CITY_LOOKUP)

def _format_mm_schedule(target_hour, target_minute, tz_str, base_date, sender_tz=TZ_LA):
    """v36: converts wall-clock in recipient tz to DD/MM/YYYY HH:MM:SS in sender_tz.
    Sender defaults to America/Los_Angeles so the output lands in the
    '[Use] Date Time LA to Send Email' column expected by Mail Merge with
    Attachments. Pass sender_tz='Europe/London' for the [London] variant."""
    recipient_tz = tz_str if tz_str else sender_tz
    return tz_to_zone(
        (base_date.year, base_date.month, base_date.day, target_hour, target_minute),
        recipient_tz, sender_tz,
    )

def _ensure_pitch_log_tab():
    try:
        existing = sheets.get_all_rows('Pitch Log')
        if existing:
            return True
    except Exception:
        pass
    try:
        sheets._retry(lambda: sheets.service.spreadsheets().batchUpdate(
            spreadsheetId=sheets.spreadsheet_id,
            body={'requests': [{'addSheet': {'properties': {'title': 'Pitch Log'}}}]}
        ).execute())
        headers = ['Date', 'Round', 'Pitch Type', 'Contact Name', 'Contact Email',
                   'Song Title', 'DISCO Link', 'Status', 'Response Date', 'Notes']
        sheets._retry(lambda: sheets.service.spreadsheets().values().update(
            spreadsheetId=sheets.spreadsheet_id, range="'Pitch Log'!A1",
            valueInputOption='USER_ENTERED', body={'values': [headers]}
        ).execute())
        sheets._invalidate_cache('Pitch Log')
        return True
    except Exception as e:
        logging.warning('Pitch Log ensure failed: %s', e)
        return False

def _log_mm_pitch(pitch_name, contact_count, sheet_url):
    if not _ensure_pitch_log_tab():
        return
    today = datetime.now().strftime('%Y-%m-%d')
    row = [today, str(contact_count), pitch_name, '', '', '', sheet_url,
           'Ready to Send', '', 'Mail Merge Export']
    try:
        sheets.batch_append('Pitch Log', [row])
    except Exception as e:
        logging.warning('Pitch Log append failed: %s', e)

def _tag_and_stamp_mm_contacts(row_indices, tag_name):
    ris = [int(i) for i in (row_indices or []) if i]
    if not ris:
        return
    try:
        data = sheets.get_all_rows('Personnel')
        if not data:
            return
        headers = data[0]
        def col(name):
            for j, h in enumerate(headers):
                if cleanH(h).lower() == name.lower():
                    return j
            return None
        tc = col('Tags')
        lc = col('Last Outreach')
        today = datetime.now().strftime('%Y-%m-%d')
        updates = []
        rows = data[1:]
        for ri in ris:
            idx = ri - 2
            if idx < 0 or idx >= len(rows):
                continue
            r = rows[idx]
            if tc is not None:
                cur = r[tc].strip() if tc < len(r) else ''
                parts = [t.strip() for t in cur.split('|') if t.strip()] if cur else []
                if tag_name not in parts:
                    parts.append(tag_name)
                    updates.append((ri, tc + 1, ' | '.join(parts)))
            if lc is not None:
                updates.append((ri, lc + 1, today))
        if updates:
            sheets.batch_update_cells('Personnel', updates)
    except Exception as e:
        logging.warning('Tag/stamp mm contacts failed: %s', e)

def _build_drive_service():
    from googleapiclient.discovery import build as _gbuild
    return _gbuild('drive', 'v3', credentials=sheets._get_creds())

def _ensure_pitch_folder():
    drive = _build_drive_service()
    q = ("name='" + PITCH_FOLDER_NAME + "' and mimeType='application/vnd.google-apps.folder' and trashed=false")
    res = drive.files().list(q=q, fields='files(id,name)', pageSize=1).execute()
    files = res.get('files', [])
    if files:
        return files[0]['id']
    folder = drive.files().create(
        body={'name': PITCH_FOLDER_NAME, 'mimeType': 'application/vnd.google-apps.folder'},
        fields='id'
    ).execute()
    return folder['id']

def _create_mm_spreadsheet(title, data_rows, folder_id, extra_headers=None):
    """Create a new Google Sheet and populate it with the required 5 columns
    plus any extra columns passed in. Caller is responsible for ensuring
    each row has len(MAIL_MERGE_HEADERS) + len(extra_headers) cells."""
    svc = sheets.service
    body = {
        'properties': {'title': title},
        'sheets': [
            {'properties': {'title': 'Sheet1'}},
            {'properties': {'title': 'Mail Merge Logs'}},
        ],
    }
    spreadsheet = sheets._retry(lambda: svc.spreadsheets().create(body=body).execute())
    new_id = spreadsheet['spreadsheetId']
    headers = list(MAIL_MERGE_HEADERS) + (list(extra_headers) if extra_headers else [])
    sheets._retry(lambda: svc.spreadsheets().values().update(
        spreadsheetId=new_id, range="'Sheet1'!A1",
        valueInputOption='USER_ENTERED',
        body={'values': [headers] + data_rows}
    ).execute())
    try:
        if folder_id:
            drive = _build_drive_service()
            drive.files().update(fileId=new_id, addParents=folder_id, fields='id,parents').execute()
    except Exception as e:
        logging.warning('Mail merge sheet folder move failed: %s', e)
    return {
        'spreadsheet_id': new_id,
        'url': 'https://docs.google.com/spreadsheets/d/' + new_id + '/edit',
    }

def _fetch_mm_contacts(row_indices):
    data = sheets.get_all_rows('Personnel')
    if not data or len(data) < 2:
        return []
    headers = data[0]
    def col(name):
        for j, h in enumerate(headers):
            if cleanH(h).lower() == name.lower():
                return j
        return None
    ac = col('Airtable ID'); nc = col('Name'); ec = col('Email'); cc = col('City')
    mc = col('MGMT Company'); lc = col('Record Label'); pc = col('Publishing Company')
    srt = col('Set Out Reach Date/Time')
    tc = col('Tags')
    indices = set(int(i) for i in (row_indices or []) if i)
    rows = data[1:]
    out = []
    for idx, r in enumerate(rows, start=2):
        if indices and idx not in indices:
            continue
        def g(ci):
            return r[ci].strip() if ci is not None and ci < len(r) and r[ci] else ''
        email = g(ec)
        if not email:
            continue
        city = g(cc)
        tag_raw = g(tc)
        tag_parts = [t.strip() for t in tag_raw.split('|') if t.strip()] if tag_raw else []
        out.append({
            'row_index': idx,
            'airtable_id': g(ac),
            'name': g(nc),
            'email': email,
            'city': city,
            'mgmt': g(mc),
            'label': g(lc),
            'publisher': g(pc),
            'set_out_reach': g(srt),
            'timezone': _timezone_for_city(city),
            'tags': tag_parts,
            'dont_mass_pitch': "Don't Mass Pitch" in tag_parts,
        })
    return out

def _filter_dont_mass_pitch(contacts, include_dmp):
    """Remove Don't Mass Pitch tagged contacts unless include_dmp is True.
    Returns (kept_contacts, skipped_count)."""
    if include_dmp:
        return contacts, 0
    kept = [c for c in contacts if not c.get('dont_mass_pitch')]
    return kept, len(contacts) - len(kept)


def _compute_cooldown_conflicts(contacts, days):
    """v37: return list of contacts whose Last Outreach falls within `days`
    of today. `days` <=0 disables the check. Each conflict dict carries
    {name, email, last_outreach, days_since}."""
    try:
        days = int(days or 0)
    except Exception:
        days = 0
    if days <= 0:
        return []
    today = datetime.now().date()
    out = []
    try:
        data = sheets.get_all_rows('Personnel')
        if not data:
            return []
        headers = data[0]
        rows = data[1:]
        def col(name):
            for j, h in enumerate(headers):
                if cleanH(h).lower() == name.lower():
                    return j
            return None
        lc = col('Last Outreach')
        nc = col('Name')
        ec = col('Email')
        if lc is None:
            return []
        ris = {int(c['row_index']) for c in contacts if c.get('row_index')}
        for idx, r in enumerate(rows, start=2):
            if idx not in ris:
                continue
            raw = str(r[lc]).strip() if lc < len(r) else ''
            if not raw:
                continue
            try:
                lo_date = None
                for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y'):
                    try:
                        lo_date = datetime.strptime(raw, fmt).date()
                        break
                    except Exception:
                        continue
                if not lo_date:
                    continue
                delta = (today - lo_date).days
                if 0 <= delta <= days:
                    out.append({
                        'row_index': idx,
                        'name': str(r[nc]).strip() if nc is not None and nc < len(r) else '',
                        'email': str(r[ec]).strip() if ec is not None and ec < len(r) else '',
                        'last_outreach': raw,
                        'days_since': delta,
                    })
            except Exception:
                continue
    except Exception as e:
        logging.warning('cooldown conflict scan failed: %s', e)
    return out

def _group_mm_contacts(contacts, group_by_company):
    """v36: delegates to relationships.group_for_pitch when group_by_company is true.

    Works With linkages override Company grouping per Phase 2D. When
    group_by_company is False, each contact is emitted as a solo group.
    """
    if not group_by_company:
        out = []
        for c in contacts:
            first = (c.get('name') or '').strip().split()
            out.append({
                'first_name': first[0] if first else '',
                'email': c.get('email', ''),
                'tz': c.get('timezone') or '',
                'row_indices': [c['row_index']],
                'ids': [c.get('airtable_id', '')],
                'greeting': 'Hi ' + (first[0] if first else ''),
                'greeting_alt': 'Hi ' + (first[0] if first else ''),
                'set_out_reach': c.get('set_out_reach', ''),
            })
        return out

    id_to_contact = {c.get('airtable_id') or f"row:{c['row_index']}": c for c in contacts}
    ids = [k for k in id_to_contact.keys() if k and not k.startswith('row:')]
    loose = [c for c in contacts if not c.get('airtable_id')]
    groups = relationships.group_for_pitch(ids) if ids else []
    out = []
    for grp in groups:
        gids = grp.get('ids') or []
        members = [id_to_contact.get(i) for i in gids if id_to_contact.get(i)]
        if not members:
            continue
        tz = next((m.get('timezone') for m in members if m.get('timezone')), '')
        set_out = next((m.get('set_out_reach') for m in members if m.get('set_out_reach')), '')
        out.append({
            'first_name': grp.get('greeting', '').replace('Hi ', '').strip(),
            'greeting': grp.get('greeting', ''),
            'greeting_alt': grp.get('greeting_alt', ''),
            'email': grp.get('emails_joined') or ', '.join(m.get('email', '') for m in members if m.get('email')),
            'tz': tz,
            'row_indices': [m['row_index'] for m in members],
            'ids': gids,
            'group_key': grp.get('group_key', 'solo'),
            'set_out_reach': set_out,
        })
    for c in loose:
        first = (c.get('name') or '').strip().split()
        fn = first[0] if first else ''
        out.append({
            'first_name': fn,
            'greeting': 'Hi ' + fn,
            'greeting_alt': 'Hi ' + fn,
            'email': c.get('email', ''),
            'tz': c.get('timezone') or '',
            'row_indices': [c['row_index']],
            'ids': [],
            'group_key': 'solo',
            'set_out_reach': c.get('set_out_reach', ''),
        })
    return out

def _resolve_mm_rows(payload):
    """If row_indices provided, use them; else use current filtered view."""
    rowidx = payload.get('row_indices') or []
    if rowidx:
        return _fetch_mm_contacts(rowidx)
    filter_args = payload.get('filter_args') or {}
    try:
        data = sheets.get_all_rows('Personnel')
        if not data:
            return []
        headers = data[0]
        rows = [(i + 2, r) for i, r in enumerate(data[1:])]
        search = (filter_args.get('search') or '').strip().lower()
        if search:
            rows = [(ri, r) for ri, r in rows if any(search in str(c).lower() for c in r)]
        advf = []
        for i in range(20):
            cvar = filter_args.get('f' + str(i) + '_col', '').strip()
            op = filter_args.get('f' + str(i) + '_op', 'contains').strip()
            val = filter_args.get('f' + str(i) + '_val', '').strip()
            if cvar:
                advf.append({'col': cvar, 'op': op, 'val': val})
        mode = (filter_args.get('filter_mode') or 'and').lower()
        if advf:
            if mode == 'or':
                allr = rows; matched = set()
                for f in advf:
                    ci, cname = resolve_filter_col(headers, f['col'])
                    if ci is None: continue
                    for ri, r in allr:
                        if ri not in matched:
                            if apply_filter([(ri, r)], ci, f['op'], f['val'], cname):
                                matched.add(ri)
                rows = [(ri, r) for ri, r in allr if ri in matched]
            else:
                for f in advf:
                    ci, cname = resolve_filter_col(headers, f['col'])
                    if ci is None: continue
                    rows = apply_filter(rows, ci, f['op'], f['val'], cname)
        return _fetch_mm_contacts([ri for ri, _ in rows])
    except Exception as e:
        logging.warning('_resolve_mm_rows error: %s', e)
        return []

@app.route('/api/directory/mail-merge-preview', methods=['POST'])
@admin_required
def api_mail_merge_preview():
    payload = request.get_json(silent=True) or {}
    group_by = bool(payload.get('group_by_company', True))
    include_dmp = bool(payload.get('include_dont_mass_pitch', False))
    cooldown_days = int(payload.get('cooldown_days', 14) or 0)
    contacts = _resolve_mm_rows(payload)
    contacts, skipped_dmp = _filter_dont_mass_pitch(contacts, include_dmp)
    conflicts = _compute_cooldown_conflicts(contacts, cooldown_days)
    rows = _group_mm_contacts(contacts, group_by)
    return jsonify({
        'contact_count': len(contacts),
        'row_count': len(rows),
        'skipped_dont_mass_pitch': skipped_dmp,
        'cooldown_days': cooldown_days,
        'cooldown_conflicts': conflicts[:50],
        'cooldown_conflict_count': len(conflicts),
    })

def _build_mm_export_rows(payload):
    """Shared builder for Mail Merge export rows.

    Returns dict with keys:
      headers, data_rows, groups, contacts, skipped_dmp,
      base_date, hh, mm, send_mode, fixed_tz, visible_cols, title, pitch_name.
    Raises ValueError if inputs are invalid."""
    pitch_name = (payload.get('pitch_name') or '').strip()
    group_by = bool(payload.get('group_by_company', True))
    send_date_s = (payload.get('send_date') or '').strip()
    send_time_s = (payload.get('send_time') or '').strip()
    send_mode = (payload.get('send_mode') or 'recipient_local').strip()
    fixed_tz = (payload.get('fixed_tz') or 'Europe/London').strip()
    visible_cols = payload.get('visible_columns') or []
    include_dmp = bool(payload.get('include_dont_mass_pitch', False))
    if not pitch_name:
        raise ValueError('Pitch name is required')

    contacts = _resolve_mm_rows(payload)
    if not contacts:
        raise ValueError('No contacts with email found in the selection')
    contacts, skipped_dmp = _filter_dont_mass_pitch(contacts, include_dmp)
    if not contacts:
        raise ValueError('All contacts in the selection carry the "Don\'t Mass Pitch" tag. Tick "Include Don\'t Mass Pitch contacts" to send to them anyway.')
    groups = _group_mm_contacts(contacts, group_by)

    today = datetime.now().date()
    if send_date_s:
        try:
            y, m, d = [int(p) for p in send_date_s.split('-')]
            base_date = datetime(y, m, d).date()
        except Exception:
            base_date = today + timedelta(days=1)
    else:
        base_date = today + timedelta(days=1)
    if send_time_s:
        try:
            hh, mm = [int(p) for p in send_time_s.split(':')]
        except Exception:
            hh, mm = 10, 22
    else:
        hh, mm = 10, 22

    # --- v37.3: final column layout ---
    # Directory visible columns first (in the order Celina sees them), then
    # append any of the 5 required Mail Merge columns that are NOT already in
    # the visible set (case-insensitive match against a known alias list).
    p_headers_all = []
    try:
        p_headers_all = sheets.get_headers('Personnel')
    except Exception:
        p_headers_all = []
    pd = sheets.get_all_rows('Personnel')
    p_data_rows = pd[1:] if pd else []

    required_aliases = {
        'First Name': {'first name', 'combined first names'},
        'Email Address': {'email address', 'emails combined'},
        'Scheduled Date': {'scheduled date', 'date/time in la to send email',
                           'send date', 'set out reach date/time'},
        'File Attachments': {'file attachments', 'attachments'},
        'Mail Merge Status': {'mail merge status'},
    }

    visible_clean = []
    for v in visible_cols or []:
        vc = cleanH(str(v)).strip()
        if vc and vc not in visible_clean:
            visible_clean.append(vc)

    final_headers = list(visible_clean)
    for req, aliases in required_aliases.items():
        if not any(vc.lower() in aliases or vc.lower() == req.lower() for vc in visible_clean):
            final_headers.append(req)

    # Map each final header to either a magic role or a Personnel column idx.
    # "Email" counts as the combined-email role so Celina's grouped rows get a
    # comma-joined address list even when her visible column is named "Email"
    # rather than "Email Address".
    header_kind = []  # list of ('role', role_name) or ('col', idx) or ('blank', '')
    for h in final_headers:
        hl = h.lower()
        if hl == 'first name' or hl in required_aliases['First Name']:
            header_kind.append(('role', 'first_name'))
        elif hl == 'email address' or hl == 'email' or hl in required_aliases['Email Address']:
            header_kind.append(('role', 'email'))
        elif hl == 'scheduled date' or hl in required_aliases['Scheduled Date']:
            header_kind.append(('role', 'scheduled'))
        elif hl == 'file attachments':
            header_kind.append(('blank', ''))
        elif hl == 'mail merge status':
            header_kind.append(('blank', ''))
        else:
            idx = _find_personnel_col(p_headers_all, h)
            header_kind.append(('col', idx))

    cfn_idx = _find_personnel_col(p_headers_all, COMBINED_FIRST_NAMES_COLUMN, 'Combined First Names')
    ec_idx = _find_personnel_col(p_headers_all, EMAILS_COMBINED_COLUMN, 'Emails Combined')

    data_rows = []
    for g in groups:
        if send_mode == 'fixed':
            scheduled = _format_mm_schedule(hh, mm, fixed_tz, base_date, sender_tz=TZ_LA)
        else:
            recipient_tz = g.get('tz', '') or fixed_tz
            scheduled = _format_mm_schedule(hh, mm, recipient_tz, base_date, sender_tz=TZ_LA)

        group_ris = g.get('row_indices') or []
        # First Name: prefer the pre-written Combined First Names [USE] cell
        # for the first group member (so the whole group shares one greeting),
        # else fall back to computed greeting / own first name.
        first_name = ''
        group_email = g.get('email') or ''
        if group_ris:
            first_ri = group_ris[0]
            idx0 = first_ri - 2
            if cfn_idx is not None and 0 <= idx0 < len(p_data_rows):
                cell = p_data_rows[idx0]
                if cfn_idx < len(cell):
                    first_name = str(cell[cfn_idx]).strip()
            if ec_idx is not None and 0 <= idx0 < len(p_data_rows):
                cell = p_data_rows[idx0]
                if ec_idx < len(cell):
                    ec_val = str(cell[ec_idx]).strip()
                    if ec_val:
                        group_email = ec_val
        if not first_name:
            # derive from greeting
            first_name = (g.get('greeting') or '').replace('Hi ', '', 1).strip() \
                or g.get('first_name', '')

        row = []
        for kind, data in header_kind:
            if kind == 'role':
                if data == 'first_name':
                    row.append(first_name)
                elif data == 'email':
                    row.append(group_email)
                elif data == 'scheduled':
                    row.append(scheduled)
                else:
                    row.append('')
            elif kind == 'col':
                if data is None:
                    row.append('')
                else:
                    joined = []
                    for ri in group_ris:
                        idx = ri - 2
                        if 0 <= idx < len(p_data_rows):
                            cell = p_data_rows[idx]
                            v = cell[data] if data < len(cell) else ''
                            try:
                                v = resolver.resolve_value('', str(v)) if v else str(v)
                            except Exception:
                                v = str(v)
                            v = v.strip()
                            if v and v not in joined:
                                joined.append(v)
                    row.append(' | '.join(joined))
            else:
                row.append('')
        data_rows.append(row)

    # Sort by scheduled date column if present
    sched_col = None
    for i, (kind, data) in enumerate(header_kind):
        if kind == 'role' and data == 'scheduled':
            sched_col = i
            break
    if sched_col is not None:
        data_rows.sort(key=lambda r: r[sched_col] if sched_col < len(r) else '')

    title = pitch_name + ' - ' + today.strftime('%b %d %Y')
    return {
        'headers': final_headers,
        'data_rows': data_rows,
        'groups': groups,
        'contacts': contacts,
        'skipped_dmp': skipped_dmp,
        'base_date': base_date,
        'hh': hh, 'mm': mm,
        'send_mode': send_mode,
        'fixed_tz': fixed_tz,
        'visible_cols': visible_clean,
        'title': title,
        'pitch_name': pitch_name,
    }


def _create_mm_spreadsheet_v2(title, headers, data_rows, folder_id):
    """Write a Google Sheet with arbitrary headers. Used by v37.3 export."""
    svc = sheets.service
    body = {
        'properties': {'title': title},
        'sheets': [
            {'properties': {'title': 'Sheet1'}},
            {'properties': {'title': 'Mail Merge Logs'}},
        ],
    }
    spreadsheet = sheets._retry(lambda: svc.spreadsheets().create(body=body).execute())
    new_id = spreadsheet['spreadsheetId']
    sheets._retry(lambda: svc.spreadsheets().values().update(
        spreadsheetId=new_id, range="'Sheet1'!A1",
        valueInputOption='USER_ENTERED',
        body={'values': [headers] + data_rows}
    ).execute())
    try:
        if folder_id:
            drive = _build_drive_service()
            drive.files().update(fileId=new_id, addParents=folder_id, fields='id,parents').execute()
    except Exception as e:
        logging.warning('Mail merge sheet folder move failed: %s', e)
    return {
        'spreadsheet_id': new_id,
        'url': 'https://docs.google.com/spreadsheets/d/' + new_id + '/edit',
    }


@app.route('/api/directory/mail-merge-export', methods=['POST'])
@admin_required
def api_mail_merge_export():
    payload = request.get_json(silent=True) or {}
    try:
        built = _build_mm_export_rows(payload)
    except ValueError as ve:
        return jsonify({'error': str(ve)}), 400
    try:
        folder_id = _ensure_pitch_folder()
    except Exception as e:
        logging.warning('Pitch folder resolve failed: %s', e)
        folder_id = None
    result = _create_mm_spreadsheet_v2(built['title'], built['headers'],
                                       built['data_rows'], folder_id)
    _log_mm_pitch(built['pitch_name'], len(built['groups']), result['url'])
    all_ris = []
    for g in built['groups']:
        all_ris.extend(g.get('row_indices') or [])
    _tag_and_stamp_mm_contacts(all_ris, 'Pitched: ' + built['pitch_name'])
    return jsonify({
        'success': True,
        'url': result['url'],
        'spreadsheet_id': result['spreadsheet_id'],
        'title': built['title'],
        'headers': built['headers'],
        'row_count': len(built['data_rows']),
        'contact_count': len(built['contacts']),
        'skipped_dont_mass_pitch': built['skipped_dmp'],
        'send_date': str(built['base_date']),
        'send_time': f"{built['hh']:02d}:{built['mm']:02d}",
        'send_mode': built['send_mode'],
    })


@app.route('/api/directory/mail-merge-export-csv', methods=['POST'])
@admin_required
def api_mail_merge_export_csv():
    """v37.3: same export as mail-merge-export but returns a CSV download."""
    from flask import Response
    import csv, io
    payload = request.get_json(silent=True) or {}
    try:
        built = _build_mm_export_rows(payload)
    except ValueError as ve:
        return jsonify({'error': str(ve)}), 400
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(built['headers'])
    for row in built['data_rows']:
        writer.writerow(row)
    today_s = datetime.now().strftime('%Y-%m-%d')
    safe_name = re.sub(r'[^A-Za-z0-9_\- ]+', '', built['pitch_name']).strip().replace(' ', '_') or 'Pitch'
    filename = f"{safe_name}_{today_s}.csv"
    _log_mm_pitch(built['pitch_name'], len(built['groups']), 'CSV download: ' + filename)
    all_ris = []
    for g in built['groups']:
        all_ris.extend(g.get('row_indices') or [])
    _tag_and_stamp_mm_contacts(all_ris, 'Pitched: ' + built['pitch_name'])
    resp = Response(buf.getvalue(), mimetype='text/csv')
    resp.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    resp.headers['X-Row-Count'] = str(len(built['data_rows']))
    resp.headers['X-Contact-Count'] = str(len(built['contacts']))
    resp.headers['X-Skipped-DMP'] = str(built['skipped_dmp'])
    return resp


# ==================== WORKS WITH (v36 relationships engine) ====================
# See modules/relationships.py. Works With is stored as pipe-separated
# Airtable IDs in the Personnel.Works With column. Writes are bidirectional.

@app.route('/api/relationships/ensure-columns', methods=['POST'])
@admin_required
def api_relationships_ensure_columns():
    try:
        added = relationships.ensure_columns()
        return jsonify({'success': True, 'columns': added})
    except Exception as e:
        logging.warning(f'ensure_columns failed: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/relationships/search', methods=['POST'])
@login_required
def api_relationships_search():
    d = request.json or {}
    q = (d.get('q') or '').strip()
    exclude_id = (d.get('exclude_id') or '').strip()
    try:
        results = relationships.search_by_name(q, limit=15, exclude_id=exclude_id)
        return jsonify({'results': results})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/relationships/works-with/<path:personnel_id>', methods=['GET'])
@login_required
def api_relationships_works_with_get(personnel_id):
    try:
        linked_ids = relationships.get_works_with(personnel_id)
        details = []
        for lid in linked_ids:
            ri = relationships.row_for_id(lid)
            data = relationships.row_data(lid) or {}
            details.append({
                'id': lid,
                'name': data.get('Name', ''),
                'email': data.get('Email', ''),
                'row_index': ri,
                'company': (data.get('MGMT Company') or data.get('Record Label')
                            or data.get('Publishing Company') or ''),
            })
        return jsonify({'links': details})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/relationships/works-with/add', methods=['POST'])
@login_required
def api_relationships_works_with_add():
    d = request.json or {}
    id_a = (d.get('from_id') or '').strip()
    id_b = (d.get('to_id') or '').strip()
    # Convenience: row_index inputs resolve to Airtable IDs
    if not id_a and d.get('from_row'):
        id_a = relationships.id_for_row(int(d['from_row']))
    if not id_b and d.get('to_row'):
        id_b = relationships.id_for_row(int(d['to_row']))
    if not id_a or not id_b:
        return jsonify({'error': 'Both from_id and to_id required'}), 400
    try:
        ok = relationships.add_link(id_a, id_b)
        if not ok:
            return jsonify({'error': 'Could not resolve one or both IDs'}), 400
        # v37.3: recompute combined columns for the newly-linked group
        threading.Thread(target=lambda: _recompute_for_group_members([id_a, id_b]),
                         daemon=True).start()
        return jsonify({
            'success': True,
            'from_id': id_a,
            'to_id': id_b,
            'links_from_a': relationships.get_works_with(id_a),
            'links_from_b': relationships.get_works_with(id_b),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/relationships/works-with/remove', methods=['POST'])
@login_required
def api_relationships_works_with_remove():
    d = request.json or {}
    id_a = (d.get('from_id') or '').strip()
    id_b = (d.get('to_id') or '').strip()
    if not id_a and d.get('from_row'):
        id_a = relationships.id_for_row(int(d['from_row']))
    if not id_b and d.get('to_row'):
        id_b = relationships.id_for_row(int(d['to_row']))
    if not id_a or not id_b:
        return jsonify({'error': 'Both IDs required'}), 400
    try:
        relationships.remove_link(id_a, id_b)
        # v37.3: recompute for both ex-partners (their groups likely differ now)
        threading.Thread(target=lambda: _recompute_for_group_members([id_a, id_b]),
                         daemon=True).start()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/relationships/group', methods=['POST'])
@login_required
def api_relationships_group():
    """Given an input list of Personnel IDs or row indices, return the pitch groups."""
    d = request.json or {}
    ids = [str(i).strip() for i in (d.get('ids') or []) if i]
    for ri in (d.get('row_indices') or []):
        try:
            aid = relationships.id_for_row(int(ri))
            if aid:
                ids.append(aid)
        except Exception:
            pass
    if not ids:
        return jsonify({'groups': []})
    try:
        groups = relationships.group_for_pitch(ids)
        return jsonify({'groups': groups})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/relationships/greeting', methods=['POST'])
@login_required
def api_relationships_greeting():
    d = request.json or {}
    ids = [str(i).strip() for i in (d.get('ids') or []) if i]
    if not ids:
        return jsonify({'named': '', 'alt': '', 'first_names': [], 'count': 0})
    try:
        return jsonify(relationships.greeting_for(ids))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/relationships/lookup/<path:personnel_id>', methods=['GET'])
@login_required
def api_relationships_lookup(personnel_id):
    try:
        return jsonify(relationships.lookup_all_relationships(personnel_id))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/relationships/group-leader/<path:personnel_id>', methods=['GET'])
@login_required
def api_relationships_group_leader_get(personnel_id):
    """Return {'leader': '<recID or empty>', 'group_ids': [...]} for a contact.

    The group is the transitive Works With closure starting from the given
    contact so the modal can show every member and which one is leader.
    """
    try:
        leader = relationships.get_group_leader(personnel_id)
        group = relationships.get_group([personnel_id])
        return jsonify({'leader': leader, 'group_ids': group})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/relationships/group-leader', methods=['POST'])
@login_required
def api_relationships_group_leader_set():
    """Set the Group Leader for a set of contacts.

    Payload:
      group_ids: [str] Airtable IDs of every group member (required)
      leader_id: str Airtable ID of the picked leader (must be in group_ids)
      auto_tag_secondaries: bool - default true. When true, every non-leader
        member gets the "Don't Mass Pitch" tag so bulk pitches only reach
        the leader.
    """
    d = request.json or {}
    ids = [str(x).strip() for x in (d.get('group_ids') or []) if x]
    leader = str(d.get('leader_id') or '').strip()
    auto_tag = bool(d.get('auto_tag_secondaries', True))
    if not ids or not leader:
        return jsonify({'error': 'group_ids and leader_id required'}), 400
    if leader not in ids:
        return jsonify({'error': 'leader_id must be one of group_ids'}), 400
    try:
        res = relationships.set_group_leader(ids, leader, auto_tag_secondaries=auto_tag)
        return jsonify({'success': True, **res})
    except Exception as e:
        logging.warning('set_group_leader failed: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/relationships/group-leader/clear', methods=['POST'])
@login_required
def api_relationships_group_leader_clear():
    d = request.json or {}
    ids = [str(x).strip() for x in (d.get('group_ids') or []) if x]
    if not ids:
        return jsonify({'error': 'group_ids required'}), 400
    try:
        res = relationships.clear_group_leader(ids)
        return jsonify({'success': True, **res})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== V37 OUTREACH EVENTS ====================
# Structured append-only log of outreach events per Personnel row. Stored
# as JSON array in the "Outreach Events" column. Every entry carries
# {ts, event_type, summary, warmth?, pitch_id?, tags_added?}. The raw
# free-text "Outreach Notes" column is preserved alongside for legacy.

OUTREACH_EVENTS_COLUMN = 'Outreach Events'
VALID_EVENT_TYPES = ('pitch_sent', 'reply_received', 'meeting', 'note', 'cooldown_skipped')
VALID_WARMTHS = ('cold', 'warming', 'warm', 'hot', 'established')

def _ensure_personnel_column(name):
    """Append a Personnel column if it does not exist. Returns 0-based index."""
    headers = sheets.get_headers('Personnel')
    for i, h in enumerate(headers):
        if cleanH(h).lower() == name.lower():
            return i
    next_idx = len(headers)
    col_letter = sheets._col_to_letter(next_idx + 1)
    sheets._retry(lambda: sheets.service.spreadsheets().values().update(
        spreadsheetId=sheets.spreadsheet_id,
        range=f"'Personnel'!{col_letter}1",
        valueInputOption='USER_ENTERED',
        body={'values': [[name]]}
    ).execute())
    sheets._invalidate_cache('Personnel')
    return next_idx


# ==================== V37.3 COMBINED COLUMNS WRITEBACK ====================
COMBINED_FIRST_NAMES_COLUMN = 'Combined First Names [USE]'
EMAILS_COMBINED_COLUMN = 'Emails Combined [USE]'
_COMBINED_LOCK = threading.Lock()
_COMBINED_STATE = {'running': False, 'last_run': None, 'updated': 0}


def _find_personnel_col(headers, *names):
    """Locate a Personnel column by any of the provided header names.
    Matches against cleanH, cleanH_full, and case-insensitive contains."""
    for n in names:
        nl = n.strip().lower()
        for i, h in enumerate(headers):
            if cleanH(h).lower() == nl or cleanH_full(h).lower() == nl:
                return i
        for i, h in enumerate(headers):
            if nl in cleanH(h).lower() or nl in cleanH_full(h).lower():
                return i
    return None


def _format_combined_first_names(first_names):
    """v37.3 combined first names format:
       1:  'Luke'
       2:  'Luke & Josie'
       3:  'Luke, Josie & Emily'
       4:  'Luke, Josie, Emily & Paul'
       5+: 'Luke, Josie, Emily, Paul & <N-4> others'"""
    names = [n.strip() for n in (first_names or []) if n and n.strip()]
    if not names:
        return ''
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f'{names[0]} & {names[1]}'
    if len(names) == 3:
        return f'{names[0]}, {names[1]} & {names[2]}'
    if len(names) == 4:
        return f'{names[0]}, {names[1]}, {names[2]} & {names[3]}'
    head = ', '.join(names[:4])
    return f'{head} & {len(names) - 4} others'


def _parse_ww_ids(raw):
    """Split a Works With cell into clean Airtable IDs."""
    if not raw:
        return []
    s = str(raw).replace(',', '|')
    return [p.strip() for p in s.split('|') if p.strip()]


def _transitive_closure(seed, ww_map):
    """BFS over the in-memory Works With adjacency map."""
    seen = set()
    stack = [seed]
    while stack:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        for peer in ww_map.get(pid, ()):
            if peer not in seen:
                stack.append(peer)
    return seen


def _collect_group_info(personnel_id, data_by_id, ww_map):
    """Return (ordered_first_names, ordered_emails) for the DIRECT Works With
    peers of personnel_id (not transitive). Each contact's combined columns
    therefore reflect the links stored on their own row — Luke sees the 5
    people he listed plus himself, Josie who only lists Luke sees "Josie &
    Luke". Uses in-memory adjacency so no Sheets API calls during recompute."""
    peers = ww_map.get(personnel_id, [])
    first_names = []
    emails = []
    seen_names = set()
    for pid in peers:
        d = data_by_id.get(pid)
        if not d:
            continue
        name = (d.get('Name') or '').strip()
        email = (d.get('Email') or '').strip()
        if name:
            first = name.split()[0]
            if first and first.lower() not in seen_names:
                first_names.append(first)
                seen_names.add(first.lower())
        if email and email not in emails:
            emails.append(email)
    return first_names, emails


def _build_personnel_data_by_id(personnel_rows, headers):
    """Build {airtable_id: {header: value}} for every Personnel row, using
    cleanH-normalised keys so relationships.row_data-style access works."""
    id_col = _find_personnel_col(headers, 'Airtable ID')
    data_by_id = {}
    if id_col is None:
        return data_by_id
    clean_headers = [cleanH_full(h) for h in headers]
    for row in personnel_rows:
        if id_col >= len(row):
            continue
        aid = str(row[id_col]).strip()
        if not aid:
            continue
        data_by_id[aid] = {clean_headers[j]: (row[j] if j < len(row) else '')
                          for j in range(len(clean_headers))}
    return data_by_id


def _recompute_combined_columns(row_indices=None):
    """Compute 'Combined First Names [USE]' and 'Emails Combined [USE]' for
    every (or given) Personnel row and write results back. Returns a dict
    with counts. Safe to call from any thread; serialises on _COMBINED_LOCK."""
    with _COMBINED_LOCK:
        _COMBINED_STATE['running'] = True
        try:
            data = sheets.get_all_rows('Personnel')
            if not data or len(data) < 2:
                return {'updated': 0, 'error': 'Personnel sheet empty'}
            headers = data[0]
            rows = data[1:]
            cfn_col = _find_personnel_col(headers, COMBINED_FIRST_NAMES_COLUMN, 'Combined First Names')
            ec_col = _find_personnel_col(headers, EMAILS_COMBINED_COLUMN, 'Emails Combined')
            if cfn_col is None:
                cfn_col = _ensure_personnel_column(COMBINED_FIRST_NAMES_COLUMN)
                headers = sheets.get_headers('Personnel')
            if ec_col is None:
                ec_col = _ensure_personnel_column(EMAILS_COMBINED_COLUMN)
                headers = sheets.get_headers('Personnel')
            id_col = _find_personnel_col(headers, 'Airtable ID')
            name_col = _find_personnel_col(headers, 'Name')
            email_col = _find_personnel_col(headers, 'Email')
            if id_col is None or name_col is None or email_col is None:
                return {'updated': 0, 'error': 'Missing Airtable ID / Name / Email column'}
            data_by_id = _build_personnel_data_by_id(rows, headers)
            # Build Works With adjacency map in memory — no per-row API reads.
            ww_col = _find_personnel_col(headers, 'Works With')
            ww_map = {}
            if ww_col is not None:
                for row in rows:
                    if id_col < len(row):
                        aid = str(row[id_col]).strip()
                        if not aid:
                            continue
                        raw = str(row[ww_col]) if ww_col < len(row) else ''
                        peers = [p for p in _parse_ww_ids(raw) if p in data_by_id and p != aid]
                        if peers:
                            ww_map[aid] = peers
                # symmetrise
                for owner, peers in list(ww_map.items()):
                    for peer in peers:
                        if owner not in ww_map.get(peer, []):
                            ww_map.setdefault(peer, []).append(owner)
            target = set(int(i) for i in (row_indices or [])) if row_indices else None
            updates = []
            scanned = 0
            for idx, row in enumerate(rows, start=2):
                if target is not None and idx not in target:
                    continue
                scanned += 1
                aid = str(row[id_col]).strip() if id_col < len(row) else ''
                own_name = str(row[name_col]).strip() if name_col < len(row) else ''
                own_email = str(row[email_col]).strip() if email_col < len(row) else ''
                own_first = own_name.split()[0] if own_name else ''
                first_names = []
                emails = []
                if aid and aid in ww_map:
                    first_names, emails = _collect_group_info(aid, data_by_id, ww_map)
                # Own info takes priority at slot 0 so the contact sees their
                # own name first in the greeting.
                if own_first and own_first not in first_names:
                    first_names.insert(0, own_first)
                else:
                    if own_first and first_names and first_names[0].lower() != own_first.lower():
                        first_names = [own_first] + [n for n in first_names if n.lower() != own_first.lower()]
                if own_email and own_email not in emails:
                    emails.insert(0, own_email)
                combined_names = _format_combined_first_names(first_names)
                combined_emails = ', '.join(emails)
                # Fallbacks: never write empty if the contact has own data
                if not combined_names and own_first:
                    combined_names = own_first
                if not combined_emails and own_email:
                    combined_emails = own_email
                existing_cfn = str(row[cfn_col]).strip() if cfn_col < len(row) else ''
                existing_ec = str(row[ec_col]).strip() if ec_col < len(row) else ''
                if combined_names != existing_cfn:
                    updates.append((idx, cfn_col + 1, combined_names))
                if combined_emails != existing_ec:
                    updates.append((idx, ec_col + 1, combined_emails))
            if updates:
                sheets.batch_update_cells('Personnel', updates)
                sheets._invalidate_cache('Personnel')
            _COMBINED_STATE['last_run'] = datetime.now().isoformat()
            _COMBINED_STATE['updated'] = len(updates)
            return {'updated': len(updates), 'scanned': scanned,
                    'rows': len(rows), 'timestamp': _COMBINED_STATE['last_run']}
        except Exception as e:
            logging.exception('recompute-combined failed')
            return {'updated': 0, 'error': str(e)}
        finally:
            _COMBINED_STATE['running'] = False


def _recompute_combined_columns_safe():
    """Startup-safe wrapper: catches and logs, never raises."""
    try:
        res = _recompute_combined_columns()
        print(f"  Combined columns: {res.get('updated', 0)} cells updated of {res.get('scanned', 0)} rows")
    except Exception as e:
        print(f"  Combined columns recompute error: {e}")


def _recompute_for_group_members(ids):
    """Fast path: recompute only rows whose Airtable ID is in the transitive
    closure of the given seed IDs. Used after Works With link add/remove."""
    try:
        seeds = [str(i).strip() for i in (ids or []) if i]
        if not seeds:
            return {'updated': 0}
        data = sheets.get_all_rows('Personnel')
        if not data or len(data) < 2:
            return {'updated': 0}
        headers = data[0]
        rows_data = data[1:]
        id_col = _find_personnel_col(headers, 'Airtable ID')
        ww_col = _find_personnel_col(headers, 'Works With')
        if id_col is None or ww_col is None:
            return {'updated': 0}
        ww_map = {}
        id_to_row = {}
        for idx, row in enumerate(rows_data, start=2):
            if id_col >= len(row):
                continue
            aid = str(row[id_col]).strip()
            if not aid:
                continue
            id_to_row[aid] = idx
            raw = str(row[ww_col]) if ww_col < len(row) else ''
            peers = [p for p in _parse_ww_ids(raw) if p != aid]
            if peers:
                ww_map[aid] = peers
        for owner, peers in list(ww_map.items()):
            for peer in peers:
                if owner not in ww_map.get(peer, []):
                    ww_map.setdefault(peer, []).append(owner)
        expanded = set()
        for seed in seeds:
            expanded.update(_transitive_closure(seed, ww_map))
        row_indices = [id_to_row[a] for a in expanded if a in id_to_row]
        return _recompute_combined_columns(row_indices=row_indices)
    except Exception as e:
        logging.warning(f'_recompute_for_group_members failed: {e}')
        return {'updated': 0, 'error': str(e)}


@app.route('/api/personnel/recompute-combined', methods=['POST'])
@login_required
def api_personnel_recompute_combined():
    """Recompute Combined First Names [USE] and Emails Combined [USE] for
    every Personnel row. Payload may include {row_indices: [int]} to scope."""
    payload = request.get_json(silent=True) or {}
    scope = payload.get('row_indices') or None
    try:
        scope_ri = [int(i) for i in scope] if scope else None
    except Exception:
        scope_ri = None
    result = _recompute_combined_columns(row_indices=scope_ri)
    return jsonify(result)


@app.route('/api/personnel/recompute-combined/status')
@login_required
def api_personnel_recompute_combined_status():
    return jsonify({
        'running': _COMBINED_STATE['running'],
        'last_run': _COMBINED_STATE['last_run'],
        'updated': _COMBINED_STATE['updated'],
    })


@app.route('/api/personnel/<int:row_index>/outreach-events', methods=['GET'])
@login_required
def api_outreach_events_get(row_index):
    try:
        col_idx = _ensure_personnel_column(OUTREACH_EVENTS_COLUMN)
        row = sheets.get_row('Personnel', row_index)
        raw = row[col_idx] if col_idx < len(row) else ''
        try:
            events = json.loads(raw) if raw else []
            if not isinstance(events, list):
                events = []
        except Exception:
            events = []
        return jsonify({'row_index': row_index, 'events': events})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/personnel/<int:row_index>/outreach-events', methods=['POST'])
@login_required
def api_outreach_events_append(row_index):
    d = request.json or {}
    etype = (d.get('event_type') or '').strip()
    summary = (d.get('summary') or '').strip()
    warmth = (d.get('warmth') or '').strip()
    pitch_id = (d.get('pitch_id') or '').strip()
    tags_added = d.get('tags_added') or []
    if etype and etype not in VALID_EVENT_TYPES:
        return jsonify({'error': 'event_type must be one of ' + ', '.join(VALID_EVENT_TYPES)}), 400
    if warmth and warmth not in VALID_WARMTHS:
        return jsonify({'error': 'warmth must be one of ' + ', '.join(VALID_WARMTHS)}), 400
    entry = {
        'ts': datetime.utcnow().isoformat() + 'Z',
        'event_type': etype or 'note',
        'summary': summary,
    }
    if warmth: entry['warmth'] = warmth
    if pitch_id: entry['pitch_id'] = pitch_id
    if tags_added: entry['tags_added'] = list(tags_added)
    try:
        col_idx = _ensure_personnel_column(OUTREACH_EVENTS_COLUMN)
        row = sheets.get_row('Personnel', row_index)
        raw = row[col_idx] if col_idx < len(row) else ''
        try:
            events = json.loads(raw) if raw else []
            if not isinstance(events, list):
                events = []
        except Exception:
            events = []
        events.append(entry)
        sheets.update_cell('Personnel', row_index, col_idx + 1, json.dumps(events, separators=(',', ':')))
        return jsonify({'success': True, 'entry': entry, 'count': len(events)})
    except Exception as e:
        logging.warning('outreach-events append failed: %s', e)
        return jsonify({'error': str(e)}), 500


# ==================== V37 TAG LIBRARY ====================
# Categorised tag vocabulary stored in a "Tag Library" sheet tab. Columns
# are Category, Tag, Color, Description. Categories used by the app:
# Warmth, Fit, Status, Relationship, Timing. Captain can add more.

TAG_LIBRARY_SHEET = 'Tag Library'
TAG_LIBRARY_HEADERS = ['Category', 'Tag', 'Color', 'Description']
TAG_LIBRARY_SEEDS = [
    ('Warmth', 'Cold', '#6b7280', 'No prior contact or long dormant.'),
    ('Warmth', 'Warming', '#f59e0b', 'Recent intro or first reply.'),
    ('Warmth', 'Warm', '#eab308', 'Ongoing conversation, responsive.'),
    ('Warmth', 'Hot', '#ef4444', 'Actively engaged, short cycle.'),
    ('Warmth', 'Established', '#10b981', 'Long-term working relationship.'),
    ('Status', 'Pitched', '#8b5cf6', 'Pitch currently live.'),
    ('Status', 'Replied', '#22c55e', 'Replied to the most recent pitch.'),
    ('Status', 'Passed', '#6b7280', 'Explicit pass on the current pitch.'),
    ('Status', 'Blocked', '#ef4444', 'Do not contact.'),
    ('Relationship', 'Celina Relationship', '#10b981', 'Celina has a personal relationship.'),
    ('Relationship', 'Sonia Relationship', '#6366f1', 'Sonia has a personal relationship.'),
    ('Fit', 'Dance Pitch', '#ec4899', 'Good target for Dance pitches.'),
    ('Fit', 'Pop Pitch', '#8b5cf6', 'Good target for Pop pitches.'),
    ('Fit', 'Sync Pitch', '#0d9488', 'Good target for Sync pitches.'),
    ('Timing', 'Writing Trip', '#ca8a04', 'Currently in a writing-trip window.'),
]

def _ensure_tag_library_tab():
    try:
        existing = sheets.get_all_rows(TAG_LIBRARY_SHEET)
        if existing and len(existing) >= 1:
            return
    except Exception:
        pass
    try:
        sheets._retry(lambda: sheets.service.spreadsheets().batchUpdate(
            spreadsheetId=sheets.spreadsheet_id,
            body={'requests': [{'addSheet': {'properties': {'title': TAG_LIBRARY_SHEET}}}]}
        ).execute())
    except Exception as e:
        logging.info('Tag Library tab may already exist: %s', e)
    seed_rows = [list(r) for r in TAG_LIBRARY_SEEDS]
    sheets._retry(lambda: sheets.service.spreadsheets().values().update(
        spreadsheetId=sheets.spreadsheet_id,
        range=f"'{TAG_LIBRARY_SHEET}'!A1",
        valueInputOption='USER_ENTERED',
        body={'values': [list(TAG_LIBRARY_HEADERS)] + seed_rows}
    ).execute())
    sheets._invalidate_cache(TAG_LIBRARY_SHEET)

@app.route('/api/tag-library', methods=['GET'])
@login_required
def api_tag_library_get():
    try:
        _ensure_tag_library_tab()
        data = sheets.get_all_rows(TAG_LIBRARY_SHEET) or []
        if not data or len(data) < 2:
            return jsonify({'tags': []})
        headers = data[0]
        idx = {h.lower(): i for i, h in enumerate(headers)}
        tags = []
        for r in data[1:]:
            def g(k):
                i = idx.get(k.lower())
                return (r[i] if i is not None and i < len(r) else '').strip()
            tags.append({
                'category': g('Category'),
                'tag': g('Tag'),
                'color': g('Color'),
                'description': g('Description'),
            })
        return jsonify({'tags': tags})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tag-library', methods=['POST'])
@admin_required
def api_tag_library_append():
    d = request.json or {}
    row = [
        (d.get('category') or '').strip(),
        (d.get('tag') or '').strip(),
        (d.get('color') or '').strip(),
        (d.get('description') or '').strip(),
    ]
    if not row[0] or not row[1]:
        return jsonify({'error': 'category and tag required'}), 400
    try:
        _ensure_tag_library_tab()
        sheets.batch_append(TAG_LIBRARY_SHEET, [row])
        return jsonify({'success': True, 'entry': {
            'category': row[0], 'tag': row[1], 'color': row[2], 'description': row[3]}})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== V37 PITCH INTELLIGENCE DASHBOARD ====================
# 10 metrics computed on demand from the live Personnel + Pitch Log + Songs
# sheets. Not cached beyond the existing 120s sheets cache.

def _parse_dt(s, fmts=('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y')):
    for f in fmts:
        try:
            return datetime.strptime(s, f).date()
        except Exception:
            continue
    return None

@app.route('/api/pitch-intelligence', methods=['GET'])
@admin_required
def api_pitch_intelligence():
    today = datetime.now().date()
    window_days = int(request.args.get('window_days', 30) or 30)
    try:
        personnel = sheets.get_all_rows('Personnel') or []
        p_headers = personnel[0] if personnel else []
        p_rows = personnel[1:] if personnel else []
        def p_col(name):
            for j, h in enumerate(p_headers):
                if cleanH(h).lower() == name.lower():
                    return j
            return None
        tags_col = p_col('Tags')
        last_col = p_col('Last Outreach')
        field_col = p_col('Field')
        country_col = p_col('Countries')
        group_leader_col = p_col('Group Leader')

        total_contacts = len(p_rows)
        recently_pitched = 0  # within window_days
        leaders = 0
        dmp_count = 0
        field_counts = {}
        country_counts = {}
        warmth_counts = {w: 0 for w in VALID_WARMTHS}
        for r in p_rows:
            # Last Outreach
            if last_col is not None and last_col < len(r):
                raw = str(r[last_col]).strip()
                if raw:
                    d = _parse_dt(raw)
                    if d and (today - d).days <= window_days:
                        recently_pitched += 1
            # Tags
            if tags_col is not None and tags_col < len(r):
                parts = [t.strip() for t in str(r[tags_col]).split('|') if t.strip()]
                if "Don't Mass Pitch" in parts:
                    dmp_count += 1
                for p in parts:
                    pl = p.lower()
                    if pl in warmth_counts:
                        warmth_counts[pl] += 1
            # Group Leader
            if group_leader_col is not None and group_leader_col < len(r) and str(r[group_leader_col]).strip():
                # A row with any Group Leader value is part of a managed group
                # We count rows that ARE leaders (own ID == leader)
                ac_idx = p_col('Airtable ID')
                if ac_idx is not None and ac_idx < len(r):
                    if str(r[ac_idx]).strip() == str(r[group_leader_col]).strip():
                        leaders += 1
            if field_col is not None and field_col < len(r):
                for f in [x.strip() for x in str(r[field_col]).split('|') if x.strip()]:
                    field_counts[f] = field_counts.get(f, 0) + 1
            if country_col is not None and country_col < len(r):
                cv = str(r[country_col]).strip()
                if cv:
                    try:
                        cv_resolved = resolver.resolve_value('', cv)
                    except Exception:
                        cv_resolved = cv
                    country_counts[cv_resolved or cv] = country_counts.get(cv_resolved or cv, 0) + 1

        # Pitch Log summary
        try:
            pl = sheets.get_all_rows('Pitch Log') or []
            pl_rows = pl[1:] if pl else []
            pitches_in_window = 0
            for r in pl_rows:
                ds = str(r[0]).strip() if len(r) > 0 else ''
                d = _parse_dt(ds)
                if d and (today - d).days <= window_days:
                    pitches_in_window += 1
            total_pitches = len(pl_rows)
        except Exception:
            pitches_in_window = 0
            total_pitches = 0

        top_fields = sorted(field_counts.items(), key=lambda x: -x[1])[:5]
        top_countries = sorted(country_counts.items(), key=lambda x: -x[1])[:5]
        return jsonify({
            'window_days': window_days,
            'as_of': today.isoformat(),
            'metrics': {
                'total_contacts': total_contacts,
                'recently_pitched': recently_pitched,
                'pitches_in_window': pitches_in_window,
                'total_pitches_logged': total_pitches,
                'group_leaders': leaders,
                'dont_mass_pitch': dmp_count,
                'warmth_breakdown': warmth_counts,
                'top_fields': [{'name': n, 'count': c} for n, c in top_fields],
                'top_countries': [{'name': n, 'count': c} for n, c in top_countries],
                'coverage_ratio': round(recently_pitched / total_contacts, 3) if total_contacts else 0,
            },
        })
    except Exception as e:
        logging.warning('pitch-intelligence failed: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/pitch-intelligence')
@admin_required
def page_pitch_intelligence():
    return render_template('pitch_intelligence.html')


# ==================== GLOBAL SEARCH (v36 Phase 6.5) ====================
# A thin wrapper around /api/search-record that is intentionally named
# /api/global-search so the top-bar search UI has a dedicated endpoint
# and can evolve independently (v36.1 adds live highlight metadata).
@app.route('/api/global-search', methods=['GET'])
@login_required
def api_global_search():
    """Global cross-table search. Returns {'results': [...], 'q': str}.

    Each result: {name, table, row_index, route, subtitle}. `route` is the
    page slug (directory/songs) when the record belongs to a grid page;
    otherwise None (e.g. MGMT Companies), and the client links to a modal
    via /api/table-record.
    """
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'results': [], 'q': q})
    try:
        results = _search_records_impl(q, limit=15)
        for r in results:
            if r.get('table') == 'Personnel':
                r['route'] = r.get('route') or 'directory'
            elif r.get('table') == 'Songs':
                r['route'] = r.get('route') or 'songs'
            r['subtitle'] = r.get('table', '')
        return jsonify({'results': results, 'q': q})
    except Exception as e:
        logging.warning('global-search failed: %s', e)
        return jsonify({'error': str(e), 'results': []}), 500

def _recompute_la_times(row_indices=None):
    """Internal helper: recompute [Use] Date Time LA to Send Email + London
    variants for the given row_indices (or every row if None). Returns
    {'updated': int, 'miss_count': int, 'misses': [...]}."""
    row_indices = set(int(i) for i in (row_indices or []) if i)
    data = sheets.get_all_rows('Personnel')
    if not data or len(data) < 2:
        return {'updated': 0, 'miss_count': 0, 'misses': []}
    headers = data[0]
    srt_col = find_col(headers, 'Set Out Reach Date/Time')
    la_col = find_col(headers, 'Date/Time In LA to send email')
    ldn_col = find_col(headers, 'Date/Time In London to send email')
    city_col = find_col(headers, 'City')
    country_col = find_col(headers, 'Countries', 'Country')
    if srt_col is None or la_col is None:
        raise RuntimeError('Required columns missing on Personnel')
    updates = []
    misses = []
    for idx, row in enumerate(data[1:], start=2):
        if row_indices and idx not in row_indices:
            continue
        raw = str(row[srt_col]).strip() if srt_col < len(row) else ''
        if not raw:
            continue
        city = str(row[city_col]).strip() if city_col is not None and city_col < len(row) else ''
        country = str(row[country_col]).strip() if country_col is not None and country_col < len(row) else ''
        tz = tz_resolve(city, country, CITY_LOOKUP)
        if not tz:
            misses.append({'row': idx, 'city': city, 'country': country})
            continue
        la_str = tz_to_la(raw, tz)
        if la_str:
            updates.append((idx, la_col + 1, la_str))
            if ldn_col is not None:
                parsed = tz_parse_iso(raw)
                if parsed:
                    ldn_str = tz_to_zone(parsed, tz, 'Europe/London')
                    updates.append((idx, ldn_col + 1, ldn_str))
    if updates:
        sheets.batch_update_cells('Personnel', updates)
    return {
        'updated': len({u[0] for u in updates}),
        'miss_count': len(misses),
        'misses': misses[:50],
    }


@app.route('/api/directory/recompute-la-times', methods=['POST'])
@login_required
def api_directory_recompute_la_times():
    d = request.json or {}
    try:
        result = _recompute_la_times(d.get('row_indices') or [])
        return jsonify({'success': True, **result})
    except Exception as e:
        logging.warning(f'recompute-la-times failed: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/directory/bulk-set-send-time', methods=['POST'])
@login_required
def api_directory_bulk_set_send_time():
    """Set the Set Out Reach Date/Time for a list of row_indices.

    Payload:
      row_indices: [int, ...] (required)
      date:  'YYYY-MM-DD'
      time:  'HH:MM'
      mode:  'recipient_local' (each contact reads in their own tz) OR
             'fixed'            (all contacts get same wall-clock in fixed_tz)
      fixed_tz: IANA zone (when mode=fixed)

    When mode=recipient_local we store the raw 'YYYY-MM-DDTHH:MM:00' and the
    recompute pass treats it as a wall-clock in the contact's own timezone.
    When mode=fixed we convert to each contact's local wall-clock before
    storing, so the recompute pass produces a consistent LA time.
    """
    d = request.json or {}
    row_indices = [int(i) for i in (d.get('row_indices') or []) if i]
    date_str = (d.get('date') or '').strip()
    time_str = (d.get('time') or '').strip()
    mode = (d.get('mode') or 'recipient_local').strip()
    fixed_tz = (d.get('fixed_tz') or 'Europe/London').strip()
    if not row_indices or not date_str or not time_str:
        return jsonify({'error': 'row_indices, date, time required'}), 400
    try:
        y, m, day = [int(p) for p in date_str.split('-')]
        hh, mm = [int(p) for p in time_str.split(':')]
    except Exception:
        return jsonify({'error': 'Invalid date or time format'}), 400
    try:
        data = sheets.get_all_rows('Personnel')
        if not data or len(data) < 2:
            return jsonify({'error': 'Personnel empty'}), 500
        headers = data[0]
        srt_col = find_col(headers, 'Set Out Reach Date/Time')
        city_col = find_col(headers, 'City')
        country_col = find_col(headers, 'Countries', 'Country')
        if srt_col is None:
            return jsonify({'error': 'Set Out Reach Date/Time column missing'}), 400
        updates = []
        recompute_rows = []
        from zoneinfo import ZoneInfo
        for idx in row_indices:
            if idx < 2 or idx > len(data):
                continue
            row = data[idx - 1]
            if mode == 'fixed':
                try:
                    src = ZoneInfo(fixed_tz)
                    city = str(row[city_col]).strip() if city_col is not None and city_col < len(row) else ''
                    country = str(row[country_col]).strip() if country_col is not None and country_col < len(row) else ''
                    recip_tz = tz_resolve(city, country, CITY_LOOKUP) or fixed_tz
                    dst = ZoneInfo(recip_tz)
                    src_dt = datetime(y, m, day, hh, mm, 0, tzinfo=src)
                    dst_dt = src_dt.astimezone(dst)
                    iso = dst_dt.strftime('%Y-%m-%dT%H:%M:00')
                except Exception:
                    iso = f'{y:04d}-{m:02d}-{day:02d}T{hh:02d}:{mm:02d}:00'
            else:
                iso = f'{y:04d}-{m:02d}-{day:02d}T{hh:02d}:{mm:02d}:00'
            updates.append((idx, srt_col + 1, iso))
            recompute_rows.append(idx)
        if updates:
            sheets.batch_update_cells('Personnel', updates)
        recompute_result = {'updated': 0, 'miss_count': 0}
        if recompute_rows:
            sheets._invalidate_cache('Personnel')
            try:
                recompute_result = _recompute_la_times(recompute_rows)
            except Exception as e:
                logging.warning(f'recompute inside bulk-set: {e}')
        return jsonify({
            'success': True,
            'set': len(updates),
            'mode': mode,
            'recompute': recompute_result,
        })
    except Exception as e:
        logging.warning(f'bulk-set-send-time failed: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/relationships/types', methods=['GET'])
@login_required
def api_relationships_types():
    """Returns the LINK_TYPES registry for the UI. Excludes the symmetric
    works_with since that has its own dedicated surface."""
    out = []
    for key, spec in RELATIONSHIP_LINK_TYPES.items():
        if key == 'works_with':
            continue
        out.append({
            'key': key,
            'column': spec['column'],
            'inverse': spec['inverse'],
            'symmetric': spec['symmetric'],
        })
    return jsonify({'types': out})

@app.route('/api/relationships/generic-add', methods=['POST'])
@login_required
def api_relationships_generic_add():
    d = request.json or {}
    id_a = (d.get('from_id') or '').strip()
    id_b = (d.get('to_id') or '').strip()
    lt = (d.get('link_type') or '').strip()
    if not (id_a and id_b and lt):
        return jsonify({'error': 'from_id, to_id, link_type required'}), 400
    if lt not in RELATIONSHIP_LINK_TYPES:
        return jsonify({'error': f'Unknown link_type {lt}'}), 400
    try:
        ok = relationships.generic_add(id_a, id_b, lt)
        if not ok:
            return jsonify({'error': 'Could not resolve IDs for link'}), 400
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/relationships/generic-remove', methods=['POST'])
@login_required
def api_relationships_generic_remove():
    d = request.json or {}
    id_a = (d.get('from_id') or '').strip()
    id_b = (d.get('to_id') or '').strip()
    lt = (d.get('link_type') or '').strip()
    if not (id_a and id_b and lt):
        return jsonify({'error': 'from_id, to_id, link_type required'}), 400
    if lt not in RELATIONSHIP_LINK_TYPES:
        return jsonify({'error': f'Unknown link_type {lt}'}), 400
    try:
        relationships.generic_remove(id_a, id_b, lt)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ---- Backwards-compat shim for the pre-v36 name-based endpoint. ----
# Old UI sent a comma-separated list of names. We resolve names to Airtable IDs
# and defer to the new engine. Kept so any cached JS/loaded page still works
# during the v36 rollout.
@app.route('/api/automate/works-with', methods=['POST'])
@login_required
def api_works_with_legacy():
    d = request.json or {}
    mri = d.get('master_row_index')
    linked_names = d.get('linked_names') or []
    if not mri or not linked_names:
        return jsonify({'error': 'Master row and names required'}), 400
    try:
        master_id = relationships.id_for_row(int(mri))
        if not master_id:
            return jsonify({'error': 'Master row has no Airtable ID'}), 400
        results = {'added': [], 'missing': []}
        for ln in linked_names:
            matches = relationships.search_by_name(ln, limit=1)
            if matches and matches[0]['id']:
                ok = relationships.add_link(master_id, matches[0]['id'])
                if ok:
                    results['added'].append({'name': matches[0]['name'], 'id': matches[0]['id']})
                    continue
            results['missing'].append(ln)
        return jsonify({'success': True, **results})
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
            ci, cname = resolve_filter_col(headers, f['col'])
            if ci is not None:
                indexed = apply_filter(indexed, ci, f['op'], f['val'], cname)
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


# ==================== SCOUT DISCOVERY ENGINE ====================
_scout_discovery = None
_scout_cache = {}  # {artist_name: {timestamp, data}}
_scout_cache_lock = threading.Lock()

def _get_scout_discovery():
    global _scout_discovery
    if _scout_discovery is None:
        _scout_discovery = ScoutDiscovery(sheets, find_col, cleanH)
    return _scout_discovery


@app.route('/api/scout/roster')
@admin_required
def api_scout_roster():
    """Get all roster artists available for scouting."""
    artists = get_roster_artists(sheets, find_col)
    return jsonify({'artists': artists})


@app.route('/api/scout/discover')
@admin_required
def api_scout_discover():
    """Run discovery for a roster artist. Returns cached if fresh (<6h)."""
    artist_name = request.args.get('artist', '').strip()
    force = request.args.get('force', '').lower() == 'true'
    if not artist_name:
        return jsonify({'error': 'Artist name required'}), 400

    # Check cache
    with _scout_cache_lock:
        cached = _scout_cache.get(artist_name.lower())
    if cached and not force:
        age = time.time() - cached.get('timestamp_epoch', 0)
        if age < 21600:  # 6 hours
            return jsonify(cached['data'])

    # Run discovery
    discovery = _get_scout_discovery()
    filters = {}
    if request.args.get('genre'):
        filters['genre'] = request.args.get('genre')
    if request.args.get('min_listeners'):
        filters['min_listeners'] = request.args.get('min_listeners')
    if request.args.get('max_listeners'):
        filters['max_listeners'] = request.args.get('max_listeners')
    if request.args.get('location'):
        filters['location'] = request.args.get('location')

    try:
        data = discovery.run_full_discovery(artist_name, filters)
        # Cache result
        with _scout_cache_lock:
            _scout_cache[artist_name.lower()] = {
                'timestamp_epoch': time.time(),
                'data': data
            }
        return jsonify(data)
    except Exception as e:
        logging.warning(f"Scout discovery error for {artist_name}: {e}")
        return jsonify({'error': str(e), 'collaborators': [], 'tours': [], 'sync_briefs': []}), 500


@app.route('/api/scout/warm-connections')
@admin_required
def api_scout_warm():
    """Find warm connections for an entity name."""
    name = request.args.get('name', '').strip()
    if not name:
        return jsonify({'connections': []})
    conns = scout_warm_connections(name, sheets, find_col, cleanH)
    return jsonify({'connections': conns, 'count': len(conns)})


@app.route('/api/scout/profile')
@admin_required
def api_scout_profile():
    """Get full profile for a roster artist."""
    name = request.args.get('artist', '').strip()
    if not name:
        return jsonify({'error': 'Artist name required'}), 400
    profile = get_artist_profile(sheets, find_col, name)
    songs = get_artist_songs(sheets, find_col, name)
    return jsonify({'profile': profile, 'songs': songs, 'song_count': len(songs)})


@app.route('/api/settings/api-keys', methods=['POST'])
@admin_required
def api_save_api_keys():
    """Save API keys to .env file."""
    d = request.json or {}
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    try:
        # Read existing .env
        existing = {}
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        existing[k.strip()] = v.strip()
        # Update with new keys (only non-empty values)
        for key in ['SPOTIFY_CLIENT_ID', 'SPOTIFY_CLIENT_SECRET', 'SONGKICK_API_KEY', 'LASTFM_API_KEY']:
            val = d.get(key, '').strip()
            if val:
                existing[key] = val
                os.environ[key] = val
        # Write back
        with open(env_path, 'w') as f:
            for k, v in existing.items():
                f.write(f"{k}={v}\n")
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/scout/sources')
@admin_required
def api_scout_sources():
    """Check which API sources are configured."""
    import os
    return jsonify({
        'spotify': bool(os.environ.get('SPOTIFY_CLIENT_ID') and os.environ.get('SPOTIFY_CLIENT_SECRET')),
        'songkick': bool(os.environ.get('SONGKICK_API_KEY')),
        'lastfm': bool(os.environ.get('LASTFM_API_KEY')),
        'bandsintown': True
    })


@app.errorhandler(404)
def not_found(e): return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e): return render_template('500.html'), 500


# ==================== V37.3 FILTER SMOKE TESTS ====================
def run_filter_smoke_tests():
    """v37.3: fail-loud startup tests ensuring the filter system returns
    non-zero results for Celina's pitching-critical queries. Raises
    RuntimeError on any failure so Deploy.command aborts."""
    data = sheets.get_all_rows('Personnel')
    if not data or len(data) < 2:
        raise RuntimeError('Personnel sheet empty; cannot run filter smoke tests')
    headers = data[0]
    rows = [(i + 2, r) for i, r in enumerate(data[1:])]
    results = {}
    def run(label, *filters):
        current = rows
        for col_name, op, val in filters:
            ci, cname = resolve_filter_col(headers, col_name)
            if ci is None:
                raise RuntimeError(f"SMOKE FAIL [{label}]: column '{col_name}' not found")
            current = apply_filter(current, ci, op, val, cname)
        results[label] = len(current)
        return len(current)

    run('Country = UK', ('Country', 'is', 'UK'))
    run('Country has any of (UK, US)', ('Country', 'has_any_of', 'UK,US'))
    run('Field has any of (Record A&R)', ('Field', 'has_any_of', 'Record A&R'))
    run('Country = UK AND Field has any of (MGMT, Publishing A&R, Record A&R, Writer MGMT)',
        ('Country', 'is', 'UK'),
        ('Field', 'has_any_of', 'MGMT,Publishing A&R,Record A&R,Writer MGMT'))
    run('Works With is not empty', ('Works With', 'is_not_empty', ''))

    print('  Filter smoke tests:')
    failed = []
    for label, count in results.items():
        status = 'OK' if count > 0 else 'FAIL'
        print(f'    [{status}] {label}: {count}')
        if count == 0:
            failed.append(label)
    if failed:
        raise RuntimeError('Filter smoke tests failed: ' + ' ; '.join(failed))
    return results


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

    print("Ensuring v36 relationship columns (Backlinks Cache, Grouping Override, Group Leader)...")
    try:
        added = relationships.ensure_columns()
        print(f"  Columns: {added}")
    except Exception as e: print(f"  Warning: {e}")

    print("Running v37.3 filter smoke tests (fail-loud)...")
    try:
        run_filter_smoke_tests()
    except Exception as e:
        print(f"\n  FATAL: {e}\n")
        raise SystemExit(2)

    print("Recomputing Combined First Names / Emails Combined (background)...")
    try:
        threading.Thread(target=lambda: _recompute_combined_columns_safe(), daemon=True).start()
    except Exception as e:
        print(f"  Warning: {e}")

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
