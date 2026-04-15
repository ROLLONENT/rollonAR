"""
SECTION 1: Data Integrity Fix — Remove incorrect brand/import tags from real people.

Tags to remove from real Personnel records:
  - "Brand Target"
  - "EMMMA Brand DNA"
  - "Import: Brand DNA"

Brand placeholder records (like "Glossier PR", "Nike PR", etc.) are NOT modified.

Usage:
  python3 cleanup_brand_tags.py          # Dry run (shows what would change)
  python3 cleanup_brand_tags.py --fix    # Actually fix the records
"""

import os, sys, re

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from modules.google_sheets import SheetsManager

GOOGLE_SHEET_ID = os.environ.get('ROLLON_SHEET_ID', '17b7HjbfXkV5w_Q8lRuG3Ae_7hwJ0M9F7ODVIFytBBmY')
CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), 'credentials.json')
TOKEN_PATH = os.path.join(os.path.dirname(__file__), 'token.json')

BAD_TAGS = {'Brand Target', 'EMMMA Brand DNA', 'Import: Brand DNA'}

# Brand placeholder patterns — these are NOT real people, skip them
BRAND_PATTERNS = re.compile(
    r'\b(PR|Marketing|Brand|Corp|Inc|LLC|Agency|Team|Dept|Department|Office|Group)\b',
    re.IGNORECASE
)
BRAND_NAMES = {
    'glossier pr', 'nike pr', 'adidas pr', 'puma pr', 'coca-cola pr',
    'red bull pr', 'apple music pr', 'spotify pr', 'tiktok pr',
    # Add more known brand placeholders as needed
}

def is_brand_placeholder(name):
    """Return True if this record looks like a brand placeholder, not a real person."""
    if not name:
        return False
    nl = name.strip().lower()
    if nl in BRAND_NAMES:
        return True
    if BRAND_PATTERNS.search(name):
        return True
    return False

def clean_header(h):
    return re.sub(r'\[.\]\s*|\[\?\?\]\s*|\[.\]\s*', '', h or '').strip()

def run(fix=False):
    sheets = SheetsManager(GOOGLE_SHEET_ID, CREDENTIALS_PATH, TOKEN_PATH)
    data = sheets.get_all_rows('Personnel')
    if not data or len(data) < 2:
        print("No Personnel data found.")
        return

    headers = data[0]
    rows = data[1:]

    # Find name and tags columns
    name_col = None
    tags_col = None
    for i, h in enumerate(headers):
        ch = clean_header(h).lower()
        if ch in ('name', 'title') and name_col is None:
            name_col = i
        if ch in ('tags', 'tag') and tags_col is None:
            tags_col = i

    if name_col is None or tags_col is None:
        print(f"Could not find Name (col={name_col}) or Tags (col={tags_col}) column.")
        return

    fixed_count = 0
    skipped_brands = 0
    updates = []  # (row_index, col_index, new_value)

    for i, row in enumerate(rows):
        row_index = i + 2  # 1-indexed, skip header
        name = row[name_col].strip() if name_col < len(row) else ''
        tags_raw = row[tags_col].strip() if tags_col < len(row) else ''

        if not tags_raw:
            continue

        # Parse tags (pipe-separated)
        tags = [t.strip() for t in tags_raw.split('|') if t.strip()]

        # Check if any bad tags exist
        bad_found = [t for t in tags if t in BAD_TAGS]
        if not bad_found:
            continue

        # Skip brand placeholders
        if is_brand_placeholder(name):
            skipped_brands += 1
            print(f"  SKIP (brand placeholder): {name} — tags: {', '.join(bad_found)}")
            continue

        # Remove bad tags from real people
        new_tags = [t for t in tags if t not in BAD_TAGS]
        new_tags_str = ' | '.join(new_tags)

        print(f"  FIX: {name}")
        print(f"    Remove: {', '.join(bad_found)}")
        print(f"    Before: {tags_raw}")
        print(f"    After:  {new_tags_str}")

        if fix:
            updates.append((row_index, tags_col + 1, new_tags_str))

        fixed_count += 1

    print(f"\n{'='*50}")
    print(f"Records to fix: {fixed_count}")
    print(f"Brand placeholders skipped: {skipped_brands}")

    if fix and updates:
        print(f"\nApplying {len(updates)} fixes...")
        sheets.batch_update_cells('Personnel', updates)
        print("Done! All fixes applied.")
    elif not fix and fixed_count > 0:
        print(f"\nDry run complete. Run with --fix to apply changes:")
        print(f"  python3 cleanup_brand_tags.py --fix")

    return fixed_count

if __name__ == '__main__':
    do_fix = '--fix' in sys.argv
    if do_fix:
        print("FIXING records (live mode)...\n")
    else:
        print("DRY RUN (no changes will be made)...\n")
    run(fix=do_fix)
