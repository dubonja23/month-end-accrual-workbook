"""Standing rules carried forward month to month.

In the baseline month a rule previews only; from the next month it sets the accrual.
A current-month override or manual add always wins (applied after this module).
"""
from __future__ import annotations

from datetime import date

from .config import key_of, keyed
from .money import ZERO, D, r2
from .period import Period, month_end, month_index
from .service import spend_ytd as _spend_ytd
from .vendor_opex import manual_line

ZERO_REASONS = {
    "billed_in_full": "Billed in full",
    "receipts": "Received via receipts",
    "not_used": "Service not used",
}

STATUS_AUTO = "Auto-applied"
STATUS_REVIEW = "Review"
STATUS_REVIEWED = "Reviewed"
STATUS_PREVIEW = "Preview"


def _as_date(value) -> date | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def paid_through_by_vendor(rows: list[dict], cfg: dict, period: Period) -> dict:
    """Latest service-period end on a positive current-year bill posted by the cutoff, per vendor.

    Bills whose service period spans more than max_service_span_days are ignored.
    A bill with no service dates uses the end of its service month. Bills whose service month is only
    Estimated (taken from the posting month) are ignored: an arrears bill posted this month usually covers
    last month, and counting it would make the vendor look billed through month-end.
    """
    max_span = int(cfg["standing"].get("max_service_span_days", 100))
    out: dict[str, date] = {}
    for row in rows:
        if row["amount"] <= 0 or row["posting_date"] > period.end:
            continue
        if row.get("basis") == "Estimated":
            continue
        if not row["service_month"].startswith(f"{period.year:04d}-"):
            continue
        if row["service_from"] and row["service_to"]:
            if (row["service_to"] - row["service_from"]).days > max_span:
                continue
            end = row["service_to"]
        else:
            y, m = map(int, row["service_month"].split("-"))
            end = month_end(y, m)
        vendor = row["vendor_id"]  # the vendor that actually billed (rollups do not transfer paid-through)
        if vendor not in out or end > out[vendor]:
            out[vendor] = end
    return out


def unbilled_months(paid_through: date | None, period: Period, granularity: str = "monthly"):
    """Whole months from the paid-through month to the cutoff month (0 if paid through month-end).

    Half-month granularity adds 0.5 when the paid-through day is on or before the 15th and is not
    the last day of its month. Returns None when there is no dated bill (caller accrues one month).
    """
    if paid_through is None:
        return None
    if paid_through >= period.end:
        return D(0)
    months = D(month_index(period.key) - (paid_through.year * 12 + paid_through.month - 1))
    if granularity == "half_month":
        last_day = month_end(paid_through.year, paid_through.month).day
        if paid_through.day <= 15 and paid_through.day != last_day:
            months += D("0.5")
    return months


def billed_for_month(line: dict, period: Period):
    return line["buckets"].get(period.key, ZERO)


def rule_amount(rule: dict, line: dict, period: Period, paid_through: date | None) -> tuple:
    """Return (amount, basis text, extra flags) for one rule type."""
    kind = rule["type"]
    flags: list[dict] = []
    if kind == "zero":
        reason = rule.get("reason", "billed_in_full")
        label = ZERO_REASONS.get(reason, reason)
        if reason == "billed_in_full" and rule.get("billed_through"):
            label += f" through {_as_date(rule['billed_through']).isoformat()}"
        return r2(ZERO), label, flags
    if kind == "unbilled":
        rate = D(rule["rate"])
        gran = rule.get("granularity", "monthly")
        months = unbilled_months(paid_through, period, gran)
        if months is None:
            months = D(1)
            flags.append({"code": "no_dated_bill", "message": "No dated bill found; accrued one month."})
            basis = f"{rate:,.2f} x 1 month (no dated bill)"
        else:
            basis = f"{rate:,.2f} x {months} months unbilled after {paid_through.isoformat()} ({gran})"
        return r2(rate * months), basis, flags
    if kind == "avg_less_billed":
        if paid_through and paid_through >= period.end:
            return r2(ZERO), f"Paid through {paid_through.isoformat()}", flags
        avg = D(line["spend_ytd"]) / period.months_elapsed
        billed = billed_for_month(line, period)
        return r2(max(avg - billed, ZERO)), f"Avg {r2(avg):,.2f}/mo less {billed:,.2f} billed for {period.short}", flags
    if kind == "rate_unless_billed":
        billed = billed_for_month(line, period)
        if billed > 0:
            return r2(ZERO), f"Billed {billed:,.2f} for {period.short}", flags
        return r2(D(rule["rate"])), f"Rate {D(rule['rate']):,.2f}; nothing billed for {period.short}", flags
    if kind == "budget":
        return line["formula_accrual"] or ZERO, "Budget formula", flags
    raise ValueError(f"unknown standing rule type {kind!r}")


def _pct_and_abs(current, baseline, pct, absolute) -> bool:
    current, baseline = D(current), D(baseline)
    diff = abs(current - baseline)
    if diff < D(absolute):
        return False
    if baseline == 0:
        return True
    return diff / abs(baseline) >= D(str(pct))


def threshold_flags(rule: dict, line: dict, period: Period, th: dict) -> list[dict]:
    flags = []
    base = rule.get("baseline") or {}
    if "annual_budget" in base and line.get("annual_budget") is not None:
        if _pct_and_abs(line["annual_budget"], base["annual_budget"], th["budget_change_pct"], th["budget_change_abs"]):
            flags.append({"code": "budget_change",
                          "message": f"Annual budget {D(line['annual_budget']):,.2f} vs baseline "
                                     f"{D(base['annual_budget']):,.2f}."})
    if "monthly_spend" in base:
        expected = D(base["monthly_spend"]) * period.months_elapsed
        if _pct_and_abs(line["spend_ytd"], expected, th["spend_change_pct"], th["spend_change_abs"]):
            flags.append({"code": "spend_change",
                          "message": f"Spend YTD {D(line['spend_ytd']):,.2f} vs expected {expected:,.2f}."})
    if rule["type"] == "zero" and line.get("posted_this_period", ZERO) > 0:
        flags.append({"code": "new_bill_on_zero",
                      "message": f"New bill of {line['posted_this_period']:,.2f} posted on a $0 line."})
    ends = _as_date(rule.get("billed_through") or rule.get("ends"))
    if ends and (rule["type"] == "zero" and rule.get("reason", "billed_in_full") == "billed_in_full"
                 or rule.get("ends")):
        horizon = period
        for _ in range(int(th.get("term_ending_lookahead_months", 1))):
            horizon = horizon.next()
        if ends <= horizon.end:
            flags.append({"code": "term_ending", "message": f"Billed-in-full term ends {ends.isoformat()}."})
    return flags


def _status(flags, confirmed: bool, active: bool) -> str:
    if not active:
        return STATUS_PREVIEW
    if not flags:
        return STATUS_AUTO
    return STATUS_REVIEWED if confirmed else STATUS_REVIEW


def apply_standing(lines: list[dict], rows: list[dict], spend, cfg: dict, period: Period, state) -> dict:
    """Annotate lines with standing-rule results and set final accruals when active.

    Returns {"table": [...], "carried_lines": [...], "baseline_month": str, "active": bool}.
    """
    st = cfg["standing"]
    th = st["thresholds"]
    baseline = st.get("baseline_month")
    active = bool(baseline) and period.key > str(baseline)
    confirmed = set(getattr(state, "standing_confirmed", set()) or set())
    paid = paid_through_by_vendor(rows, cfg, period)
    rules = keyed(st.get("rules"))
    table = []

    if not baseline:
        return {"table": table, "carried_lines": [], "baseline_month": None, "active": False, "paid_through": paid}

    for line in lines:
        key = key_of(line["vendor_id"], line["gl_account"])
        pt = paid.get(line["vendor_id"])
        rule = rules.get(key)
        if rule:
            amount, basis, flags = rule_amount(rule, line, period, pt)
            flags += threshold_flags(rule, line, period, th)
            rule_name = rule["type"] if rule["type"] != "zero" else f"zero ({rule.get('reason', 'billed_in_full')})"
        elif st.get("generic_paid_through", True) and pt and pt >= period.end \
                and line["formula_accrual"] > line["liability_remaining"] and line["applied_by"] == "formula":
            # Billed up to date for this year: keep only any unpaid prior-year liability.
            amount = r2(min(line["formula_accrual"], line["liability_remaining"]))
            basis = f"Billed through {pt.isoformat()} (generic rule)"
            if amount > 0:
                basis += f"; prior-year liability {amount:,.2f} still accrued"
            flags = []
            removed = line["formula_accrual"] - amount
            if removed >= D(th["paid_through_removal_min"]):
                flags.append({"code": "paid_through_removal",
                              "message": f"Paid-through rule removes {removed:,.2f} of the formula accrual."})
            rule_name = "paid through (generic)"
        else:
            continue
        status = _status(flags, line["key"] in confirmed, active)
        line["standing"] = {"rule": rule_name, "basis": basis, "amount": amount, "flags": flags,
                            "status": status, "active": active, "paid_through": pt,
                            "note": (rule or {}).get("note", "")}
        if active and line["applied_by"] == "formula":
            line["final_accrual"] = amount
            line["applied_by"] = "standing rule"
        table.append(_table_row(line, line["standing"]))

    carried_lines = []
    current_manual = {f"{m['vendor_id']}|{int(m['gl_account'])}" for m in getattr(state, "manual_adds", []) or []}
    for entry in st.get("carried_manual_adds") or []:
        key = key_of(entry["vendor_id"], entry["gl_account"])
        k = f"{key[0]}|{key[1]}"
        line = manual_line({**entry, "amount": entry.get("amount", entry.get("rate", 0)) or 0}, "carried")
        s = spend.get(key)
        line.update({"buckets": dict(s["buckets"]), "spend_ytd": r2(_spend_ytd(s)), "gl_total_ytd": s["gl_total"],
                     "posted_this_period": s["posted_this_period"]})
        kind = entry.get("type", "fixed")
        pt = paid.get(key[0])
        if kind == "fixed":
            amount, basis, flags = r2(D(entry["amount"])), "Fixed amount carried forward", []
        else:
            line["formula_accrual"] = ZERO
            amount, basis, flags = rule_amount(entry, line, period, pt)
        flags += threshold_flags({**entry, "type": kind}, line, period, th)
        if kind != "zero" and s["posted_this_period"] > 0 and not any(f["code"] == "new_bill_on_zero" for f in flags):
            flags.append({"code": "new_bill", "message": f"New bill of {s['posted_this_period']:,.2f} posted on a "
                                                         f"carried manual add; check for double counting."})
        superseded = k in current_manual
        status = _status(flags, k in confirmed, active and not superseded)
        line["standing"] = {"rule": f"carried manual add ({kind})", "basis": basis, "amount": amount, "flags": flags,
                            "status": status, "active": active and not superseded, "paid_through": pt,
                            "note": entry.get("explanation", "")}
        line["final_accrual"] = amount
        table.append(_table_row(line, line["standing"], superseded=superseded))
        if active and not superseded:
            carried_lines.append(line)

    return {"table": table, "carried_lines": carried_lines, "baseline_month": str(baseline), "active": active,
            "paid_through": paid}


def _table_row(line: dict, s: dict, superseded: bool = False) -> dict:
    return {
        "key": line["key"], "vendor_id": line["vendor_id"], "vendor_name": line["vendor_name"],
        "gl_account": line["gl_account"], "rule": s["rule"], "basis": s["basis"], "amount": s["amount"],
        "formula_accrual": line.get("formula_accrual"), "flags": s["flags"], "status": s["status"],
        "needs_confirm": bool(s["flags"]) and s["active"], "superseded": superseded, "note": s.get("note", ""),
    }
