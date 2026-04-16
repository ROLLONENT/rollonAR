"""
One-time migration: Import Music Supervisor data from Airtable into Google Sheets Personnel tab.
Run from the rollon/ directory: python3 migrate_music_supervisors.py

Source: Airtable base "Music Supervisor Database" (appoZWMZrCk3xyUGf)
Tables imported: Supervisor, Perspective Shows, Songs, Publisher / Manager, Company, Targets
Tag: "Import: Music Supervisors Airtable 2026-04-15"
Dedup: name + email against existing Personnel rows
"""
import os, sys, json, re

sys.path.insert(0, os.path.dirname(__file__))
from modules.google_sheets import SheetsManager

# ── Config ──────────────────────────────────────────────────────────────
GOOGLE_SHEET_ID = os.environ.get('ROLLON_SHEET_ID', '17b7HjbfXkV5w_Q8lRuG3Ae_7hwJ0M9F7ODVIFytBBmY')
CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), 'credentials.json')
TOKEN_PATH = os.path.join(os.path.dirname(__file__), 'token.json')
if not os.path.exists(TOKEN_PATH):
    TOKEN_PATH = os.path.join(os.path.dirname(__file__), '..', 'token.json')

IMPORT_TAG = "Import: Music Supervisors Airtable 2026-04-15"
AIRTABLE_DATA = '/tmp/airtable_music_sups.json'

# ── Load Airtable data ─────────────────────────────────────────────────
with open(AIRTABLE_DATA) as f:
    at_data = json.load(f)

supervisors = at_data['Supervisor']
shows = at_data['Perspective Shows']
songs = at_data['Songs']
publishers = at_data['Publisher / Manager']
companies = at_data['Company']
targets = at_data['Targets']

print(f"Loaded from Airtable:")
print(f"  Supervisors: {len(supervisors)}")
print(f"  Perspective Shows: {len(shows)}")
print(f"  Songs: {len(songs)}")
print(f"  Publishers/Managers: {len(publishers)}")
print(f"  Companies: {len(companies)}")
print(f"  Targets: {len(targets)}")

# ── Build lookup tables for resolving Airtable record IDs ──────────────
company_lookup = {}
for r in companies:
    company_lookup[r['id']] = r['fields'].get('Name', '')

supervisor_lookup = {}
for r in supervisors:
    supervisor_lookup[r['id']] = r['fields'].get('Full Name', '')

show_lookup = {}
for r in shows:
    f = r['fields']
    show_lookup[r['id']] = f.get('Network Outlet', f.get('Outlet', ''))

song_lookup = {}
for r in songs:
    f = r['fields']
    song_lookup[r['id']] = f.get('Name', '')

publisher_lookup = {}
for r in publishers:
    publisher_lookup[r['id']] = r['fields'].get('Name', '')


def resolve_ids(val, lookup):
    """Resolve a list of Airtable record IDs to names using a lookup dict."""
    if not val:
        return ''
    if isinstance(val, list):
        names = []
        for v in val:
            if isinstance(v, str) and v.startswith('rec'):
                names.append(lookup.get(v, v))
            else:
                names.append(str(v))
        return ' | '.join(names)
    return str(val)


def flatten(val):
    """Flatten a list or scalar to a pipe-separated string."""
    if isinstance(val, list):
        parts = []
        for v in val:
            if isinstance(v, bool):
                parts.append('Yes' if v else 'No')
            else:
                parts.append(str(v))
        return ' | '.join(parts)
    if isinstance(val, bool):
        return 'Yes' if val else 'No'
    return str(val) if val is not None else ''


# ── Connect to Google Sheets ───────────────────────────────────────────
sheets = SheetsManager(GOOGLE_SHEET_ID, CREDENTIALS_PATH, TOKEN_PATH)

# ── Read existing Personnel for dedup ──────────────────────────────────
rows = sheets.get_all_rows('Personnel')
headers = rows[0] if rows else []
data_rows = rows[1:] if len(rows) > 1 else []

def clean_header(h):
    return re.sub(r'^\[.*?\]\s*', '', h).strip().lower()

clean_headers = [clean_header(h) for h in headers]

name_col = next((i for i, h in enumerate(clean_headers) if h == 'name'), None)
email_col = next((i for i, h in enumerate(clean_headers) if h == 'email'), None)

print(f"\nExisting Personnel: {len(data_rows)} rows")
print(f"  Name col: {name_col} ({headers[name_col]})")
print(f"  Email col: {email_col} ({headers[email_col]})")

# Build dedup set: (lowercase name, lowercase email)
existing_set = set()
for r in data_rows:
    name = r[name_col].strip().lower() if name_col is not None and name_col < len(r) and r[name_col] else ''
    email = r[email_col].strip().lower() if email_col is not None and email_col < len(r) and r[email_col] else ''
    if name:
        existing_set.add((name, email))

print(f"  Unique name+email combos for dedup: {len(existing_set)}")

# ── Map Airtable Supervisor fields to Personnel columns ────────────────
# Personnel columns (cleaned): name, genre, city, outreach notes, tags, title,
# works with, field, email, linkedin/socials, company, credits [sync], ...

def find_col(target):
    """Find column index by cleaned header name (partial match ok)."""
    for i, h in enumerate(clean_headers):
        if h == target:
            return i
    for i, h in enumerate(clean_headers):
        if target in h:
            return i
    return None

# Column mapping
col_map = {
    'name': find_col('name'),
    'field': find_col('field'),
    'email': find_col('email'),
    'city': find_col('city'),
    'tags': find_col('tags'),
    'title': find_col('title'),
    'works_with': find_col('works with'),
    'linkedin': find_col('linkedin/socials'),
    'company': find_col('company'),
    'outreach_notes': find_col('outreach notes'),
    'website': find_col('website'),
    'bio': find_col('bio'),
    'credits_sync': find_col('credits [sync]'),
    'pitched_songs': find_col('pitched songs'),
}

print("\nColumn mapping:")
for k, v in col_map.items():
    h = headers[v] if v is not None else 'NOT FOUND'
    print(f"  {k} -> col {v} ({h})")

# ── Build import rows ──────────────────────────────────────────────────
num_cols = len(headers)
imported = []
skipped_dupes = []
skipped_no_name = []

for rec in supervisors:
    f = rec['fields']
    full_name = f.get('Full Name', '').strip()
    if not full_name:
        skipped_no_name.append(rec['id'])
        continue

    email = f.get('Email', '').strip()

    # Dedup check
    key = (full_name.lower(), email.lower())
    if key in existing_set:
        skipped_dupes.append(full_name)
        continue

    # Build row (empty string for each column)
    row = [''] * num_cols

    # Map fields
    if col_map['name'] is not None:
        row[col_map['name']] = full_name
    if col_map['email'] is not None:
        row[col_map['email']] = email
    if col_map['field'] is not None:
        # Use source data's Field value, default to "Music Supervisor"
        field_val = flatten(f.get('Field', []))
        row[col_map['field']] = field_val if field_val else 'Music Supervisor'
    if col_map['city'] is not None:
        row[col_map['city']] = f.get('Location', '')
    if col_map['title'] is not None:
        row[col_map['title']] = flatten(f.get('Title', []))
    if col_map['company'] is not None:
        row[col_map['company']] = resolve_ids(f.get('Company'), company_lookup)
    if col_map['works_with'] is not None:
        row[col_map['works_with']] = resolve_ids(f.get('Works With'), supervisor_lookup)
    if col_map['linkedin'] is not None:
        # Combine linkedin, IMDB, top social media
        socials = []
        if f.get('Linkedin'):
            socials.append(f['Linkedin'])
        if f.get('IMDB'):
            socials.append(f['IMDB'])
        if f.get('Top Social Media'):
            socials.append(f['Top Social Media'])
        row[col_map['linkedin']] = ' | '.join(socials)
    if col_map['website'] is not None and 'Website' in f:
        val = f['Website']
        if val and val != 'NA':
            row[col_map['website']] = val

    # Notes: combine Note, NO CONTACT flag, Not working flag, Accepted, pitch dates
    notes_parts = []
    if f.get('Note'):
        notes_parts.append(f['Note'].strip())
    if f.get('NO CONTACT'):
        notes_parts.append('⚠️ NO CONTACT')
    if f.get('Not working!'):
        notes_parts.append('⚠️ Not working')
    if f.get('Accepted'):
        notes_parts.append(f'Accepted: {flatten(f["Accepted"])}')
    if f.get('1st Pitch Date'):
        notes_parts.append(f'1st Pitch: {f["1st Pitch Date"]}')
    if f.get('1st Follow Up Date'):
        notes_parts.append(f'1st Follow Up: {f["1st Follow Up Date"]}')
    if f.get('Personal Disco Link'):
        notes_parts.append(f'Disco: {f["Personal Disco Link"]}')
    # Resolve Perspective Shows
    if f.get('Perspective Shows'):
        show_names = resolve_ids(f['Perspective Shows'], show_lookup)
        if show_names:
            notes_parts.append(f'Shows: {show_names}')
    # Resolve Songs Pitched
    if f.get('Songs Pitched'):
        song_names = resolve_ids(f['Songs Pitched'], song_lookup)
        if song_names:
            notes_parts.append(f'Songs Pitched: {song_names}')

    if col_map['outreach_notes'] is not None and notes_parts:
        row[col_map['outreach_notes']] = ' | '.join(notes_parts)

    # Tags: include import tag + any existing Airtable tags
    tag_parts = [IMPORT_TAG]
    if f.get('Tag'):
        tag_parts.extend(f['Tag'] if isinstance(f['Tag'], list) else [f['Tag']])
    if f.get('To Pitch') and f['To Pitch'] == [True]:
        tag_parts.append('To Pitch')
    if col_map['tags'] is not None:
        row[col_map['tags']] = ' | '.join(tag_parts)

    # Pitched songs in dedicated column
    if col_map['pitched_songs'] is not None and f.get('Songs Pitched'):
        row[col_map['pitched_songs']] = resolve_ids(f['Songs Pitched'], song_lookup)

    # Airtable ID in first column
    row[0] = rec['id']

    imported.append(row)
    existing_set.add(key)  # prevent intra-batch dupes

print(f"\n── Import Summary ──")
print(f"  Total Supervisor records: {len(supervisors)}")
print(f"  Importing: {len(imported)}")
print(f"  Skipped (exact dupes): {len(skipped_dupes)}")
print(f"  Skipped (no name): {len(skipped_no_name)}")

if skipped_dupes:
    print(f"\n  Sample dupes skipped: {skipped_dupes[:10]}")

# ── Append to Personnel ────────────────────────────────────────────────
if imported:
    print(f"\nAppending {len(imported)} rows to Personnel...")
    sheets.batch_append('Personnel', imported)
    sheets._invalidate_cache('Personnel')
    print("Done!")

    # Verify
    verify = sheets.get_all_rows('Personnel')
    print(f"Personnel now has {len(verify)-1} data rows (was {len(data_rows)})")
else:
    print("\nNothing to import (all records already exist).")

# ── Summary of all tables ──────────────────────────────────────────────
print(f"\n── Airtable Data Summary ──")
print(f"  Supervisor: {len(supervisors)} records (primary import)")
print(f"  Perspective Shows: {len(shows)} records (referenced in notes)")
print(f"  Songs: {len(songs)} records (referenced in notes)")
print(f"  Companies: {len(companies)} records (resolved to names)")
print(f"  Publishers/Managers: {len(publishers)} records (resolved to names)")
print(f"  Targets: {len(targets)} records (reference data)")
print(f"\nAll record IDs from linked tables resolved to human-readable names.")
print(f"Every imported record tagged: '{IMPORT_TAG}'")
