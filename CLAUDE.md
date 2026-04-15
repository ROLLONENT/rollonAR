# ROLLON AR — System Philosophy & Rules

## Core Philosophy

ROLLON AR is **ONE unified system**. Any change to any page must be applied across ALL pages. Never work in isolation. Never say "Done" without verification. Never modify existing records during imports.

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

2. **New Record modals** (Songs, Directory, Invoices): Options for fields like Genre, Audio Status, Field, Tag, Category are loaded dynamically from the autocomplete API on modal open.

3. **Submit form** (`submit.html`): Genre and Audio Status options load dynamically from `/api/public/autocomplete/songs/<field>` on page load. Fallback arrays exist only for offline/error scenarios.

4. **Calendar filters**: Uses the same `buildFilterPanelV2` system as all other pages. Sets `window._currentTable='songs'`.

5. **Invoice categories**: Fetched from `/api/autocomplete/invoices/Category` when creating new invoices.

6. **All pages** set `window._currentTable` so filter pill dropdowns know which table to query.

### API Endpoints for Dynamic Data

- `GET /api/autocomplete/<table>/<field>?q=&limit=` — authenticated, returns unique values from any column
- `GET /api/public/autocomplete/<table>/<field>` — public (for submit form), rate-limited
- Tables: `songs`, `directory`, `personnel`, `invoices`, `cities`, `mgmt`, `labels`, `publishers`, `agents`, `studios`, `agencies`

### What IS Acceptable to Keep Static

- **Entity names** (ROLLON ENT, RESTLESS YOUTH, Tyber Heart Limited) — legal entities, not data
- **Currency codes** (USD, GBP, EUR) — ISO standards
- **Filter operators** (contains, is, is_empty) — UI logic
- **Pitch campaign types** (Dance, Pop, KPOP) — business logic mapping tags to filters
- **TAG_COLORS** — UI styling, not data options
- **Default visible columns** — UI defaults, not data constraints
- **Fallback arrays on submit form** — only for offline/error resilience

## Import Safety Rule

**NEVER modify existing records during imports.** Import endpoints (`/api/songs/import`, `/api/directory/import`) use `batch_append` only — they add new rows, never update existing ones. This prevents data corruption from bulk operations.

## System-Wide Feature Parity Checklist

Every grid page (Songs, Directory, Pitch, Invoices) MUST support:

- [ ] **Views persistence** via ViewSync (localStorage + Sheets API)
- [ ] **Multi-level sort** via `buildSortPanelV2`
- [ ] **Advanced filters** via `buildFilterPanelV2` with AND/OR mode
- [ ] **Column visibility** toggle panel
- [ ] **Column resize** with persistent widths
- [ ] **Bulk operations** bar (add/remove tag, set field, delete)
- [ ] **Behavioral search** across all visible fields
- [ ] **CSV export** of current filtered view
- [ ] **Group by** with collapse/expand and direction toggle
- [ ] **Inline grid editing** on click
- [ ] **Detail modal** with hide empty fields floating toggle
- [ ] **Pill editor** for multi-select fields (tags, genres, links)
- [ ] **Pagination** with record count display
- [ ] **Record count** showing filtered vs total

## Lyric Doc Generator

- Module: `modules/lyric_doc.py`
- Auto-generates formatted PDF lyric documents
- Triggered automatically on:
  - Song submission via `/api/submit-song` (when lyrics included)
  - Lyrics field edit via `/api/songs/update`
- PDFs stored in `static/lyric_docs/`
- Download endpoint: `GET /api/songs/<row_index>/lyric-doc`
- "Lyric Doc" button in song detail modal actions
- Format: Title bold, writer credits, producer, artist, BPM, duration, key, genre, then lyrics with section headers ([Verse], [Chorus], [Bridge] etc)

## Invoice System

- Entity auto-detection: ROLLON ENT (ROL-), RESTLESS YOUTH (RYE-), Tyber Heart Limited (TYB-)
- Auto-numbering: ROL-001, RYE-001, TYB-001 (auto-increments per entity)
- Overdue detection: scans on startup + every 60 min, marks Sent invoices past Due Date as Overdue
- Follow-up flags: 7 days yellow, 14 days orange, 30 days red
- Duplicate button for recurring retainers
- PDF generation with branded letterhead per entity

## Music Player

- Built into `/p/{id}` public playlist page and song detail modal
- Streams from Dropbox links (converts dl=0 to dl=1 for direct playback)
- Features: play/pause, scrub bar, volume, auto-advance, now-playing highlight
- Play logging to Play Log sheet tab

## Dropbox Integration

- Submit form validates Dropbox URLs on paste
- Converts share links (dl=0) to direct download (dl=1)
- Green checkmark on valid links
- Clickable play button in song detail modal

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

| Sheet | Purpose | Key Columns |
|-------|---------|-------------|
| Songs | Master song catalog | Title, Artist, Producer, Audio Status, Tag, Genre |
| Personnel | All contacts/people | Name, Field, Tags, Email, City, Record Label |
| Invoices | Invoice tracking | Invoice No, Entity, Client, Amount, Status, Due Date |
| Cities | City → country/timezone lookup | Name, Country, Timezone |
| MGMT Companies | Management companies | Company Name |
| Record Labels | Labels | Label Name, Label Parent |
| Publishing Company | Publishers | Company Name |
| Agent | Booking agents | Name |
| Studios | Recording studios | Name, City |
| Agency Company | Talent agencies | Company Name |
| Templates | Email templates | Name, Subject, Body |
| Pitch Log | Pitch history | Date, Type, Songs, Contacts |
| Playlists | Shared playlists | ID, Name, Song Data, Views |
| Views | Saved view states | Page, Data (JSON) |
| Play Log | Audio play tracking | Timestamp, Song, Playlist, Duration |

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
- **Invoice numbers**: Format {PREFIX}-{NNN} (ROL-001, RYE-001, TYB-001)
- **Session roles**: `admin` (full access), `assistant` (no invoices)
- **Cache TTL**: 120 seconds for Google Sheets data
- **Rate limiting**: Public endpoints: 10/hour general, 30/hour submissions
