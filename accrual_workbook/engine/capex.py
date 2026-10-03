"""Capex Projects accrual (read-only in the app).

Line accrual = Cost x % Complete - Invoiced to Date (blank cost or % -> $0).
The journal amount is netted by project + vendor and floored at $0.
"""
from __future__ import annotations

from .money import ZERO, D, r2


def line_accrual(cost, pct_complete, invoiced):
    """pct_complete is a percent (0-100). Blank cost or % gives $0."""
    if cost is None or pct_complete is None:
        return ZERO
    return r2(D(cost) * D(pct_complete) / 100 - D(invoiced))


def build(tracker: list[dict], meta: dict) -> dict:
    lines = []
    for i, r in enumerate(tracker):
        lines.append({**r, "line_no": i, "accrual": line_accrual(r["cost"], r["pct_complete"], r["invoiced_to_date"])})

    groups: dict = {}
    for ln in lines:
        g = groups.setdefault((ln["project_id"], ln["vendor_id"]), {
            "deal": ln["deal"], "project_id": ln["project_id"], "vendor": ln["vendor"], "vendor_id": ln["vendor_id"],
            "location_id": ln["location_id"], "line_nos": [], "cost": ZERO, "net": ZERO,
        })
        g["line_nos"].append(ln["line_no"])
        g["cost"] += ln["cost"] or ZERO
        g["net"] += ln["accrual"]
    group_list = []
    for g in groups.values():
        g["je_amount"] = max(g["net"], ZERO)
        g["invoiced_beyond_earned"] = g["net"] < 0
        group_list.append(g)

    deals: dict = {}
    for ln in lines:
        d = deals.setdefault(ln["deal"], {"deal": ln["deal"], "cost": ZERO, "budget": ZERO, "has_budget": False})
        d["cost"] += ln["cost"] or ZERO
        if ln["budgeted_cost"] is not None:
            d["budget"] += ln["budgeted_cost"]
            d["has_budget"] = True
    for d in deals.values():
        diff = d["cost"] - d["budget"]
        d["difference"] = diff
        if not d["has_budget"]:
            d["status"] = "no budget"
        elif diff == 0:
            d["status"] = "ties to budget"
        else:
            d["status"] = f"{'over' if diff > 0 else 'under'} by ${abs(diff):,.2f}"

    unallocated = D(meta.get("unallocated_gl_total", 0))
    total = sum((g["je_amount"] for g in group_list), ZERO)
    blank = [ln for ln in lines if ln["cost"] is None or ln["pct_complete"] is None]
    return {
        "lines": lines,
        "groups": group_list,
        "deals": list(deals.values()),
        "total": total,
        "over_invoiced": [g for g in group_list if g["invoiced_beyond_earned"]],
        "unallocated_gl": unallocated,
        "not_final": unallocated != 0,
        "needs_attention_count": int(meta.get("needs_attention_count", 0)),
        "needs_attention_total": D(meta.get("needs_attention_total", 0)),
        "blank_lines": len(blank),
        "complete_lines": sum(1 for ln in lines if ln["fully_complete"]),
    }
