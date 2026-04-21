# Spreadsheet Grid Cell Mechanics (v37.7)

Source file: `static/js/cell_mechanics.js`
CSS classes: `cell-selected`, `cell-range`, `cell-fill-handle`, `cell-fill-ghost`, `cell-copied`, `cell-ctx-menu`, `cell-undo-toast`
Cache-buster: `?v=37.7`
Loaded by: `templates/base.html` (after core.js / filters.js / grid-engine.js / monitor.js)

All interactions work on any `<td data-field data-ri>` cell rendered by `buildGridV2` or `buildGroupedGrid` in `static/js/core.js`. That covers Directory, Songs, Pitches, Invoices, and Calendar. Scout, Playlists, Pitch Intelligence, Settings, and Dashboard render through card / panel layouts that are not `.data-grid` tables, so cell mechanics do not apply there until those pages migrate to the canonical grid renderer.

## Keyboard shortcuts

| Key | Action |
|---|---|
| Click cell | Select single cell. The selected cell shows a 2px gold outline and an 8px gold fill handle at its bottom-right corner. |
| Click and drag | Select rectangular range. |
| Shift+click | Extend the existing selection to the clicked cell. |
| Cmd+A | Select every cell in the active grid (the grid that owns the active cell). |
| Arrow keys | Move selection one cell. Stops at grid edges. |
| Tab / Shift+Tab | Move right / left. |
| Enter | Edit selected editable cell, or move down on a read-only cell. |
| Shift+Enter | Move up. |
| Escape | Deselect. |
| Double click | Open the inline editor on editable cells, or open the full record modal on non-editable cells. |
| Any printable character | Enter edit mode and type the character. |
| Cmd+C | Copy selection. Single cell -> plain text value. Range -> TSV. |
| Cmd+Shift+C | Copy entire row as TSV (headers + values, two-line payload). |
| Cmd+V | Paste. Single-cell clipboard into a range fills the whole range. TSV clipboard pastes as a 2D block starting at the rangeAnchor (top-left of selection). |
| Delete / Backspace | Clear every cell in the selection (skips read-only cells silently). |
| Cmd+Z | Undo the last drag-fill, range paste, or range delete batch. |

## Right-click context menu

Right-click any cell to open the menu. Right-clicking a cell outside the current selection single-selects it first, so the menu always operates on a known target.

Cell items: Copy, Copy as TSV, Copy as CSV, Copy as JSON, Paste, Fill down from here, Clear cell.
Row items: Copy row as TSV, Copy row as CSV, Copy row as JSON.

The menu closes on outside click or scroll.

## Drag fill (the primary use case)

Every selected editable cell shows a small gold square handle at its bottom-right corner. Mouse down on the handle and drag to draw the fill range; a dashed gold ghost outline expands in real time. Mouse up writes the source value into every cell in the range.

The canonical workflow: filter Directory to UK MGMT, click the top row's Set Out Reach Date/Time cell, type the value (or paste it), grab the handle, drag down 200 rows. Every row inherits the same date and time, the LA / London send times recompute server side, and the toast offers a 10-second Undo.

- v37.7 behavior: literal copy only. Smart fill (numeric series, date ladder, day of week) is deferred to v37.8.
- Drag-fill source can be a single cell or a multi-cell range. Range sources tile their pattern across the target rectangle modulo source rows / cols, matching Sheets' fill-by-pattern behavior.
- Read-only targets are skipped silently and counted in the completion toast ("Filled 18 cells (skipped 2 read only)").
- The completion toast carries an Undo button visible for 10 seconds. Cmd+Z fires the same undo whether or not a cell is currently selected.

## Copy serialization (type-aware)

| Field type | Serialized to clipboard |
|---|---|
| text / url / email / contact / long / duration / plaintext / id | raw string |
| number / currency / percent / rating | raw string of the number |
| date | sheet-format string as stored |
| datetime | sheet-format string as stored (e.g. `21/04/2026 11:06:00`) |
| tag / autocomplete / field_type / link | pipe-separated pills reformatted as comma-separated ("Warm, Hot Lead") |

## Paste parsing (type-aware)

| Field type | Parsing |
|---|---|
| number / currency / percent / rating | `parseFloat` after stripping non-digit chars. Error toast if NaN. |
| date | ISO `YYYY-MM-DD`, `DD/MM/YYYY`, `MM/DD/YYYY`. DD/MM is preferred for the UK workflow. |
| datetime | Same as date plus `HH:MM[:SS]`. Stored with seconds suffix. |
| tag / link / autocomplete / field_type | Split on `,`, `;`, or `|`, trimmed, rejoined with ` | `. |
| text / url / contact / long / duration / plaintext | Raw string. |

If the clipboard contains tabs or newlines, it is treated as TSV and pasted as a 2D block starting at the top-left corner of the selection.

## Read-only cells (computed)

These headers are treated as read-only. Paste, delete, and drag-fill into them are silent no-ops and show "This cell is computed":

- Combined First Names / Combined First Names [USE]
- Emails Combined / Emails Combined [USE]
- Date/Time In LA to send email
- Date/Time In London to send email
- Backlinks Cache
- Group Leader
- Grouping Override

Copy works on read-only cells (so you can copy the computed value elsewhere). Cells with type `id` or `checklist` are also effectively read-only at the grid layer (their values render but inline editing is disabled). They are copyable.

## Undo

Drag-fill, range paste, and range delete each stack one undo snapshot. A new action drops the previous snapshot. Cmd+Z (or the Undo button in the toast) restores every cell to its pre-action value by re-calling `_gridSave` with the prior cached value.

Single-cell inline edits are not on this undo stack; they use the existing per-cell save / cancel flow in `gridEdit`.

## Compatibility hooks

The old globals `cellSelect(td)`, `cellDeselect()`, `cellMove(dir)`, and `window._selectedCell` are kept as thin shims over the new module so the existing inline-edit blur handler at `core.js:1859` (which calls `cellSelect(td)` to re-highlight after save) keeps working. The shims also deduplicate same-cell re-selection so the fill handle does not flicker after every save.

## What is not in v37.7 (deferred)

- Smart fill (numeric sequences, date ladders, day-of-week) -> v37.8
- External TSV paste from Excel / Numbers / Sheets that crosses column types (e.g. pasting a Sheets block with a mix of date / number / tag columns) -> parses per-cell but with no column-type inference at the source side; validate live before promoting
- Multi-column non-contiguous range selection (Cmd+click individual cells)
- Freeze-pane-aware auto-scroll at the viewport edge during drag-fill (drag still works, it just does not auto-scroll when the range exits the viewport)
- Selection persistence across filter / sort re-renders (selection clears today; the V36.1 spec required survival but the current implementation does not yet snapshot + restore)

## Verification

Automated:

- `node -c static/js/cell_mechanics.js` -> ok
- Grep proofs: every CSS class name (`cell-range`, `cell-fill-handle`, `cell-fill-ghost`, `cell-ctx-menu`) cross-references JS + CSS.
- Grep proof of universal load: `grep -rn "cell_mechanics" templates/` -> base.html script tag.

Live (run at http://localhost:5001 with password rollon2026):

- F1 Click a cell on Directory -> 2px gold outline. Arrow keys move. Tab / Shift+Tab. Escape clears. Click a tag pill -> the cell still selects (the new global mousedown handler runs before the cell's onclick).
- F2 Select a tag cell -> Cmd+C -> paste into TextEdit -> reads as comma-separated. Select a 1x3 range -> Cmd+C -> paste into Sheets -> three columns populate.
- F3 Select a Set Out Reach Date/Time cell -> Cmd+V with "21/04/2026 11:06" in clipboard -> cell saves and the on-edit backfill recomputes LA / London. Cmd+V on Combined First Names [USE] -> "This cell is computed" toast and the cell is unchanged.
- F4 Select a Set Out Reach Date/Time cell with a value -> grab the gold handle -> drag down 20 rows -> toast "Filled 20 cells. Undo". Click Undo -> all 20 rows revert.
- F5 Click and drag a 5x3 range -> Cmd+C -> Sheets paste preserves rows and columns. Delete -> all non-read-only cells clear. Cmd+A in a filtered view -> every visible cell selects.
- F6 Same checks on Songs, Pitches, Invoices, Calendar. Card-based pages (Scout, Playlists, Pitch Intelligence) are out of scope.
