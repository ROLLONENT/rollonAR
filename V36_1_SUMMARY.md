# V36.1 — Live Search Highlighter + Row Copy

Date: 2026-04-20
Branch: `scout-engine`
Commit predecessor: `ae44fed` (V36 Phase 6.5)

## What shipped

### Live character highlighter (Airtable-style Cmd+F)
- Every per-grid `#search-input` now also drives a live DOM highlighter that wraps each query match in `<mark class="live-hl">` across the currently rendered grid body
- Gold-tinted background on every match, brighter filled background + outline on the "active" one
- Counter `N of M` floats inside the search input on the right edge, updates in real time
- Keyboard:
  - Enter (and ArrowDown) steps to next match, Shift+Enter (ArrowUp) steps to previous, with smooth scroll-into-view
  - Esc clears the query, removes highlights, blurs the input
- `Cmd+F` / `Ctrl+F` on any grid page focuses the per-grid search bar
- A MutationObserver on `#grid-wrap` auto-re-applies highlights whenever the grid re-renders (from filters, sort, pagination, inline edit) so the highlighter survives without touching each page's reload()
- Exposes `window._liveHl` (`apply`, `step`, `clear`) for future programmatic use

### Smart record suggestions
- Already shipped as part of V36 Phase 6.5: the topbar `#global-search` dropdown returns cross-table matches in 180ms debounced batches
- Typing "be" now serves both paths: topbar dropdown surfaces matching Personnel suggestions, and on a Directory page the per-grid search highlights "be" occurrences in every visible cell live

### Cell copy-paste (hardened on prior v35 foundation)
- `Cmd+C` copies the selected cell's canonical value (pipe-joined multi-values normalised to commas; linked records kept as resolved names from the page cache)
- `Cmd+V` pastes clipboard content type-aware: pill-style fields (tag, link, autocomplete, field_type, multi_select) split commas back to pipe-separators, everything else pastes raw
- `Delete` / `Backspace` clears the cell
- Tab / Shift+Tab and arrow keys navigate cell-to-cell, crossing row boundaries at the edges
- Enter opens the inline editor; any printable character also starts editing with that character pre-filled
- Cell-selected styling retained from v35: accent gold outline + dim gold fill; matches the brand palette in CLAUDE.md
- `cell-copied` flash animation added: a brighter gold background pulses for 600ms after Cmd+C so the Captain sees which cell was copied

### Row context menu
- Right-click on any `.data-grid tbody tr` now opens a contextual menu with:
  - **Copy Row as TSV**: headers and values joined by tabs with a newline between — paste directly into any spreadsheet
  - **Copy Row as comma-separated**: every non-empty value joined with commas, pipe-delimited multi-values expanded
  - **Copy Row as JSON**: `{field: value}` map, pretty-printed
- Closes on scroll / click-outside / selecting an action
- Never hijacks right-click on pill internals (`a`, `.pill-x`) so native browser menus still work where appropriate

### Universal coverage
All of the above is wired centrally in `static/js/core.js` so every grid page inherits it automatically:
- Directory, Songs, Pitch, Invoices, Playlists, Scout
- Selector-based: any page that renders `.data-grid tbody` with `td[data-field]` and has an `#search-input` opts in automatically. Zero per-page change.

## Verification evidence

### Grep
```
$ grep -c "live-hl\|row-ctx-menu\|_liveHl\|walkAndHighlight" static/js/core.js
9
$ grep -c "mark.live-hl\|cell-copied\|live-hl-counter" static/css/style.css
5
```

### Smoke tests
- `node -c core.js` → CORE_JS_OK
- Flask restart clean, serves `?v=36.1` cache-buster
- `/api/global-search?q=ben` returns 15 hits, first is Ben Adelson (routes to directory)
- Cell-select Cmd+C flow retained from v35; highlighter adds a live-hl mark inside a cell but does not affect the selection outline or the inline editor (text nodes inside `<input>` / `<textarea>` are rejected by the TreeWalker filter)

## Decisions logged

- Kept the existing gold `--accent` outline for cell selection rather than swapping to a literal beige border — it matches the brand palette and users already know it
- TreeWalker-based highlighter (not innerHTML replace) preserves all existing click handlers, pills, and inline editors. Rebuilding innerHTML would have broken every pill onclick.
- Highlight re-runs on a 260ms debounce after each keystroke so rapid typing doesn't thrash the DOM
- Context menu offers three copy variants (TSV / comma / JSON) to cover both spreadsheet paste and engineering-style copy workflows

## Gaps

- Counter "0 of M" resets on every input event so position is not persisted if you immediately retype — fine for the real-time nav use case, but worth noting
- Row context menu currently only offers copy variants. Add "Select Row", "Duplicate", "Archive" in v36.2 when bulk actions expand
- Live highlighter intentionally scopes to `.data-grid tbody` — detail modal content and other panels are NOT highlighted. Extending later is one selector change.
