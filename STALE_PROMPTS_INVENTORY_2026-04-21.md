# STALE PROMPTS INVENTORY 2026-04-21

Inventory taken: 2026-04-21 07:05 BST
Inventory author: autonomous queue cleanup run (prompt_2e95a84d)
Source of truth: `/Users/celinarollon/tools/rollon-queue/logs/q_v2_2026-04-20.jsonl` + `q_v2_2026-04-21.jsonl`
Queue implementation note: ROLLON Q v2 holds its queue in RAM only. There is no persistent state file for v2. The old `queue/state.json` at `/Users/celinarollon/tools/rollon-queue/queue/state.json` is leftover from the v1 watcher and is not consulted by the running v2 process.

## HEADLINE

**Killed this run:** 0
**Kept in queue (including active):** 2

There were no stale prompts in the live queue at inventory time. Every item from Celina's STALE categories (V36 rebuild variants, V37/V37.1/V37.2/V37.3 clarifications, V36.1 Directory UX, V35.7 universal filter, CSRF addenda, Combined First Names / Emails Combined rebuilds, system audit re-runs, trivial liveness tests) had already been processed by Q v2 overnight. They reached natural exit states (completed cleanly or crashed with exit 1) before this cleanup fired. No SIGTERM was dispatched and no queue entry was removed.

## CURRENT QUEUE (KEPT)

### 1. prompt_2e95a84d (active, running right now)
- Title: QUEUE CLEANUP + STALE PROMPTS INVENTORY - AUTONOMOUS
- Slack ts: 1776749519.565569
- Queued at: 2026-04-21T06:32:20 BST
- Started: 2026-04-21T07:00:40 BST
- Priority: self (inventory run)
- Estimated runtime: 5 to 10 min
- Status: this prompt. Writing the file you are reading.

### 2. prompt_537de512 (queued, next after this run exits)
- Title: Q V2.2 UPGRADE - VISIBILITY COST CAP RUN AFTER V37.7
- Slack ts: 1776750411.963339
- Queued at: 2026-04-21T06:47:19 BST
- Priority: Celina authored, not in any STALE category, explicitly tagged to run after v37.7. V37.7 already shipped overnight, so this is cleared to run.
- Estimated runtime: 30 to 60 min (infra upgrade work on rollon-queue, typical scope)
- Status: waiting in deque.

## KEEP LIST ITEMS NOT YET QUEUED

Celina's KEEP priority list names items that have not hit `#rollonbots` with a `PROMPT:` prefix, so Q v2 never enqueued them. They are NOT in the queue:

- V37.7 SPREADSHEET CELL COPY PASTE DRAG FILL: already shipped. See commits e023deb, bf37661, 4ed5551, 4e87d32, c58335c, ebe6ffe, 08a2850, f9adc9d on scout-engine. Inventory run started two seconds after V37.7 exited cleanly.
- EMMMA RR Pre-Save popup: not yet queued.
- EMMMA RR Stimulation Reward Central: not yet queued.
- Game Session 3.1 Personalization: not yet queued.
- Game Session 3.3 Mobile First Controls: not yet queued.
- Game Weapon Positioning URGENT: not yet queued.
- Game Session 3 Deep Audit: not yet queued.
- EMMMA.co Full Audit: not yet queued.

Celina needs to post these in `#rollonbots` with the `PROMPT:` prefix for Q v2 to pick them up. Once prompt_537de512 completes, Q will be idle and ready.

## V37.7 SPREADSHEET CHECK

The prompt Celina refers to as "V37.7 spreadsheet just queued (ts 1776749486.678129)" is prompt_09144fc3.
- Queued: 2026-04-21T06:31:49 BST
- Started: 2026-04-21T06:31:50 BST
- Completed: 2026-04-21T07:00:38 BST exit 0 natural runtime 1728.4s
- Commits pushed: e023deb, bf37661, 4ed5551, 4e87d32, c58335c, ebe6ffe, 08a2850, f9adc9d on scout-engine
- Last commit on branch: f9adc9d `chore: version bump to v37.7`

## WATCHDOG HEALTH CHECK

Celina asked: if Q v2 is silent past ~01:07 BST on a big run, V38 watchdog should fire. Finding: **watchdog is firing correctly, no fix required.**

Trace for prompt_09144fc3 (V37.7 spreadsheet, the big silent run):
- 06:31:50 BST subprocess_started pid=51802
- 06:31:50 through 07:00:33 BST stdout stayed at 0 bytes (Claude Code thinking silently)
- 06:56:51 BST watchdog emitted `subprocess_frozen` `no output for 1500s` (25 min threshold)
- 06:56:52 BST `alarm_dm_sent subprocess_frozen -> U020YALUBRA` (DM to Celina)
- 06:56:52 BST `alarm_notification macOS notification fired`
- 07:00:38 BST subprocess_exited exit_code=0 cause=natural stdout 3990B (output landed before the 5 min grace kill fired)
- 07:00:38 BST prompt_completed done in 1728.4s

Watchdog flow per `watchdog.py` is: 3-strike HealthTracker at 60s cadence, `subprocess_frozen` alarm on third strike, 5 min grace timer, auto SIGTERM if still silent. For this run, natural output arrived inside the grace window so the kill was not needed. DM + macOS notification both dispatched. Nothing to patch.

Note on the "silent since ~01:07 BST" phrasing in the source prompt: at 01:07 BST the active run was prompt_3d83d646 (V37.5 SPREADSHEET). That subprocess exited with exit_code=1 at 01:24:49 BST (runtime 1024s) and fired `subprocess_crashed` + `alarm_dm_sent`. After that, no subprocess ran until V37.7 came in at 06:31 BST. There was no stuck prompt between those two windows.

## HISTORICAL RECORD: STALE CATEGORY PROMPTS PROCESSED BEFORE CLEANUP

For Celina's review, here is every prompt that matched a STALE category and had already reached a terminal state before this inventory. None required SIGTERM from this run. `source=boot_backlog` means Q v2 re-read Slack history on its 22:18 BST reboot and pulled these in.

| prompt_id | title (truncated 100 chars) | queued slack_ts | terminal state | superseding shipment |
| --- | --- | --- | --- | --- |
| prompt_75bef165 | ROLLON AR AIRTABLE PARITY AUDIT DIAGNOSIS ONLY | 1776668893.965439 | completed | V36 rebuild (already shipped) |
| prompt_3baddb6a | ROLLON AR V36 AIRTABLE PARITY FULL REBUILD AUTONOMOUS RUN | 1776669963.156179 | completed | v37.5 backfill commits ba9b868, 8266c55, af052de |
| prompt_8b23fba0 | ROLLON AR V37 RESPONSE INTELLIGENCE AUTONOMOUS RUN | 1776670078.763199 | completed | v37.6 at 9d9fd8e |
| prompt_1a7186b3 | V36 ADDENDUM CSRF TOKEN BUG MUST BE EXPLICITLY FIXED | 1776670145.770489 | completed | CSRF fix at cf2d88f (v37.4.1) |
| prompt_71d41828 | V36 PHASE 6.5 ADDENDUM MASS PITCH AUTO-TAG + SEARCH RECORDS FIX | 1776671315.633599 | completed | v36 phases shipped |
| prompt_4be1d248 | ROLLON AR V36.1 DIRECTORY UX LIVE SEARCH + CELL COPY PASTE AUTONOMOUS RUN | 1776671919.822329 | completed | superseded by V37.7 (shipped f9adc9d) |
| prompt_f4c43c9e | ROLLON AR V38 AUTONOMOUS WATCHDOG + CLAUDE PAGING AUTONOMOUS RUN | 1776684983.047999 | completed | V38 shipped at 0adc9db + edd2648 |
| prompt_9d35b840 | ROLLON AR V37.1 SMART SUGGESTIONS SIDEBAR AUTONOMOUS RUN | 1776685464.908929 | completed | v37.1 at e461617, 66d50ca, 2d578ee |
| prompt_24417207 | V37.2 URGENT COMBINED FIRST NAMES + EMAILS COMBINED NOT RENDERING IN DIRECTORY | 1776685542.892139 | crashed exit 1 | fixed in v37.2 / v37.3 / v37.4 chain |
| prompt_16f39017 | V37.3 URGENT FILTER REGRESSION + COMBINED COLUMNS DIAGNOSIS | 1776685696.816119 | completed | v37.3 at d888c95 |
| prompt_373a1f57 | V37.3 CLARIFICATION ROOT CAUSE CONFIRMED BY CELINA | 1776685895.254839 | completed | v37.3 at d888c95 |
| prompt_cd28afe1 | V37.3 SCOPE EXPANSION FILTER SYSTEM AIRTABLE PARITY | 1776686018.915759 | completed | v37.3 at d888c95 |
| prompt_b8b767c5 | ROLLON AR SYSTEM AUDIT READ-ONLY AUTONOMOUS | 1776687076.760349 | completed | SYSTEM_AUDIT_2026-04-20.md at 00:43 BST |
| prompt_dcac18f4 | V38 URGENT AUTONOMOUS WATCHDOG + CLAUDE PAGING | 1776697633.510279 | completed | V38 shipped |
| prompt_15aa9056 | ROLLON AR V35.7 FIX SET OUT REACH DATE/TIME PICKER | 1776701076.498639 | completed | superseded by v37.3 filter rebuild |
| prompt_60d25e87 | ROLLON AR V35.7 OUTREACH DATE+TIME FIX + COMBINED PILL RENDERING | 1776701178.680179 | completed | v37.3 / v37.4 chain |
| prompt_f08309cf | ROLLON Q V38 AUTONOMOUS WATCHDOG + CLAUDE PAGING (DM-ONLY) | 1776701209.444529 | completed | V38 shipped |
| prompt_c033d8fc | ROLLON AR V35.7 test ping | 1776701288.342459 | completed | liveness test, validated 01:05 BST |
| prompt_8e06b81c | ROLLON AR V35.7 part 1 of 2 SET OUT REACH DATE/TIME PICKER | 1776701342.961779 | completed | v37.3 filter rebuild |
| prompt_4acb0d91 | ROLLON AR V35.7 part 2 of 2 COMBINED FIRST NAMES AND EMAILS COMBINED | 1776701363.465749 | completed | v37.2 / v37.3 / v37.4 |
| prompt_f1a5069c | ROLLON V38 SLACK PAGER AND WATCHDOG AUTONOMOUS RUN | 1776701402.257539 | completed | V38 shipped |
| prompt_c588ad0a | Q HEALTHCHECK TRIVIAL TEST AUTONOMOUS | 1776709044.093059 | completed | liveness already validated |
| prompt_e11390c4 | Q AUTH TEST TRIVIAL AUTONOMOUS | 1776710135.994219 | completed | auth already validated |
| prompt_bb10ae9c | Q V2 PAUSED TEST TRIVIAL | 1776720251.424469 | completed | liveness already validated |
| prompt_51c85451 | Q V2 LIVENESS TRIVIAL TEST AUTONOMOUS | 1776720443.959689 | completed | liveness already validated |
| prompt_3d83d646 | ROLLON AR V37.5 SPREADSHEET CELL COPY PASTE DRAG FILL AUTONOMOUS | 1776721113.144639 | crashed exit 1 | superseded by V37.7 (shipped f9adc9d) |
| prompt_7a229caa | V37.3 CLARIFICATION ROOT CAUSE CONFIRMED BY CELINA (re-post) | 1776727102.559249 | completed | v37.3 at d888c95 |
| prompt_09144fc3 | ROLLON AR V37.7 SPREADSHEET CELL COPY PASTE DRAG FILL AUTONOMOUS PRIORITY | 1776749486.678129 | completed | shipped this run: f9adc9d |

## NOTES FOR CELINA

1. The queue is effectively clean. V37.7 already shipped. Only one item behind this inventory run: Q V2.2 UPGRADE.
2. EMMMA and Game prompts need to be posted to `#rollonbots` with the `PROMPT:` prefix before Q v2 will see them.
3. V38 watchdog is working. It fired the DM and macOS notification on V37.7's long silent stretch at 06:56:51 BST.
4. Two crashed runs in the history (prompt_24417207 V37.2 at 00:15 BST, prompt_3d83d646 V37.5 at 01:24 BST) are worth a quick postmortem later. Both exit_code=1 cause=natural, both fired alarms correctly.
5. No Q restart, no watcher_v2.py patch, no queue reorder performed. Scope held to read + document.
