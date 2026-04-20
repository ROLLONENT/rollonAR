# ROLLON AR v37.3 — Release Summary

Scope: Mail Merge tonight. Filter parity with Airtable, Combined First
Names / Emails Combined writeback to the Sheet, Mail Merge export with
CSV fallback.

## 1. Filter system parity

Every column is filterable through the universal panel, every operator
is type-aware, and multi-value cells match correctly. Highlights:

- **Operators per column type**:
  - Text: `contains`, `does_not_contain`, `is`, `is_not`, `is_empty`,
    `is_not_empty`, `starts_with`, `ends_with`.
  - Multi-value (Field, Genre, Tags, Role): `has_any_of`, `has_all_of`,
    `has_none_of`, `is_empty`, `is_not_empty`.
  - Single-select (Country, Status, Warmth): `is`, `is_not`,
    `is_any_of`, `is_none_of`.
  - Number: `equals`, `not_equals`, `greater_than`, `less_than`, `gte`,
    `lte`, `is_empty`.
  - Date: `is`, `before`, `after`, `between`, `within_last`,
    `more_than_n_days_ago`, `is_empty`.
  - Linked record (Works With, Manager, A&R Rep): `contains_any`,
    `contains_all`, `has_none_of`, `has_any_links`, `has_no_links`.

- **Multi-value matching**: cells like
  `"Record A&R | Writer MGMT | Producer"` are split on `[|,;]` with
  optional whitespace, lowercased, and matched per piece for
  `has_any_of` / `has_all_of` / `has_none_of`.

- **Case insensitive everywhere** (filter values, cell values, column
  names).

- **Column aliases** (`resolve_filter_col`):
  - `Country` -> `Countries`
  - `Manager` -> `MGMT Rep`
  - `A&R Rep` -> `Record Label A&R`
  - `First Name` -> `Combined First Names`
  - `Email Address` -> `Email`
  - `Role` -> `Field`

- **Value aliases** for countries so `UK` -> `United Kingdom`,
  `US`/`USA` -> `United States`, `GB`/`ENG` -> same.

- **AND / OR combinator** at the request level
  (`filter_mode=or`) still honoured by the rewritten `apply_filter`.

- **Universal autocomplete**: `/api/autocomplete/<table>/<field>` now
  resolves linked record IDs (so Countries/Field/Tags dropdowns show
  real values) and splits cells on `[|,;]`.

## 2. Startup smoke tests (fail-loud)

`run_filter_smoke_tests()` runs before the Flask server binds:

| Test                                                                                               | Expected | Actual (2026-04-20) |
|----------------------------------------------------------------------------------------------------|----------|---------------------|
| `Country = UK`                                                                                     | > 0      | 1172                |
| `Country has any of (UK, US)`                                                                      | > 0      | 3437                |
| `Field has any of (Record A&R)`                                                                    | > 0      | 482                 |
| `Country = UK AND Field has any of (MGMT, Publishing A&R, Record A&R, Writer MGMT)`                | > 0      | 424                 |
| `Works With is not empty`                                                                          | > 0      | 699                 |

Any failure raises `SystemExit(2)` so `Deploy.command` aborts loudly
instead of serving a broken filter panel.

## 3. Combined First Names [USE] / Emails Combined [USE] writeback

`POST /api/personnel/recompute-combined` iterates the Personnel sheet
and writes back:

- `Combined First Names [USE]`: `Luke`, `Luke & Josie`,
  `Luke, Josie & Emily`, `Luke, Josie, Emily & Paul`, or
  `Luke, Josie, Emily, Paul & 2 others` depending on group size.
- `Emails Combined [USE]`: comma-joined addresses for every member.

Own first name / own email always serve as fallback when the contact
has no Works With links, so neither column is ever blank.

The recompute runs automatically on:
- app startup (background thread, does not block smoke tests);
- every `/api/relationships/works-with/add` and `/remove` (scoped to
  the transitive group of the touched contacts);
- manual trigger via the new **Recompute Combined** button in Settings.

## 4. Mail Merge export

The `Export to Mail Merge` modal now exposes two primary buttons:

- **Create Google Sheet** — drops a spreadsheet into the
  `ROLLON AR Pitches` Drive folder with tabs `Sheet1` +
  `Mail Merge Logs` ready for MMwA.
- **Download CSV** — browser download at
  `PitchName_YYYY-MM-DD.csv` for use without Drive.

Both paths share `_build_mm_export_rows`, so they honour the same
grouping, Don't Mass Pitch filter, timezone chain, and column layout:

- Output columns = the Directory's visible columns in order, then any
  of the 5 required columns that aren't already present (First Name,
  Email Address, Scheduled Date, File Attachments, Mail Merge Status).
- `First Name` is the Combined First Names [USE] cell for the first
  group member, `Email Address` is the Emails Combined [USE] cell.
- `Scheduled Date` is produced by the V36 Phase 4 timezone chain
  (recipient-local stagger or fixed timezone), formatted
  `DD/MM/YYYY HH:MM:SS` in `America/Los_Angeles`.

## 5. 12 verification tests

| #  | Query                                                                 | Expected             | Observed                                                     |
|----|-----------------------------------------------------------------------|----------------------|--------------------------------------------------------------|
| 1  | UK + MGMT / Publishing A&R / Record A&R / Writer MGMT                 | > 0                  | 424                                                          |
| 2  | US + Field = Record A&R                                               | > 0                  | 257                                                          |
| 3  | Works With is not empty                                               | > 0, includes LJJ    | 699 (Luke Williams row 72, Josie Smith 96, Josef Martin 122) |
| 4  | Tags has any of Warm                                                  | no error             | 459                                                          |
| 5  | Clear all filters                                                     | ~5305 real contacts  | 5307                                                         |
| 6  | Luke Williams Combined First Names                                    | 4+ format            | `Luke, Paul, Josie, Emily & 2 others`                        |
| 7  | Josie Smith Combined First Names                                      | `Josie & Luke`       | `Josie & Luke`                                               |
| 8  | Justin Bishop Combined First Names                                    | `Justin`             | `Justin`                                                     |
| 9  | CSV export UK + MGMT, grouping + DMP filter                           | CSV with groups      | 149 rows, 75 DMP skipped, `V37_3_Test_UK_MGMT_2026-04-20.csv`|
| 10 | Google Sheet export same filter                                       | URL in Pitches folder| `https://docs.google.com/spreadsheets/d/1bFaB56Tgu6hUITL...` |
| 11 | First Name = greeting, Email Address = combined, Scheduled Date set   | all filled           | `Jon & Marc` / `jb@insanity.com, ms@insanity.com` / `21/04/2026 02:00:00` |
| 12 | Output columns match Directory visible + appended required            | visible then 5 req   | `Name, Field, Tags, City, Email, Record Label, MGMT Company, First Name, Email Address, Scheduled Date, File Attachments, Mail Merge Status` |
