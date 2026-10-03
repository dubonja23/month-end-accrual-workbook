"""Small builders for hand-computed test fixtures."""
from __future__ import annotations

from decimal import Decimal

from accrual_workbook.engine.config import build_config
from accrual_workbook.engine.loader import Inputs, parse_budget_row, parse_capex_row, parse_gl_row, parse_roster_row

_counter = [0]


def gl(vendor="V1", acct=60100, amount=0, posted="2026-09-15", svc_from="", svc_to="", memo="", journal="APJ",
       doc=None, svc_month="", dept="Finance", loc="Main Office", name=None):
    _counter[0] += 1
    return parse_gl_row({
        "entry_date": posted, "gl_account": acct, "gl_account_name": f"Acct {acct}", "vendor_id": vendor,
        "vendor_name": name if name is not None else (f"Vendor {vendor}" if vendor else ""),
        "department_name": dept, "location_name": loc, "signed_amount": str(amount), "gl_journal_id": journal,
        "journal_posting_date": posted, "service_period_from": svc_from, "service_period_to": svc_to,
        "service_month": svc_month, "service_date_source": "", "description": memo,
        "document_id": doc or f"DOC-{_counter[0]}",
    }, _counter[0])


def monthly_bills(vendor, acct, amount, months, year=2026, post_day=20):
    """One bill per service month with service-period dates, posted in that month."""
    import calendar
    out = []
    for m in months:
        last = calendar.monthrange(year, m)[1]
        out.append(gl(vendor, acct, amount, f"{year}-{m:02d}-{post_day:02d}", f"{year}-{m:02d}-01",
                      f"{year}-{m:02d}-{last:02d}"))
    return out


def roster(vendor="V1", acct=60100, spread=0, liability=0, owner="Owner A", vtype="Services", name=None):
    return parse_roster_row({
        "vendor_name": name or f"Vendor {vendor}", "vendor_id": vendor, "gl_account": acct,
        "gl_account_name": f"Acct {acct}", "vendor_type": vtype, "budget_ytd_spread": str(spread),
        "gl_actual_ytd": "0", "liability_prior_year_remaining": str(liability), "owner": owner,
    })


def budget(vendor="V1", acct=60100, annual=0, monthly=None):
    cols = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    if monthly is None:
        each = Decimal(str(annual)) / 12
        monthly = [each] * 12
    row = {"vendor_id": vendor, "vendor_name": f"Vendor {vendor}", "gl_account": acct,
           "gl_account_name": f"Acct {acct}", "annual": str(annual)}
    row.update({c: str(v) for c, v in zip(cols, monthly)})
    return parse_budget_row(row)


def capex_row(deal="Deal A", project="P1", vendor="VC1", area="Area", budgeted=None, cost=None, pct=None,
              invoiced=0, location="L1"):
    return parse_capex_row({
        "deal": deal, "project_id": project, "location_id": location, "vendor": f"Vendor {vendor}", "area": area,
        "budgeted_cost": "" if budgeted is None else str(budgeted), "cost": "" if cost is None else str(cost),
        "work_request_date": "2026-05-01", "pct_complete": "" if pct is None else str(pct), "fully_complete": "N",
        "placed_in_service": "N", "invoiced_to_date": str(invoiced), "vendor_id": vendor, "account_id": "16000",
        "dept_id": "D7",
    })


def inputs(gl_rows=(), roster_rows=(), budget_rows=(), legal_rows=(), capex_rows=(), je_dims=(), mom_gl=(),
           unallocated="0") -> Inputs:
    return Inputs(
        gl=list(gl_rows), roster=list(roster_rows), budget=list(budget_rows), legal_rows=list(legal_rows),
        capex=list(capex_rows),
        capex_meta={"unallocated_gl_total": Decimal(unallocated), "needs_attention_count": 0,
                    "needs_attention_total": Decimal(0)},
        prior_je=[], prior_je_meta={"period": "2026-08", "reversed_total": Decimal(0)},
        dim_names={"dept": {"D1": "Finance"}, "location": {"L1": "Main Office"}},
        je_dims=list(je_dims) or [], mom_gl=list(mom_gl),
    )


def dims_row(vendor="V1", acct=60100, dept="D1", location="L1", item="I1", source="prior_je"):
    return {"vendor_id": vendor, "gl_account": acct, "dept": dept, "location": location, "item": item,
            "source": source}


def config(**overrides):
    base = {"legal": {"vendor_ids": [], "accounts": [61500]}}
    base.update(overrides)
    return build_config(base)


def D(x) -> Decimal:
    return Decimal(str(x))
