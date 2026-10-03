"""Vendor OpEx formula. Every expected value is hand-computed in the comment beside it."""
from accrual_workbook.engine import model
from accrual_workbook.engine.vendor_opex import budget_ytd, formula_accrual, liability_remaining
from helpers import D, budget, config, gl, inputs, monthly_bills, roster


def run(gl_rows=(), roster_rows=(), budget_rows=(), cfg=None, period="2026-09", state=None):
    return model.run(period, inputs(gl_rows, roster_rows, budget_rows), cfg or config(), state)


def line(result, key):
    return next(ln for ln in result["vendor_opex"]["lines"] if ln["key"] == key)


# ---------- Budget YTD ----------

def test_budget_ytd_rounds_half_up_to_cents():
    assert budget_ytd(D(10000), 7) == D("5833.33")      # 10,000 x 7 / 12 = 5,833.333...
    assert budget_ytd(D("1000.10"), 5) == D("416.71")   # 1,000.10 x 5 / 12 = 416.7083...
    assert budget_ytd(D("12.30"), 1) == D("1.03")       # 1.025 -> half-up 1.03 (banker's would give 1.02)


def test_budget_ytd_uses_months_elapsed_for_the_period():
    r = run(roster_rows=[roster("V1", 60100)], budget_rows=[budget("V1", 60100, 24000)])
    assert line(r, "V1|60100")["budget_ytd"] == D("18000.00")  # 24,000 x 9 / 12


def test_budget_ytd_falls_back_to_roster_spread_when_no_budget_line():
    r = run(roster_rows=[roster("V1", 60100, spread="4321.55")])
    ln = line(r, "V1|60100")
    assert ln["annual_budget"] is None
    assert ln["budget_ytd"] == D("4321.55")
    assert ln["budget_source"] == "roster spread"


# ---------- formula ----------

def test_formula_accrual_is_budget_plus_liability_less_spend():
    assert formula_accrual(D(9000), D(500), D(6000)) == D("3500.00")


def test_formula_accrual_floors_at_zero():
    assert formula_accrual(D(9000), D(0), D(9500)) == D("0.00")
    r = run(monthly_bills("V1", 60100, "1100", range(1, 10)), [roster("V1", 60100)], [budget("V1", 60100, 12000)])
    ln = line(r, "V1|60100")
    assert ln["spend_ytd"] == D("9900.00")       # 9 x 1,100
    assert ln["formula_accrual"] == D("0.00")    # 9,000 - 9,900 < 0 -> 0


def test_formula_accrual_on_partial_spend():
    r = run(monthly_bills("V1", 60100, 1000, range(1, 7)), [roster("V1", 60100)], [budget("V1", 60100, 12000)])
    assert line(r, "V1|60100")["formula_accrual"] == D("3000.00")  # 9,000 - 6,000


# ---------- prior-year liability ----------

def test_prior_year_liability_from_config_opening_less_prior_year_bills():
    rows = monthly_bills("V1", 60100, 1000, range(1, 7)) + [
        gl("V1", 60100, 2000, "2026-01-10", "2025-12-01", "2025-12-31")]  # prior-year service bill
    cfg = config(prior_year_liability=[{"vendor_id": "V1", "gl_account": 60100, "opening": 5000}])
    ln = line(run(rows, [roster("V1", 60100)], [budget("V1", 60100, 12000)], cfg), "V1|60100")
    assert ln["prior_year_service"] == D("2000.00")
    assert ln["spend_ytd"] == D("6000.00")              # prior-year service is excluded from spend
    assert ln["liability_remaining"] == D("3000.00")     # MAX(5,000 - 2,000, 0)
    assert ln["formula_accrual"] == D("6000.00")         # 9,000 + 3,000 - 6,000


def test_prior_year_liability_never_negative():
    assert liability_remaining(D(1000), D(1500)) == D("0.00")


def test_prior_year_liability_uses_roster_value_without_config_and_ignores_prior_year_bills():
    rows = monthly_bills("V1", 60100, 1000, range(1, 7)) + [
        gl("V1", 60100, 2000, "2026-01-10", "2025-12-01", "2025-12-31")]
    ln = line(run(rows, [roster("V1", 60100, liability=2500)], [budget("V1", 60100, 12000)]), "V1|60100")
    assert ln["liability_remaining"] == D("2500.00")
    assert ln["formula_accrual"] == D("5500.00")  # 9,000 + 2,500 - 6,000


def test_vendor_without_prior_year_liability_ignores_prior_year_bills():
    rows = monthly_bills("V1", 60100, 1000, range(1, 10)) + [
        gl("V1", 60100, 5000, "2026-01-09", "2025-12-01", "2025-12-31")]
    ln = line(run(rows, [roster("V1", 60100)], [budget("V1", 60100, 12000)]), "V1|60100")
    assert ln["liability_remaining"] == D("0.00")
    assert ln["spend_ytd"] == D("9000.00")
    assert ln["formula_accrual"] == D("0.00")


# ---------- regression tests ----------

def test_regression_annual_budget_must_not_be_compared_with_ytd_spend():
    """Bug guarded: comparing the ANNUAL budget (180,000) with YTD spend would accrue 36,000."""
    rows = monthly_bills("V1", 60200, 16000, range(1, 10))
    r = run(rows, [roster("V1", 60200)], [budget("V1", 60200, 180000)])
    ln = line(r, "V1|60200")
    assert ln["budget_ytd"] == D("135000.00")   # 180,000 x 9 / 12
    assert ln["spend_ytd"] == D("144000.00")    # 16,000 x 9
    assert ln["formula_accrual"] == D("0.00")
    over = next(o for o in r["over_budget"] if o["key"] == "V1|60200")
    assert over["over_by"] == D("9000.00")


def test_regression_spend_matched_on_vendor_and_account_not_vendor_only():
    """Bug guarded: two roster lines for one vendor must not absorb each other's spend."""
    rows = monthly_bills("V1", 61100, 1000, range(1, 10))  # 9,000 all on 61100
    r = run(rows, [roster("V1", 61100), roster("V1", 65300)],
            [budget("V1", 61100, 12000), budget("V1", 65300, 12000)])
    assert line(r, "V1|61100")["spend_ytd"] == D("9000.00")
    assert line(r, "V1|61100")["formula_accrual"] == D("0.00")
    assert line(r, "V1|65300")["spend_ytd"] == D("0.00")
    assert line(r, "V1|65300")["formula_accrual"] == D("9000.00")


# ---------- config: budget overrides, excluded lines, accrual rules, removed lines ----------

def test_budget_override_replaces_annual_budget():
    cfg = config(budget={"overrides": [{"vendor_id": "V1", "gl_account": 60100, "annual": 45000}]})
    ln = line(run([], [roster("V1", 60100)], [budget("V1", 60100, 30000)], cfg), "V1|60100")
    assert ln["annual_budget"] == D("45000.00")
    assert ln["budget_ytd"] == D("33750.00")  # 45,000 x 9 / 12
    assert ln["budget_source"] == "override"


def test_excluded_budget_line_falls_back_to_roster_spread():
    cfg = config(budget={"excluded_lines": [{"vendor_id": "V1", "gl_account": 60100}]})
    ln = line(run([], [roster("V1", 60100, spread=7500)], [budget("V1", 60100, 24000)], cfg), "V1|60100")
    assert ln["budget_ytd"] == D("7500.00")


def test_accrual_rule_forces_zero_and_keeps_formula_visible():
    cfg = config(accrual_rules=[{"vendor_id": "V1", "gl_account": 60100, "label": "Received monthly via receipts"}])
    ln = line(run([], [roster("V1", 60100)], [budget("V1", 60100, 12000)], cfg), "V1|60100")
    assert ln["formula_accrual"] == D("9000.00")
    assert ln["final_accrual"] == D("0.00")
    assert ln["accrual_rule"] == "Received monthly via receipts"


def test_removed_roster_line_is_not_accrued():
    cfg = config(roster={"removed_lines": [{"vendor_id": "V1", "gl_account": 60100}]})
    r = run([], [roster("V1", 60100), roster("V2", 60100)], [budget("V1", 60100, 12000)], cfg)
    assert [ln["key"] for ln in r["vendor_opex"]["lines"]] == ["V2|60100"]


# ---------- prior formula ----------

def test_prior_formula_is_last_months_formula_on_last_months_data():
    # 800/month posted in the service month. Aug: 8,000 - 6,400 = 1,600. Sep: 9,000 - 7,200 = 1,800.
    rows = monthly_bills("V1", 60100, 800, range(1, 10))
    ln = line(run(rows, [roster("V1", 60100)], [budget("V1", 60100, 12000)]), "V1|60100")
    assert ln["prior_formula"] == D("1600.00")
    assert ln["formula_accrual"] == D("1800.00")
