# ROLLON AR Slowness Audit (v37.4.1)

Generated 2026-04-20, scout-engine @ cf2d88f. Diagnostic only. No code changes.

## TL;DR

Two root causes, both addressable without rewriting the data layer.

1. **Socket timeouts on Google Sheets API reads (~60s hangs).** Seen repeatedly in `rollon.log` in the 22:08 window. Any network blip stalls the UI for a full minute per endpoint because `SheetsManager._retry` only handles `HttpError`, not `socket.timeout`. No per-call timeout is set on the API client.
2. **Aggressive cache invalidation on every write.** The 120s cache in `SheetsManager` works well when reads dominate, but every `update_cell` / `batch_update_cells` call wipes the entire sheet cache. After any edit, the next read pays a 3.0s cold-fetch for Personnel (12,780 rows). My v37.4 auto-recompute hook writes 2 cells on every Set Out Reach save, which means a 3.0s cold read is guaranteed right after each edit.

Everything else in this audit is secondary. Ranked fixes at the bottom.

---

## 1. Live process check

```
PID 41120   1.8% MEM  0% CPU  up since 22:03:16  python3 app.py   (rollon v37.4.1)
PID 10385   0.0% MEM  0% CPU  python3 -m http.server 5173  (unrelated, static server for another project)
```

One rollon process. Not a duplication problem. Deploy.command's `pkill -f "python3 app.py"` + `pgrep` + `pkill -9` escalation works as designed; I tripped on a stale process earlier today but `kill -9` on the exact PID cleared it. No ongoing multi-instance contention.

## 2. Sheets read timing

Direct timing of `SheetsManager.get_all_rows()` from a fresh Python process against the live workbook:

| Sheet            | Cold   | Warm   | Rows   |
| ---------------- | ------ | ------ | ------ |
| Personnel        | 2.98s  | 0.02s  | 12,780 |
| Songs            | 0.81s  | 0.00s  |    803 |
| Cities           | 0.44s  | 0.00s  |    132 |
| Views            | 0.41s  | 0.00s  |      4 |
| MGMT Companies   | 0.44s  | 0.00s  |    542 |
| Record Labels    | 0.48s  | 0.00s  |    312 |

Three back-to-back Personnel reads: `2.96s / 0.01s / 0.01s`. Cache is working.

Live HTTP (warm) against localhost right now: `/api/directory?per_page=999` = 67ms, `/api/directory?per_page=50` = 17ms, `/api/directory/tags` = 85ms, `/api/views/directory` = 442ms, `/api/scout/count` = 2ms. When the cache is warm and the network is healthy, the app is fast.

## 3. Caching audit

Caching IS in the data path, at four layers:

- **`SheetsManager._cache` (modules/google_sheets.py:17, TTL=120s).** Caches `get_all_rows` and `get_headers` by key `"{sheet}:all"` / `"{sheet}:headers"`. Returns a deep-copied list per call. Thread-safe via `_lock`. Auto-invalidates on every write method (`update_cell`, `append_row`, `batch_append`, `batch_update_cells`, `clear_sheet`, `batch_update`).
- **`NAME_CACHE` in app.py:176.** In-memory dict built once at startup for pill-click navigation. 14,392 entries.
- **`_dash_cache` in app.py:1016 (TTL=300s).** Dashboard stats.
- **Module-level caches** in `relationships.py`, `pub_splits.py`, `id_resolver.py`.

**Not cached:** `SheetsManager.get_row()` (line 113-117) hits the API on every call. This matters because:

- `run_directory_automations` (my v37.4 auto-recompute hook, app.py:942) calls `sheets.get_row('Personnel', ri)` on every Set Out Reach Date/Time edit. 1 uncached API call per edit.
- Plus two `sheets.update_cell` calls (LA + London), each invalidating the whole Personnel cache.
- Net: every Set Out Reach edit costs 1 uncached `get_row` + 2 writes + forces the next Personnel read to be cold (3.0s).

**Not cached beyond first hit per 120s:** list_sheets(), get_row_count() (delegates to get_all_rows).

## 4. Startup load (Deploy.command)

Reviewed. The script kills old processes correctly:

```
pkill -f "python3 app.py"    # line 21
sleep 1                      # line 23
pgrep -f "python3 app.py" && pkill -9 -f "python3 app.py"   # line 26-29
```

Cleanup is sound. Not the slowness cause.

Side note: Deploy.command contains em-dashes on lines 3, 15, 36 (pre-existing, not introduced by v37.4 or v37.4.1). Flagging against the "no em-dashes anywhere" rule but leaving untouched per "diagnostic only".

## 5. Combined columns recompute

`_recompute_combined_columns` is called in exactly three places:

- **Startup** (app.py:6238): `threading.Thread(target=lambda: _recompute_combined_columns_safe(), daemon=True).start()`. One background pass at boot.
- **Manual API** (app.py:3251): `/api/personnel/recompute-combined` POST.
- **Group-member auto-trigger** (app.py:3243 via `_recompute_for_group_members`): fires when a Works With link is added or removed (app.py:2830, 2857). Runs in a background daemon thread, not on the request path.

**It does NOT run on page loads.** Greeting engine is idle during normal viewing. Ruled out as a slowness cause.

## 6. Log tail findings (rollon.log)

Log lives at `rollon.log` (in project root), not `/tmp/rollon_v37_3.log`. Level = WARNING, which means only warnings/errors and `SLOW` markers (>500ms).

**Catastrophic window at 22:08 (before v37.4.1 restart):**

```
22:08:19   SLOW GET /api/views/directory:    61,121ms
22:08:23   SLOW GET /api/directory/tags:     60,033ms
22:08:23   SLOW GET /api/scout/count:        60,031ms   "The read operation timed out"
22:08:23   SLOW GET /api/directory:          60,026ms   HTTP 500
22:08:24   SLOW GET /api/views/directory:    61,335ms
22:08:26        GET /api/directory/tags:      3,008ms
22:08:38   SLOW GET /api/directory:          60,040ms   HTTP 500
22:08:39   SLOW GET /api/views/pitch:        61,159ms
22:09:24   SLOW GET /:                       60,677ms   "Dashboard song count failed: The read operation timed out"
22:10:25   SLOW GET /api/briefing:           60,610ms
22:10:25   SLOW GET /api/dashboard-stats:    60,646ms   "The read operation timed out"
```

Five distinct endpoints hit 60+s timeouts in a two-minute window. After the v37.4.1 restart at 22:10:27, the same endpoints served in 30ms to 4.3s. Either the network recovered or the connection pool was rebuilt. The pattern matches a connection-pool corruption event.

**SSL errors** appeared during recovery:

```
22:10:34   Upcoming invoices fetch: [SSL: UNEXPECTED_RECORD] unexpected record
22:10:34   Scout leads count:       [SSL: WRONG_VERSION_NUMBER] wrong version number
```

These are classic stale-TLS-session symptoms after network resumption. The `google-api-python-client` httplib2 transport does not always rebuild cleanly.

**Repeated waste: `_ensure_views_sheet` tries to create 'Views' every time reads time out** (20+ occurrences). Logic: if `get_all_rows('Views')` throws (or returns falsy), try to create the sheet. Views already exists, so creation always fails with 400 "already exists". When reads are healthy, cache hides this. When reads time out, every /api/views/* hits a 60s timeout followed by a failed creation attempt.

**Pre-existing bug, NOT introduced by v37.4 / v37.4.1: `Name cache build: name 'cleanH' is not defined`** (20+ occurrences). `build_name_cache()` is invoked at app.py:226 (module top-level), but `cleanH` is defined at app.py:451. At call time `cleanH` is an undefined name, so every table's header-detection path raises NameError, is caught, and the supporting-tables loop falls back to indexing by column 0 (Airtable IDs, `recXXX...`). Net effect: `NAME_CACHE` reports 14,392 entries but its keys for supporting tables are Airtable IDs, not names. Pill-click navigation on MGMT / Label / Publisher / Agent / City records likely misses. Does not directly cause slowness but degrades pill click UX and may trigger fallback scan paths.

---

## Ranked fixes: impact vs. effort

### HIGH impact, LOW effort

1. **Set a per-call timeout on Google Sheets API client.** Currently uses defaults (60s socket timeout, no handler). Passing `httplib2.Http(timeout=15)` to `build()` would cap hangs at 15s and let the retry loop run 3 times in 45s instead of 180s. Also add `socket.timeout` + `OSError` to the retry-classifier in `SheetsManager._retry` so timeouts trigger backoff + retry instead of bubbling up. **~15 min.**
2. **Fix `_ensure_views_sheet`: cache the "exists" result in a module-level bool.** Once we've confirmed the Views sheet exists (either a non-empty read or a successful creation), never attempt creation again. Removes the wasted creation API call on every /api/views/* request. Also add the missing case: if read returned an empty sheet, return True (sheet exists, just no data). **~5 min.**
3. **Move `build_name_cache()` call below `cleanH` definition.** Literally move line 226 to after line 451. Cache will build correctly, `NAME_CACHE` keys become names across all tables, pill-click navigation works. **~2 min + restart.**
4. **Bump CACHE_TTL from 120s to 300s.** Most sheets change slowly; 5-minute cache is plenty for active editing. Doubles cache hit rate during typical sessions. **~1 min.**

### HIGH impact, MEDIUM effort

5. **Cache `get_row` with per-row key.** Currently uncached; every `get_row` hits the API. Build `{sheet}:row:{ri}` cache, invalidate on writes to that sheet, reuse TTL. Would make my v37.4 auto-recompute hook ~500ms faster per edit. **~30 min.**
6. **Surgical cache invalidation on writes.** Instead of `_invalidate_cache(sheet_name)` wiping everything, update the cached rows in place when a cell is updated. The cached `_cache["{sheet}:all"]` is a list of lists; for `update_cell(sheet, row, col, val)` just do `data[row-1][col-1] = val`. For `batch_update_cells` loop over the updates. Eliminates the 3.0s cold read after every Set Out Reach edit. **~20 min. Has a correctness gotcha: concurrent edits from another tab or another user are lost until TTL expiry. Could be mitigated by keeping invalidation on writes that can affect other rows (append, clear, batch_update).**

### MEDIUM impact, MEDIUM effort

7. **Preload Personnel cache at startup.** Currently every first /api/directory request after boot pays 3s. Kick `sheets.get_all_rows('Personnel')` in the startup thread alongside `_recompute_combined_columns_safe()` so the cache is warm before the first user request. **~10 min.**
8. **Persistent disk cache for Personnel snapshots.** Pickle the sheet data to disk every N minutes; load on boot if fresh. Eliminates cold-boot penalty entirely. **~45 min. Adds complexity; skip unless frequent restarts become a pattern.**

### HIGH impact, HIGH effort

9. **Replace full-sheet reads with targeted queries.** `api_directory` loads all 12,780 rows then filters in Python. For filtered views (country, tag, field), a Sheets `developerMetadata` or external SQLite index would reduce per-request work by 10x to 100x. Real rebuild work. **Days.**
10. **Switch from `sheets.values().get(range=sheet)` to `values().batchGet(ranges=[...])` at startup.** Fetch Personnel, Songs, Cities, MGMT Companies, Record Labels in a single round-trip instead of 5. Cold boot time drops from ~5.1s aggregate to ~3s. **~1 hour.**

### SITUATIONAL

11. **Network health indicator in UI.** The 60s timeout window in the log was severe but recovered. Showing a banner when requests start timing out would let Celina know it's network, not app. **~1 hour.**

---

## Recommended sequence for tonight/tomorrow

If you want one change that meaningfully speeds up active editing: **fix 6 (surgical cache invalidation)**. 20 minutes of work, eliminates the 3s cold-read after every edit, zero behavior change for reads.

If you want one change that prevents the catastrophic 60s hang window you saw at 22:08: **fix 1 (15s timeout + retry on socket.timeout)**. 15 minutes, caps worst-case latency.

If you want both: do them together as v37.4.2, ~35 minutes + live smoke test. Quick wins 2 and 3 can piggyback in the same commit.

Nothing in this audit requires a schema change or a hotfix before tonight's pitch.
