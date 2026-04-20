"""Phase 1 diagnostic: list every tab, headers, row count, and 3 sample rows."""
import os, json, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from modules.google_sheets import SheetsManager

SHEET_ID = os.environ.get('ROLLON_SHEET_ID', '17b7HjbfXkV5w_Q8lRuG3Ae_7hwJ0M9F7ODVIFytBBmY')
BASE = os.path.dirname(os.path.abspath(__file__))
sm = SheetsManager(SHEET_ID, os.path.join(BASE, 'credentials.json'), os.path.join(BASE, 'token.json'))

out = {}
tabs = sm.list_sheets()
print(f'Found {len(tabs)} tabs')
for t in tabs:
    try:
        rows = sm.get_all_rows(t)
        headers = rows[0] if rows else []
        sample = rows[1:4] if len(rows) > 1 else []
        out[t] = {
            'row_count': max(0, len(rows) - 1),
            'headers': list(headers),
            'samples': sample,
        }
        print(f'  {t}: {len(headers)} cols, {max(0, len(rows)-1)} rows')
    except Exception as e:
        out[t] = {'error': str(e)}
        print(f'  {t}: ERROR {e}')

with open(os.path.join(BASE, 'phase1_audit.json'), 'w') as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
print(f'\nWrote phase1_audit.json')
