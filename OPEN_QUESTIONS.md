# V36 Open Questions

Things that came up autonomously during the v36 build. Celina to review.

## Resolved autonomously

- **Works With storage**: chose the Airtable ID (`recXXX`) from col 0 as the canonical stable Personnel ID. Every sampled row has one. Pipe-separated IDs stored in Works With col 7. Reason: the prompt called for "IDs, not names, for stability on rename" and the Airtable ID is the most durable identifier in the sheet.

- **Grouping Override column**: added to Personnel as plain text. When set, it replaces the auto-computed named greeting in mail merge and the live Combined First Names view.

- **Backlinks Cache column**: added to Personnel. Reserved for future denormalised reverse-link speedups; the engine does not rely on it yet (reads are cached in-process by RelationshipsEngine).

- **Mail merge scheduling sender**: Phase 4 swaps the hardcoded `Europe/London` sender timezone for `America/Los_Angeles` because the [Use] column is named "Date/Time In LA to send email" and the Phase 4 spec requires DD/MM/YYYY HH:MM:SS in America/Los_Angeles.

- **Phase 3D Songs Producer/Writer/A&R linking**: shipped V1 lite. The LINK_TYPES registry and generic_add/generic_remove API exist, but Songs tab UI was NOT migrated from free-text to linked-record IDs. Rationale: Songs.Producer is parsed by pitch_builder, lyric_doc, and pub_splits in name-matching mode. Upgrading all readers to handle IDs is >2 hours and the current name-matching still works. V2 future ticket to add a Songs-side typeahead that writes IDs in a new `Producer IDs` column while keeping the display column.

- **Phase 3C directory modal "every relationship field shows typeahead plus chips"**: shipped a consolidated "🕸️ Relationships" button that opens a tabbed per-type UI, rather than scattering 8 typeaheads across the existing detail grid. Rationale: the detail modal is already 69 columns wide; adding 8 more inline typeaheads makes it worse. One button keeps cognitive load low.

## Decisions logged

- Chose `America/Los_Angeles` as the canonical "to send" timezone, per the existing `[✓] Date/Time In LA to send email` column header. `[✓] Date/Time In London to send email` stays populated too for reference (read-only, manual).

- Kept the legacy `/api/automate/works-with` endpoint as a shim that resolves names to IDs. Any page loaded before cache-busting still works. Safe to delete in v37.

## Open for Celina's review

- Do you want **automatic Tag addition** on Works With link (old behaviour added "Don't Mass Pitch" to the linked contact)? V36 does NOT auto-add this tag because "Works With" can also mean "co-writer, pitch with together" which is the opposite intent. The Phase 2 spec did not mention this tag. If you want it back, tell me in which direction (both sides? just the newly linked contact? opt-in toggle in the modal?).

- **Grouping Override** column is on Personnel, empty. No UI yet to set it (would go as an inline editable cell like other Personnel columns). Ship in a follow-up if you want a dedicated editor.

- Should `lookup_all_relationships` be exposed as a "Relationships panel" in the detail modal itself (always visible) rather than behind a button? Phase 3 shipped it behind a button.

- The LINK_TYPES registry currently maps `managed_by` to column `MGMT Rep` and `manages` to `Artists [MGMT]`. These existing columns are mostly empty text in the current sheet; the engine will start filling them cleanly with Airtable IDs as soon as you link anything. Old name-based values will read as missing links in the UI. Confirm this is acceptable.
