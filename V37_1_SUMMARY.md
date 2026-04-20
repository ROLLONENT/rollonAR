# V37.1 — Smart Suggestions Sidebar (deferred V37 piece)

Date: 2026-04-20
Branch: `scout-engine`
Commit predecessor: `edd2648` (V38 queue dashboard)
Runs before V38 watchdog. Ships the deferred piece from V37.

## Mission

V37 deferred the per-pitch suggestions UI. All feeder data was already
reachable via `/api/pitch/suggestions` and `/api/personnel/<id>/outreach-events`.
V37.1 renders that data in a real composer surface and adds three new fields
(top templates, length insight, contact-level score) to the suggestions API.

## What shipped

### New page: `GET /pitch/<int:contact_row>` (admin-only)
Per-contact pitch composer at `templates/pitch_compose.html`. Two-column layout:

- **Main pane**: contact header with responsiveness pill, Subject input, Email
  Body textarea (auto word-count, warns when over 120), Copy and Save Draft
  buttons.
- **Sidebar (sticky)**: "Smart Suggestions" panel that auto-loads on render.
  Shows contact-level score, top 3 subject lines, top 3 templates, timing
  pattern, length insight, top responders.

Save Draft writes the composed text back to the contact's Outreach Events log
as a `note` event (capped at 200 chars, same schema as Log Response).

### Extended `/api/pitch/suggestions`
Now accepts `?contact_row=<int>` and returns three new fields plus an
empty-state guard:

- `top_templates`: top 3 templates from the Templates sheet ranked by
  reply rate. Pitches and replies are joined to Pitch Log rows whose Pitch
  Type contains the template name (case-insensitive substring).
- `length_insight`: compares reply rate of templates whose body is under 120
  words vs 120-plus words. Returns `{message, short_pitches, short_replies,
  long_pitches, long_replies}` only when both buckets have at least one pitch
  and one bucket has a higher rate.
- `contact_score`: when `contact_row` is passed, counts `pitch_sent` vs reply
  events on that contact in the last 365 days. Falls back to lifetime when no
  events fall in the window. Returns `{name, sent, replies, window, message}`.
  Message format: "Tom Smith has responded 3 out of 4 times in the last year."
- `total_pitches`, `min_pitches`: feeds the empty-state guard. Sidebar shows
  "Send more pitches to unlock suggestions (N of 10)" when below 10.

Existing fields preserved: `top_responders`, `top_subjects`, `best_timing`,
`cooldown_days`.

### Click-to-insert
- Subject suggestions render as inline accent-colored buttons. Click to set
  the Subject field and toast confirmation.
- Template suggestions render as inline accent-colored buttons. Click inserts
  the template body into the Email Body textarea, and the template subject
  into the Subject field if it is currently empty. Templates are cached on
  `window._pcTemplateCache` to avoid round-tripping.

### Directory detail modal: contact-level responsiveness pill + Compose Pitch button
`dirActions()` in `static/js/core.js` now renders:

- A `dir-score-${ri}` placeholder pill that lazy-fetches
  `/api/personnel/<ri>/outreach-events` and renders
  "{name} responded {N} of {M} {window}" with color coding (green when 50%-plus
  reply rate, gold 25–50%, gray below). Clicking the pill jumps to
  `/pitch/<ri>`.
- A new "Compose Pitch" button (accent style) that navigates to `/pitch/<ri>`.

Pill hides when the contact has no `pitch_sent` or reply events.

## Files touched

- `app.py` (+~150 lines, two regions)
  - Extended `/api/pitch/suggestions` (`@ line 4212`)
  - Added `/pitch/<int:contact_row>` route (`@ line 5217`)
- `templates/pitch_compose.html` (new, ~250 lines)
- `static/js/core.js` (+~30 lines)
  - `dirActions()` adds Compose Pitch button + score-badge placeholder
  - new `loadDirScore(ri, name)` helper

## Verification (live, 127.0.0.1:5001)

1. **Empty body sidebar renders** — `GET /pitch/2` returns 200; HTML contains
   `pc-sidebar`, `Smart Suggestions`, `pc-subject`, `pc-body`. Verified via
   curl + Chrome.
2. **Click subject inserts** — `GET /api/pitch/suggestions?contact_row=2`
   returns `top_subjects: [{subject:"V37_3_Test_UK_MGMT", pitches:4, ...}]`.
   `PC.insertSubject(subj)` writes to `#pc-subject` and toasts.
3. **Contact responsiveness score in Directory** — `loadDirScore(ri, name)` is
   wired into `dirActions()`. Code path exercised via
   `/api/personnel/2/outreach-events` (returns `{events:[]}`); pill is hidden
   when sent and replies are both zero, which matches current data.
   Captain test required on a contact that already has logged outreach events
   to see the colored pill render — code is in place, no contact in the first
   500 personnel rows currently has any outreach events to render against.
4. **Empty state** — current `total_pitches=4` is below the `min_pitches=10`
   threshold; sidebar empty banner triggers and reads "Send more pitches to
   unlock suggestions (4 of 10)."

## House rules

- No em-dashes or double-dashes in user-visible prose.
- ROLLON ENT remains all caps.
- Grep after edits: confirmed all new identifiers
  (`Compose Pitch`, `loadDirScore`, `dir-score-`, `insertSubject`,
  `insertTemplate`, `min_pitches`) resolve.
- Live browser test via Chrome at `http://127.0.0.1:5001/pitch/2`.

## Known gaps for next pass

- No `body` or `subject` columns on Pitch Log today, so reply attribution for
  templates relies on Pitch Type containing the template name. When V37.6's
  Gmail read-only path lands real subject/body capture, swap the join to
  exact-match.
- `contact_score` could be enriched with average response latency once enough
  reply timestamps land alongside pitch_sent timestamps.
- Save Draft logs to outreach events as a `note`. A future pass can add a
  `draft_saved` event_type and surface drafts in the timeline.
