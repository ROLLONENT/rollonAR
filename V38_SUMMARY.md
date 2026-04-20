# V38 Summary: Autonomous Watchdog and Claude Paging

V38 makes ROLLON Q self-monitoring. Celina no longer has to chase status.
When a subprocess stalls, Q detects it within 60 seconds, fires a
structured alarm DM that the next Claude chat will read first, plays a
macOS Glass ping, and (if silence persists past 30 minutes) kills the
subprocess and auto-resumes the next queued prompt.

## Scope landed

| Layer | What shipped                                                             | Where                                                         |
|-------|--------------------------------------------------------------------------|---------------------------------------------------------------|
| 1     | PID, CPU, stdout liveness check every 60s with 3-strike STALLED rule     | `rollon-queue/watchdog.py` (HealthTracker)                    |
| 2     | 25 min freeze detection plus 5 min grace auto-kill and auto-resume       | `rollon-queue/watcher_v2.py` (_schedule_frozen_kill)          |
| 3     | Structured `@claude ROLLON Q ALARM` DM with log tail and last commit     | `rollon-queue/alarms.py` (format_alarm_dm)                    |
| 4     | macOS Glass notification with event and phase hint                       | `rollon-queue/alarms.py` (fire_macos_notification)            |
| 5     | `/queue` dashboard (Captain only) auto-refresh every 10s                 | `ROLLON AR/rollon/templates/queue.html`, `app.py`             |
| 5     | `/api/queue-status` JSON endpoint                                        | `ROLLON AR/rollon/app.py` (api_queue_status)                  |
| 5     | KILL, RESUME, PAUSE buttons posting control commands to `#rollonbots`    | `ROLLON AR/rollon/app.py` (api_queue_kill, api_queue_resume)  |
| 6     | Email alarm fallback                                                     | Skipped, optional per spec                                    |

Shared contract: `rollon-queue/state.json` is the live state file the
dashboard reads. Schema is documented in `WATCHDOG.md`.

## Alarm flow at a glance

```
Claude Code subprocess
  -> every 5s heartbeat (stdout bytes, CPU, PID)
     -> HealthTracker samples every 60s
        -> 3 failed checks  -> subprocess_stalled (WARNING DM + channel + macOS)
     -> no stdout for 25 min -> subprocess_frozen  (WARNING DM + channel + macOS)
                              -> arm 5 min grace Timer
                                 -> still stuck    -> heartbeat_timeout (CRITICAL)
                                                   -> SIGTERM, worker moves on
```

On every one of the alarm paths the `WatchdogState` publishes to
`state.json`, so the dashboard shows the new status within seconds.

## Status model

| Status    | Meaning                                                        |
|-----------|----------------------------------------------------------------|
| ALIVE     | Subprocess PID is alive, heartbeats are progressing            |
| STALLED   | Active entry exists but PID is dead or HealthTracker flagged   |
| IDLE      | No active entry, worker waiting on queue                       |
| PAUSED    | `_paused_event` is set (PAUSE command or self-pause at boot)   |

## Verification

Unit-level smoke test (ran before commit):

- `parse_phase("starting Phase 6.5 now")` returns `"Phase 6.5"` ✓
- `WatchdogState.set_active({pid: 12345...})` returns status `STALLED`
  because PID 12345 is not alive ✓
- `HealthTracker.record_sample` with no stdout progression flips to
  `stalled=True` after 3 samples and fires `on_stalled` exactly once ✓
- `format_alarm_dm` output contains `ROLLON Q ALARM`, the phase hint, and
  has no em-dashes or en-dashes ✓
- All Python files parse cleanly with `ast.parse` ✓

Functional integration tests recommended once the dashboard is open:

1. Kill the current `claude --print` subprocess with
   `kill -9 <PID>` and watch for a `subprocess_crashed` alarm within 5
   seconds (the heartbeat interval).
2. Send a prompt containing only `sleep 2000` to trigger frozen
   detection after 25 minutes. Confirm the WARNING DM arrives, then the
   CRITICAL auto-kill DM at 30 minutes and the next prompt picks up.
3. Open `localhost:5001/queue`. Confirm the status pill, queue depth,
   alarms table, and log tail populate and refresh.
4. Click `PAUSE` from the dashboard. Confirm `#rollonbots` receives
   `PAUSE` and status flips to `PAUSED`.

## Version bump

- ROLLON Q: `Q_VERSION = "2.1.0"` in `watcher_v2.py`. Reflected in the
  boot message and the `state.json` payload.
- ROLLON AR: dashboard route added, no schema changes to the Google
  Sheet. Compatible with v37 session and CSRF middleware.

## Files touched

### `rollon-queue/`

- `watchdog.py` new
- `alarms.py` rewritten with `format_channel_alert`, `_git_last_commit`,
  `_tail_log`, enriched `format_alarm_dm`
- `claude_runner_v2.py` added `on_heartbeat` callback wiring
- `watcher_v2.py` wired WatchdogState, HealthTracker, grace-kill timer,
  enriched `_fire_alarm`, bumped Q_VERSION
- `WATCHDOG.md` new runbook

### `ROLLON AR/rollon/`

- `app.py` added `/queue`, `/api/queue-status`, `/api/queue-kill`,
  `/api/queue-resume`, `/api/queue-pause`, plus `_q_*` helpers
- `templates/queue.html` new
- `V38_SUMMARY.md` new

## Known gaps

- Email alarm fallback (Layer 6) is not shipped. It was marked optional
  in the spec and requires Slack presence gating. If Celina wants it,
  an SMTP send via the existing `SMTP_*` config is a 20-line addition.
- The dashboard does not yet stream via SSE; it polls at 10s. Fine for
  now; upgrade if the alarm latency is ever user-visible.
- Q restart is manual. The watchdog watches the subprocess, not Q
  itself. Stale `state.json` is the tell.

## Post-deploy checklist

- [ ] Bookmark `http://localhost:5001/queue` in Celina's browser.
- [ ] Confirm `watcher_v2.py` was restarted after the edits (the old
      process at PID 41589 does not have the new watchdog code).
- [ ] Send a test `PROMPT: echo hello` to `#rollonbots` to verify the
      state file fills and the dashboard updates.
