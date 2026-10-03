"""Read and validate the input CSVs into plain Python rows (Decimal money, date objects)."""
from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .money import D, D_or_none

MONTH_COLS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]

REQUIRED_COLUMNS: dict[str, list[str]] = {
    "gl_detail.csv": [
        "entry_date", "gl_account", "gl_account_name", "vendor_id", "vendor_name",
        "department_name", "location_name", "signed_amount", "gl_journal_id",
        "journal_posting_date", "service_period_from", "service_period_to", "service_month",
        "service_date_source", "description", "document_id",
    ],
    "roster.csv": [
        "vendor_name", "vendor_id", "gl_account", "gl_account_name", "vendor_type",
        "budget_ytd_spread", "gl_actual_ytd", "liability_prior_year_remaining", "owner",
    ],
    "budget.csv": ["vendor_id", "vendor_name", "gl_account", "gl_account_name", *MONTH_COLS, "annual"],
    "legal_rows.csv": ["vendor", "vendor_id", "amount", "customer", "project", "dept", "location", "item"],
    "capex_tracker.csv": [
        "deal", "project_id", "location_id", "vendor", "area", "budgeted_cost", "cost",
        "work_request_date", "pct_complete", "fully_complete", "placed_in_service",
        "invoiced_to_date", "vendor_id", "account_id", "dept_id",
    ],
    "prior_je.csv": ["je_id", "acct", "vendor_id", "vendor", "dept", "amount"],
    "dimension_names.csv": ["dim_type", "id", "name"],
    "je_dims.csv": ["vendor_id", "gl_account", "dept", "location", "item", "source"],
    "mom_gl.csv": [
        "vendor_id", "vendor", "gl_account", "prior_bills", "prior_accrual", "prior_reversal",
        "current_bills", "current_reversal", "other",
    ],
}

REQUIRED_META = {
    "capex_meta.json": ["unallocated_gl_total", "needs_attention_count", "needs_attention_total"],
    "prior_je_meta.json": ["period", "reversed_total"],
}


class InputError(ValueError):
    """An input file is missing or malformed."""


@dataclass
class Inputs:
    gl: list[dict] = field(default_factory=list)
    roster: list[dict] = field(default_factory=list)
    budget: list[dict] = field(default_factory=list)
    legal_rows: list[dict] = field(default_factory=list)
    capex: list[dict] = field(default_factory=list)
    capex_meta: dict = field(default_factory=dict)
    prior_je: list[dict] = field(default_factory=list)
    prior_je_meta: dict = field(default_factory=dict)
    dim_names: dict = field(default_factory=dict)  # {dim_type: {id: name}}
    je_dims: list[dict] = field(default_factory=list)
    mom_gl: list[dict] = field(default_factory=list)


def parse_date(value) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise InputError(f"bad date {value!r} (use YYYY-MM-DD or MM/DD/YYYY)")


def _int(value) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError as exc:
        raise InputError(f"bad number {value!r}") from exc


def _req_int(value, what: str) -> int:
    out = _int(value)
    if out is None:
        raise InputError(f"{what} is blank")
    return out


def _bool(value) -> bool:
    return str(value or "").strip().lower() in {"y", "yes", "true", "1", "x"}


def _s(r: dict, key: str) -> str:
    return str(r.get(key, "") or "").strip()


def normalize_header(name: str) -> str:
    """'Vendor ID' / 'vendor-id' / ' VENDOR_ID ' -> 'vendor_id'. Lets Excel-style headers through."""
    return re.sub(r"[\s\-]+", "_", str(name).strip().lstrip("﻿").lower())


def check_columns(name: str, columns) -> None:
    missing = [c for c in REQUIRED_COLUMNS[name] if c not in set(columns)]
    if missing:
        raise InputError(f"{name}: missing columns: {', '.join(missing)}")


def frame_records(name: str, source) -> list[dict]:
    """Read a CSV (path or text) into records with normalized headers, checking required columns."""
    frame = pd.read_csv(source, dtype=str, keep_default_na=False)
    frame.columns = [normalize_header(c) for c in frame.columns]
    check_columns(name, frame.columns)
    return frame.to_dict(orient="records")


def read_csv(folder: Path, name: str) -> list[dict]:
    path = Path(folder) / name
    if not path.exists():
        raise InputError(f"{name}: file not found in {folder}")
    return frame_records(name, path)


def read_csv_text(name: str, text: str) -> list[dict]:
    return frame_records(name, io.StringIO(text))


def read_meta(folder: Path, name: str) -> dict:
    path = Path(folder) / name
    if not path.exists():
        raise InputError(f"{name}: file not found in {folder}")
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED_META[name] if k not in data]
    if missing:
        raise InputError(f"{name}: missing keys: {', '.join(missing)}")
    return data


# ---------- row parsers (also used by tests to build fixtures) ----------

def parse_gl_row(r: dict, idx: int = 0) -> dict:
    posting = parse_date(r.get("journal_posting_date"))
    if posting is None:
        raise InputError("journal_posting_date is blank")
    return {
        "row_id": idx,
        "entry_date": parse_date(r.get("entry_date")) or posting,
        "gl_account": _req_int(r.get("gl_account"), "gl_account"),
        "gl_account_name": _s(r, "gl_account_name"),
        "vendor_id": _s(r, "vendor_id"),
        "vendor_name": _s(r, "vendor_name"),
        "department_name": _s(r, "department_name"),
        "location_name": _s(r, "location_name"),
        "amount": D(r.get("signed_amount")),
        "journal": _s(r, "gl_journal_id"),
        "posting_date": posting,
        "service_from": parse_date(r.get("service_period_from")),
        "service_to": parse_date(r.get("service_period_to")),
        "service_month_field": _s(r, "service_month"),
        "description": _s(r, "description"),
        "document_id": _s(r, "document_id"),
    }


def parse_roster_row(r: dict, idx: int = 0) -> dict:
    vid = _s(r, "vendor_id")
    if not vid:
        raise InputError("vendor_id is blank")
    return {
        "vendor_name": _s(r, "vendor_name"),
        "vendor_id": vid,
        "gl_account": _req_int(r.get("gl_account"), "gl_account"),
        "gl_account_name": _s(r, "gl_account_name"),
        "vendor_type": _s(r, "vendor_type"),
        "budget_ytd_spread": D(r.get("budget_ytd_spread")),
        "gl_actual_ytd": D(r.get("gl_actual_ytd")),
        "liability_prior_year_remaining": D(r.get("liability_prior_year_remaining")),
        "owner": _s(r, "owner"),
    }


def parse_budget_row(r: dict, idx: int = 0) -> dict:
    monthly = [D(r.get(m)) for m in MONTH_COLS]
    annual = D_or_none(r.get("annual"))
    return {
        "vendor_id": _s(r, "vendor_id"),
        "vendor_name": _s(r, "vendor_name"),
        "gl_account": _req_int(r.get("gl_account"), "gl_account"),
        "gl_account_name": _s(r, "gl_account_name"),
        "monthly": monthly,
        "annual": annual if annual is not None else sum(monthly),
    }


def parse_capex_row(r: dict, idx: int = 0) -> dict:
    return {
        "deal": _s(r, "deal"),
        "project_id": _s(r, "project_id"),
        "location_id": _s(r, "location_id"),
        "vendor": _s(r, "vendor"),
        "vendor_id": _s(r, "vendor_id"),
        "area": _s(r, "area"),
        "budgeted_cost": D_or_none(r.get("budgeted_cost")),
        "cost": D_or_none(r.get("cost")),
        "work_request_date": parse_date(r.get("work_request_date")),
        "pct_complete": D_or_none(r.get("pct_complete")),  # percent, 0-100
        "fully_complete": _bool(r.get("fully_complete")),
        "placed_in_service": _bool(r.get("placed_in_service")),
        "invoiced_to_date": D(r.get("invoiced_to_date")),
        "account_id": _int(r.get("account_id")),
        "dept_id": _s(r, "dept_id"),
    }


def parse_legal_row(r: dict, idx: int = 0) -> dict:
    return {"vendor": _s(r, "vendor"), "vendor_id": _s(r, "vendor_id"), "amount": D(r.get("amount")),
            "customer": _s(r, "customer"), "project": _s(r, "project"), "dept": _s(r, "dept"),
            "location": _s(r, "location"), "item": _s(r, "item")}


def parse_prior_je_row(r: dict, idx: int = 0) -> dict:
    return {"je_id": _s(r, "je_id"), "acct": _req_int(r.get("acct"), "acct"), "vendor_id": _s(r, "vendor_id"),
            "vendor": _s(r, "vendor"), "dept": _s(r, "dept"), "amount": D(r.get("amount"))}


def parse_dim_row(r: dict, idx: int = 0) -> dict:
    if not _s(r, "dim_type") or not _s(r, "id"):
        raise InputError("dim_type and id are required")
    return {"dim_type": _s(r, "dim_type").lower(), "id": _s(r, "id"), "name": _s(r, "name")}


def parse_je_dims_row(r: dict, idx: int = 0) -> dict:
    return {"vendor_id": _s(r, "vendor_id"), "gl_account": _req_int(r.get("gl_account"), "gl_account"),
            "dept": _s(r, "dept"), "location": _s(r, "location"), "item": _s(r, "item"),
            "source": _s(r, "source") or "latest_bill"}


def parse_mom_row(r: dict, idx: int = 0) -> dict:
    return {"vendor_id": _s(r, "vendor_id"), "vendor": _s(r, "vendor"),
            "gl_account": _req_int(r.get("gl_account"), "gl_account"),
            **{k: D(r.get(k)) for k in ("prior_bills", "prior_accrual", "prior_reversal",
                                       "current_bills", "current_reversal", "other")}}


ROW_PARSERS = {
    "gl_detail.csv": parse_gl_row, "roster.csv": parse_roster_row, "budget.csv": parse_budget_row,
    "legal_rows.csv": parse_legal_row, "capex_tracker.csv": parse_capex_row, "prior_je.csv": parse_prior_je_row,
    "dimension_names.csv": parse_dim_row, "je_dims.csv": parse_je_dims_row, "mom_gl.csv": parse_mom_row,
}


def parse_rows(name: str, records: list[dict], max_errors: int = 10) -> list[dict]:
    """Parse every row; collect errors with spreadsheet row numbers (header is row 1)."""
    parser = ROW_PARSERS[name]
    out, errors = [], []
    for i, r in enumerate(records):
        try:
            out.append(parser(r, i))
        except (InputError, ValueError) as exc:
            errors.append(f"row {i + 2}: {exc}")
    if errors:
        more = f" (+{len(errors) - max_errors} more)" if len(errors) > max_errors else ""
        raise InputError(f"{name}: " + "; ".join(errors[:max_errors]) + more)
    return out


def load_inputs(folder: str | Path) -> Inputs:
    folder = Path(folder)
    rows = {name: parse_rows(name, read_csv(folder, name)) for name in REQUIRED_COLUMNS}
    inp = Inputs(gl=rows["gl_detail.csv"], roster=rows["roster.csv"], budget=rows["budget.csv"],
                 legal_rows=rows["legal_rows.csv"], capex=rows["capex_tracker.csv"], prior_je=rows["prior_je.csv"],
                 je_dims=rows["je_dims.csv"], mom_gl=rows["mom_gl.csv"])
    meta = read_meta(folder, "capex_meta.json")
    inp.capex_meta = {
        "unallocated_gl_total": D(meta["unallocated_gl_total"]),
        "needs_attention_count": int(meta["needs_attention_count"]),
        "needs_attention_total": D(meta["needs_attention_total"]),
    }
    pmeta = read_meta(folder, "prior_je_meta.json")
    inp.prior_je_meta = {"period": pmeta["period"], "reversed_total": D(pmeta["reversed_total"])}
    names: dict[str, dict[str, str]] = {}
    for d in rows["dimension_names.csv"]:
        names.setdefault(d["dim_type"], {})[d["id"]] = d["name"]
    inp.dim_names = names
    return inp
