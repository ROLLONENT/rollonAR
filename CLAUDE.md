# ROLLON AR — System Philosophy & Rules

## Core Philosophy

ROLLON AR is **ONE unified system**. Not separate pages. A single data bank with endless customizable views. Any change to any page must be applied across ALL pages. No exceptions.

### Golden Rule
ANY change to ANY page MUST be checked and applied across ALL pages. No exceptions.

### Verification Rule
NEVER say "Done" without reading the actual file and showing the relevant lines as proof.

### Data Safety Rule
NEVER modify existing records during imports. Append only. Tags on existing records are sacred.

### Data Protection Rule (CRITICAL)
No record in ROLLON AR is ever truly deleted. ALL "delete" operations are SOFT DELETES:
1. Move the record to an "Archive" sheet tab (copies full row, then clears original)
2. Keep all linked records, tags, history, and timestamps intact in the archive
3. Archived records are recoverable from Settings > Archive section with a Restore button
4. The Archive sheet has an extra "Archived From" column (source sheet) and "Archived Date"

**Hard deletes are FORBIDDEN** except via an explicit Captain confirmation modal:
"This will permanently delete X records and cannot be undone. Type DELETE to confirm."

**Never auto-purge** "cold", "stale", or "inactive" data records. The Captain decides.
Memory-only caches (rate limiter, playlist view buffer, edit tokens) are exempt.

**Merge flow**: merging duplicates keeps the "winner" in the main sheet and soft-archives the "loser" to Archive (never hard delete).

Implementation: `_archive_rows(sheet_name, row_indices)` in app.py copies rows to Archive sheet before clearing originals. Every endpoint that removes data calls this function first.

### Unified Search Rule
Any input that could match an existing record MUST use typeahead search against the full database. Never create standalone data. Never allow duplicates. If typed input matches 90%+ of existing, prompt to use existing or explicitly create new. This applies to:
- **New Song**: Artist, Producer, Vocalist, Songwriter Credits typeahead into Personnel
- **New Contact**: Record Label, MGMT Company, Publishing, Agent typeahead into company tables
- **New Invoice**: Client typeahead into Personnel + Companies
- **New Playlist**: Song search typeahead into Songs, contact share typeahead into Personnel
- **Scout Tour**: Headliner and Agent/Manager typeahead into Personnel, auto-create if new
- **Pitch form**: Contact search already uses typeahead (verify on changes)

Implementation: `wirePromptTypeahead(fieldIdx, table, multiValue)` in core.js wires search onto any prompt modal input.

## Architecture

- **Backend**: Flask (Python) — `app.py` is the main server
- **Frontend**: Vanilla JS (no framework) — `static/js/core.js`, `static/js/filters.js`
- **Database**: Google Sheets via `modules/google_sheets.py`
- **Pages**: Songs, Directory, Pitch, Calendar, Invoices, Playlists, Submit (public)
- **Templates**: Jinja2 in `templates/`
- **Roles**: `admin` (Captain, full access), `assistant` (Co-Pilot, no invoices)

## Core Principle: ONE System, Dynamic Data

**NEVER hardcode dropdown options, filter values, or field lists.**

Every dropdown, filter pill selector, and field option across the entire system pulls its values dynamically from the actual Google Sheet data via the autocomplete API.

### How It Works

1. **Filter pill dropdowns** (`filters.js` → `toggleFilterPillDropdown`): Always call `/api/autocomplete/<table>/<field>?limit=200` to get unique values. No hardcoded lists.
2. **New Record modals** (Songs, Directory, Invoices): All options loaded dynamically from the autocomplete API on modal open.
3. **Submit form** (`submit.html`): Genre and Audio Status load from `/api/public/autocomplete/songs/<field>`. Fallback arrays exist only for offline/error.
4. **Calendar filters**: Uses `buildFilterPanelV2`. Sets `window._currentTable='songs'`.
5. **Invoice categories**: Fetched from `/api/autocomplete/invoices/Category`.
6. **All pages** set `window._currentTable` so filter pill dropdowns know which table to query.

### API Endpoints for Dynamic Data

- `GET /api/autocomplete/<table>/<field>?q=&limit=` — authenticated, returns unique values from any column
- `GET /api/public/autocomplete/<table>/<field>` — public (for submit form), rate-limited
- Tables: `songs`, `directory`, `personnel`, `invoices`, `cities`, `mgmt`, `labels`, `publishers`, `agents`, `studios`, `agencies`

### What IS Acceptable to Keep Static

- **Entity names** (ROLLON ENT, RESTLESS YOUTH, Tyber Heart Limited) — legal entities
- **Currency codes** (USD, GBP, EUR) — ISO standards
- **Filter operators** (contains, is, is_empty) — UI logic
- **TAG_COLORS** — UI styling, not data options
- **Default visible columns** — UI defaults, not data constraints
- **Fallback arrays on submit form** — only for offline/error resilience

## System-Wide Feature Parity Checklist

Every grid page (Songs, Directory, Pitch, Invoices) MUST support ALL of these:

- [ ] **Views persistence** via ViewSync (localStorage + Sheets API, survive logout)
- [ ] **Multi-level sort** via `buildSortPanelV2` with persistent state
- [ ] **Advanced filters** via `buildFilterPanelV2` with AND/OR mode
- [ ] **Column visibility** toggle panel
- [ ] **Column resize** with drag handles, widths persist in localStorage
- [ ] **Bulk operations** bar (add/remove tag, set field, delete, clear)
- [ ] **Behavioral search** across all visible fields
- [ ] **CSV export** of current filtered view
- [ ] **Group by** with collapse/expand all and direction toggle
- [ ] **Inline grid editing** (click select, double-click edit, tab nav)
- [ ] **Detail modal** with ALL fields from sheet
- [ ] **Floating Hide Empty** toggle (pill-style, position:sticky, stays visible when scrolling)
- [ ] **Pill editor** for all multi-select fields (tags, genre, links)
- [ ] **Pagination** with record count display
- [ ] **Record count** showing filtered vs total

## Import Safety Rule

**NEVER modify existing records during imports.** Import endpoints (`/api/songs/import`, `/api/directory/import`) use `batch_append` only — they add new rows, never update existing ones.

## Lyric Doc Generator

- Module: `modules/lyric_doc.py`
- Auto-generates formatted PDF lyric documents
- Triggered automatically on song submission and lyrics field edit
- PDFs stored in `static/lyric_docs/`
- Download endpoint: `GET /api/songs/<row_index>/lyric-doc`
- Format: Title bold, writer credits, producer, artist, BPM, duration, key, genre, then lyrics with section headers

## Invoice System

- Entity auto-detection: ROLLON ENT (ROL-), RESTLESS YOUTH (RYE-), Tyber Heart Limited (TYB-)
- Auto-numbering: ROL-001, RYE-001, TYB-001
- Overdue detection: startup + every 60 min, marks Sent past Due Date as Overdue
- Follow-up flags: 7 days yellow, 14 days orange, 30 days red
- Duplicate button for recurring retainers
- PDF generation with branded letterhead per entity

## Music Player

- Built into `/p/{id}` public playlist page and song detail modal
- Streams from Dropbox links (converts dl=0 to dl=1)
- Features: play/pause, scrub bar, volume, auto-advance, now-playing highlight
- Play logging to Play Log sheet tab

## Distribution System

- Rightsbridge: CSV export with rights/registration fields, SMTP delivery
- Sync: CSV export with sync-specific fields, multi-select contacts
- Configurable channels via Distribution Channels settings
- Distribution Log sheet tracks all sends

## Field Types

| Type | Examples | Behavior |
|------|----------|----------|
| `tag` | Tag, Tags | Pipe-separated, colored pills, pill editor |
| `link` | Artist, Producer, Record Label | Linked record navigation, typeahead |
| `autocomplete` | Genre, Audio Status, Format | Multi-select typeahead from autocomplete API |
| `date` | Release Date, Written Date | Date picker, comparison operators |
| `url` | Dropbox Link, DISCO, Song URL | Clickable links with icons |
| `long` | Lyrics, Bio, Outreach Notes | Long text popup editor |
| `checklist` | Song Admin | Interactive checkboxes |
| `contact` | Email, Phone | Copyable with click |

## Sheet Structure

| Sheet | Purpose |
|-------|---------|
| Songs | Master song catalog |
| Personnel | All contacts/people |
| Invoices | Invoice tracking |
| Cities | City/country/timezone lookup |
| MGMT Companies | Management companies |
| Record Labels | Labels |
| Publishing Company | Publishers |
| Agent | Booking agents |
| Studios | Recording studios |
| Agency Company | Talent agencies |
| Templates | Email templates |
| Pitch Log | Pitch history |
| Playlists | Shared playlists |
| Views | Saved view states |
| Play Log | Audio play tracking |
| Distribution Log | Distribution sends |

## Key Files

| File | Purpose |
|------|---------|
| `app.py` | Flask server, all API endpoints |
| `static/js/core.js` | Grid, modal, inline editing, ViewSync |
| `static/js/filters.js` | Filter/sort panel UI, pill selectors |
| `static/css/style.css` | All styling (dark theme, gold accent) |
| `modules/google_sheets.py` | Google Sheets API wrapper with caching |
| `modules/lyric_doc.py` | PDF lyric doc generator |
| `modules/pitch_builder.py` | Pitch campaign generation |
| `modules/id_resolver.py` | Airtable ID resolution & linking |
| `modules/pub_splits.py` | Publishing split calculations |
| `Deploy.command` | One-click deploy script |

## Conventions

- **Color scheme**: Dark background (#131316), gold accent (#d4a853)
- **Pipe separator**: Multi-value fields use ` | ` (space-pipe-space)
- **System IDs**: Format RLN-XXXXX (universal across all tables)
- **Invoice numbers**: {PREFIX}-{NNN} (ROL-001, RYE-001, TYB-001)
- **Session roles**: `admin` = Captain (full access), `assistant` = Co-Pilot (no invoices)
- **Cache TTL**: 120 seconds for Google Sheets data
- **Rate limiting**: Public: 10/hour general, 30/hour submissions
