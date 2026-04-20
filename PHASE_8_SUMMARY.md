# V36 — Phase 8 Summary

Date: 2026-04-20
Branch: `scout-engine`
Final commits: Phase 1-6 (d888c95) → Phase 6.5 / CSRF / Global Search (this commit)

## What shipped

### Phase 1-6 (previously committed)
- `AIRTABLE_PARITY_GAP.md`: 28-tab audit, orphaned-logic grep, Personnel 69-col map
- `modules/relationships.py`: RelationshipsEngine with Works With storage, bidirectional links, transitive closure, greeting generator, generic typed link registry (managed_by, represented_by, ar_rep, publishing_rep, creative_of)
- `modules/timezone_map.py`: 90+ city IANA zone map with Cities.Timezone aliases and country-code defaults
- Timezone chain: `Set Out Reach Date/Time` (recipient TZ) → `[Use] Date Time LA to Send Email` (America/Los_Angeles) + `[Use] Date Time London to Send Email` (Europe/London) recomputed on every edit
- `_group_mm_contacts` now delegates to `relationships.group_for_pitch` (Works With wins, then Company)
- Mail Merge export builds a Drive Sheet in "ROLLON AR Pitches" folder with the 5-column Mail Merge with Attachments schema + Pitch Log entry + `Pitched: <name>` tag + `Last Outreach` stamp

### Phase 6.5 — Group Leader, Don't Mass Pitch, Star icon (this push)
- New `Group Leader` column appended to Personnel on startup (col 71). Holds one Airtable ID per row: the leader of the Works With cluster.
- `POST /api/relationships/group-leader`: writes the leader to every group member, auto-tags non-leaders with `Don't Mass Pitch` (idempotent). `GET` returns `{leader, group_ids}` for a contact.
- `POST /api/relationships/group-leader/clear`: blanks the leader on every group member.
- Leader-picker modal (core.js `openGroupLeaderPicker` / `_renderLeaderPickerModal`): opens after `_wwAddLink` when the cluster reaches ≥2 contacts. Radio of every member, pre-selected to existing leader if any, checkbox "Tag secondaries with Don't Mass Pitch" defaulted on. "Skip" dismisses, "Save Leader" calls the API and refreshes the detail modal and directory grid.
- Directory row now renders a gold ★ next to `Name` when the row is its own Group Leader (core.js `_isGroupLeader`). Title tooltip: "Group Leader — receives mass pitches for this group".
- Mail Merge preview + export now accept `include_dont_mass_pitch` (default false). Preview returns `skipped_dont_mass_pitch` count; export refuses with a helpful error when every contact carries the tag and the override is off. Directory modal shows a dedicated checkbox with live red pill styling.

### CSRF addendum
- `POST /api/csrf/refresh`: CSRF-exempt, authenticated-only; returns a fresh token.
- `base.html` fetch wrapper: already globally intercepts all POST/PUT/DELETE. Added 403 auto-refresh — peeks the response body, if `error` contains "csrf" it hits `/api/csrf/refresh`, stores the new token, and retries the original request exactly once (`opts._csrfRetried` guard). Also exposes `window.__csrfGetToken()` for diagnostic use and syncs a `<meta name="csrf-token">` tag so legacy `_jsonHeaders()` callers pick it up.

### Global Search + Cmd+K
- `GET /api/global-search?q=`: cross-table search returning `{name, table, row_index, route, subtitle}`. Resolves Personnel → `/directory?open=`, Songs → `/songs?open=`, everything else → modal via `/api/table-record`.
- Internally refactored `_search_records_impl` so both `/api/search-record` and `/api/global-search` share one code path (fixes the earlier attempt that piped through `test_request_context` and lost session).
- Topbar `#global-search` input in `base.html` now wires to a live dropdown. Typing fires the API with 180ms debounce, shows up to 12 matches with subtitle, Arrow keys navigate the highlight, Enter opens, Esc/outside-click closes.
- Cmd+K (or Ctrl+K on non-Mac) focuses and selects the global search from any page.

## Verification evidence

### Grep
```
YAMM rename complete: only doc refs remain
  $ grep -rn YAMM --include='*.py' --include='*.js' --include='*.html' .
  AIRTABLE_PARITY_GAP.md:6 hits (audit doc, intentional)
  0 hits in app.py / static/js / templates

V36 markers present:
  31 occurrences across app.py, core.js, base.html, directory.html, relationships.py
  (openGroupLeaderPicker, _isGroupLeader, /api/relationships/group-leader,
   /api/csrf/refresh, /api/global-search, include_dont_mass_pitch,
   DONT_MASS_PITCH_TAG, GROUP_LEADER_COLUMN)
```

### API-level Phase 7 verification (curl-driven, live Flask)
1. `/api/relationships/search` returns Ben Adelson at `recEwaiYym1QiqHqF` ✔
2. `/api/relationships/group-leader/recEwaiYym1QiqHqF` returns `{leader: "", group_ids: [...]}` — endpoint live ✔
3. `/api/relationships/works-with/recEwaiYym1QiqHqF` returns empty links (solo baseline) ✔
4. `/api/directory/mail-merge-preview` with `include_dont_mass_pitch=false` returns `skipped_dont_mass_pitch` field ✔
5. `POST /api/directory/update` with valid token returns `{success: true}` ✔
6. Same request without CSRF token → `HTTP 403 {"error":"CSRF token missing or invalid"}` ✔ (retry path in base.html will match "csrf" substring)
7. `/api/csrf/refresh` returns fresh token; second call picks it up cleanly ✔
8. `/api/global-search?q=ben` returns 15 Personnel hits, all with `route: "directory"` ✔
9. Advanced filter `Countries contains "United Kingdom"` AND `Field contains_any "Record A&R,Record Label"` returns 106 rows ✔
10. Startup log: `Columns: {'Backlinks Cache': 69, 'Grouping Override': 70, 'Group Leader': 71}` ✔

### Live browser flows (not yet driven by agent — handoff to Celina)
Flow | Covered by agent | Remaining browser step
---|---|---
Link + leader-picker | API live, UI code landed | Open a Directory record, link to a second contact, confirm modal appears
Filter Country UK AND Field any-of | 106 records | Click the filter chips, confirm grid renders
Group Email Rows toggle | Back-end via `/api/relationships/group` | Toggle `👥 Group Email Rows`, confirm Combined First Names populates
Export to Mail Merge | `/api/directory/mail-merge-export` endpoint unchanged except new DMP filter + extra cols intact | Create pitch "TEST UK 21 April" at 11:06 London, confirm Drive Sheet spawns
Generated sheet DD/MM/YYYY | `_format_mm_schedule` unchanged from Phase 4 | Confirm `21/04/2026 11:06:00` in Scheduled Date column
Click Set Out Reach Date/Time cell | Endpoint 403-safe + CSRF wrapper retries | Open detail modal, click the field, save a date, confirm no CSRF toast
Search "be" suggests Ben | 15 results returned | Type in topbar, confirm dropdown lands below the input
Cmd+K focus | Global keydown listener in `core.js:1588-1593` | From /dashboard, hit Cmd+K, confirm focus jumps to topbar input

## Decisions logged (v36)

From `OPEN_QUESTIONS.md`:
- Airtable ID (`recXXX`) = canonical Personnel ID (not sheet row index, which shifts on archive)
- Grouping Override column lives on Personnel, plain text, overrides named greeting
- Sender timezone is `America/Los_Angeles` (matches `[Use] Date Time LA to Send Email`)
- Songs producer/writer upgrade to linked IDs deferred to v37 (V1 name-matching still works)
- Relationships UI consolidated behind one "🕸️ Relationships" button rather than 8 inline typeaheads
- Leader-picker modal ships ON BY DEFAULT for 2+ link clusters; Skip button dismisses without writing

## Gaps / open for next phase

- Phase 7 browser QA (8 flows above) — agent verified the HTTP surface, live UI clicks remain for Celina
- `_bulk_data` cache in `RelationshipsEngine` is declared but unused; future optimization for `contacts_tagged_dont_mass_pitch` N-row reads
- Scout page not migrated to the `window._currentTable` dynamic filter pattern — unrelated to V36 scope but worth a v36.2 pass
- Legacy `/api/automate/works-with` shim still present; safe to delete in v37 per Phase 3 decision log

## Next up

- V36.1 — live character highlighter, smart suggestions, cell copy-paste (task #7)
- V37 — Outreach Notes schema, Tag Library, Gmail read-only OAuth, /pitch-intelligence dashboard, cooldown warnings (task #8)
