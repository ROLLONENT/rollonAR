# Airtable Parity Gap Audit - v36 Phase 1

Sheet ID: `17b7HjbfXkV5w_Q8lRuG3Ae_7hwJ0M9F7ODVIFytBBmY`
Scanned 28 tabs. Personnel has 69 columns, 12,779 rows. Songs has 48 columns, 802 rows.

## Header legend the sheet already uses

- `[✓]` - Airtable-checked column (originally a linked/formula/rollup field)
- `[LU]` - legacy lookup from Airtable
- `[USE]` - computed "use this for pitching" column
- `[Sync]` - sync-specific field
- Plain header - data entry field

All `[✓]` columns are COMPUTED in Airtable. Migration left them intact as data or blank. Work: restore the computation engine.

## Personnel tab column audit

| # | Header | State | Notes |
|---|---|---|---|
| 0 | Airtable ID | GREEN | `recXXXX` stable ID. Our canonical Personnel ID. |
| 1 | [✓] Name | GREEN | data |
| 2 | [✓] Genre | GREEN | data |
| 3 | [✓] City | GREEN | data, keys CITY_LOOKUP |
| 4 | [✓] Outreach Notes | GREEN | data |
| 5 | [✓] Tags | GREEN | pipe-separated pills |
| 6 | [✓] Title | GREEN | data |
| 7 | [✓] Works With | RED BROKEN | empty on every sampled row. This is THE field Phase 2 rebuilds. |
| 8 | [✓] Works with Button | RED MISSING (data only) | stores old Airtable button JSON. Not usable. Will leave alone. |
| 9 | [✓] Backlink | RED MISSING (data only) | old Airtable dynamic-backlink button JSON. Replaced by live engine. |
| 10 | [✓] Field | GREEN | role field (MGMT, Record A&R etc) |
| 11 | [✓] Email | GREEN | data |
| 12 | [✓] Linkedin/Socials | GREEN | |
| 13 | [✓] Countries | GREEN | rec ID or name |
| 14-18 | PRO, IPI, Telephone, Publishing IPI | GREEN | data |
| 19 | [✓] Last Outreach | GREEN | stamped by export |
| 20 | [✓] Songs Written | YELLOW | legacy rollup, not live |
| 21 | [✓] Artists | YELLOW | linked-record text, not live link |
| 22 | [✓] Creatives | YELLOW | same |
| 23 | [✓] Bio | GREEN | data |
| 24 | [✓] MGMT Rep | YELLOW | text name, not linked to Personnel |
| 25 | [✓] MGMT Company | GREEN | holds `recXXX` from MGMT Companies |
| 26 | [✓] URL (from MGMT Company) | YELLOW | rollup, not live |
| 27 | [✓] Publishing Rep | YELLOW | text |
| 28 | [✓] Publishing Company | GREEN | recXXX |
| 29 | [✓] Record Label A&R | YELLOW | text |
| 30 | [✓] Record Label | GREEN | recXXX |
| 31 | [✓] PPL | GREEN | |
| 32 | [✓] Type of Label | GREEN | |
| 33 | [✓] Agent | YELLOW | text |
| 34 | [✓] Agency | GREEN | recXXX |
| 35-38 | Featured Artist/Produced/Mixed/Mastered [LU] | YELLOW | rollups, stale text |
| 39 | [✓] Website [LU] | YELLOW | rollup |
| 40 | [✓] Combined First Names [USE] | RED BROKEN | empty, Phase 5 populates live |
| 41 | [✓] Emails Combined [USE] | RED BROKEN | empty, Phase 5 populates live |
| 42 | [✓] Company | YELLOW | rollup label |
| 43-45 | Credits [Sync], Sync Type, Alt Pitch Lines | GREEN | data |
| 46 | [✓] Set Out Reach Date/Time | NEUTRAL (data entry) | most rows empty, a few ancient 2023 timestamps |
| 47 | [✓] Date/Time In LA to send email | RED BROKEN | empty, Phase 4 computes live from col 46 + timezone |
| 48 | Songs | YELLOW | linked rollup |
| 49 | Creatives Publishing | YELLOW | legacy rollup |
| 50 | [✓] Pitched Songs | YELLOW | rollup |
| 51 | Admin Due Date | GREEN | data |
| 52-58 | [✓] Artists [MGMT], [Agent MGMT], [Publishing Rep], [Record Label A&R]; Creatives [MGMT], [Publishing Rep], [Record Label A&R] | RED BROKEN | these are THE back-links that Phase 3 reanimates |
| 59 | Known | GREEN | data |
| 60 | [✓] Date/Time In London to send email | YELLOW | similar to 47, London version |
| 61-68 | Brand, Brand Category, Instagram Handle, Outreach Method, Partnership Type, Campaign Notes, Budget Range, One Sheet URL | GREEN | brand-partnership data entry |

## Songs tab column audit

| # | Header | State | Notes |
|---|---|---|---|
| 0 | Airtable ID | GREEN | |
| 1-7 | Title/Written Date/Tag/Audio Status/Song Admin/Lyrics/Lyrics Docs | GREEN | |
| 8 | Songwriter Credits | GREEN/YELLOW | pipe text, names only. Phase 3D upgrades to linked Personnel IDs. |
| 9 | [✓] Artist | YELLOW | text, should link Personnel |
| 10 | [✓] Producer | YELLOW | text, should link Personnel |
| 11 | [✓] Record Label | GREEN | recXXX |
| 12-33 | Format, Dropbox, DISCO, Mix/Master Engineer, Release Date, CAT NO, PRO, SX, ISWC/ISRC/Barcode, Spotify, Splits, Recording Date/Studio/Country/City, Song Trust | mixed GREEN/YELLOW | |
| 34-36 | Last Modified / Created / Modified by | GREEN | metadata |
| 37 | [✓] Vocalist | YELLOW | text, should link Personnel |
| 38 | [✓] Pitches | YELLOW | rollup |
| 39 | [✓] Pub Credit | YELLOW | |
| 40-47 | Project, Label Copy, Artists/Labels/Pubs Pitched, Writer IPI, Publishing IPI, Legal Docs | GREEN | |

## Other tabs

| Tab | Rows | State |
|---|---|---|
| A&R Contacts | 0 | unused |
| Pitches | 5 | pitch templates |
| Companies | 22 | |
| MGMT Companies | 541 | keyed by recXXX |
| Record Labels | 311 | |
| Publishing Co / Publishing Company | 124 / 124 | DUPLICATE TABS. Publishing Company is canonical in app.py |
| Agent | 66 | |
| Publicist / PR Company | 3 / 3 | thin |
| Music Sup Co / Music Sup Company | 47 / 47 | DUPLICATE TABS |
| Cities | 131 | has Timezone column, already fed into CITY_LOOKUP |
| Clean Up Tasks | 33 | admin |
| Admin Date | 1 | singleton |
| Agency Company | 22 | |
| Countries + Codes | 250 | |
| Studios | 27 | |
| Email Task Logs | 3 | |
| Templates | 2 | email templates |
| Playlists | 0 | |
| Invoices | 277 | |
| Views | 3 | saved view states |
| Scout Leads | 0 | scout engine leads |

## Orphaned logic grep (per Phase 1 requirement)

| Symbol | File:Line | Status |
|---|---|---|
| `CITY_LOOKUP` | app.py:238, 625-650 | LIVE, hydrated at startup from Cities + Personnel |
| `TIMEZONE_OFFSETS` | app.py:242-257 | LIVE fallback for `_format_mm_schedule` |
| `_timezone_for_city` | app.py:1860 | LIVE, reads CITY_LOOKUP[city]['timezone'] |
| `_format_mm_schedule` | app.py:1866 | LIVE. Uses zoneinfo then falls back to offsets. HARDCODED Europe/London sender - Phase 4 changes to America/Los_Angeles |
| `works_with` | app.py:2197 (api_works_with) | LIVE but limited: name-based matching, single direction only, rewrites Combined columns per-contact not per-group |
| `worksWithUI` | static/js/core.js:793 | LIVE button hook |
| Works With prompt | static/js/core.js:1078 | existing modal |
| `combined_names`, `combine_emails` | nowhere in backend | NEVER built. Empty shell |
| `backlink` | sheet col 9 only (Airtable relic JSON) | No live logic |
| `group_by` | app.py:1849, 2036, 2148, 2158 | LIVE in mail-merge flow (Company only, no Works With override) |
| `timezone_map`/`TIMEZONE_MAP` | nowhere | not in repo. CITY_LOOKUP+Cities sheet is the map. |
| `pytz` | nowhere | not used. zoneinfo is. |
| `zoneinfo` | app.py:1870 | one import inside try block |

## YAMM references (rename to "Mail Merge" in Phase 6)

1. `app.py:1854` comment "YAMM-compatible Google Sheet"
2. `templates/directory.html:45` button tooltip "YAMM-ready Google Sheet"
3. `templates/directory.html:361` JS comment "YAMM-ready Google Sheet"
4. `FEATURES.md:12,16` documentation mentions YAMM
5. `migrate_music_supervisors.py` - one mention (non-functional)
6. `scout_engine.py` - one mention (non-functional)

5-column schema `First Name, Email Address, Scheduled Date, File Attachments, Mail Merge Status` confirmed compatible with Mail Merge with Attachments (Digital Inspiration). No schema change needed.

## Airtable ID = canonical Personnel ID

Col 0 "Airtable ID" holds `recXXXXXXXXXXXXXX`. Every sampled row has one. This is what Phase 2 uses as the stable Personnel identifier in Works With (NOT sheet row indices, which shift on archive).

## Phase 2-6 readiness

| Phase | Readiness | Notes |
|---|---|---|
| 2 Works With | Works With col 7 exists, empty. Just needs engine + UI. New Backlinks Cache + Grouping Override columns to be added. |
| 3 Relationship web | Linked-record columns 24-34 partially populated with recXXX IDs for Companies. Need linked-to-Personnel upgrade on Rep columns (24,27,29,33) and backlink population on 52-58. |
| 4 Timezone | `_format_mm_schedule` already uses zoneinfo. Swap sender Europe/London to America/Los_Angeles, wire col 46 (Set Out Reach Date/Time) to col 47 (Date/Time In LA to send email). |
| 5 Live view | Cols 40, 41 exist. Wire live population. |
| 6 Export | rename YAMM, use new grouping. |

Continuing to Phase 2 immediately.
