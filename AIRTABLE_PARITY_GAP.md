# AIRTABLE PARITY GAP AUDIT

Branch: `scout-engine`
Sheet ID: `17b7HjbfXkV5w_Q8lRuG3Ae_7hwJ0M9F7ODVIFytBBmY`
Scope: diagnose which Airtable computations were NOT rebuilt when data migrated to Google Sheets. No code or sheet changes made.

## Summary totals

- **Tabs scanned**: 29 tabled sections exported from Drive. Named tabs match `CLAUDE.md` sheet list (Songs, Personnel, Invoices, Cities, MGMT Companies, Record Labels, Publishing Company, Agent, Studios, Agency Company, Templates, Pitch Log, Playlists, Views, Play Log, Distribution Log, plus Scout, Countries, Brand Partnerships, Jobs, etc.).
- **Personnel columns**: 73. Of those, 47 carry the `[✓]` or `[USE]` / `[LU]` prefixes, which the sheet itself flags as computed Airtable origin.
- **Critical broken chains**: **5 of 6** tested are broken at the sheet level. Only Chain 6 (Timezone resolver) has all the machinery live.
- **Root cause (overall)**: most computation modules exist in `/modules` and are imported by `app.py`, but they depend on `Works With` being populated with `recXXX` Airtable IDs. `Works With` is empty across every Personnel row sampled, so the dependent chains (Combined First Names, Emails Combined, per-group greetings, Date/Time In LA/London send) collapse to single-contact output.
- **Secondary root cause**: the per-row formula fields (`Date/Time In LA to send email`, `Date/Time In London to send email`) only recompute inside the `set_cell` write path (`app.py:945-981`). There is **no startup backfill** that walks existing rows, so legacy `Set Out Reach Date/Time` values (many from 2022-2023) have never triggered the computation.

## Critical broken chains blocking pitches

Top 3 (ranked by pitch-blocking severity):

1. **Date/Time In LA to send email** is empty on every sampled Personnel row even when `Set Out Reach Date/Time` is filled. This is the YAMM-schedulable column Mail Merge with Attachments reads. Without it, no scheduled send lands. `app.py:945` only triggers on edit — no backfill.
2. **Works With** is empty on every sampled row. Without it, Combined First Names collapses to the single contact's first name (code falls back at `app.py:3163-3174`), Emails Combined drops co-contacts, and greeting_alt ("Hi both / Hi all") never fires. Pitches to MGMT/Label/Publishing/Agency groups go out addressed to one person with one email instead of the grouping Celina expects.
3. **Combined First Names [USE]** and **Emails Combined [USE]** output is therefore degraded, even though the recompute logic IS wired at startup (`app.py:6236`) and on edit.

## Chain-by-chain findings

### Chain 1 - Combined First Names [USE] (Personnel col 40)

- **State**: RED BROKEN (output degraded, not empty).
- **Expected**: group by MGMT / Label / Publishing / Agency company; format by group size.
- **Observed in sheet**: filled on every sampled row but only with the contact's own first name (Steve, Don, Torbjörn, Matteo). Group formatting never observed.
- **Code present**:
  - `app.py:3012 _format_combined_first_names` implements 1 / 2 / 3 / 4 / 5+ formatting.
  - `app.py:3102 _recompute_combined_columns` runs at startup in background (`app.py:6236`) and on Works With edit.
  - `app.py:3128` builds the `ww_map` from Personnel `Works With` cells.
- **Missing**: the `ww_map` is empty because Works With itself is empty. Function falls through to the own-first-name fallback.
- **Formatting rule mismatch (open question)**: the task brief says `1=Andrew, 2-3=Alex & Daniel, 4+=all`, but the code at `app.py:3012-3031` uses a different 1 / 2 / 3 / 4 / 5+ scheme (`Luke, Josie & Emily` for 3, etc.). This is either a brief simplification or a real behavior gap. Flag for Celina review.
- **Fix location (when fixing)**: depends on upstream Works With backfill, not the format function.

### Chain 2 - Emails Combined [USE] (Personnel col 41)

- **State**: RED BROKEN.
- **Expected**: same grouping, comma-separated emails.
- **Observed**: sampled rows have either a single email (the contact's own) or blank. No multi-email joins observed.
- **Code present**: same path as Chain 1, at `app.py:3171` `combined_emails = ', '.join(emails)`.
- **Missing**: same root cause — Works With empty, `_collect_group_info` returns only the caller's own email.

### Chain 3 - Set Out Reach Date/Time -> Date/Time In LA to send email

- **State**: RED BROKEN (hard blocker).
- **Expected**: given `Set Out Reach Date/Time` (recipient-local wall-clock) + resolved recipient IANA timezone, emit a `DD/MM/YYYY HH:MM:SS` string in `America/Los_Angeles`. YAMM reads this to schedule.
- **Observed**: column exists at Personnel col 47. Empty on every sampled row, including rows that have non-empty `Set Out Reach Date/Time` (e.g. `rec034iTqJI6AZraJ` Torbjörn - Stockholm - 2022-12-13T10:00:00.000Z, `rec03NDX2hHTbjTbu` Matteo - New York - 2023-12-13T11:00:00.000Z).
- **Mirror column**: `Date/Time In London to send email` (Personnel col 60). Same pattern: empty everywhere.
- **Code present**:
  - `app.py:945-981` `ch == 'set out reach date/time'` branch: resolves tz via `tz_resolve(city, country, CITY_LOOKUP)`, writes LA + London cells on cell-write.
  - `modules/timezone_map.py` exposes `resolve_timezone`, `CITY_IANA_MAP` (~90 cities), `COUNTRY_DEFAULT_TZ`, `to_la_string`, `parse_iso`.
  - `app.py:3583-3610` has a second `la_col` / `ldn_col` path inside what looks like a pitch/export routine that recomputes at pitch time.
- **Missing**:
  - No startup backfill loop. Legacy rows with a `Set Out Reach Date/Time` that predates this logic never get LA/London strings written.
  - No manual `/api/personnel/recompute-la-times` endpoint observed.
- **Fix location**: write a one-shot backfill that mirrors `app.py:947-981` across every Personnel row where `Set Out Reach Date/Time` is non-empty, then wire a startup-background thread like `_recompute_combined_columns_safe` at `app.py:6236`. Uses the already-imported `tz_resolve`, `tz_to_la`, `tz_to_zone`, `tz_parse_iso`.

### Chain 4 - Works With (Personnel col 7)

- **State**: RED BROKEN (hardest blocker, feeds Chains 1/2/5).
- **Expected**: pipe-separated list of linked Airtable IDs per `modules/relationships.py:5-17` contract. Bidirectional — adding A->B writes B to A and A to B.
- **Observed**: empty on every sampled row. The Airtable-origin columns that DO still have data are `Works with Button` (col 8) and `Backlink` (col 9), which contain raw Airtable JSON blobs, e.g. `{"label": "Works With", "url": "https://airtable.com/tblK6myDn1w2j8Ns2/rec02PMaTJJKoEIQL?blocks=bliHPL8e5o9k8Lb2x"}`. Those are not machine-usable without hitting Airtable.
- **Code present**: `modules/relationships.py` LINK_TYPES at line 25 declares Works With as symmetric; full engine around `add_link` / `group_for_pitch` / `greeting_for` exists.
- **Missing**: the migration never converted the Airtable-side backlink data to `recXXX | recXXX` strings in the Works With column. This is the single biggest load-bearing gap in the whole audit.
- **Fix location**: one-shot migration that walks `Works with Button` (col 8), follows the Airtable URL block pattern to recover peer IDs (or re-ingests the original Airtable export), and writes pipe-separated recIDs into `Works With`. Grouping Override (col 70) and Group Leader (col 71) can stay as manual overrides.

### Chain 5 - Last Outreach tracking + 14-day cooldown warning

- **State**: YELLOW (field tracking live, cooldown logic live, but depends on correctly grouped contacts).
- **Expected**: `Last Outreach` stamp on pitch send, warn if same contact was pitched within 14 days.
- **Observed**:
  - `Last Outreach` column filled on ~38% of sampled rows.
  - `modules/pitch_builder.py:134` stamps Last Outreach on pitch export.
  - `app.py:2294 _compute_cooldown_conflicts` returns contacts pitched within `days`.
  - `app.py:2465` default cooldown is 14 days, matching brief.
- **Missing**: nothing intrinsic. But: because Works With is empty, a pitch to a group counts as N independent contacts, so the cooldown surface per group is smaller than intended. Fixing Chain 4 also tightens this.

### Chain 6 - Timezone Formula (Country/City -> IANA)

- **State**: GREEN.
- **Expected**: resolve a contact's `City` + `Countries` to an IANA zone.
- **Observed**:
  - `Cities` sheet (section 13, ~131 rows) has a `Timezone` column with Airtable-style codes (`Eastern US`, `Pacific US`, `CEST [EU]`, `AEST [Australia]`, `WIB [Indonesia]`, etc.). Matches every key in `TIMEZONE_ALIAS_MAP` at `modules/timezone_map.py:28-71`.
  - `modules/timezone_map.py` has a ~150-entry `CITY_IANA_MAP` (line 75 onward) plus `COUNTRY_DEFAULT_TZ` (line 239).
  - `resolve_timezone` at line 309 does the 4-step resolve: Cities sheet alias, CITY_IANA_MAP, country fallback, empty.
- **No gap here**. The chain is fully plumbed and Chain 3 already consumes it at `app.py:956`.

## Orphaned / latent logic in app.py and modules

- `modules/timezone_map.py` - imported at `app.py:20`, consumed by `app.py:956`, `app.py:3610`. Live.
- `modules/relationships.py`
  - `ensure_columns` runs at startup (`app.py:6223`) and writes Backlinks Cache, Grouping Override, Group Leader into Personnel if missing.
  - `greeting_for` called from `/api/personnel/group-greeting` (referenced at `app.py:2892`).
  - `group_for_pitch` called from `_group_mm_contacts` at `app.py:2354`.
  - All logic LIVE but starves when Works With is empty.
- `_recompute_combined_columns` at `app.py:3102` runs in a daemon thread at startup (`app.py:6238`). LIVE but degraded for the same reason.
- `_recompute_for_group_members` at `app.py:3206` - on-demand recompute keyed on seed Airtable IDs. Called from Works With edit hooks. LIVE.
- `app.py:6198` runs a smoke test `'Works With is not empty'` that expects at least one row to match. If the data truly is empty everywhere, this test would be FAILing at every startup (`app.py:6208` raises `RuntimeError` and SystemExit(2) at `app.py:6234`). Worth confirming: either the current service is not starting cleanly, or a small number of rows have been manually populated to pass the smoke test while the bulk of Personnel is unconverted. Open question.
- No orphaned dead-code modules found. The machinery is correct; the data upstream is missing.

## Full column inventory - Personnel (73 cols, critical tab)

Based on the 13-row slice Drive returned. Empty percentages are against that slice, not the full 12,779-row sheet, so treat "100% empty" as "no filled rows in the slice" pending a live re-read.

| # | Header | State | Notes |
|---|---|---|---|
| 0 | Airtable ID | GREEN | `recXXXX` canonical ID. 100% filled. |
| 1 | [✓] Name | GREEN | 100% filled. |
| 2 | [✓] Genre | NEUTRAL | 100% empty in slice; data entry field. |
| 3 | [✓] City | GREEN | 69% filled; feeds timezone resolver. |
| 4 | [✓] Outreach Notes | NEUTRAL | data entry. |
| 5 | [✓] Tags | NEUTRAL | pipe-separated pills, data entry + pitch-tag writes. |
| 6 | [✓] Title | NEUTRAL | data entry. |
| 7 | [✓] Works With | **RED BROKEN** | empty on every sampled row; the root cause for Chains 1/2. |
| 8 | [✓] Works with Button | RED MISSING (data only) | raw Airtable JSON blob, not machine-usable. |
| 9 | [✓] Backlink | RED MISSING (data only) | raw Airtable Dynamic Backlink JSON. |
| 10 | [✓] Field | GREEN | role category. |
| 11 | [✓] Email | GREEN | |
| 12 | [✓] Linkedin/Socials | NEUTRAL | |
| 13 | [✓] Countries | GREEN | stored as recID or name; feeds timezone resolver. |
| 14-18 | Writer IPI / PRO / Pub Credit / Publishing IPI / Telephone | NEUTRAL | data entry. |
| 19 | [✓] Last Outreach | GREEN | stamped by `pitch_builder.py:134`. |
| 20-22 | [✓] Songs Written / Artists / Creatives | YELLOW | legacy Airtable rollup text; not live link. |
| 23 | [✓] Bio | NEUTRAL | |
| 24 | [✓] MGMT Rep | YELLOW | text name, not a Personnel recID link. |
| 25 | [✓] MGMT Company | GREEN | holds `recXXX` from MGMT Companies. |
| 26 | [✓] URL (from MGMT Company) | RED BROKEN (LOOKUP) | lookup of MGMT Companies.URL; empty in slice; needs lookup engine. |
| 27 | [✓] Publishing Rep | YELLOW | text. |
| 28 | [✓] Publishing Company | GREEN | recXXX. |
| 29 | [✓] Record Label A&R | YELLOW | text. |
| 30 | [✓] Record Label | GREEN | recXXX. |
| 31 | [✓] PPL | NEUTRAL | |
| 32 | [✓] Type of Label | GREEN | |
| 33 | [✓] Agent | YELLOW | text. |
| 34 | [✓] Agency | GREEN | recXXX. |
| 35-39 | [✓] Featured Artist / Produced / Mixed / Mastered / Website [LU] | RED BROKEN (LOOKUP) | Airtable lookup fields; migration left them empty; no lookup engine in Sheets. |
| 40 | [✓] Combined First Names [USE] | **RED BROKEN** | computes to single first name; group output starves on empty Works With. |
| 41 | [✓] Emails Combined [USE] | **RED BROKEN** | same root cause. |
| 42 | [✓] Company | RED BROKEN | empty; unclear derivation, likely rollup. Open question. |
| 43 | [✓] Credits [Sync] | NEUTRAL/RED | Sync-specific rollup; unused if sync export not in scope. |
| 44 | [✓] Sync Type | NEUTRAL | |
| 45 | [✓] Alt Pitch Lines | NEUTRAL | |
| 46 | [✓] Set Out Reach Date/Time | NEUTRAL | data entry, recipient-local wall-clock. |
| 47 | [✓] Date/Time In LA to send email | **RED BROKEN** | empty even with (46) populated; no startup backfill. THE field YAMM reads. |
| 48 | Songs | RED BROKEN | legacy link rollup; not live. |
| 49 | Creatives Publishing | RED BROKEN | same. |
| 50 | [✓] Pitched Songs | RED BROKEN | legacy; Phase 8 pitch tagger writes to Tags instead. |
| 51 | Admin Due Date | NEUTRAL | |
| 52-58 | [✓] Artists [MGMT] / [Agent MGMT] / [Publishing Rep] / [Record Label A&R] / Creatives [MGMT] / [Publishing Rep] / [Record Label A&R] | RED BROKEN | each is an Airtable linked-record field; declared in `modules/relationships.py:25-102 LINK_TYPES`; live engine reads these but data is empty. |
| 59 | Known | NEUTRAL | |
| 60 | [✓] Date/Time In London to send email | **RED BROKEN** | mirror of col 47; same issue. |
| 61-68 | Brand / Brand Category / Instagram Handle / Outreach Method / Partnership Type / Campaign Notes / Budget Range / One Sheet URL | NEUTRAL | Brand Partnership data entry fields. |
| 69 | Backlinks Cache | GREEN (managed) | auto-added by `relationships.ensure_columns()`. |
| 70 | Grouping Override | GREEN (managed) | manual override, Phase 2D. |
| 71 | Group Leader | GREEN (managed) | manual pin. |
| 72 | Outreach Events | NEUTRAL | |

## Full column inventory - other tabs (summary, not critical to pitch send)

Slice-derived row counts; each section is mapped to the most likely tab name from `CLAUDE.md`. All samples show live data entry; none have the same formula-starvation pattern as Personnel.

| Tab (mapped) | Cols | Sampled rows | State | Notes |
|---|---|---|---|---|
| Songs | 48 | 51 | GREEN / YELLOW | `[✓]` prefixes on 37 cols; data-entry dominant. Rollup fields (Artists Pitched, Labels Pitched, Pubs Pitched) are populated as text, not live links. |
| Brand Partnerships | 12 | 0 | NEUTRAL | empty in slice. |
| Producer Groups (guess) | 4 | 5 | YELLOW | `Songs` column holds pipe-separated recIDs; no rollup. |
| Agencies / Companies (guess) | 6 | 22 | GREEN | data entry. |
| MGMT Companies | 10 | 249 | YELLOW | columns `Mgmt Reps (from MGMT Rep (Personnel))`, `Artists (from MGMT Rep (Personnel))`, `Creatives (from MGMT Rep (Personnel))` look like Airtable lookup text; not live. Usable as reference but stale. |
| Record Labels | 14 | 177 | YELLOW | similar lookup text columns on A&R rollups. |
| ~Label Parents | 3 | 18 | GREEN | |
| Publishing Company | 10 | 124 | YELLOW | same lookup pattern. |
| Agent | 7 | 66 | GREEN / YELLOW | |
| PR Company | 8 | 3 | NEUTRAL | |
| Publicists | 7 | 3 | NEUTRAL | |
| Artists (guess, appears 2x) | 3 | 47 | YELLOW | linked-record rollup text. |
| Cities | 4 | 131 | GREEN | `Timezone` column populated with alias codes that match `TIMEZONE_ALIAS_MAP`. |
| Jobs / Tasks | 11 | 33 | NEUTRAL | |
| Pitches | 4 | 1 | NEUTRAL | |
| Publishing Creatives (guess) | 10 | 124 | YELLOW | duplicate-shape of Publishing Company. |
| Agency Company | 5 | 22 | GREEN | |
| Countries | 7 | 250 | GREEN | stable reference. |
| Studios | 9 | 27 | GREEN | |
| Distribution Log | 6 | 3 | NEUTRAL | |
| Templates | 5 | 2 | NEUTRAL | Subject / Body / Last Used. |
| Playlists | 9 | 0 | NEUTRAL | empty in slice. |
| Invoices | 23 | 107 | GREEN | |
| Views | 3 | 3 | GREEN | ViewSync state. |
| Scout | 21 | 0 | NEUTRAL | empty; matches scout-engine branch being in-progress. |
| Tag Categories | 4 | 16 | GREEN | color config. |
| Pitch Log | 10 | 4 | GREEN | |

## Recommended fix order (ask Celina before executing anything)

1. **Rebuild `Works With`** (Chain 4). Everything downstream unblocks once this column carries `recXXX | recXXX` strings. Requires either re-ingesting the Airtable export (the JSON blobs in `Works with Button` / `Backlink` suggest this data was dropped during migration rather than transformed) or hitting Airtable's API once to pull the linked-record graph. Write once, then delete both JSON-blob columns.
2. **One-shot backfill of `Date/Time In LA / London to send email`** (Chain 3). Can ship independently of fix #1. Mirror `app.py:947-981` over every Personnel row where `Set Out Reach Date/Time` is non-empty. Hook as a startup background thread next to `_recompute_combined_columns_safe` at `app.py:6236`, plus an `/api/personnel/recompute-send-times` endpoint for on-demand.
3. **Re-run Combined First Names / Emails Combined** (Chains 1-2). The startup thread at `app.py:6238` already calls this; once Works With is populated, a single restart or a POST to `/api/personnel/recompute-combined` resolves it.
4. **Confirm cooldown bucketing post-fix** (Chain 5). After groupings exist, verify `_compute_cooldown_conflicts` sees the group as one pitch target instead of N. Low-effort smoke test.
5. **Lookup fields `[LU]` cols 35-39 and `URL (from MGMT Company)` col 26**: decide whether these get resurrected. Each is a pull from a parent table. Probably yes for `URL (from MGMT Company)` (pitch-useful); others are historical.
6. **Rollup text cols on MGMT / Labels / Publishing / Agent tabs**: the "from X" columns are stale Airtable lookup snapshots. Either rebuild as live lookups or mark them deprecated. Not pitch-blocking.

## Open questions for Celina

1. **Format rule**: the task brief says `1=Andrew, 2-3=Alex & Daniel, 4+=all`, but `_format_combined_first_names` in `app.py:3012-3031` uses 1 / 2 / 3 / 4 / 5+ with distinct comma/ampersand rules for each count. Is the task brief a simplification, or does the code need to change?
2. **Works With origin data**: is the source of truth the Airtable export we no longer have, or is there an ability to re-export? The JSON blobs in `Works with Button` / `Backlink` point at Airtable URLs, not peer IDs, so direct recovery from the sheet is not possible.
3. **Smoke test at `app.py:6198`**: it asserts `Works With is not empty` and SystemExits on fail. If Works With truly is empty everywhere, this test should be crashing startup. Either the running service has a handful of manually filled rows, or the test is disabled elsewhere. Confirm service has been running cleanly lately.
4. **Grouping rule coverage**: brief lists MGMT / Label / Publishing / Agency as the grouping boundaries. `modules/relationships.py:25` LINK_TYPES has `works_with` (symmetric) plus directional pairs for manages / represents / ar_rep / publishing_rep / creative_of. Should Combined First Names respect company-type boundaries (e.g. never group a MGMT contact with a Label contact even if Works With links them), or is pure transitive closure correct?
5. **`Grouping Override` column**: currently empty. Is this intended as a per-contact pin (forces grouping = this string) or a per-group pin? Phase 2D comment at `app.py:2357` is ambiguous.
6. **`[LU]` fields 35-39**: Featured Artist, Produced, Mixed, Mastered, Website. Needed for pitching or decorative/historical?
7. **`[✓] Pitched Songs` col 50 vs Pitched tag on col 5 (Tags)**: Phase 8 writes `Pitched: <name>` into Tags. Is col 50 dead and should be archived, or should it mirror the tag?

## Scope note

Audit based on a 13-row Personnel slice Drive returned (full Personnel is 12,779 rows per the prior `AIRTABLE_PARITY_GAP.md`). Empty-percentage columns in the Personnel inventory above may shift on a full re-read. The broken-chain conclusions do NOT shift — they are structural: the computation code paths depend on `Works With` being populated and on a startup backfill for send times, and neither is present.

---

Produced: 2026-04-20. ROLLON ENT internal diagnostic. No code or sheet changes in this session.
