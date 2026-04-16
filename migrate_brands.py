"""
EMMMA Brand Partnership System — Import brands into Personnel.
Sections A + B + F: Add columns, import 200+ brands, create templates.
Run from rollon/ directory: python3 migrate_brands.py
"""
import os, sys, json, re, time

sys.path.insert(0, os.path.dirname(__file__))
from modules.google_sheets import SheetsManager

GOOGLE_SHEET_ID = os.environ.get('ROLLON_SHEET_ID', '17b7HjbfXkV5w_Q8lRuG3Ae_7hwJ0M9F7ODVIFytBBmY')
CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), 'credentials.json')
TOKEN_PATH = os.path.join(os.path.dirname(__file__), 'token.json')
if not os.path.exists(TOKEN_PATH):
    TOKEN_PATH = os.path.join(os.path.dirname(__file__), '..', 'token.json')

sheets = SheetsManager(GOOGLE_SHEET_ID, CREDENTIALS_PATH, TOKEN_PATH)

IMPORT_TAG = "Import: Brand DNA 2026-04-15"

# ── SECTION A: Add brand columns if missing ────────────────────────────
print("=" * 60)
print("SECTION A: Adding brand columns to Personnel")
print("=" * 60)

NEW_COLUMNS = ["Brand", "Brand Category", "Instagram Handle", "Outreach Method",
               "Partnership Type", "Campaign Notes", "Budget Range", "One Sheet URL"]

headers = sheets.get_headers('Personnel')

def clean_header(h):
    return re.sub(r'^\[.*?\]\s*', '', h).strip().lower()

clean_existing = [clean_header(h) for h in headers]

added_cols = []
for col_name in NEW_COLUMNS:
    if col_name.lower() in clean_existing:
        print(f"  [exists] {col_name}")
    else:
        col_idx = len(headers) + 1
        sheets.update_cell('Personnel', 1, col_idx, col_name)
        headers.append(col_name)
        clean_existing.append(col_name.lower())
        added_cols.append(col_name)
        print(f"  [added]  {col_name} (col {col_idx})")

sheets._invalidate_cache('Personnel')
print(f"\nAdded {len(added_cols)} new columns: {added_cols}")

# Refresh headers after adding columns
headers = sheets.get_headers('Personnel')
clean_existing = [clean_header(h) for h in headers]

# ── SECTION B: Import 200+ brand records ────────────────────────────────
print("\n" + "=" * 60)
print("SECTION B: Importing brand records")
print("=" * 60)

BRANDS = {
    "Fashion": [
        "AllSaints", "Cheap Monday", "Converse", "Doc Martens", "Dr. Denim",
        "Free People", "Ganni", "Killstar", "Levi's", "Lisa Says Gah",
        "Madewell", "Monki", "Nasty Gal", "Nudie Jeans", "Reformation",
        "Stussy", "The Kooples", "The Ragged Priest", "UNIF", "Urban Outfitters",
        "Weekday", "Chanel", "Gucci", "Dior", "Prada", "Hermes", "Louis Vuitton",
        "Saint Laurent", "Balenciaga", "Givenchy", "Bottega Veneta", "ASOS",
        "Depop", "Msbhv", "Diesel", "Acne"
    ],
    "Footwear": [
        "Adidas", "Nike", "Puma", "New Balance", "Solomon", "Asics", "Hoka",
        "Under Armour", "Reebok", "Vans", "Columbia", "Patagonia",
        "The North Face", "Allbirds", "On Running", "Veja", "Rothy's",
        "Vivobarefoot", "Altra"
    ],
    "Cosmetics": [
        "Anastasia Beverly Hills", "bareMinerals", "Benefit", "Bobbi Brown",
        "Charlotte Tilbury", "Clinique", "Fenty Beauty", "Glossier", "Haus Labs",
        "Hourglass", "Huda Beauty", "MAC", "NARS", "Pat McGrath", "Rare Beauty",
        "Sephora", "Sol de Janeiro", "Tarte", "Too Faced", "Urban Decay",
        "La Mer", "SK-II", "Milk Makeup", "Lime Crime", "The Ordinary",
        "Glow Recipe", "Byredo", "Le Labo", "Tom Ford Beauty", "Kosas", "Saie",
        "Freck", "Refy", "Westman Atelier", "Youth To The People", "Laneige",
        "Dr. Jart", "Buxom", "Iconic London", "IT Cosmetics", "Smashbox",
        "Valentino", "La Prairie", "Sisley", "Guerlain", "Cle de Peau",
        "Chantecaille"
    ],
    "Fragrance": [
        "DS & Durga", "Imaginary Authors", "Maison Margiela", "Phlur", "Skylar",
        "Henry Rose", "Boy Smells", "DedCool"
    ],
    "Music Tech": [
        "Ableton", "Fender", "Gibson", "Korg", "Moog", "Roland", "Sennheiser",
        "Shure", "Beats by Dre", "Sony", "Bose", "Audio-Technica", "Taylor",
        "Nord", "Neumann", "Yamaha", "Behringer", "AKG", "Apollo Universal Audio"
    ],
    "Lifestyle": [
        "Polaroid", "Urbanears", "Bang & Olufsen", "Aesop", "Dyson", "Leica",
        "Apple", "Rimowa", "Diptyque", "Rolex", "Smeg", "Vitra", "Assouline"
    ],
    "Beverages": [
        "Red Bull", "Liquid Death", "Topo Chico", "Oatly", "White Claw",
        "Casamigos", "Hendrick's", "Aperol"
    ],
    "Media": [
        "Notion", "The Face", "Vogue", "Dazed", "i-D", "Pitchfork",
        "Rolling Stone", "NME", "The Fader", "Hypebeast", "Highsnobiety",
        "Complex", "Refinery29", "Allure", "Byrdie", "Elle", "Harper's Bazaar",
        "GQ", "Esquire", "Into the Gloss", "Goop", "Stereogum", "The Hundreds"
    ]
}

total_brands = sum(len(v) for v in BRANDS.values())
print(f"Total brands to import: {total_brands}")

# Column index lookup
def find_col(target):
    target_l = target.lower()
    for i, h in enumerate(clean_existing):
        if h == target_l:
            return i
    for i, h in enumerate(clean_existing):
        if target_l in h:
            return i
    return None

col = {
    'name': find_col('name'),
    'field': find_col('field'),
    'tags': find_col('tags'),
    'brand': find_col('brand'),
    'brand_category': find_col('brand category'),
    'outreach_notes': find_col('outreach notes'),
    'email': find_col('email'),
}

print(f"\nColumn mapping:")
for k, v in col.items():
    h = headers[v] if v is not None else 'NOT FOUND'
    print(f"  {k} -> col {v} ({h})")

# Load existing Personnel names for dedup
print("\nLoading existing Personnel for dedup...")
rows = sheets.get_all_rows('Personnel')
data_rows = rows[1:] if len(rows) > 1 else []
existing_names = set()
for r in data_rows:
    name = r[col['name']].strip().lower() if col['name'] is not None and col['name'] < len(r) and r[col['name']] else ''
    if name:
        existing_names.add(name)
print(f"  Existing records: {len(data_rows)}")
print(f"  Unique names: {len(existing_names)}")

# Build import rows
num_cols = len(headers)
imported = []
skipped = []

for category, brands in BRANDS.items():
    for brand_name in brands:
        display_name = f"{brand_name} PR"
        if display_name.lower() in existing_names:
            skipped.append(display_name)
            continue

        row = [''] * num_cols
        if col['name'] is not None:
            row[col['name']] = display_name
        if col['field'] is not None:
            row[col['field']] = "Brand PR"
        if col['tags'] is not None:
            row[col['tags']] = f"Brand Target | EMMMA Brand DNA | {IMPORT_TAG}"
        if col['brand'] is not None:
            row[col['brand']] = brand_name
        if col['brand_category'] is not None:
            row[col['brand_category']] = category
        if col['outreach_notes'] is not None:
            row[col['outreach_notes']] = f"{brand_name} — {category} brand. Contact research pending."
        # No email yet — will be researched in Section E

        imported.append(row)
        existing_names.add(display_name.lower())

print(f"\n── Import Summary ──")
print(f"  Total brands: {total_brands}")
print(f"  Importing: {len(imported)}")
print(f"  Skipped (dupes): {len(skipped)}")
if skipped:
    print(f"  Dupes: {skipped[:10]}...")

if imported:
    print(f"\nAppending {len(imported)} rows to Personnel...")
    sheets.batch_append('Personnel', imported)
    sheets._invalidate_cache('Personnel')
    print("Done!")

    verify = sheets.get_all_rows('Personnel')
    print(f"Personnel now has {len(verify)-1} data rows")
else:
    print("\nNothing to import.")

# ── SECTION F: Create pitch templates ───────────────────────────────────
print("\n" + "=" * 60)
print("SECTION F: Creating pitch templates")
print("=" * 60)

def ensure_templates():
    try:
        data = sheets.get_all_rows('Templates')
        if data: return True
    except:
        pass
    try:
        sheets.service.spreadsheets().batchUpdate(
            spreadsheetId=sheets.spreadsheet_id,
            body={'requests': [{'addSheet': {'properties': {'title': 'Templates'}}}]}
        ).execute()
        h = ['Name', 'Type', 'Subject', 'Body', 'Last Used']
        sheets.service.spreadsheets().values().update(
            spreadsheetId=sheets.spreadsheet_id, range="'Templates'!A1",
            valueInputOption='USER_ENTERED', body={'values': [h]}
        ).execute()
        sheets._invalidate_cache('Templates')
        return True
    except:
        return False

ensure_templates()
data = sheets.get_all_rows('Templates')
t_headers = data[0] if data else ['Name', 'Type', 'Subject', 'Body', 'Last Used']
nc = next((i for i, h in enumerate(t_headers) if 'name' in h.lower()), 0)

existing_templates = set()
if data and len(data) > 1:
    for r in data[1:]:
        if nc < len(r) and r[nc].strip():
            existing_templates.add(r[nc].strip().lower())

TEMPLATES = [
    {
        'name': 'Brand DM',
        'type': 'Brand',
        'subject': '',
        'body': "Hey [Brand]! I'm EMMMA, alt-pop artist based between London and Brazil. Obsessed with your brand and would love to explore a creative collab. Just dropped my debut single Honey with a Brazil-shot music video. Think our aesthetics align perfectly. Would love to chat! @emmmasays"
    },
    {
        'name': 'Brand Email',
        'type': 'Brand',
        'subject': 'Artist Partnership Opportunity: EMMMA x [Brand]',
        'body': """Hi [Name],

I'm reaching out from ROLLON ENT on behalf of our artist EMMMA — an alt-pop artist with a striking Brazilian visual identity, currently building momentum with her debut campaign.

EMMMA's 2026 release slate includes five singles — Honey, Russian Roulette, Experiment, Fall From Grace, and Porcelain — each accompanied by a music video shot on location in Brazil. Her aesthetic is bold, cinematic, and deeply tied to her Brazilian-British identity.

Current stats and activity:
- 16K Instagram followers (@emmmasays)
- UK headline tour April/May 2026: Glasgow, London (The Grace), Bristol, Manchester
- Growing press coverage and playlist momentum

We'd love to explore a partnership with [Brand]. Potential collaboration formats include:
- Content creation and social campaign integration
- Campaign sync licensing
- Gifting program
- Brand ambassador relationship

I'd be happy to share EMMMA's one-sheet and latest music video for your review.

Looking forward to connecting.

Best,
Celina Rollon
ROLLON ENT
celina@rollonent.com
+1 (747) 258-5952
www.rollonent.com"""
    }
]

from datetime import datetime
today = datetime.now().strftime('%Y-%m-%d')

for tmpl in TEMPLATES:
    if tmpl['name'].lower() in existing_templates:
        print(f"  [exists] {tmpl['name']}")
        # Update existing
        for ri, r in enumerate(data[1:], start=2):
            if nc < len(r) and r[nc].strip().lower() == tmpl['name'].lower():
                sheets.update_cell('Templates', ri, 2, tmpl['type'])
                sheets.update_cell('Templates', ri, 3, tmpl['subject'])
                sheets.update_cell('Templates', ri, 4, tmpl['body'])
                sheets.update_cell('Templates', ri, 5, today)
                print(f"    Updated.")
                break
    else:
        row = [tmpl['name'], tmpl['type'], tmpl['subject'], tmpl['body'], today]
        sheets.append_row('Templates', row)
        print(f"  [added]  {tmpl['name']}")

sheets._invalidate_cache('Templates')
print("Templates done.")

print("\n" + "=" * 60)
print("ALL SECTIONS COMPLETE")
print("=" * 60)
print(f"  Columns added: {len(added_cols)}")
print(f"  Brands imported: {len(imported)}")
print(f"  Templates created: {len(TEMPLATES)}")
