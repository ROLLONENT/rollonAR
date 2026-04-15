# ROLLON AR — System Philosophy & Rules

## Architecture

- **Backend**: Flask (Python) — `app.py` is the main server
- **Frontend**: Vanilla JS (no framework) — `static/js/core.js`, `static/js/filters.js`
- **Database**: Google Sheets via `modules/google_sheets.py`
- **Pages**: Songs, Directory, Pitch, Calendar, Invoices, Playlists, Submit (public)
- **Templates**: Jinja2 in `templates/`

## Core Principle: ONE System, Dynamic Data

**NEVER hardcode dropdown options, filter values, or field lists.**

Every dropdown, filter pill selector, and field option across the entire system pulls its values dynamically from the actual Google Sheet data via the autocomplete API.

### How It Works

1. **Filter pill dropdowns** (`filters.js` → `toggleFilterPillDropdown`): Always call `/api/autocomplete/<table>/<field>?limit=200` to get unique values. No hardcoded lists.

2. **Submit form** (`submit.html`): Genre and Audio Status options load dynamically from `/api/public/autocomplete/songs/<field>` on page load. Fallback arrays exist only for offline/error scenarios.

3. **Calendar filters**: Uses the same `buildFilterPanelV2` system as all other pages. Sets `window._currentTable='songs'`.

4. **Invoice categories**: Fetched from `/api/autocomplete/invoices/Category` when creating new invoices.

5. **All pages** set `window._currentTable` so filter pill dropdowns know which table to query.

### API Endpoints for Dynamic Data

- `GET /api/autocomplete/<table>/<field>?q=&limit=` — authenticated, returns unique values from any column
- `GET /api/public/autocomplete/<table>/<field>` — public (for submit form), rate-limited
- Tables: `songs`, `directory`, `personnel`, `invoices`, `cities`, `mgmt`, `labels`, `publishers`, `agents`, `studios`, `agencies`

### What IS Acceptable to Keep Static

- **Entity names** (ROLLON ENT, RESTLESS YOUTH) — legal entities, not data
- **Currency codes** (USD, GBP, EUR) — ISO standards
- **Filter operators** (contains, is, is_empty) — UI logic
- **Pitch campaign types** (Dance, Pop, KPOP) — business logic mapping tags to filters
- **TAG_COLORS** — UI styling, not data options

## Lyric Doc Generator

- Module: `modules/lyric_doc.py`
- Auto-generates formatted PDF lyric documents
- Triggered automatically on:
  - Song submission via `/api/submit-song` (when lyrics included)
  - Lyrics field edit via `/api/songs/update`
- PDFs stored in `static/lyric_docs/`
- Download endpoint: `GET /api/songs/<row_index>/lyric-doc`
- "Lyric Doc" button in song detail modal actions

## Checklist for New Features

- [ ] Does it use hardcoded option lists? **Replace with API calls.**
- [ ] Does it set `window._currentTable`? **Required for filters to work.**
- [ ] Does the page use `buildFilterPanelV2`? **Standard filter system.**
- [ ] New sheet columns? **They auto-appear in filters — no code change needed.**
- [ ] New tag values? **They auto-appear in filter dropdowns — no code change needed.**

## Key Files

| File | Purpose |
|------|---------|
| `app.py` | Flask server, all API endpoints |
| `static/js/core.js` | Grid, modal, inline editing |
| `static/js/filters.js` | Filter/sort panel UI |
| `modules/google_sheets.py` | Google Sheets API wrapper with caching |
| `modules/lyric_doc.py` | PDF lyric doc generator |
| `modules/pitch_builder.py` | Pitch campaign generation |
| `modules/id_resolver.py` | Airtable ID resolution & linking |
| `modules/pub_splits.py` | Publishing split calculations |
