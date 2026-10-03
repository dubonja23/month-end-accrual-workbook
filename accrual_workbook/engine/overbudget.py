"""Over-budget list with checks, and the Budget tab views."""
from __future__ import annotations

from .money import ZERO, D
from .period import Period


def over_budget(lines: list[dict], budgets_by_vendor: dict, last_billed: dict, period: Period) -> list[dict]:
    """Roster lines where Spend YTD > Budget YTD, with the reviewer's standard checks."""
    out = []
    by_vendor: dict = {}
    for ln in lines:
        if ln["line_type"] == "roster":
            by_vendor.setdefault(ln["vendor_id"], []).append(ln)
    for ln in lines:
        if ln["line_type"] != "roster" or ln["budget_ytd"] is None or ln["spend_ytd"] <= ln["budget_ytd"]:
            continue
        over = ln["spend_ytd"] - ln["budget_ytd"]
        vendor_lines = by_vendor.get(ln["vendor_id"], [])
        vendor_budget_ytd = sum((x["budget_ytd"] or ZERO for x in vendor_lines), ZERO)
        vendor_spend = sum((x["spend_ytd"] for x in vendor_lines), ZERO)
        months_billed = {m for m, v in ln["buckets"].items() if v != 0}
        excluding_ahead = ln["spend_ytd"] - ln["prepaid_included"] - ln["after_cutoff"]
        checks = {
            "budget_on_another_account": len(vendor_lines) > 1 and vendor_spend <= vendor_budget_ytd,
            "within_phased_budget": ln["phased_budget_ytd"] is not None and ln["spend_ytd"] <= ln["phased_budget_ytd"],
            "bills_monthly_no_current_service": len(months_billed) >= period.months_elapsed - 1
            and period.key not in months_billed,
            "driven_by_prepaid_or_billed_ahead": (ln["prepaid_included"] + ln["after_cutoff"]) > 0
            and excluding_ahead <= ln["budget_ytd"],
            "over_full_year_budget": ln["annual_budget"] is not None and ln["spend_ytd"] > ln["annual_budget"],
        }
        out.append({
            "key": ln["key"], "vendor_id": ln["vendor_id"], "vendor_name": ln["vendor_name"],
            "gl_account": ln["gl_account"], "budget_ytd": ln["budget_ytd"], "annual_budget": ln["annual_budget"],
            "spend_ytd": ln["spend_ytd"], "over_by": over,
            "over_pct": (over / ln["budget_ytd"]) if ln["budget_ytd"] else None,
            "vendor_budget_all_accounts": budgets_by_vendor.get(ln["vendor_id"], ZERO),
            "last_billed": last_billed.get(ln["vendor_id"]), "checks": checks,
        })
    return sorted(out, key=lambda r: r["over_by"], reverse=True)


def budget_views(budget_rows: list[dict], period: Period) -> dict:
    m = period.months_elapsed
    by_account: dict = {}
    by_vendor: dict = {}
    by_va: list = []
    no_vendor = ZERO
    for b in budget_rows:
        ytd = sum(b["monthly"][:m], ZERO)
        a = by_account.setdefault(b["gl_account"], {"gl_account": b["gl_account"], "name": b["gl_account_name"],
                                                     "annual": ZERO, "phased_ytd": ZERO})
        a["annual"] += b["annual"]
        a["phased_ytd"] += ytd
        if not b["vendor_id"]:
            no_vendor += b["annual"]
            continue
        v = by_vendor.setdefault(b["vendor_id"], {"vendor_id": b["vendor_id"], "vendor_name": b["vendor_name"],
                                                  "annual": ZERO, "phased_ytd": ZERO, "accounts": set()})
        v["annual"] += b["annual"]
        v["phased_ytd"] += ytd
        v["accounts"].add(b["gl_account"])
        by_va.append({"vendor_id": b["vendor_id"], "vendor_name": b["vendor_name"], "gl_account": b["gl_account"],
                      "name": b["gl_account_name"], "annual": b["annual"], "phased_ytd": ytd})
    vendors = []
    for v in by_vendor.values():
        vendors.append({**v, "accounts": len(v["accounts"])})
    return {
        "by_account": sorted(by_account.values(), key=lambda x: x["gl_account"]),
        "by_vendor": sorted(vendors, key=lambda x: x["vendor_name"]),
        "by_vendor_account": sorted(by_va, key=lambda x: (x["vendor_name"], x["gl_account"])),
        "no_vendor_total": no_vendor,
        "total": sum((b["annual"] for b in budget_rows), ZERO),
    }


def vendor_budget_totals(budget_rows: list[dict]) -> dict:
    out: dict = {}
    for b in budget_rows:
        if b["vendor_id"]:
            out[b["vendor_id"]] = out.get(b["vendor_id"], ZERO) + D(b["annual"])
    return out
