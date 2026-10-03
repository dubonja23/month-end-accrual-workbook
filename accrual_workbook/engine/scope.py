"""GL scope filter. Every excluded row is kept with the reason it was excluded."""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import in_ranges
from .money import ZERO
from .period import Period
from .service import assign_service_month

# Reasons, in the order they are tested. A row gets the first reason that applies.
REMOVED = "removed document"
AFTER_CUTOFF = "after cutoff"
NON_QUALIFYING = "non-qualifying journal"
BLANK_VENDOR = "blank vendor"
OUT_OF_SCOPE = "out-of-scope account"
LEGAL = "legal"
REASONS = [REMOVED, AFTER_CUTOFF, NON_QUALIFYING, BLANK_VENDOR, OUT_OF_SCOPE, LEGAL]


@dataclass
class ScopeResult:
    rows: list[dict] = field(default_factory=list)       # in-scope rows, with kind + service month
    excluded: list[dict] = field(default_factory=list)   # rows with "reason"
    counts: dict = field(default_factory=dict)           # reason -> row count
    amounts: dict = field(default_factory=dict)          # reason -> amount


def journal_code(journal: str) -> str:
    """'APJ-000123' or 'APJ' -> 'APJ'."""
    return str(journal or "").split("-")[0].strip().upper()


def account_kind(acct: int | None, cfg: dict) -> str | None:
    sc = cfg["scope"]
    if acct is None:
        return None
    if acct in {int(a) for a in sc.get("excluded_accounts", [])}:
        return None
    if in_ranges(acct, sc["prepaid_accounts"]):
        return "prepaid"
    if in_ranges(acct, sc["capex_accounts"]):
        return "capex"
    if in_ranges(acct, sc["expense_accounts"]):
        return "expense"
    return None


def exclusion_reason(row: dict, cfg: dict, period: Period) -> str | None:
    sc = cfg["scope"]
    if row["document_id"] and row["document_id"] in set(sc.get("removed_documents", [])):
        return REMOVED
    if row["posting_date"] is None or row["posting_date"] > period.end:
        return AFTER_CUTOFF
    journals = {j.upper() for j in sc["journals"]}
    if journal_code(row["journal"]) not in journals:
        return NON_QUALIFYING
    if row["vendor_id"] in set(sc.get("corporate_card_vendor_ids", [])):
        return NON_QUALIFYING
    if not row["vendor_id"]:
        return BLANK_VENDOR
    if account_kind(row["gl_account"], cfg) is None:
        return OUT_OF_SCOPE
    legal = cfg["legal"]
    if row["vendor_id"] in set(legal.get("vendor_ids", [])) or row["gl_account"] in {
        int(a) for a in legal.get("accounts", [])
    }:
        return LEGAL
    return None


def apply_scope(gl_rows: list[dict], cfg: dict, period: Period) -> ScopeResult:
    res = ScopeResult(counts={r: 0 for r in REASONS}, amounts={r: ZERO for r in REASONS})
    for row in gl_rows:
        reason = exclusion_reason(row, cfg, period)
        if reason:
            res.excluded.append({**row, "reason": reason})
            res.counts[reason] += 1
            res.amounts[reason] += row["amount"]
            continue
        svc_month, source, basis = assign_service_month(row, cfg)
        res.rows.append({
            **row,
            "kind": account_kind(row["gl_account"], cfg),
            "service_month": svc_month,
            "service_source": source,
            "basis": basis,
        })
    return res
