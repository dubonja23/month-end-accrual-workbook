"""Load config/rules.yaml and fill defaults. Vendor-specific exceptions are data here, never code."""
from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml

DEFAULTS: dict = {
    "company": "Sample Co.",
    "user": "reviewer",
    "current_period": None,
    "scope": {
        "journals": ["APJ", "UNB"],
        "corporate_card_vendor_ids": [],
        "expense_accounts": [[60000, 65999]],
        "excluded_accounts": [],
        "prepaid_accounts": [[13100, 13101]],
        "capex_accounts": [[16000, 16010]],
        "removed_documents": [],
    },
    "legal": {
        "vendor_ids": [],
        "accounts": [],
        "default_gl": 61500,
        "add_vendor_defaults": {"gl": 61500, "item": "", "dept": "", "location": "", "customer": "", "project": ""},
    },
    "service_rules": [],
    "rollups": {"account": [], "vendor": []},
    "roster": {"removed_lines": []},
    "budget": {"overrides": [], "excluded_lines": []},
    "prior_year_liability": [],
    "accrual_rules": [],
    "standing": {
        "baseline_month": None,
        "rules": [],
        "carried_manual_adds": [],
        "generic_paid_through": True,
        "max_service_span_days": 100,
        "thresholds": {
            "budget_change_pct": 0.20,
            "budget_change_abs": 5000,
            "spend_change_pct": 0.50,
            "spend_change_abs": 5000,
            "paid_through_removal_min": 10000,
            "term_ending_lookahead_months": 1,
        },
    },
    "capex": {"accrual_account": 16005, "dept": "", "customer": "", "item": ""},
    "je": {
        "journal": "GJ",
        "accrued_expenses_account": 20500,
        "reference_prefix": "ACCR",
        "dept_splits": [],
    },
    "mom": {"large_swing_abs": 10000, "large_swing_pct": 0.25, "no_change_tolerance": 1.00},
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def build_config(overrides: dict | None = None) -> dict:
    """Defaults merged with overrides. Tests use this to build small configs."""
    return _merge(DEFAULTS, overrides or {})


def load_config(path: str | Path) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    cfg = build_config(data)
    env_user = os.environ.get("ACCRUAL_USER")
    if env_user:
        cfg["user"] = env_user
    return cfg


def in_ranges(acct: int | None, ranges) -> bool:
    if acct is None:
        return False
    return any(int(lo) <= acct <= int(hi) for lo, hi in ranges)


def key_of(vendor_id: str, acct: int) -> tuple[str, int]:
    return (str(vendor_id), int(acct))


def keyed(items, vendor_field: str = "vendor_id", acct_field: str = "gl_account") -> dict:
    return {key_of(i[vendor_field], i[acct_field]): i for i in items or []}
