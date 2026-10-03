"""Data sets: the read-only sample data and the user's own data (uploaded on the Settings tab).

The user's files live in data/user/ (git-ignored) with their own rules.yaml and SQLite database,
so their edits and sign-offs never mix with the sample data.
"""
from __future__ import annotations

import csv
import io
import json
import shutil
import tempfile
from datetime import date
from pathlib import Path

import yaml

from .engine import model
from .engine.config import load_config
from .engine.loader import (REQUIRED_COLUMNS, InputError, load_inputs, parse_rows, read_csv, read_csv_text)
from .engine.money import D
from .engine.period import Period

# Upload order on the Settings tab: what to set up first.
FILES = [
    ("dimension_names.csv", "Chart of accounts & dimensions",
     "Accounts, departments, locations, items, projects, customers and vendor names. One row per item: "
     "dim_type (account, dept, location, item, project, customer or vendor), id, name."),
    ("budget.csv", "Budget",
     "Full-year budget by vendor + account: monthly amounts jan … dec and the annual total. Leave vendor_id "
     "blank for budget that has no vendor."),
    ("roster.csv", "Vendor roster",
     "The vendor + account lines to accrue each month, with owner and any prior-year liability remaining."),
    ("gl_detail.csv", "GL detail (ERP export)",
     "Year-to-date GL lines: AP bills (APJ) and unbilled receipts (UNB) with posting date, service dates and memo. "
     "Other journals are excluded automatically."),
    ("je_dims.csv", "JE dimensions",
     "Dept, location and item to use on the JE for each vendor + account (source: prior_je or latest_bill)."),
    ("legal_rows.csv", "Legal estimates", "One row per law firm with this month's estimate (editable later on the Legal tab)."),
    ("capex_tracker.csv", "Capex project tracker", "Project lines with cost, % complete (0-100) and invoiced to date."),
    ("prior_je.csv", "Last month's accrual JE",
     "Last month's booked accrual lines. Only needed for your first month: once you sign off a month here, "
     "the next month takes it from the app's history automatically."),
    ("mom_gl.csv", "Month-over-month GL",
     "Per vendor + account: last month's and this month's bills, accrual booked and reversals. Only needed for "
     "your first month: after a sign-off here it is built from your GL detail and the saved JE."),
]
FILE_NAMES = [f[0] for f in FILES]

# Vendor-specific sections are cleared when a new data set starts from the sample rules.
_VENDOR_SPECIFIC = {
    ("scope", "removed_documents"), ("scope", "corporate_card_vendor_ids"), ("legal", "vendor_ids"),
    ("roster", "removed_lines"), ("budget", "overrides"), ("budget", "excluded_lines"), ("je", "dept_splits"),
}


class DatasetError(ValueError):
    """A settings / upload request was rejected."""


def default_period(today: date | None = None) -> str:
    return Period.parse((today or date.today()).strftime("%Y-%m")).prev().key


def starter_rules(sample_rules: Path, period: str) -> dict:
    """The sample rules with every vendor-specific exception removed."""
    rules = yaml.safe_load(Path(sample_rules).read_text(encoding="utf-8")) or {}
    for section, key in _VENDOR_SPECIFIC:
        if isinstance(rules.get(section), dict):
            rules[section][key] = []
    for key in ("service_rules", "prior_year_liability", "accrual_rules"):
        rules[key] = []
    rules["rollups"] = {"account": [], "vendor": []}
    standing = rules.get("standing") or {}
    standing.update({"baseline_month": None, "rules": [], "carried_manual_adds": []})
    rules["standing"] = standing
    rules["company"] = "My Company"
    rules["current_period"] = period
    return rules


def ensure_user_folder(folder: Path, sample_rules: Path) -> None:
    """Create an empty, runnable data set: header-only CSVs, zero metas, starter rules."""
    folder.mkdir(parents=True, exist_ok=True)
    for name, cols in REQUIRED_COLUMNS.items():
        p = folder / name
        if not p.exists():
            p.write_text(",".join(cols) + "\n", encoding="utf-8")
    period = default_period()
    if not (folder / "capex_meta.json").exists():
        write_json(folder / "capex_meta.json", {"unallocated_gl_total": "0", "needs_attention_count": 0,
                                                "needs_attention_total": "0"})
    if not (folder / "prior_je_meta.json").exists():
        write_json(folder / "prior_je_meta.json", {"period": Period.parse(period).prev().key, "reversed_total": "0"})
    if not (folder / "rules.yaml").exists():
        write_rules(folder / "rules.yaml", starter_rules(sample_rules, period))


def reset_user_folder(folder: Path, sample_rules: Path) -> None:
    for name in [*REQUIRED_COLUMNS, "capex_meta.json", "prior_je_meta.json", "rules.yaml", "workbook.db"]:
        (folder / name).unlink(missing_ok=True)
    ensure_user_folder(folder, sample_rules)


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_rules(path: Path, rules: dict) -> None:
    header = "# Accrual rules for this data set. Edit on the Settings tab or here.\n"
    path.write_text(header + yaml.safe_dump(rules, sort_keys=False, allow_unicode=True), encoding="utf-8")


def template_csv(name: str) -> str:
    if name not in REQUIRED_COLUMNS:
        raise DatasetError(f"Unknown file {name!r}.")
    return ",".join(REQUIRED_COLUMNS[name]) + "\n"


def decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise DatasetError("Could not read the file as text. Save it as CSV (UTF-8) and try again.")


def _check_runs(folder: Path, period: str) -> None:
    """Load the whole data set and run the period, so a bad upload never breaks the app."""
    cfg = load_config(folder / "rules.yaml")
    model.run(period, load_inputs(folder), cfg)


def validate_and_save(folder: Path, name: str, raw: bytes) -> int:
    """Check an uploaded CSV (columns, every row, and a full run) and save it. Returns rows loaded."""
    if name not in REQUIRED_COLUMNS:
        raise DatasetError(f"Unknown file {name!r}.")
    text = decode(raw)
    try:
        records = read_csv_text(name, text)
    except InputError as exc:
        raise DatasetError(f"{exc}. Expected columns: {', '.join(REQUIRED_COLUMNS[name])}.") from exc
    except Exception as exc:  # noqa: BLE001 - pandas parser errors
        raise DatasetError(f"{name}: could not read the CSV ({exc}).") from exc
    try:
        parse_rows(name, records)
    except InputError as exc:
        raise DatasetError(str(exc)) from exc
    cols = REQUIRED_COLUMNS[name]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in records:
        w.writerow({c: r.get(c, "") for c in cols})
    period = str(load_config(folder / "rules.yaml").get("current_period") or default_period())
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        for f in folder.iterdir():
            if f.is_file() and f.suffix in (".csv", ".json", ".yaml"):
                shutil.copy(f, tmpdir / f.name)
        (tmpdir / name).write_text(buf.getvalue(), encoding="utf-8")
        try:
            _check_runs(tmpdir, period)
        except Exception as exc:  # noqa: BLE001
            raise DatasetError(f"{name} loaded, but the workbook could not run with it: {exc}") from exc
    (folder / name).write_text(buf.getvalue(), encoding="utf-8")
    return len(records)


def file_status(folder: Path) -> list[dict]:
    out = []
    for name, label, description in FILES:
        path = folder / name
        try:
            rows = len(read_csv(folder, name))
            problem = ""
        except InputError as exc:
            rows, problem = 0, str(exc)
        out.append({"name": name, "label": label, "description": description, "columns": REQUIRED_COLUMNS[name],
                    "rows": rows, "problem": problem,
                    "updated": date.fromtimestamp(path.stat().st_mtime).isoformat() if path.exists() else None})
    return out


def cross_checks(inp, cfg: dict, current_period: str) -> list[dict]:
    """Checks across files that a single-file upload check cannot see.

    level: "error" (numbers will be wrong), "warning" (likely a mistake), "info" (worth knowing).
    """
    from .engine.scope import account_kind
    from .engine.service import map_key

    out: list[dict] = []

    def add(level, files, message, examples, hint=""):
        if examples:
            ex = sorted({str(e) for e in examples})
            out.append({"level": level, "files": files, "message": message, "count": len(ex), "examples": ex[:6],
                        "hint": hint})

    names = inp.dim_names
    if not names.get("account"):
        if inp.roster or inp.budget or inp.gl:
            out.append({"level": "warning", "files": "dimension_names.csv", "count": 0, "examples": [],
                        "message": "No chart of accounts uploaded yet, so account names and checks are missing.",
                        "hint": "Upload dimension_names.csv with dim_type = account rows."})
    else:
        coa = set(names["account"])
        add("error", "roster.csv", "Roster accounts that are not in the chart of accounts",
            [r["gl_account"] for r in inp.roster if str(r["gl_account"]) not in coa],
            "Add the account to dimension_names.csv or fix the roster.")
        add("error", "budget.csv", "Budget accounts that are not in the chart of accounts",
            [b["gl_account"] for b in inp.budget if str(b["gl_account"]) not in coa])
        add("warning", "gl_detail.csv", "GL accounts that are not in the chart of accounts",
            [g["gl_account"] for g in inp.gl if str(g["gl_account"]) not in coa])

    seen, dups = set(), []
    for r in inp.roster:
        k = (r["vendor_id"], r["gl_account"])
        if k in seen:
            dups.append(f"{k[0]} | {k[1]}")
        seen.add(k)
    add("error", "roster.csv", "Duplicate roster lines (same vendor + account); spend would be counted twice", dups)

    add("error", "roster.csv", "Roster lines on accounts outside the accrual scope; they can never receive spend",
        [f"{r['vendor_id']} | {r['gl_account']}" for r in inp.roster if account_kind(r["gl_account"], cfg) is None],
        "Fix the account, or widen the account ranges in rules.yaml.")

    budget_keys = {map_key(b["vendor_id"], b["gl_account"], cfg) for b in inp.budget if b["vendor_id"]}
    add("warning", "roster.csv + budget.csv",
        "Roster lines with no budget line and no spread YTD; they will accrue $0 (plus any prior-year liability)",
        [f"{r['vendor_id']} | {r['gl_account']}" for r in inp.roster
         if (r["vendor_id"], r["gl_account"]) not in budget_keys and not r["budget_ytd_spread"]])
    roster_keys = {(r["vendor_id"], r["gl_account"]) for r in inp.roster}
    add("info", "budget.csv", "Budget lines for a vendor + account that is not on the roster (not accrued)",
        [f"{k[0]} | {k[1]}" for k in budget_keys if k not in roster_keys])

    for kind, label in (("dept", "Departments"), ("location", "Locations")):
        if names.get(kind):
            known = set(names[kind])
            add("warning", "je_dims.csv", f"{label} in JE dimensions that are not in the chart",
                [d[kind] for d in inp.je_dims if d[kind] and d[kind] not in known])
            add("warning", "legal_rows.csv", f"{label} on legal rows that are not in the chart",
                [r[kind] for r in inp.legal_rows if r[kind] and r[kind] not in known])

    try:
        end = Period.parse(current_period).end
        add("info", "gl_detail.csv", f"GL lines posted after {current_period}; excluded until that month",
            [g["document_id"] or g["row_id"] for g in inp.gl if g["posting_date"] > end])
    except ValueError:
        pass
    order = {"error": 0, "warning": 1, "info": 2}
    return sorted(out, key=lambda c: order[c["level"]])


def read_rules(folder: Path) -> dict:
    return yaml.safe_load((folder / "rules.yaml").read_text(encoding="utf-8")) or {}


def save_general(folder: Path, company: str, current_period: str) -> None:
    company = str(company or "").strip()
    if not company:
        raise DatasetError("Company name is required.")
    try:
        period = Period.parse(current_period).key
    except ValueError as exc:
        raise DatasetError(str(exc)) from exc
    rules = read_rules(folder)
    rules["company"], rules["current_period"] = company, period
    write_rules(folder / "rules.yaml", rules)


def save_inputs_meta(folder: Path, values: dict) -> None:
    try:
        capex = {"unallocated_gl_total": str(D(values.get("unallocated_gl_total") or 0)),
                 "needs_attention_count": int(values.get("needs_attention_count") or 0),
                 "needs_attention_total": str(D(values.get("needs_attention_total") or 0))}
        prior = {"period": Period.parse(values.get("prior_period") or "").key,
                 "reversed_total": str(D(values.get("reversed_total") or 0))}
    except (ValueError, TypeError) as exc:
        raise DatasetError(f"Check the numbers and month: {exc}") from exc
    write_json(folder / "capex_meta.json", capex)
    write_json(folder / "prior_je_meta.json", prior)


def save_rules_upload(folder: Path, raw: bytes) -> None:
    text = decode(raw)
    try:
        rules = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise DatasetError(f"rules.yaml is not valid YAML: {exc}") from exc
    if not isinstance(rules, dict):
        raise DatasetError("rules.yaml must be a set of settings (key: value).")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        for f in folder.iterdir():
            if f.is_file() and f.suffix in (".csv", ".json"):
                shutil.copy(f, tmpdir / f.name)
        (tmpdir / "rules.yaml").write_text(text, encoding="utf-8")
        try:
            _check_runs(tmpdir, str(rules.get("current_period") or default_period()))
        except Exception as exc:  # noqa: BLE001
            raise DatasetError(f"The workbook could not run with these rules: {exc}") from exc
    (folder / "rules.yaml").write_text(text, encoding="utf-8")
