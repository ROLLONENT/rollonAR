# V37.6 Response Intelligence (UI + Gmail scaffold)

Date: 2026-04-20
Branch: `scout-engine`
Built on top of V37 (commit `ac82e29`) and V37.3-V37.5 pitch parity fixes.

## What shipped

### 1. Outreach Events timeline UI (Directory > contact detail > Timeline)
Replaces the legacy free-text `renderActivityTimeline` with a live read of the
Personnel `Outreach Events` JSON column.

- Per-event card color-coded by warmth: `hot` gold, `warm`/`warming` amber,
  `cold` grey, `established` green, `ghosted` dark.
- Shows event type label, warmth pill, pitch_id pill when present, `auto`
  badge for Gmail-sourced entries, and the operator summary.
- `+ Log Response` button opens an inline form: event type dropdown, 200-char
  summary, warmth picker, multi-select tags (pulled live from Tag Library),
  optional pitch_id.
- Submitting the form:
  - POSTs to `/api/personnel/<ri>/outreach-events` (appends structured event).
  - POSTs selected tags to new `/api/personnel/<ri>/apply-tags` (merges into
    Personnel `Tags` column, pipe-separated, idempotent, undo-tracked).
  - Reloads the timeline in place.
- Legacy `Last Outreach` date line still renders below the structured log so
  nothing is lost.

Files: `static/js/core.js` (renderActivityTimeline + `LogResponse` controller),
`app.py` (apply-tags endpoint added after the outreach-events routes).

### 2. Tag Library editor (Settings)
New **Tag Library** section renders the categorised tag vocabulary as colored
chips grouped by category, with inline add form (Category, Tag, Color,
Description) wired to the existing `POST /api/tag-library` endpoint. New tags
become available to the Log Response form on next open.

### 3. Gmail read-only integration
Separate OAuth token (`token_gmail.json`, gitignored). Sheets/Drive auth is
untouched.

Endpoints:
- `GET /api/gmail/status` (@admin_required)
- `POST /api/gmail/connect` (@admin_required) - runs `InstalledAppFlow`
  against `credentials.json` with scope `gmail.readonly` on port 0, writes
  the token on success.
- `POST /api/gmail/disconnect` - removes `token_gmail.json`.
- `POST /api/gmail/sync-now` - manual poll, scans last N days of replies.
- `POST /api/gmail/ghost-scan` - runs nightly ghost detection on demand.

Matcher logic (`gmail_sync_once`):
- Builds `{lowercased email -> (row_index, name)}` index from Personnel.
- Queries Gmail for `newer_than:{N}d -from:me`, reads metadata only
  (headers `From`, `Subject`, `Date`, plus snippet), not full bodies.
- For each new thread whose sender email matches a Personnel row:
  - Infers event_type + warmth + extra tag via keyword heuristics:
    - declined: "not interested", "not a fit", "unfortunately", "pass"
    - introduced: "will forward", "passing to", "introducing you"
    - warm_follow_up: "yes", "love to", "let's", "sounds good", "book",
      "schedule"
    - fallback: `reply_received` + `warming`.
  - Appends an `Outreach Events` entry with `auto_generated: true`.
  - Applies `Responded` + inferred tag to the Personnel Tags column.
  - Writes `Last Response Date` (auto-creates the column if missing).
- Stored per event: sender email, timestamp, thread_id, subject (120 chars),
  inferred event type, warmth, 200-char summary from Gmail snippet. **No
  full email body is ever persisted.**

Background loops (started daemon-threaded in `if __name__ == '__main__'`):
- `_gmail_poll_loop` - sleeps `gmail_poll_minutes` (default 15, min 5) then
  runs `gmail_sync_once(days=2)` when connected. No-op otherwise.
- `_ghost_nightly_loop` - sleeps until next 03:00 local then runs
  `ghost_detection_scan`.

### 4. Ghost detection (`ghost_detection_scan`)
- Threshold from `ghost_days` setting (default 14).
- Personnel rows with `Last Outreach` older than threshold and NO
  `reply_received | warm_follow_up | declined | introduced` event in the
  structured log get:
  - An auto `ghosted` event (warmth cold, summary includes day count).
  - The `Ghosted` tag added to the Personnel Tags column.
- Idempotent: rows that already carry a `ghosted` event are skipped.

### 5. Pitch Intelligence dashboard - response roll-ups
Endpoint `/api/pitch-intelligence` now also returns:
- `top_responders` - contacts with the most `reply_received` / `warm_follow_up` /
  `introduced` events (all-time, top 10).
- `top_ghosters` - contacts with the most `ghosted` events (top 10).
- `recent_meetings` - up to 10 `meeting` events in the current window with
  date + summary.
- `territory_heatmap` - reply rate per country = replies in window / pitches
  in window (needs structured `pitch_sent` events to populate).
- `total_events_logged` - counter across responders + ghosts + meetings.
- `insufficient_data: true` when `total_pitches_logged < 10` so the dashboard
  can render an empty state with a helpful hint.

Dashboard template updated:
- Warmth distribution card with 5 horizontal bars (Hot, Warm, Warming, Cold,
  Established) sized by share.
- Territory heatmap card with country, pitches, replies, rate bar, percent.
- Top responders + Top ghosters + Recent meetings cards next to existing
  Top Fields + Top Countries.
- Explicit empty state when pitch history is insufficient.

### 6. Smart Suggestions on /pitch
New `Suggestions` button on Pitch page. Calls `/api/pitch/suggestions`
(Captain-only) and renders three cards:
- Top responders all-time (from Outreach Events).
- Best subject lines (derived from Pitch Log subjects matched to reply events
  via pitch_id; only subjects with >=2 pitches surface).
- Timing recommendation - emits "Your [territory] pitches perform best at
  [hour] on [day]" when >=10 reply events have usable timestamps. Otherwise
  explicit "Not enough pitch history yet" empty state.

### 7. Cooldown threshold persistence
New **Settings > Response Intelligence Defaults** section exposes three
numbers (cooldown days, ghost days, Gmail poll minutes) with save button +
run-ghost-scan-now button. Values persist in a new `Settings` sheet tab
(key-value) via:
- `GET /api/settings/store?keys=...`
- `POST /api/settings/store` (@admin_required)

`/api/directory/mail-merge-preview` now falls back to
`settings_get('cooldown_days', '14')` when the client omits the parameter, so
future API callers don't need to know the default.

### 8. Startup wiring + gitignore
- `token_gmail.json` added to `.gitignore`.
- Both new background threads started in `__main__` block after the existing
  cleanup/overdue threads.
- Startup logs a "v37.6 response intelligence loops started" line so the
  Deploy.command console confirms the wiring every boot.

## Verification evidence (curl, logged in as Captain)

```
$ GET /api/tag-library              # 16 tags (15 seed + 1 prior test)
$ GET /api/settings/store           # {cooldown_days: '14', ghost_days: '14', gmail_poll_minutes: '15'}
$ GET /api/gmail/status             # {connected: false, scopes: ['gmail.readonly'], ...}
$ POST /api/personnel/1196/outreach-events  # appended, count 2
$ GET  /api/personnel/1196/outreach-events  # reads back structured entry
$ POST /api/settings/store {cooldown_days:'10'}  # persisted, readback matches, restored to 14
$ POST /api/gmail/ghost-scan        # {ghosted: 0, threshold_days: 14}
$ GET /pitch-intelligence           # 200, contains 'Warmth distribution' + 'Territory heatmap' + 'Recent meetings'
$ GET /settings                     # 200, contains 'Tag Library' + 'Integrations · Gmail' + 'Response Intelligence Defaults' + 'Run ghost scan'
$ GET /pitch                        # 200, contains 'loadSuggestions' + 'p-suggestions'
$ GET /api/pitch/suggestions        # returns {top_responders, top_subjects, best_timing, cooldown_days:14}
$ GET /api/pitch-intelligence       # insufficient_data: true, 15 metric keys incl heatmap + responders + meetings
```

Server startup (system Python 3.9 via CommandLineTools Framework):
```
Ensuring v36 relationship columns ...
Running v37.3 filter smoke tests (fail-loud)...
  [OK] all 5 smoke tests pass
v37.6 response intelligence loops started (gmail poll + ghost nightly)
Serving Flask app 'app' on 0.0.0.0:5001
```

## Decisions logged

- **Gmail uses a second token file** (`token_gmail.json`) instead of
  extending Sheets scopes on `token.json`. Rationale: narrower blast radius
  if Gmail access is ever revoked, and avoids triggering a full Sheets
  re-consent when enabling the integration.
- **Metadata-only Gmail reads.** The matcher uses
  `format='metadata'` with `metadataHeaders=['From','Subject','Date']` +
  `snippet`. Email body is never fetched or stored. Celina's privacy rule
  ("no email body beyond 200-char summary") is enforced at the source, not
  the persistence layer.
- **Settings sheet** is a flat Key-Value tab (two columns). Simpler than
  JSON blob and keeps values auditable in the live sheet.
- **Cooldown fallback only when key is absent**, not when value is 0. A
  Captain who explicitly passes `cooldown_days: 0` gets a disabled warning;
  a Captain on an older client that doesn't send the key gets the persisted
  default.
- **Ghost nightly runs at 03:00 local**, not UTC. Chosen so Celina never sees
  a tag change in the middle of her workday.
- **Timing suggestions require 10+ samples** before surfacing so a random
  early reply doesn't skew the recommendation.

## Gaps / next sprint

- **Gmail OAuth flow requires interactive consent.** `InstalledAppFlow.run_local_server`
  opens a browser and blocks until consent. Works locally; needs a refresh
  flow design for headless deploys.
- **Pitch Log schema is narrow.** We assume `Subject` and `Pitch ID` columns;
  existing rows don't carry them consistently, so `top_subjects` and reply
  attribution will be thin until the Mail Merge export starts writing them.
  V37.7 should standardize the Pitch Log writeback.
- **No "undo" on auto events.** Celina can edit the Tags column to remove an
  auto-applied tag, but cannot yet mass-delete a bad Gmail match. Add a
  "dismiss auto event" control in v37.7.
- **Cooldown warning UI** on the Mail Merge export still reads from the modal
  input, not the persisted default. Client-side pickup of the saved default
  is a v37.7 polish item.

## House rules observed

- No em-dashes in UI copy or docs.
- ROLLON ENT stays all caps where it appears.
- Buttons over forms: "+ Log Response", "Connect Gmail", "Sync Now", "Run
  ghost scan now", "Suggestions" are all first-class buttons on their pages.
- Grep after edits (endpoints + UI markers verified in cURL dump above).
- Live browser test: settings, pitch-intelligence, and pitch pages opened in
  Chrome on localhost:5001 after server restart.
