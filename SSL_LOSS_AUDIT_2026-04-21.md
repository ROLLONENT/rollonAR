# SSL Data-Loss Audit, 2026-04-21

**Incident**: Drag-fill of 20 rows on Set Out Reach Date/Time showed green
"Filled 20 cells" toast. Cmd+Shift+R revealed values had not persisted. Red
toast followed: `[SSL: WRONG_VERSION_NUMBER] wrong version number (_ssl.c:2633)`.

**Shipped fix**: v37.7.1 (this branch, commits below).

## Scope of the audit

rollon.log was grepped for SSL signatures and Flask exception markers between
v37.7 go-live (2026-04-20 ~12:40 BST per git log) and this hotfix (2026-04-21
~08:17 BST, last captured SSL error before TLS pin was applied). Structured
per-write logging does not exist in the current codebase, so this is a
best-effort count from exception traces, not a ledger.

## Numbers

| Signal | Count | Notes |
|---|---|---|
| `SSL: WRONG_VERSION_NUMBER` occurrences in rollon.log (all-time) | 36 | grep WRONG_VERSION_NUMBER rollon.log |
| `UNEXPECTED_RECORD` occurrences | 3 | same grep |
| SSL WARNING lines on 2026-04-21 (all endpoints) | 7 | `scout`, `views save`, `_resolve_mm_rows`, `settings_get` |
| `Directory update failed` ERROR lines on 2026-04-21 | **6** | `/api/directory/update` (drag-fill + inline edits) |
| `Songs update failed` on 2026-04-21 | 0 | |
| Invoice update failed on 2026-04-21 | 0 | |
| Timestamps of the 6 failed directory writes | 08:02:57 x2, 08:04:59 x2, 08:06:27 x2 | Paired (same second) = likely drag-fill batches |

The paired 08:02:57 / 08:04:59 / 08:06:27 failures are consistent with
multi-cell drag-fills where the first write tripped an SSL handshake error and
subsequent parallel writes in the same batch inherited the same failed
socket/service object. v37.7 frontend reported these as green "Filled N cells"
because it did not await backend responses (bug fixed in the third commit of
v37.7.1).

## Lost vs persisted

Without structured write logging we cannot name the 6 lost records directly,
but the time windows give the Captain a clear recovery target.

**Best-effort list of write attempts that did NOT persist during v37.7 window
(sorted by timestamp):**

- 2026-04-21 08:02:57 BST: 2 x `/api/directory/update` failed, same second.
- 2026-04-21 08:04:59 BST: 2 x `/api/directory/update` failed, same second.
- 2026-04-21 08:06:27 BST: 2 x `/api/directory/update` failed, same second.

Total attempted directory writes that failed SSL on 2026-04-21: **6**.
Total attempted directory writes that persisted: unknown (no structured log).

## What was not audited

- Writes prior to 2026-04-20 23:59 (rollon.log already contains SSL errors on
  2026-04-20 at 23:10 on scout leads; those are read failures on background
  jobs, not drag-fill data loss).
- Whether any read (cache fill) returning an SSL error caused silent stale
  state on the frontend.
- Pitch log and playlist writes on 2026-04-21 (no failure markers found, so
  presumed clean).

## Action items beyond v37.7.1

Add structured write logging so the next incident is countable, not inferred.
One line per write attempt with request id, sheet, row, col, outcome
(`ok|retry|fail`), and retry count. That is out of hotfix scope and should go
into v37.8.

## Commits shipping the fix

- fix(v37.7.1): force TLS 1.2+ on Google Sheets client
- fix(v37.7.1): SSL exception handling in _retry with exp backoff
- fix(v37.7.1): drag-fill and inline edit await write confirmation
- perf(v37.7.1): column hide/show no longer blocks on Sheets write
- docs(v37.7.1): SSL_LOSS_AUDIT_2026-04-21.md (this file)
- chore: version bump to v37.7.1
