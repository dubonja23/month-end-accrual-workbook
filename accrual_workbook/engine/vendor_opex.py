"""Vendor OpEx accrual: budget YTD, spend YTD, prior-year liability and the formula accrual."""
from __future__ import annotations

from .config import key_of, keyed
from .money import ZERO, D, r2
from .period import Period
from .service import SpendContext, map_key, spend_ytd


class ValidationError(ValueError):
    """User input rejected by an accounting rule."""


# ---------- the formulas ----------

def budget_ytd(annual, months_elapsed: int):
    """Budget YTD = ROUND(annual x months_elapsed / 12, 2). Never the annual budget itself."""
    return r2(D(annual) * months_elapsed / 12)


def formula_accrual(budget_ytd_amt, liability_remaining, spend_ytd_amt):
    """Calculated accrual = MAX(Budget YTD + Liability Remaining - Spend YTD, 0)."""
    return r2(max(D(budget_ytd_amt) + D(liability_remaining) - D(spend_ytd_amt), ZERO))


def liability_remaining(opening, prior_year_bills):
    """MAX(opening - prior-year-service bills paid this year, 0)."""
    return r2(max(D(opening) - D(prior_year_bills), ZERO))


# ---------- budget lines ----------

def budget_lines(budget_rows: list[dict], cfg: dict) -> dict:
    """Budget by vendor+account after exclusions, rollups and annual overrides."""
    excluded = keyed(cfg["budget"].get("excluded_lines"))
    out: dict = {}
    for row in budget_rows:
        if not row["vendor_id"]:
            continue  # budget with no vendor: shown on the Budget tab, never accrued
        raw = key_of(row["vendor_id"], row["gl_account"])
        if raw in excluded:
            continue
        key = map_key(row["vendor_id"], row["gl_account"], cfg)
        line = out.setdefault(key, {"annual": ZERO, "monthly": [ZERO] * 12, "source": "budget", "from": []})
        line["annual"] += row["annual"]
        line["monthly"] = [a + b for a, b in zip(line["monthly"], row["monthly"])]
        line["from"].append(f"{row['vendor_id']}|{row['gl_account']}")
    for o in cfg["budget"].get("overrides") or []:
        key = key_of(o["vendor_id"], o["gl_account"])
        annual = r2(D(o["annual"]))
        line = out.setdefault(key, {"annual": ZERO, "monthly": [r2(annual / 12)] * 12, "source": "budget", "from": []})
        line["annual"] = annual
        line["source"] = "override"
        line["note"] = o.get("note", "")
    return out


def roster_lines(roster: list[dict], cfg: dict) -> list[dict]:
    removed = keyed(cfg["roster"].get("removed_lines"))
    return [r for r in roster if key_of(r["vendor_id"], r["gl_account"]) not in removed]


# ---------- formula lines ----------

def compute_formula_lines(roster: list[dict], budgets: dict, spend: SpendContext, cfg: dict,
                          period: Period) -> list[dict]:
    liab_cfg = keyed(cfg.get("prior_year_liability"))
    rules = keyed(cfg.get("accrual_rules"))
    months = period.months_elapsed
    lines = []
    for r in roster:
        key = key_of(r["vendor_id"], r["gl_account"])
        s = spend.get(key)
        b = budgets.get(key)
        if b is not None:
            annual, b_ytd, b_source = b["annual"], budget_ytd(b["annual"], months), b["source"]
            phased_ytd = sum(b["monthly"][:months], ZERO)
        else:
            annual, b_ytd, b_source = None, r2(r["budget_ytd_spread"]), "roster spread"
            phased_ytd = b_ytd
        if key in liab_cfg:
            opening = D(liab_cfg[key]["opening"])
            liab = liability_remaining(opening, s["prior_year"])
            liab_basis = "config opening - prior-year bills"
        else:
            opening = None
            liab = r2(r["liability_prior_year_remaining"])
            liab_basis = "roster"
        spend_amt = r2(spend_ytd(s))
        formula = formula_accrual(b_ytd, liab, spend_amt)
        line = {
            "key": f"{key[0]}|{key[1]}",
            "vendor_id": key[0],
            "vendor_name": r["vendor_name"],
            "gl_account": key[1],
            "gl_account_name": r["gl_account_name"],
            "vendor_type": r["vendor_type"],
            "owner": r["owner"],
            "line_type": "roster",
            "annual_budget": annual,
            "budget_source": b_source,
            "budget_ytd": b_ytd,
            "phased_budget_ytd": phased_ytd,
            "gl_total_ytd": s["gl_total"],
            "spend_ytd": spend_amt,
            "buckets": dict(s["buckets"]),
            "prior_year_service": s["prior_year"],
            "prepaid_included": s["prepaid_current"],
            "after_cutoff": s["after_cutoff"],
            "prepaid_next_year": s["prepaid_next"],
            "posted_this_period": s["posted_this_period"],
            "liability_opening": opening,
            "liability_prior_year_bills": s["prior_year"] if opening is not None else ZERO,
            "liability_remaining": liab,
            "liability_basis": liab_basis,
            "formula_accrual": formula,
            "accrual_rule": None,
            "standing": None,
            "override": None,
            "final_accrual": formula,
            "applied_by": "formula",
            "prior_formula": None,
        }
        if key in rules:
            line["accrual_rule"] = rules[key].get("label", "Accrual rule")
            line["final_accrual"] = r2(ZERO)
            line["applied_by"] = "accrual rule"
        lines.append(line)
    return lines


# ---------- overrides and manual adds ----------

def validate_override(amount, explanation) -> None:
    if amount is None or str(amount).strip() == "":
        raise ValidationError("Override amount is required.")
    try:
        value = D(amount)
    except ValueError as exc:
        raise ValidationError("Override amount must be a number.") from exc
    if value < 0:
        raise ValidationError("Override amount cannot be negative.")
    validate_explanation(explanation)


def validate_explanation(explanation) -> None:
    if len(str(explanation or "").strip()) < 5:
        raise ValidationError("An explanation of at least 5 characters is required.")


def validate_manual_add(entry: dict, roster_vendor_ids, current_period: str) -> None:
    if str(entry.get("period")) != str(current_period):
        raise ValidationError("Manual adds are allowed in the current period only.")
    for f in ("vendor", "vendor_id", "dept", "location", "item"):
        if not str(entry.get(f) or "").strip():
            raise ValidationError(f"Manual add needs {f.replace('_', ' ')}.")
    if str(entry["vendor_id"]).strip() in set(roster_vendor_ids):
        raise ValidationError("Vendor is on the roster; use an override instead of a manual add.")
    acct = str(entry.get("gl_account") or "").strip()
    if not (acct.isdigit() and len(acct) == 5):
        raise ValidationError("Account must be 5 digits.")
    try:
        amount = D(entry.get("amount"))
    except ValueError as exc:
        raise ValidationError("Amount must be a number.") from exc
    if amount <= 0:
        raise ValidationError("Manual add amount must be greater than $0.")
    validate_explanation(entry.get("explanation"))


def manual_line(entry: dict, line_type: str = "manual") -> dict:
    acct = int(entry["gl_account"])
    amount = r2(D(entry["amount"]))
    return {
        "key": f"{entry['vendor_id']}|{acct}",
        "vendor_id": str(entry["vendor_id"]),
        "vendor_name": entry["vendor"],
        "gl_account": acct,
        "gl_account_name": entry.get("gl_account_name", ""),
        "vendor_type": "Manual add" if line_type == "manual" else "Carried manual add",
        "owner": entry.get("user", entry.get("owner", "")),
        "line_type": line_type,
        "annual_budget": None, "budget_source": None, "budget_ytd": None, "phased_budget_ytd": None,
        "gl_total_ytd": ZERO, "spend_ytd": ZERO, "buckets": {}, "prior_year_service": ZERO,
        "prepaid_included": ZERO, "after_cutoff": ZERO, "prepaid_next_year": ZERO, "posted_this_period": ZERO,
        "liability_opening": None, "liability_prior_year_bills": ZERO, "liability_remaining": ZERO,
        "liability_basis": None,
        "formula_accrual": None, "accrual_rule": None, "standing": None, "override": None,
        "final_accrual": amount,
        "applied_by": "manual add" if line_type == "manual" else "carried manual add",
        "prior_formula": None,
        "manual": {
            "id": entry.get("id"), "explanation": entry.get("explanation", ""), "user": entry.get("user"),
            "at": entry.get("at"),
        },
        "manual_dims": {"dept": entry.get("dept", ""), "location": entry.get("location", ""),
                        "item": entry.get("item", "")},
    }


def apply_overrides(lines: list[dict], overrides: dict) -> None:
    """A current-month override always wins. The formula value stays visible on the line."""
    for line in lines:
        o = overrides.get(line["key"])
        if o:
            line["override"] = dict(o)
            line["final_accrual"] = r2(D(o["amount"]))
            line["applied_by"] = "override"
