# Month-End Accrual Workbook

A month-end OpEx accrual tool: a tested Python calculation engine plus a small local web app. It estimates the expenses a company has incurred but not yet been billed for, builds the journal entry that books them, and walks a reviewer through checks and sign-off.

This is a portfolio rebuild of an internal accounting tool. **Everything runs on invented sample data for a fictional company, "Sample Co."** No real company, vendor, person or amount appears in the repo.

## What it does

For a period (e.g. September 2026) the workbook:

1. Reads the GL detail, the vendor roster, the budget, law-firm estimates and the capex project tracker (CSV files exported from "the ERP").
2. Calculates three accrual components: **Vendor OpEx + Legal + Capex Projects = Total Accrual**.
3. Builds a balanced journal entry (dated month-end, auto-reversing on the 1st), checks that it ties to every tab, and exports an ERP upload CSV and an Excel backup workbook.
4. Supports review: overrides with explanations, manual adds, standing rules with flags, a month-over-month review with plain-English explanations, a needs-attention log, and a sign-off that locks the month and keeps a read-only snapshot.

All accounting rules live in Python (`accrual_workbook/engine/`) and are covered by tests. The browser only displays what the API returns. Vendor-specific exceptions are data in `config/rules.yaml`, never vendor names in code.

## The accounting rules in plain English

**Scope.** Only AP bills and unbilled receipts count, on configured expense, prepaid and capex accounts, posted on or before month-end. Generic journal entries, corporate-card lines, blank-vendor lines, commission accounts and legal bills are excluded. Every excluded row is counted with its reason.

**Service month.** Each bill is placed in the month the service happened: the bill's service-period field if present (Confirmed), else a date or month in the memo, else the posting month (Estimated). Config can force a service month for a vendor and posting window.

**Vendor OpEx formula**, one row per vendor + account on the roster:

- *Budget YTD* = annual budget × months elapsed ÷ 12, rounded to cents. (A regression test makes sure the annual budget is never compared with year-to-date spend.) No budget line → the roster's spread YTD.
- *Spend YTD* = bills by service month from January through the cutoff month + the current-year share of a prepaid (split by days at 1/1 and 12/31, only when the vendor has exactly one roster line) + bills already received for service after the cutoff. Prior-year service, including the prior-year share of a prepaid, and the next-year share of prepaids are excluded. Spend is matched on vendor **and** account.
- *Prior-year liability remaining* = opening balance − prior-year-service bills paid this year (never below $0), or the roster value.
- *Calculated accrual* = MAX(Budget YTD + Liability Remaining − Spend YTD, $0).
- Rollups move one account's or vendor's spend and budget onto another line. Accrual rules can force a line to $0 with a label.

**Standing rules** are reviewed once in a baseline month, then re-applied automatically: `zero` (billed in full / via receipts / not used), `unbilled` (rate × months since the vendor's paid-through date, monthly or half-month), `avg_less_billed`, `rate_unless_billed` and `budget`. A vendor billed through month-end accrues $0, except for any unpaid prior-year liability. The paid-through date only uses bills with a real service date (service period or memo); a bill dated only by its posting month is ignored, because an arrears bill posted this month usually covers last month. Risky changes are flagged for a human to confirm: budget or spend moving past thresholds, a new bill on a $0 vendor, a paid-through rule removing a $10K+ accrual, a billed-in-full term ending.

**Overrides and manual adds.** A reviewer can override any line (amount ≥ 0, explanation required, logged with who and when) or add a vendor that is not on the roster. These always win.

**Legal.** Law-firm estimates are editable per firm and can be split across several GL lines; each line is its own JE debit.

**Capex Projects.** Line accrual = cost × % complete − invoiced to date, netted by project + vendor and floored at $0. The figure is marked Not final while capex GL is unallocated.

**Journal entry.** Every debit gets a matching credit to Accrued Expenses with identical dimensions. Dimensions come from last month's JE, else the vendor's latest bill; missing ones are flagged. Optional department splits put any rounding cent on the first part. Four checks must pass: debits = credits, and each section ties to its tab. A failed check is shown in the app and makes the CLI exit non-zero.

**Review and sign-off.** The month-over-month review classifies each line's driver and writes a one-sentence explanation; swings of ≥ $10K and ≥ 25% must be reviewed. Sign-off is blocked until there are no open needs-attention items, all large swings are reviewed, all three components are complete, all flagged standing rules are confirmed and the JE passes all four checks. Signing off saves a snapshot and locks the month.

## Run it

Python 3.11+.

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt

python scripts/make_sample_data.py                 # writes data/sample/ (fixed seed)
python -m accrual_workbook run --period 2026-09    # headless: writes out/ (JE CSV, backup xlsx, summary JSON)
python -m accrual_workbook serve                   # web app at http://localhost:5000
```

Edits are saved in `data/workbook.db` (SQLite). Delete it to start fresh. The user name comes from `ACCRUAL_USER` or `user:` in `config/rules.yaml`.

## Using your own data

Open the **Settings** tab and switch from *Sample data* to *My data*. You get an empty data set; upload your CSV files in the order shown (chart of accounts and dimensions, budget, vendor roster, GL detail, …). Each row has a blank template and a filled-in example to download.

Every upload is checked before it is saved: missing columns are named, and a bad date or number is reported with its spreadsheet row number. The whole workbook is then run with the new file, so a bad upload can never break the app. Headers such as "Vendor ID" are accepted. Company name, the open month and a few one-number inputs are edited on screen; the advanced `rules.yaml` can be downloaded, edited and uploaded back.

Your files, rules and database live in `data/user/`, which is git-ignored, so they are never committed. Edits and sign-offs on your data are kept separate from the sample. To run headless on your data: `python -m accrual_workbook run --period 2026-09 --dataset user`.

A **Data checks across files** panel compares the files with each other: roster or budget accounts missing from the chart of accounts, duplicate roster lines, roster lines outside the accrual scope, roster lines with no budget, and unknown departments or locations. Errors and warnings show as a count on the Settings tab.

### Month-end, month after month

1. Upload the month's files and review the tabs.
2. Sign off on the Summary tab. This locks the month and saves the JE and backup.
3. Click **Start {next month}** on the Summary tab. The open month moves forward; standing rules keep applying, with the first closed month becoming their baseline if none was set; and this month's manual adds are carried forward, flagged if the vendor sends a bill. Overrides are current-month only.
4. Upload the new month's GL detail, legal estimates and capex tracker, and repeat.

Last month's JE, its dimensions and the month-over-month figures only need to be uploaded for your first month. After a sign-off in the app, the next month builds them from the saved JE and the GL detail. The MoM tab shows which source is in use.

## Starting the app without the terminal (Windows)

Double-click **`Start Accrual Workbook.bat`**. The first time, it sets up the Python packages (Python 3.11+ must be installed). It then opens http://localhost:5000 in your browser. Keep its window open while you work; closing it stops the app.

## Tests

```bash
python -m pytest
```

Unit tests use small hand-computed fixtures, one rule per test; an end-to-end test runs the generated sample data and asserts the period totals; API tests drive every edit and the sign-off through Flask's test client.

## Project structure

```
accrual_workbook/
  engine/          loader, scope, service months, Vendor OpEx, standing rules, legal, capex,
                   journal, MoM, over-budget, backup workbook, model (runs a period)
  store.py         SQLite: overrides, manual adds, legal edits, reviews, needs-attention, sign-offs
  api.py           JSON endpoints (Flask)
  web/             index.html, app.js, styles.css (no build step, no framework)
  cli.py           run / serve
config/rules.yaml  scope, rollups, service rules, standing rules, JE settings
scripts/make_sample_data.py   invented sample data for period 2026-09
data/sample/       generated CSVs
tests/
```

## Sample data

`scripts/make_sample_data.py` generates about 45 invented vendors, nine months of GL and every input file, with deliberately seeded cases so each rule above is exercised (annual-vs-YTD, two lines for one vendor, a prepaid across year-end, rollups, every standing-rule type and flag, a removed document, missing dimensions, an over-invoiced capex group, and more). Last month's booked JE is produced by running the engine on August. All names are made up.

## Left out compared with the original

- **AI reading of legal backup.** Not built. How it would work: a reviewer attaches a firm's invoice or WIP estimate, an AI model reads it and proposes the amount, matter and customer for that Legal row, and the reviewer accepts or edits the proposal before saving. It would never save on its own. The entry point is a clearly marked stub, `engine/legal.py: read_backup_document`.
- **Multi-user permissions.** Not built. This rebuild is single-user and local; the user name comes from config.

---

Built with Claude Code; accounting rules and review by Jorge Dubon.
