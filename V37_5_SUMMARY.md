# V37.5 SUMMARY

Date: 2026-04-20
Branch: `scout-engine`
Final commits:
- `ba9b868` docs: refresh Airtable parity gap audit with root-cause chains
- `8266c55` feat(v37.5): backfill Date/Time In LA and London send times

## Context

The queued "V36 AIRTABLE PARITY FULL REBUILD" brief was run against a repo where v36 phases 1-8 had already shipped in prior sessions. Git log confirms:
- `a82f04a` docs: Phase 1 Airtable parity gap audit
- `fdc750e` feat(v36): Phase 2 Works With engine
- `7459c50` feat(v36): Phase 3 Relationship web
- `d888c95` feat(v36): Phase 4-6 timezone chain, group toggle, mail merge rebuild
- `ae44fed` feat(v36): Phase 6.5 Group Leader, CSRF retry, global search
- `3d2a1c1` feat(v36.1), `ac82e29` feat(v37), plus v37.3 / v37.4.x

Rather than re-ship code that already exists, this pass treated the brief as a verification sweep and gap-fill. One real code gap was found and shipped.

## Reality check against the brief's assumptions

The original Phase 1 audit described `Works With is empty on every sampled Personnel row`. That claim was based on a 13-row sample. The live startup smoke test against the full Personnel sheet (5,305 rows) reports:

```
[OK] Works With is not empty: 699
```

699 Personnel rows have populated Works With clusters. The v36 engine is running against real data, not starving. This section of the audit was overstated and has been corrected in the refreshed `AIRTABLE_PARITY_GAP.md`.

## What shipped in v37.5

### 1. `_backfill_send_times` (app.py ~3212)
Walks every Personnel row with a populated `Set Out Reach Date/Time`, resolves the recipient timezone via `tz_resolve(city, country, CITY_LOOKUP)`, and writes `Date/Time In LA to send email` + `Date/Time In London to send email` in `DD/MM/YYYY HH:MM:SS` format. Same logic as the on-edit branch at app.py:947, but applied to legacy rows whose `Set Out Reach Date/Time` predates that branch.

`force=False` by default so it only touches cells where the computed value differs from the existing cell. Idempotent.

### 2. Startup thread (app.py ~6343)
Daemon thread kicks the backfill at boot next to the existing `_recompute_combined_columns_safe` thread. Logs `Send times: N cells updated of M rows (tz fallbacks: K)` when done.

### 3. API surface
- `POST /api/personnel/recompute-send-times` — body: `{row_indices: [int], force: bool}`, both optional. Returns `{updated, scanned, tz_fallbacks, timestamp}`.
- `GET /api/personnel/recompute-send-times/status` — returns `{running, last_run, updated, scanned}`.

### 4. Refreshed parity audit
`AIRTABLE_PARITY_GAP.md` replaced with a chain-by-chain diagnosis (214 insertions, 148 deletions). Six chains diagnosed: three RED BROKEN, one YELLOW, one GREEN, one mirrored. Chain 3 is now closed by this ship. Chain 4 (Works With data) is partially closed (699 rows populated); the remaining ~86% without links is a data-entry gap, not a code gap.

## Verification evidence

### Startup log (live)
```
Ensuring v36 relationship columns (Backlinks Cache, Grouping Override, Group Leader)...
  Columns: {'Backlinks Cache': 69, 'Grouping Override': 70, 'Group Leader': 71}
Running v37.3 filter smoke tests (fail-loud)...
  Filter smoke tests:
    [OK] Country = UK: 1172
    [OK] Country has any of (UK, US): 3437
    [OK] Field has any of (Record A&R): 482
    [OK] Country = UK AND Field has any of (MGMT, Publishing A&R, Record A&R, Writer MGMT): 424
    [OK] Works With is not empty: 699
Recomputing Combined First Names / Emails Combined (background)...
Backfilling Date/Time In LA / London to send email (background)...
 * Serving Flask app 'app'
```

### Backfill status endpoint (live)
```
GET /api/personnel/recompute-send-times/status
200 {"last_run":"2026-04-20T22:45:15.348246","running":false,"scanned":1085,"updated":2170}
```

1,085 Personnel rows had `Set Out Reach Date/Time` populated. 2,170 cells written back (LA + London, roughly 2x scanned). Completed in under 2 minutes. Idempotent on re-run — second invocation will return `updated: 0` unless source data changed.

### Symbol grep (static)
```
app.py:3209 _SEND_TIMES_STATE
app.py:3212 def _backfill_send_times(row_indices=None, force=False)
app.py:3273 def _backfill_send_times_safe()
app.py:3349 @app.route('/api/personnel/recompute-send-times', methods=['POST'])
app.py:3362 @app.route('/api/personnel/recompute-send-times/status')
app.py:6343 threading.Thread(target=lambda: _backfill_send_times_safe(), daemon=True).start()
```

### Syntax / import check
```
python3.12 -m py_compile app.py → ok
4 new symbols parse cleanly
Flask boot on port 5001 → Serving Flask app after ~22s
```

## What was NOT re-shipped (already present, verified)

| Brief phase | Status | Evidence |
|---|---|---|
| Phase 2 Works With engine | SHIPPED earlier | `modules/relationships.py` 671 lines, `group_for_pitch`, `greeting_for`, LINK_TYPES registry |
| Phase 3 Relationship web | SHIPPED earlier | LINK_TYPES symmetric + directional pairs; generic bidirectional linking live |
| Phase 4 Timezone send-time chain (on-edit) | SHIPPED earlier | app.py:947 branch, `tz_resolve`, CITY_IANA_MAP 142 cities |
| Phase 5 Live combined fields / Group Email Rows | SHIPPED earlier | `_recompute_combined_columns` + startup thread |
| Phase 6 Export to Mail Merge | SHIPPED earlier | `_group_mm_contacts` delegates to `relationships.group_for_pitch` |
| Mail Merge rename from YAMM | SHIPPED earlier | `grep -rn YAMM --include='*.py' --include='*.js' --include='*.html'` returns 0 code matches; only audit docs reference YAMM intentionally |

## Decisions logged autonomously

- Did NOT re-execute v36 phases 2-6. Re-running them would have rewritten working code on top of itself, risking regressions for no gain.
- Did NOT block or wait on Celina for approval. Task brief explicitly allows autonomous decisions.
- Shipped the one real code gap as `v37.5` rather than relabelling v36. Relabelling would rewrite git history and break the existing v36 / v37 tagging.
- Restarted the running Flask process to pick up the new endpoint. Task brief explicitly calls for `Deploy.command restart`.
- Used `force=False` as the default for the backfill to keep the startup thread idempotent. A `force=true` API call is available if Celina wants to blow away all existing LA strings and recompute.

## Remaining gaps (honest list)

1. **Works With data coverage**: 699 of 5305 Personnel rows have Works With populated (13%). The other ~4,600 rows are a data-entry gap, not a code gap. Resolving this requires either a source-of-truth re-ingest from Airtable export, or manual linking via the existing Works With typeahead. Out of scope for code.
2. **Live browser QA**: the HTTP endpoints are verified. Click-through flows (Works With typeahead, Group Leader modal, Group Email Rows toggle, Export to Mail Merge end-to-end) remain for Celina to validate in her session.
3. **Backfill re-run on Set Out Reach Date/Time edit**: already covered by the on-edit branch at app.py:947. The new startup backfill closes the gap for rows edited before that branch existed.
4. **`phase1_audit.py` script** (present in the repo) runs the dry Phase 1 scan. Not wired into anything production-critical.

## How to verify on Celina's side

1. Open a Directory record with `Set Out Reach Date/Time` populated and check `Date/Time In LA to send email` and `Date/Time In London to send email` render. Previously blank on legacy rows; now filled.
2. `POST /api/personnel/recompute-send-times` with `{force: true}` if Celina wants to recompute everything.
3. Run a Mail Merge export. `Scheduled Date` column should match the LA cell per contact.

## Heartbeats posted

- 1/2: V36 HEARTBEAT at run start, declaring verification mode.
- 2/2: V36 HEARTBEAT after server restart + backfill completion.

Both in `#rollonbots` (`C0ATRUE7JS1`).
