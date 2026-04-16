"""
ID Resolver v8 — converts Airtable record IDs to human-readable names.
Builds cache from all tables. Logs progress for debugging.
"""

import re

STRICT_ID_PATTERN = re.compile(r'^rec[A-Za-z0-9]{10,}$')

_CLEAN_H_RE = re.compile(r'\[✓\]\s*|\[✗\]\s*|\[\?\?\]\s*|\[∅\]\s*|\[\s*✓\]\s*')

def cleanH(h):
    """Clean Airtable-style header markers. Shared across modules."""
    return _CLEAN_H_RE.sub('', h or '').strip()


class IDResolver:
    def __init__(self, sheets_manager):
        self.sheets = sheets_manager
        self._cache = {}

    def rebuild(self):
        """Build lookup cache from ALL available tables."""
        self._cache = {}

        try:
            available_tabs = self.sheets.list_sheets()
        except Exception as e:
            print(f"  Resolver: Failed to list sheets: {e}")
            return

        for table_name in available_tabs:
            try:
                data = self.sheets.get_all_rows(table_name)
                if not data or len(data) < 2:
                    continue

                headers = data[0]
                rows = data[1:]

                # Find Airtable ID column — check multiple possible names
                id_col = None
                for i, h in enumerate(headers):
                    hl = h.lower().strip()
                    if hl in ('airtable id', 'airtable_id', 'record id', 'system id', 'id'):
                        id_col = i
                        break

                if id_col is None:
                    # Also check if first column contains recXXX values
                    if len(rows) > 0 and len(rows[0]) > 0:
                        sample = str(rows[0][0]).strip()
                        if STRICT_ID_PATTERN.match(sample):
                            id_col = 0

                if id_col is None:
                    continue

                # Find the best name/title column
                name_col = None
                skip_words = ('airtable', 'created', 'modified', 'last modified', 'time', 'date')

                # Pass 1: exact matches
                for i, h in enumerate(headers):
                    hl = h.strip().lower()
                    if hl in ('[✓] name', '[✓] title', 'name', 'title'):
                        name_col = i
                        break

                # Pass 2: contains name or title
                if name_col is None:
                    for i, h in enumerate(headers):
                        if i == id_col:
                            continue
                        hl = h.lower().strip()
                        if ('name' in hl or 'title' in hl) and not any(s in hl for s in skip_words):
                            name_col = i
                            break

                # Pass 3: first non-junk column after ID
                if name_col is None:
                    for i, h in enumerate(headers):
                        if i == id_col:
                            continue
                        hl = h.lower().strip()
                        if not any(s in hl for s in skip_words):
                            name_col = i
                            break

                if name_col is None:
                    continue

                count = 0
                for row in rows:
                    if id_col < len(row) and name_col < len(row):
                        rec_id = str(row[id_col]).strip()
                        name = str(row[name_col]).strip()
                        if rec_id and name and STRICT_ID_PATTERN.match(rec_id):
                            if not STRICT_ID_PATTERN.match(name):
                                self._cache[rec_id] = name
                                count += 1

                if count > 0:
                    print(f"    {table_name}: {count} IDs (col {id_col} '{headers[id_col]}' -> col {name_col} '{headers[name_col]}')")

            except Exception as e:
                print(f"    {table_name}: ERROR - {e}")
                continue

    def resolve_id(self, record_id):
        record_id = record_id.strip()
        return self._cache.get(record_id, record_id)

    def resolve_value(self, header, value):
        """Resolve any record IDs in a cell value to names."""
        if not value or not isinstance(value, str):
            return value

        value = value.strip()
        if not value:
            return value

        # Skip URLs and dates
        if value.startswith('http'):
            return value

        # Parse JSON button/formula fields into clickable format
        if value.startswith('{') and '"label"' in value and '"url"' in value:
            try:
                import json
                obj = json.loads(value)
                label = obj.get('label', 'Link')
                url = obj.get('url', '')
                if url: return url
            except Exception as e: pass
            return value
        if value.startswith('[') or value.startswith('{'):
            return value

        # Split on pipe or comma separator
        if ' | ' in value:
            parts = [p.strip() for p in value.split(' | ')]
        elif ',' in value and STRICT_ID_PATTERN.match(value.split(',')[0].strip()):
            parts = [p.strip() for p in value.split(',')]
        else:
            parts = [value]

        # Check if ANY part is a record ID
        has_ids = any(STRICT_ID_PATTERN.match(p) for p in parts)
        if not has_ids:
            return value

        # Resolve each ID
        resolved = []
        for part in parts:
            if STRICT_ID_PATTERN.match(part):
                resolved.append(self.resolve_id(part))
            else:
                resolved.append(part)

        return ' | '.join(resolved)
