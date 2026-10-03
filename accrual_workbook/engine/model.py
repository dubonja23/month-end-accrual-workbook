"""Run everything for a period and return one result object (plain dicts, Decimal money)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from . import capex as capex_mod
from . import journal, legal as legal_mod, mom as mom_mod
from .loader import Inputs
from .money import ZERO
from .overbudget import budget_views, over_budget, vendor_budget_totals
from .period import Period
from .scope import apply_scope
from .service import build_spend, posting_vs_service
from .standing import apply_standing
from .vendor_opex import apply_overrides, budget_lines, compute_formula_lines, manual_line, roster_lines

COMPONENTS = [
    ("vendor_opex", "Vendor OpEx", "Roster formula, standing rules, overrides and manual adds", "Monthly"),
    ("legal", "Legal", "Law firm estimates (Legal tab)", "Monthly"),
    ("capex", "Capex Projects", "Capex project tracker (read-only)", "Monthly"),
]


@dataclass
class State:
    """Reviewer edits for one period, as read from the store."""
    overrides: dict = field(default_factory=dict)        # "vid|acct" -> {amount, explanation, user, at}
    manual_adds: list = field(default_factory=list)      # current-period manual adds
    legal_edits: dict = field(default_factory=dict)      # vendor_id -> edited fields (+ splits)
    legal_added: list = field(default_factory=list)      # vendors added on the Legal tab
    standing_confirmed: set = field(default_factory=set)  # "vid|acct"
    mom_reviewed: dict = field(default_factory=dict)     # "vid|acct" -> {user, at}
    components: dict = field(default_factory=dict)       # component -> {user, at}
    attention: list = field(default_factory=list)        # needs-attention items for the period
    locked: bool = False
    signoff: dict | None = None


def run(period_key: str, inputs: Inputs, cfg: dict, state: State | None = None) -> dict:
    state = state or State()
    period = Period.parse(period_key)

    scope = apply_scope(inputs.gl, cfg, period)
    roster = roster_lines(inputs.roster, cfg)
    roster_keys = [(r["vendor_id"], r["gl_account"]) for r in roster]
    spend = build_spend(scope.rows, roster_keys, cfg, period)
    budgets = budget_lines(inputs.budget, cfg)
    lines = compute_formula_lines(roster, budgets, spend, cfg, period)

    # prior_formula: last month's formula on last month's data (n-1 months, spend posted by last month-end)
    prev = period.prev()
    if prev.year == period.year:
        p_scope = apply_scope(inputs.gl, cfg, prev)
        p_spend = build_spend(p_scope.rows, roster_keys, cfg, prev)
        prior = {ln["key"]: ln["formula_accrual"] for ln in compute_formula_lines(roster, budgets, p_spend, cfg, prev)}
        for ln in lines:
            ln["prior_formula"] = prior.get(ln["key"])

    standing = apply_standing(lines, scope.rows, spend, cfg, period, state)
    manual = []
    for m in state.manual_adds:
        if str(m.get("period")) == period.key:
            ml = manual_line(m, "manual")
            s = spend.get((ml["vendor_id"], ml["gl_account"]))
            ml.update({"buckets": dict(s["buckets"]), "gl_total_ytd": s["gl_total"]})
            manual.append(ml)
    opex_lines = lines + standing["carried_lines"] + manual
    apply_overrides(opex_lines, state.overrides)

    dims_ctx = journal.build_dims_context(inputs.je_dims, scope.rows, inputs.dim_names)
    for ln in opex_lines:
        ln["dims"] = resolve = journal.resolve_dims(ln, dims_ctx)
        ln["needs_input"] = (not ln["owner"] and ln["line_type"] == "roster") or (
            bool(resolve["missing"]) and ln["final_accrual"] > 0) or bool(
            ln.get("standing") and ln["standing"]["status"] == "Review")

    legal = legal_mod.build(inputs.legal_rows, cfg, state)
    capex = capex_mod.build(inputs.capex, inputs.capex_meta)
    je = journal.build(period, opex_lines, legal, capex, cfg, inputs.dim_names)

    # MoM review
    current: dict = {}
    for ln in opex_lines:
        c = current.setdefault(ln["key"], {"accrual": ZERO, "vendor_name": ln["vendor_name"], "line": ln})
        c["accrual"] += ln["final_accrual"]
    for row in legal["rows"]:
        for jl in row["je_lines"]:
            k = f"{row['vendor_id']}|{jl['gl']}"
            c = current.setdefault(k, {"accrual": ZERO, "vendor_name": row["vendor"],
                                       "line": {"line_type": "legal", "applied_by": "legal"}})
            c["accrual"] += jl["amount"]
    account_names = inputs.dim_names.get("account", {})
    mom = mom_mod.build(inputs.mom_gl, current, cfg, state.mom_reviewed, account_names)

    last_billed: dict = {}
    for r in scope.rows:
        if r["amount"] > 0 and (r["vendor_id"] not in last_billed or r["posting_date"] > last_billed[r["vendor_id"]]):
            last_billed[r["vendor_id"]] = r["posting_date"]
    overb = over_budget(opex_lines, vendor_budget_totals(inputs.budget), last_billed, period)

    gl_detail = [{
        "row_id": r["row_id"], "posting_date": r["posting_date"], "gl_account": r["gl_account"],
        "gl_account_name": r["gl_account_name"], "vendor_id": r["vendor_id"], "vendor_name": r["vendor_name"],
        "department_name": r["department_name"], "location_name": r["location_name"], "journal": r["journal"],
        "service_from": r["service_from"], "service_to": r["service_to"], "service_month": r["service_month"],
        "service_source": r["service_source"], "basis": r["basis"], "amount": r["amount"], "kind": r["kind"],
        "description": r["description"], "document_id": r["document_id"],
    } for r in scope.rows]

    opex_total = sum((ln["final_accrual"] for ln in opex_lines), ZERO)
    totals = {"vendor_opex": opex_total, "legal": legal["total"], "capex": capex["total"],
              "total": opex_total + legal["total"] + capex["total"]}
    counts = {"vendor_opex": sum(1 for ln in opex_lines if ln["final_accrual"] > 0),
              "legal": sum(len([j for j in r["je_lines"] if j["amount"] != 0]) for r in legal["rows"]),
              "capex": sum(1 for g in capex["groups"] if g["je_amount"] > 0)}
    detail = []
    for name, label, source, cadence in COMPONENTS:
        done = state.components.get(name)
        detail.append({"component": name, "label": label, "source": source, "lines": counts[name],
                       "amount": totals[name], "cadence": cadence, "complete": bool(done),
                       "completed_by": (done or {}).get("user"), "completed_at": (done or {}).get("at")})

    result = {
        "period": period.key, "period_label": period.label, "period_short": period.short,
        "company": cfg["company"], "generated_at": datetime.now().isoformat(timespec="seconds"),
        "months_elapsed": period.months_elapsed,
        "totals": totals, "components": detail,
        "scope": {"counts": scope.counts, "amounts": scope.amounts, "in_scope_rows": len(scope.rows),
                  "accounts": _scope_accounts(cfg, inputs)},
        "vendor_opex": {"lines": opex_lines, "total": opex_total, "month_columns": list(reversed(period.fy_month_keys())),
                        "prepaid_ignored": spend.prepaid_ignored},
        "standing": {"table": standing["table"], "baseline_month": standing["baseline_month"],
                     "active": standing["active"]},
        "legal": legal, "capex": capex, "je": je,
        "mom": mom, "over_budget": overb, "budget": budget_views(inputs.budget, period),
        "posting_vs_service": posting_vs_service(scope.rows, period), "gl_detail": gl_detail,
        "prior_je": {"lines": inputs.prior_je, "reversed_total": inputs.prior_je_meta.get("reversed_total")},
        "locked": state.locked, "signoff": state.signoff,
    }
    result["attention_candidates"] = attention_candidates(result)
    result["checklist"] = signoff_checklist(result, state)
    return result


def _scope_accounts(cfg: dict, inputs: Inputs) -> list[dict]:
    from .scope import account_kind
    names = inputs.dim_names.get("account", {})
    accts = sorted({int(a) for a in names if str(a).isdigit()})
    return [{"gl_account": a, "name": names[str(a)], "kind": account_kind(a, cfg)} for a in accts
            if account_kind(a, cfg)]


def attention_candidates(result: dict) -> list[dict]:
    """System-generated needs-attention items (stable keys; the store keeps their status)."""
    out = []
    for ln in result["je"]["lines"]:
        if ln["side"] == "debit" and ln["missing_dims"] and ln["section"] == journal.SECTION_OPEX:
            out.append({"key": f"dims|{ln['ref']}", "category": "JE dimensions", "vendor": ln["vendor_name"],
                        "vendor_id": ln["vendor_id"], "account": ln["acct"], "amount": ln["debit"],
                        "summary": f"Missing {' and '.join(ln['missing_dims'])} on JE line",
                        "detail": "No dimensions on last month's JE or a recent bill for this vendor + account.",
                        "proposed": "Enter dept/location before posting."})
    for g in result["capex"]["over_invoiced"]:
        out.append({"key": f"capex_over|{g['project_id']}|{g['vendor_id']}", "category": "Capex", "vendor": g["vendor"],
                    "vendor_id": g["vendor_id"], "account": None, "amount": g["net"],
                    "summary": f"Invoiced beyond earned on {g['deal']} ({g['project_id']})",
                    "detail": f"Net earned less invoiced is {g['net']:,.2f}; booked at $0.",
                    "proposed": "Confirm % complete with the project manager."})
    if result["capex"]["not_final"]:
        out.append({"key": "capex_unallocated", "category": "Capex", "vendor": "", "vendor_id": "", "account": None,
                    "amount": result["capex"]["unallocated_gl"],
                    "summary": "Unallocated capex GL; capex figure is not final",
                    "detail": "GL charges on capex accounts are not yet allocated to a project line.",
                    "proposed": "Allocate the GL to projects in the tracker."})
    for row in result["vendor_opex"]["prepaid_ignored"]:
        out.append({"key": f"prepaid|{row['document_id'] or row['row_id']}", "category": "Prepaid",
                    "vendor": row["vendor_name"], "vendor_id": row["vendor_id"], "account": row["gl_account"],
                    "amount": row["amount"],
                    "summary": f"Prepaid not counted in spend: vendor has {row['roster_lines']} roster lines",
                    "detail": "Prepaid bills only count when the vendor has exactly one roster line.",
                    "proposed": "Check which roster line the prepaid belongs to; override if needed."})
    return out


def signoff_checklist(result: dict, state: State) -> dict:
    open_items = [a for a in state.attention if a.get("status") != "Resolved"]
    mom = result["mom"]
    missing_components = [c["label"] for c in result["components"] if not c["complete"]]
    unconfirmed = [r for r in result["standing"]["table"] if r["needs_confirm"] and r["status"] == "Review"]
    items = [
        {"id": "attention", "label": "No open needs-attention items", "ok": not open_items,
         "detail": f"{len(open_items)} open"},
        {"id": "swings", "label": "All large swings reviewed",
         "ok": mom["large_swings_reviewed"] == mom["large_swings"],
         "detail": f"{mom['large_swings_reviewed']} of {mom['large_swings']} reviewed"},
        {"id": "components", "label": "All three components marked complete", "ok": not missing_components,
         "detail": ", ".join(missing_components) or "all complete"},
        {"id": "standing", "label": "All flagged standing-rule lines confirmed", "ok": not unconfirmed,
         "detail": f"{len(unconfirmed)} to confirm"},
        {"id": "je", "label": "Journal entry balances and ties to every tab", "ok": result["je"]["ok"],
         "detail": ", ".join(c["name"] for c in result["je"]["checks"] if not c["ok"]) or "all four checks pass"},
    ]
    return {"items": items, "can_sign_off": all(i["ok"] for i in items) and not state.locked}


def jsonable(obj):
    """Convert a result to JSON-safe types (Decimal -> float rounded to cents, dates -> ISO)."""
    if isinstance(obj, Decimal):
        return float(obj.quantize(Decimal("0.0001")))
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [jsonable(v) for v in obj]
    return obj
