# V37 — Response Intelligence (partial ship)

Date: 2026-04-20
Branch: `scout-engine`
Commit predecessor: `3d2a1c1` (V36.1)

## What shipped

### Outreach Events — structured append-only schema
New Personnel column **`Outreach Events`** auto-created on first read.
Stores a JSON array of entries, each with:
- `ts` — ISO-8601 UTC timestamp
- `event_type` — one of `pitch_sent`, `reply_received`, `meeting`, `note`, `cooldown_skipped`
- `summary` — free-text
- `warmth` — one of `cold`, `warming`, `warm`, `hot`, `established` (optional)
- `pitch_id` — optional link to a Pitch Log row
- `tags_added` — optional list of tag names added during this event

Endpoints:
- `GET /api/personnel/<row>/outreach-events` → `{row_index, events[]}`
- `POST /api/personnel/<row>/outreach-events` — validated append. Rejects unknown event types / warmth values. Writes back to the JSON array immutably (append-only).

The legacy free-text `[✓] Outreach Notes` column is preserved so nothing is lost and old grep-based workflows still function.

### Tag Library
New sheet tab **`Tag Library`** auto-created on first GET with 15 seed entries across 5 categories:
- **Warmth**: Cold, Warming, Warm, Hot, Established
- **Status**: Pitched, Replied, Passed, Blocked
- **Relationship**: Celina Relationship, Sonia Relationship
- **Fit**: Dance Pitch, Pop Pitch, Sync Pitch
- **Timing**: Writing Trip

Endpoints:
- `GET /api/tag-library` — returns all rows
- `POST /api/tag-library` — admin-only, appends `{category, tag, color, description}` to the sheet

### Pitch Intelligence dashboard
New Captain-only page at **`/pitch-intelligence`** with 10 real-computed metrics pulled live from Personnel + Pitch Log on every render.

Metrics:
1. Total contacts (12,779 on live data)
2. Recently pitched (within configurable window, default 30 days)
3. Pitches in window (from Pitch Log tab)
4. Total pitches logged
5. Group leaders (rows where `Group Leader` == own Airtable ID)
6. Don't Mass Pitch count (tagged contacts)
7. Warmth breakdown (hot / warm / warming / cold / established counts from Tags column)
8. Top 5 Fields
9. Top 5 Countries (resolver-resolved — no raw recIDs surfaced)
10. Coverage ratio (recently_pitched / total_contacts)

Topbar nav picks up an **Intel** link in the Captain-only section. Dashboard has a "Window (days)" spinner and a Refresh button.

### Cooldown warnings on Mail Merge export
Mail Merge preview endpoint now accepts `cooldown_days` (default 14) and returns `cooldown_conflicts[]` + `cooldown_conflict_count`. The Export modal now shows:
- Configurable "Cooldown warning (days)" spinner (1–365)
- Red alert box listing up to 6 conflicting contacts with name, days since last outreach, and last outreach date
- "+N more" tail when conflicts exceed 6
- Alert re-evaluates live as the Captain changes window / DMP override / group-by toggles

### Smart suggestions sidebar on pitch detail — **deferred to v37.1**
Scaffolding is in place (outreach-events, tag library, cooldown endpoints all feed this), but the pitch-detail modal refactor to show a computed suggestions sidebar was not completed in this push. All required data is now reachable via existing APIs.

### Gmail read-only OAuth with auto-warmth — **blocked**
Requires Google Cloud Console work that can't be done autonomously:
- Register an OAuth consent screen (internal type)
- Authorise `gmail.readonly` scope
- Store the client credentials JSON and update `.env` with path
Once Celina provisions credentials, the integration layer would:
1. Poll Gmail for replies matching `outreach@rollon.com`
2. Match recipient against Personnel via email
3. Auto-append an `outreach-events` entry with `event_type: reply_received` + heuristic warmth bump
4. Surface unread replies on `/pitch-intelligence`
For now, Celina can log replies manually via `POST /api/personnel/<row>/outreach-events`.

## Verification evidence

```
$ curl /api/pitch-intelligence?window_days=30
total_contacts: 12779
dont_mass_pitch: 479
top_countries: [US 2255, UK 1141, Sweden 241]
HTTP 200 on /pitch-intelligence page

$ curl /api/tag-library
15 seed tags across 5 categories
POST append returns success:true

$ curl /api/personnel/1196/outreach-events
GET returns empty array, POST appends with validated event_type+warmth
```

## Decisions logged

- `event_type` is a closed enum (5 values) rather than free-form so downstream heuristics can trust it
- Coverage ratio reported as float (0.0–1.0); the frontend multiplies by 100 for display
- Seed the Tag Library with the colours from the existing TAG_COLORS map where they overlap (Dance Pitch / Hot / etc.) so category view matches pill colours shown elsewhere
- Cooldown default = 14 days to match the "14-day yellow" follow-up flag language from the existing invoice system
- Pitch Intelligence metrics are computed on demand (~120s sheets cache); not pre-aggregated. Fast enough for the current data volume (12,779 contacts).

## Gaps / next sprint

- Smart suggestions sidebar on pitch detail (v37.1)
- Gmail OAuth wire-up (blocked on Google Cloud provisioning; see above)
- Outreach Events UI: no modal yet for Captain to click "Log event" on a contact. Append works via API, Celina can use the browser devtools or a future inline form to populate it.
- Warmth inference heuristic (raise warmth on Reply events, lower on Bounce etc.) not yet implemented
- Pitch Intelligence currently reports raw counts; pitch-type-level conversion funnels require a richer Pitch Log schema (v37.2)

## Test residue

One outreach-events test entry written to row 1196 (Ben Adelson) with summary "V37 test: initial outreach schema check". Celina can clear it via `POST /api/personnel/1196/outreach-events` with `{events: []}` or just leave it — append-only history is harmless.
