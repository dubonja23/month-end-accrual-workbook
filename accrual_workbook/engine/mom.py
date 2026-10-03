"""Month-over-month review: per vendor + account totals, drivers and plain-English explanations."""
from __future__ import annotations

from .money import ZERO, D, fmt, r2

NEW_ACCRUAL = "new accrual"
ACCRUAL_NOW_ZERO = "accrual now $0"
OVER_BUDGET_ZERO = "over budget → $0"
NOT_REBOOKED = "prior accrual not rebooked"
OVERRIDDEN = "overridden"
MANUAL_ADD = "manual add"
ACCRUAL_CHANGED = "accrual changed"
BILLS_CHANGED = "bills changed"
NO_CHANGE = "no change"
DRIVERS = [BILLS_CHANGED, ACCRUAL_CHANGED, NEW_ACCRUAL, ACCRUAL_NOW_ZERO, OVER_BUDGET_ZERO, NOT_REBOOKED,
           OVERRIDDEN, MANUAL_ADD, NO_CHANGE]


def derive_mom_gl(gl_rows: list[dict], cfg: dict, period, prior_accruals: dict, earlier_accruals: dict,
                  vendor_names: dict | None = None) -> list[dict]:
    """Build the month-over-month GL input from the GL itself and the app's own sign-off history.

    Bills = AP bills and receipts on expense accounts (legal included, commissions excluded) posted in the
    month. prior_accruals = last month's booked accrual by "vendor|acct" (reversed on the 1st of this month);
    earlier_accruals = the month before that (reversed on the 1st of last month).
    """
    from .config import in_ranges
    from .scope import journal_code

    sc = cfg["scope"]
    journals = {j.upper() for j in sc["journals"]}
    excluded = {int(a) for a in sc.get("excluded_accounts", [])}
    names = dict(vendor_names or {})
    prev_key = period.prev().key

    def bills(month_key: str) -> dict:
        out: dict = {}
        for r in gl_rows:
            if journal_code(r["journal"]) not in journals or not r["vendor_id"]:
                continue
            if r["gl_account"] in excluded or not in_ranges(r["gl_account"], sc["expense_accounts"]):
                continue
            if r["posting_date"].strftime("%Y-%m") != month_key:
                continue
            k = f"{r['vendor_id']}|{r['gl_account']}"
            out[k] = out.get(k, ZERO) + r["amount"]
            names.setdefault(r["vendor_id"], r["vendor_name"])
        return out

    prior_b, cur_b = bills(prev_key), bills(period.key)
    rows = []
    for k in sorted(set(prior_b) | set(cur_b) | set(prior_accruals) | set(earlier_accruals)):
        vid, acct = k.split("|")
        rows.append({"vendor_id": vid, "vendor": names.get(vid, vid), "gl_account": int(acct),
                     "prior_bills": prior_b.get(k, ZERO), "prior_accrual": D(prior_accruals.get(k, 0)),
                     "prior_reversal": D(earlier_accruals.get(k, 0)), "current_bills": cur_b.get(k, ZERO),
                     "current_reversal": D(prior_accruals.get(k, 0)), "other": ZERO})
    return rows


def is_large_swing(mom_amount, prior_total, cfg: dict) -> bool:
    """Large swing = |MoM $| >= threshold AND |MoM %| >= threshold (a move from $0 counts as 100%+)."""
    m = cfg["mom"]
    mom_amount, prior_total = D(mom_amount), D(prior_total)
    if abs(mom_amount) < D(str(m["large_swing_abs"])):
        return False
    if prior_total == 0:
        return True
    return abs(mom_amount) / abs(prior_total) >= D(str(m["large_swing_pct"]))


def classify(r: dict, line: dict | None, cfg: dict) -> str:
    tol = D(str(cfg["mom"]["no_change_tolerance"]))
    prior_acc, cur_acc = r["prior_accrual"], r["current_accrual"]
    if line and line.get("line_type") in ("manual", "carried"):
        return MANUAL_ADD
    if line and line.get("applied_by") == "override":
        return OVERRIDDEN
    if prior_acc > 0 and line is None:
        return NOT_REBOOKED
    if prior_acc == 0 and cur_acc > 0:
        return NEW_ACCRUAL
    if prior_acc > 0 and cur_acc == 0:
        if line and line.get("budget_ytd") is not None and line["spend_ytd"] > line["budget_ytd"]:
            return OVER_BUDGET_ZERO
        return ACCRUAL_NOW_ZERO
    if abs(r["mom"]) < tol:
        return NO_CHANGE
    accrual_change = cur_acc - prior_acc
    bills_change = r["current_bills"] - r["prior_bills"]
    if accrual_change != 0 and abs(accrual_change) >= abs(bills_change):
        return ACCRUAL_CHANGED
    return BILLS_CHANGED


def _direction(mom, pct) -> str:
    if mom == 0:
        return "Flat"
    word = "Up" if mom > 0 else "Down"
    pct_txt = f" ({abs(pct) * 100:.0f}%)" if pct is not None else " (from $0)"
    return f"{word} {fmt(abs(mom))}{pct_txt}"


def explain(r: dict, line: dict | None) -> str:
    d = r["driver"]
    head = _direction(r["mom"], r["pct"])
    pa, ca, pb, cb = r["prior_accrual"], r["current_accrual"], r["prior_bills"], r["current_bills"]
    if d == MANUAL_ADD:
        why = f"manual add of {fmt(ca)}"
        note = (line or {}).get("manual", {}).get("explanation")
        why += f": {note}" if note else ""
    elif d == OVERRIDDEN:
        o = (line or {}).get("override") or {}
        why = f"accrual overridden to {fmt(ca)} (formula {fmt(line.get('formula_accrual'))})"
        why += f": {o.get('explanation')}" if o.get("explanation") else ""
    elif d == NOT_REBOOKED:
        why = f"last month's accrual of {fmt(pa)} was not rebooked; the line is no longer accrued"
    elif d == NEW_ACCRUAL:
        why = f"new accrual of {fmt(ca)} this month"
    elif d == OVER_BUDGET_ZERO:
        why = (f"spend YTD {fmt(line['spend_ytd'])} is over budget YTD {fmt(line['budget_ytd'])}, "
               f"so the {fmt(pa)} accrual dropped to $0")
    elif d == ACCRUAL_NOW_ZERO:
        reason = ""
        if line and line.get("standing"):
            reason = f" ({line['standing']['basis']})"
        elif line and line.get("accrual_rule"):
            reason = f" ({line['accrual_rule']})"
        why = f"accrual went from {fmt(pa)} to $0{reason}"
    elif d == ACCRUAL_CHANGED:
        why = f"accrual {fmt(pa)} → {fmt(ca)}; bills {fmt(pb)} → {fmt(cb)}"
    elif d == BILLS_CHANGED:
        why = f"bills {fmt(pb)} → {fmt(cb)}; accrual {fmt(pa)} → {fmt(ca)}"
    else:
        return "No material change from last month."
    return f"{head}: {why}."


def build(mom_gl: list[dict], current_lines: dict, cfg: dict, reviewed: dict, account_names: dict) -> dict:
    """current_lines: {"vendor_id|acct": {"accrual": Decimal, "vendor_name": str, "line": opex line or None}}."""
    keys: dict = {}
    for g in mom_gl:
        keys[f"{g['vendor_id']}|{g['gl_account']}"] = g
    for k in current_lines:
        keys.setdefault(k, None)

    rows = []
    for k, g in keys.items():
        vid, acct = k.split("|")
        cur = current_lines.get(k)
        g = g or {"vendor": cur["vendor_name"], "prior_bills": ZERO, "prior_accrual": ZERO, "prior_reversal": ZERO,
                  "current_bills": ZERO, "current_reversal": ZERO, "other": ZERO}
        prior_total = g["prior_bills"] + g["prior_accrual"] - g["prior_reversal"]
        current_gl = g["current_bills"] - g["current_reversal"] + g["other"]
        current_accrual = cur["accrual"] if cur else ZERO
        current_total = current_gl + current_accrual
        mom_amt = current_total - prior_total
        pct = (mom_amt / abs(prior_total)) if prior_total != 0 else None
        r = {
            "key": k, "vendor_id": vid, "vendor": (cur or {}).get("vendor_name") or g["vendor"],
            "gl_account": int(acct), "account_name": account_names.get(str(acct), ""),
            "prior_bills": g["prior_bills"], "prior_accrual": g["prior_accrual"], "prior_reversal": g["prior_reversal"],
            "current_bills": g["current_bills"], "current_reversal": g["current_reversal"], "other": g["other"],
            "prior_total": prior_total, "current_gl": current_gl, "current_accrual": current_accrual,
            "current_total": current_total, "mom": mom_amt, "pct": None if pct is None else r2(pct * 100) / 100,
        }
        line = (cur or {}).get("line")
        r["in_current"] = cur is not None
        r["driver"] = classify(r, line if cur else None, cfg)
        r["why"] = explain(r, line)
        r["large_swing"] = is_large_swing(mom_amt, prior_total, cfg)
        rev = reviewed.get(k)
        r["reviewed"] = bool(rev)
        r["reviewed_by"] = (rev or {}).get("user")
        r["reviewed_at"] = (rev or {}).get("at")
        rows.append(r)
    rows.sort(key=lambda x: (x["gl_account"], x["vendor"]))

    accounts: dict = {}
    for r in rows:
        a = accounts.setdefault(r["gl_account"], {"gl_account": r["gl_account"], "account_name": r["account_name"],
                                                  "prior_total": ZERO, "current_gl": ZERO, "current_accrual": ZERO,
                                                  "current_total": ZERO, "mom": ZERO, "rows": []})
        for f in ("prior_total", "current_gl", "current_accrual", "current_total", "mom"):
            a[f] += r[f]
        a["rows"].append(r)
    for a in accounts.values():
        a["pct"] = (a["mom"] / abs(a["prior_total"])) if a["prior_total"] != 0 else None
        movers = sorted(a["rows"], key=lambda x: abs(x["mom"]), reverse=True)[:2]
        movers = [m for m in movers if m["mom"] != 0]
        head = _direction(a["mom"], a["pct"])
        if movers:
            parts = ", ".join(f"{m['vendor']} ({'+' if m['mom'] > 0 else '-'}{fmt(abs(m['mom']))}, {m['driver']})"
                              for m in movers)
            a["why"] = f"{head} vs last month, driven mainly by {parts}."
        else:
            a["why"] = "No change from last month."
        a["rows"] = [x["key"] for x in a["rows"]]

    large = [r for r in rows if r["large_swing"]]
    totals = {f: sum((r[f] for r in rows), ZERO) for f in ("prior_total", "current_gl", "current_accrual",
                                                            "current_total", "mom")}
    return {"rows": rows, "accounts": sorted(accounts.values(), key=lambda a: a["gl_account"]), "totals": totals,
            "large_swings": len(large), "large_swings_reviewed": sum(1 for r in large if r["reviewed"])}
