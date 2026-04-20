"""Relationships engine for ROLLON AR v36.

Rebuilds the linked-record / bidirectional backlink / group-resolve logic that
Airtable provided via Dynamic Backlinks but was flattened in the Sheets migration.

The canonical Personnel ID is the Airtable ID (column 'Airtable ID', values like
'recXXXXXXXXXXXX'). Every Personnel row has one; no row uses the sheet index.

Link storage:
  * Works With column (col 7 in Personnel) stores pipe-separated Airtable IDs of
    linked contacts. Bidirectional: add_link(A,B) writes B to A and A to B.
  * Generic link columns (Managed By, Represents, A&R Rep etc) follow the same
    recID storage format once upgraded, governed by LINK_TYPES below.

greeting_for returns a dict with both the "named" greeting and the "alt"
(Hi both / Hi all) versions so the export layer can pick either.
"""

import json
import logging
import threading
from collections import defaultdict


LINK_TYPES = {
    'works_with': {
        'column': 'Works With',
        'inverse': 'works_with',
        'symmetric': True,
    },
    'manages': {
        'column': 'Artists [MGMT]',
        'inverse': 'managed_by',
        'symmetric': False,
    },
    'managed_by': {
        'column': 'MGMT Rep',
        'inverse': 'manages',
        'symmetric': False,
    },
    'represents': {
        'column': 'Artists [Agent MGMT]',
        'inverse': 'represented_by',
        'symmetric': False,
    },
    'represented_by': {
        'column': 'Agent',
        'inverse': 'represents',
        'symmetric': False,
    },
    'ar_rep': {
        'column': 'Artists [Record Label A&R]',
        'inverse': 'is_ar_for',
        'symmetric': False,
    },
    'is_ar_for': {
        'column': 'Record Label A&R',
        'inverse': 'ar_rep',
        'symmetric': False,
    },
    'publishing_rep': {
        'column': 'Artists [Publishing Rep]',
        'inverse': 'is_publishing_rep_for',
        'symmetric': False,
    },
    'is_publishing_rep_for': {
        'column': 'Publishing Rep',
        'inverse': 'publishing_rep',
        'symmetric': False,
    },
    'creative_of': {
        'column': 'Creatives [MGMT]',
        'inverse': 'works_with_creative',
        'symmetric': False,
    },
    'works_with_creative': {
        'column': 'Creatives Publishing',
        'inverse': 'creative_of',
        'symmetric': False,
    },
}

PERSONNEL_SHEET = 'Personnel'
WORKS_WITH_COLUMN = 'Works With'
BACKLINKS_CACHE_COLUMN = 'Backlinks Cache'
GROUPING_OVERRIDE_COLUMN = 'Grouping Override'
GROUP_LEADER_COLUMN = 'Group Leader'
AIRTABLE_ID_COLUMN = 'Airtable ID'
TAGS_COLUMN = 'Tags'
DONT_MASS_PITCH_TAG = "Don't Mass Pitch"

_CLEAN_RE = None

def _clean_header(h):
    """Strip the [✓]/[∅] prefixes used in ROLLON headers."""
    global _CLEAN_RE
    if _CLEAN_RE is None:
        import re
        _CLEAN_RE = re.compile(r'\[\s*[✓✗∅?]+\s*\]\s*|\[USE\]\s*|\[LU\]\s*|\[Sync\]\s*')
    return _CLEAN_RE.sub('', h or '').strip()


class RelationshipsEngine:
    """All Works With / linked-record logic. Constructed once per process.

    Caches header -> column index mapping and Airtable ID -> row index mapping
    with lazy invalidation on writes.
    """

    def __init__(self, sheets_manager):
        self.sheets = sheets_manager
        self._lock = threading.RLock()
        self._header_cache = {}
        self._id_to_row = {}
        self._id_to_row_ts = 0
        self._bulk_data = None
        self._bulk_ts = 0
        self._ID_CACHE_TTL = 120

    # ---------- helpers ----------

    def _headers(self, sheet=PERSONNEL_SHEET):
        return self.sheets.get_headers(sheet)

    def _col_idx(self, header_name, sheet=PERSONNEL_SHEET):
        """Case-insensitive, prefix-tolerant column lookup."""
        headers = self._headers(sheet)
        target = header_name.lower().strip()
        for i, h in enumerate(headers):
            if _clean_header(h).lower() == target:
                return i
        for i, h in enumerate(headers):
            if target in _clean_header(h).lower():
                return i
        return None

    def ensure_columns(self):
        """Ensure Backlinks Cache, Grouping Override, and Group Leader columns
        exist on Personnel. Returns dict of {column_name: column_index}."""
        headers = list(self._headers())
        added = False
        next_idx = len(headers)
        needed = [BACKLINKS_CACHE_COLUMN, GROUPING_OVERRIDE_COLUMN, GROUP_LEADER_COLUMN]
        for name in needed:
            if self._col_idx(name) is None:
                headers.append(name)
                col_letter = self.sheets._col_to_letter(next_idx + 1)
                self.sheets._retry(lambda cl=col_letter, nm=name: (
                    self.sheets.service.spreadsheets().values().update(
                        spreadsheetId=self.sheets.spreadsheet_id,
                        range=f"'{PERSONNEL_SHEET}'!{cl}1",
                        valueInputOption='USER_ENTERED',
                        body={'values': [[nm]]}
                    ).execute()
                ))
                next_idx += 1
                added = True
        if added:
            self.sheets._invalidate_cache(PERSONNEL_SHEET)
        return {h: self._col_idx(h) for h in needed}

    def _refresh_id_to_row(self):
        import time
        with self._lock:
            if time.time() - self._id_to_row_ts < self._ID_CACHE_TTL and self._id_to_row:
                return self._id_to_row
            data = self.sheets.get_all_rows(PERSONNEL_SHEET)
            if not data or len(data) < 2:
                self._id_to_row = {}
                self._id_to_row_ts = time.time()
                return self._id_to_row
            id_col = self._col_idx(AIRTABLE_ID_COLUMN)
            if id_col is None:
                self._id_to_row = {}
                self._id_to_row_ts = time.time()
                return self._id_to_row
            mapping = {}
            for i, row in enumerate(data[1:], start=2):
                if id_col < len(row):
                    aid = str(row[id_col]).strip()
                    if aid:
                        mapping[aid] = i
            self._id_to_row = mapping
            self._id_to_row_ts = time.time()
            return self._id_to_row

    def row_for_id(self, personnel_id):
        """Return sheet row index (1-based, header=1) for a given Airtable ID."""
        mapping = self._refresh_id_to_row()
        return mapping.get(str(personnel_id).strip())

    def id_for_row(self, row_index):
        """Return Airtable ID for a given Personnel sheet row index."""
        row = self.sheets.get_row(PERSONNEL_SHEET, row_index)
        id_col = self._col_idx(AIRTABLE_ID_COLUMN)
        if id_col is None or id_col >= len(row):
            return ''
        return str(row[id_col]).strip()

    def row_data(self, personnel_id):
        """Return dict of {header: value} for a Personnel ID, or None."""
        ri = self.row_for_id(personnel_id)
        if not ri:
            return None
        row = self.sheets.get_row(PERSONNEL_SHEET, ri)
        headers = self._headers()
        return {_clean_header(h): (row[i] if i < len(row) else '') for i, h in enumerate(headers)}

    # ---------- Works With link helpers ----------

    def _parse_ids(self, raw):
        """Split pipe-separated IDs, tolerate commas too. Returns list of trimmed ids."""
        if not raw:
            return []
        s = str(raw)
        parts = [p.strip() for p in s.replace(',', '|').split('|')]
        return [p for p in parts if p]

    def _format_ids(self, ids):
        seen = set()
        ordered = []
        for i in ids:
            if i and i not in seen:
                ordered.append(i)
                seen.add(i)
        return ' | '.join(ordered)

    def get_works_with(self, personnel_id):
        """Return list of linked Personnel IDs for a given Personnel ID."""
        ri = self.row_for_id(personnel_id)
        if not ri:
            return []
        row = self.sheets.get_row(PERSONNEL_SHEET, ri)
        ww_col = self._col_idx(WORKS_WITH_COLUMN)
        if ww_col is None or ww_col >= len(row):
            return []
        raw = row[ww_col]
        ids = self._parse_ids(raw)
        mapping = self._refresh_id_to_row()
        return [i for i in ids if i in mapping and i != personnel_id]

    def get_related(self, personnel_id):
        """Alias for get_works_with (Phase 2 API requirement)."""
        return self.get_works_with(personnel_id)

    def _write_works_with(self, personnel_id, ids):
        ri = self.row_for_id(personnel_id)
        if not ri:
            return False
        ww_col = self._col_idx(WORKS_WITH_COLUMN)
        if ww_col is None:
            return False
        self.sheets.update_cell(PERSONNEL_SHEET, ri, ww_col + 1, self._format_ids(ids))
        return True

    def add_link(self, id_a, id_b):
        """Bidirectional link. Returns True on success."""
        if not id_a or not id_b or id_a == id_b:
            return False
        mapping = self._refresh_id_to_row()
        if id_a not in mapping or id_b not in mapping:
            return False
        with self._lock:
            a_ids = self.get_works_with(id_a)
            b_ids = self.get_works_with(id_b)
            if id_b not in a_ids:
                a_ids.append(id_b)
                self._write_works_with(id_a, a_ids)
            if id_a not in b_ids:
                b_ids.append(id_a)
                self._write_works_with(id_b, b_ids)
        return True

    def remove_link(self, id_a, id_b):
        if not id_a or not id_b:
            return False
        with self._lock:
            a_ids = [i for i in self.get_works_with(id_a) if i != id_b]
            b_ids = [i for i in self.get_works_with(id_b) if i != id_a]
            self._write_works_with(id_a, a_ids)
            self._write_works_with(id_b, b_ids)
        return True

    def get_group(self, personnel_ids):
        """Transitive closure over Works With graph. Returns sorted list of IDs."""
        seen = set()
        stack = [str(p).strip() for p in (personnel_ids or []) if p]
        while stack:
            pid = stack.pop()
            if pid in seen:
                continue
            seen.add(pid)
            for linked in self.get_works_with(pid):
                if linked not in seen:
                    stack.append(linked)
        return sorted(seen)

    # ---------- greeting engine ----------

    def greeting_for(self, personnel_ids):
        """Returns dict with named and alt greeting variants.

        1 contact : Hi {Name} | alt: Hi {Name}
        2 contacts: Hi {A} and {B} | alt: Hi both
        3 contacts: Hi {A}, {B} and {C} | alt: Hi all
        4+       : Hi {A}, {B}, ... and {N} | alt: Hi all
        """
        first_names = []
        for pid in personnel_ids:
            data = self.row_data(pid)
            if not data:
                continue
            nm = (data.get('Name') or '').strip()
            if not nm:
                continue
            first = nm.split()[0]
            if first:
                first_names.append(first)
        n = len(first_names)
        if n == 0:
            return {'named': '', 'alt': '', 'first_names': [], 'count': 0}
        if n == 1:
            g = f'Hi {first_names[0]}'
            return {'named': g, 'alt': g, 'first_names': first_names, 'count': 1}
        if n == 2:
            named = f'Hi {first_names[0]} and {first_names[1]}'
            return {'named': named, 'alt': 'Hi both', 'first_names': first_names, 'count': 2}
        if n == 3:
            named = f'Hi {first_names[0]}, {first_names[1]} and {first_names[2]}'
            return {'named': named, 'alt': 'Hi all', 'first_names': first_names, 'count': 3}
        named = 'Hi ' + ', '.join(first_names[:-1]) + f' and {first_names[-1]}'
        return {'named': named, 'alt': 'Hi all', 'first_names': first_names, 'count': n}

    # ---------- group build for pitching ----------

    def group_for_pitch(self, personnel_ids):
        """Given a set of contacts, return sorted list of pitch groups.

        Pre-condition: personnel_ids is a list/iterable of Airtable IDs.
        Post-condition: list of dicts, each group has
            ids: list of Airtable IDs
            greeting: named greeting
            greeting_alt: alt greeting
            emails: comma-separated email list
            first_names: list of first names
            group_key: ('works_with'|'company'|'solo', identifier)
            company_label: display label for the group's shared company if any
        """
        all_ids = list({str(p).strip() for p in personnel_ids if p})
        id_set = set(all_ids)
        data_by_id = {pid: self.row_data(pid) for pid in all_ids}

        visited = set()
        ww_groups = []
        for pid in all_ids:
            if pid in visited:
                continue
            cluster = [i for i in self.get_group([pid]) if i in id_set]
            visited.update(cluster)
            if len(cluster) > 1:
                ww_groups.append(cluster)
            else:
                ww_groups.append(cluster)

        company_grouped = []
        final_groups = []

        def company_key_for(pid):
            d = data_by_id.get(pid) or {}
            for col in ('MGMT Company', 'Record Label', 'Publishing Company', 'Agency'):
                v = (d.get(col) or '').strip()
                if v:
                    return (col, v.lower(), v)
            return None

        solo_ids = []
        ww_ids_consumed = set()
        for cluster in ww_groups:
            if len(cluster) > 1:
                ww_ids_consumed.update(cluster)
                final_groups.append(self._build_group(cluster, data_by_id, origin='works_with'))
            else:
                solo_ids.append(cluster[0])

        by_key = defaultdict(list)
        leftover = []
        for pid in solo_ids:
            ck = company_key_for(pid)
            if ck is None:
                leftover.append(pid)
            else:
                by_key[ck].append(pid)

        for ck, cluster in by_key.items():
            if len(cluster) > 1:
                g = self._build_group(cluster, data_by_id, origin='company')
                g['company_label'] = ck[2]
                final_groups.append(g)
            else:
                leftover.append(cluster[0])

        for pid in leftover:
            final_groups.append(self._build_group([pid], data_by_id, origin='solo'))

        return final_groups

    def _build_group(self, ids, data_by_id, origin='solo'):
        first_names = []
        emails = []
        rows = []
        override = ''
        for pid in ids:
            d = data_by_id.get(pid) or {}
            rows.append(pid)
            nm = (d.get('Name') or '').strip()
            if nm:
                first_names.append(nm.split()[0])
            em = (d.get('Email') or '').strip()
            if em:
                emails.append(em)
            ov = (d.get(GROUPING_OVERRIDE_COLUMN) or '').strip()
            if ov and not override:
                override = ov
        greet = self.greeting_for(ids)
        greeting = override or greet['named']
        return {
            'ids': ids,
            'first_names': first_names,
            'emails': emails,
            'emails_joined': ', '.join(emails),
            'greeting': greeting,
            'greeting_alt': greet['alt'],
            'group_key': origin,
            'count': len(ids),
        }

    # ---------- generic linked-record infra ----------

    def lookup_all_relationships(self, personnel_id):
        """Return dict of link_type -> list of linked Personnel IDs (resolved names)."""
        out = {}
        d = self.row_data(personnel_id)
        if not d:
            return out
        for lt, spec in LINK_TYPES.items():
            col_name = spec['column']
            raw = (d.get(col_name) or '').strip()
            ids = self._parse_ids(raw)
            resolved = []
            for rid in ids:
                peer = self.row_data(rid)
                if peer:
                    resolved.append({'id': rid, 'name': peer.get('Name', '')})
                else:
                    resolved.append({'id': rid, 'name': rid})
            out[lt] = resolved
        return out

    def generic_add(self, id_a, id_b, link_type):
        """Write both sides for a named link_type, honouring the LINK_TYPES registry."""
        spec = LINK_TYPES.get(link_type)
        if not spec:
            raise ValueError(f'Unknown link_type {link_type}')
        if id_a == id_b:
            return False
        mapping = self._refresh_id_to_row()
        if id_a not in mapping or id_b not in mapping:
            return False
        self._append_link(id_a, id_b, spec['column'])
        if spec['symmetric']:
            self._append_link(id_b, id_a, spec['column'])
        else:
            inv = LINK_TYPES.get(spec['inverse'])
            if inv:
                self._append_link(id_b, id_a, inv['column'])
        return True

    def generic_remove(self, id_a, id_b, link_type):
        spec = LINK_TYPES.get(link_type)
        if not spec:
            raise ValueError(f'Unknown link_type {link_type}')
        self._remove_link(id_a, id_b, spec['column'])
        if spec['symmetric']:
            self._remove_link(id_b, id_a, spec['column'])
        else:
            inv = LINK_TYPES.get(spec['inverse'])
            if inv:
                self._remove_link(id_b, id_a, inv['column'])
        return True

    def _append_link(self, owner_id, peer_id, column_name):
        ri = self.row_for_id(owner_id)
        if not ri:
            return False
        col = self._col_idx(column_name)
        if col is None:
            return False
        row = self.sheets.get_row(PERSONNEL_SHEET, ri)
        raw = row[col] if col < len(row) else ''
        ids = self._parse_ids(raw)
        if peer_id not in ids:
            ids.append(peer_id)
            self.sheets.update_cell(PERSONNEL_SHEET, ri, col + 1, self._format_ids(ids))
        return True

    def _remove_link(self, owner_id, peer_id, column_name):
        ri = self.row_for_id(owner_id)
        if not ri:
            return False
        col = self._col_idx(column_name)
        if col is None:
            return False
        row = self.sheets.get_row(PERSONNEL_SHEET, ri)
        raw = row[col] if col < len(row) else ''
        ids = [i for i in self._parse_ids(raw) if i != peer_id]
        self.sheets.update_cell(PERSONNEL_SHEET, ri, col + 1, self._format_ids(ids))
        return True

    # ---------- Group Leader ----------

    def get_group_leader(self, personnel_id):
        """Return the Group Leader Airtable ID for a given personnel row,
        or '' if not set."""
        d = self.row_data(personnel_id)
        if not d:
            return ''
        return (d.get(GROUP_LEADER_COLUMN) or '').strip()

    def set_group_leader(self, group_ids, leader_id, auto_tag_secondaries=True):
        """Mark every member of `group_ids` with Group Leader = leader_id.
        If `auto_tag_secondaries` is True, append the "Don't Mass Pitch" tag
        to every non-leader member (idempotent). Returns summary dict."""
        ids = [str(i).strip() for i in (group_ids or []) if i]
        leader = str(leader_id or '').strip()
        if not ids or not leader or leader not in ids:
            return {'updated': 0, 'tagged': [], 'leader': leader}
        gl_col = self._col_idx(GROUP_LEADER_COLUMN)
        tags_col = self._col_idx(TAGS_COLUMN)
        if gl_col is None:
            self.ensure_columns()
            gl_col = self._col_idx(GROUP_LEADER_COLUMN)
        if gl_col is None:
            return {'updated': 0, 'tagged': [], 'leader': leader,
                    'error': 'Group Leader column could not be ensured'}
        updates = []
        tagged = []
        for pid in ids:
            ri = self.row_for_id(pid)
            if not ri:
                continue
            updates.append((ri, gl_col + 1, leader))
            if auto_tag_secondaries and pid != leader and tags_col is not None:
                row = self.sheets.get_row(PERSONNEL_SHEET, ri)
                cur = row[tags_col] if tags_col < len(row) else ''
                parts = [t.strip() for t in str(cur).split('|') if t.strip()] if cur else []
                if DONT_MASS_PITCH_TAG not in parts:
                    parts.append(DONT_MASS_PITCH_TAG)
                    updates.append((ri, tags_col + 1, ' | '.join(parts)))
                    tagged.append(pid)
        with self._lock:
            if updates:
                self.sheets.batch_update_cells(PERSONNEL_SHEET, updates)
        return {'updated': len({u[0] for u in updates}), 'tagged': tagged, 'leader': leader}

    def clear_group_leader(self, group_ids):
        """Blank out Group Leader on every member of the group."""
        ids = [str(i).strip() for i in (group_ids or []) if i]
        if not ids:
            return {'cleared': 0}
        gl_col = self._col_idx(GROUP_LEADER_COLUMN)
        if gl_col is None:
            return {'cleared': 0}
        updates = []
        for pid in ids:
            ri = self.row_for_id(pid)
            if ri:
                updates.append((ri, gl_col + 1, ''))
        with self._lock:
            if updates:
                self.sheets.batch_update_cells(PERSONNEL_SHEET, updates)
        return {'cleared': len(updates)}

    def contacts_tagged_dont_mass_pitch(self, personnel_ids):
        """Return subset of `personnel_ids` that currently carry the
        Don't Mass Pitch tag. Used by the Mail Merge export filter."""
        ids = [str(i).strip() for i in (personnel_ids or []) if i]
        if not ids:
            return []
        out = []
        for pid in ids:
            d = self.row_data(pid)
            if not d:
                continue
            tags = str(d.get(TAGS_COLUMN) or '')
            parts = [t.strip() for t in tags.split('|') if t.strip()]
            if DONT_MASS_PITCH_TAG in parts:
                out.append(pid)
        return out

    # ---------- search (for typeahead) ----------

    def search_by_name(self, query, limit=15, exclude_id=None):
        """Case-insensitive name search. Returns list of {id, name, company, field, row_index}."""
        q = (query or '').strip().lower()
        if not q or len(q) < 2:
            return []
        data = self.sheets.get_all_rows(PERSONNEL_SHEET)
        if not data or len(data) < 2:
            return []
        headers = data[0]
        id_col = self._col_idx(AIRTABLE_ID_COLUMN)
        name_col = self._col_idx('Name')
        field_col = self._col_idx('Field')
        mgmt_col = self._col_idx('MGMT Company')
        label_col = self._col_idx('Record Label')
        pub_col = self._col_idx('Publishing Company')
        out = []
        for i, row in enumerate(data[1:], start=2):
            if name_col is None or name_col >= len(row):
                continue
            nm = str(row[name_col]).strip()
            if not nm or q not in nm.lower():
                continue
            aid = str(row[id_col]).strip() if id_col is not None and id_col < len(row) else ''
            if exclude_id and aid == exclude_id:
                continue
            def g(ci):
                return str(row[ci]).strip() if ci is not None and ci < len(row) else ''
            company = g(mgmt_col) or g(label_col) or g(pub_col)
            out.append({
                'id': aid,
                'name': nm,
                'row_index': i,
                'company': company,
                'field': g(field_col),
            })
            if len(out) >= limit:
                break
        return out
