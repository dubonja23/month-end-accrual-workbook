"""Month-over-month driver classification and the large-swing threshold."""
import pytest

from accrual_workbook.engine import mom
from helpers import D, config

CFG = config()


def g(prior_bills=0, prior_accrual=0, prior_reversal=0, current_bills=0, current_reversal=None, other=0):
    return {"vendor_id": "V1", "vendor": "Vendor 1", "gl_account": 60100, "prior_bills": D(prior_bills),
            "prior_accrual": D(prior_accrual), "prior_reversal": D(prior_reversal),
            "current_bills": D(current_bills),
            "current_reversal": D(prior_accrual if current_reversal is None else current_reversal), "other": D(other)}


def roster_line(**kw):
    base = {"line_type": "roster", "applied_by": "formula", "budget_ytd": D(9000), "spend_ytd": D(6000),
            "formula_accrual": D(3000), "standing": None, "accrual_rule": None, "override": None}
    base.update(kw)
    return base


def build(gl_row, accrual=None, line=None):
    current = {} if accrual is None else {"V1|60100": {"accrual": D(accrual), "vendor_name": "Vendor 1",
                                                       "line": line or roster_line()}}
    return mom.build([gl_row], current, CFG, {}, {"60100": "Professional Services"})["rows"][0]


@pytest.mark.parametrize("gl_row,accrual,line,driver", [
    (g(1000, 500, 400, 3000), 500, None, mom.BILLS_CHANGED),
    (g(1000, 500, 500, 1000), 2000, None, mom.ACCRUAL_CHANGED),
    (g(1000, 0, 0, 1000), 2000, None, mom.NEW_ACCRUAL),
    (g(1000, 2000, 0, 1000), 0, None, mom.ACCRUAL_NOW_ZERO),
    (g(1000, 2000, 0, 1000), 0, roster_line(spend_ytd=D(9500)), mom.OVER_BUDGET_ZERO),
    (g(1000, 2000, 0, 1000), None, None, mom.NOT_REBOOKED),
    (g(1000, 2000, 0, 1000), 2500, roster_line(applied_by="override",
                                               override={"explanation": "Vendor quote"}), mom.OVERRIDDEN),
    (g(0, 0, 0, 0), 900, roster_line(line_type="manual", manual={"explanation": "Offsite"}), mom.MANUAL_ADD),
    (g(1000, 500, 500, 1000), 500, None, mom.NO_CHANGE),
])
def test_driver_classification(gl_row, accrual, line, driver):
    row = build(gl_row, accrual, line)
    assert row["driver"] == driver
    assert row["why"].endswith(".")


def test_mom_totals():
    # prior total = 1,000 + 500 - 400 = 1,100; current GL = 3,000 - 500 = 2,500; + accrual 500 = 3,000
    row = build(g(1000, 500, 400, 3000), 500)
    assert (row["prior_total"], row["current_gl"], row["current_total"], row["mom"]) == \
        (D(1100), D(2500), D(3000), D(1900))


def test_explanation_sentence():
    row = build(g(1000, 0, 0, 1000), 20000)
    assert row["why"] == "Up $20,000.00 (2000%): new accrual of $20,000.00 this month."


@pytest.mark.parametrize("mom_amt,prior,large", [
    (10000, 40000, True),       # 10K and 25%
    (-10000, 40000, True),      # direction does not matter
    ("9999.99", 20000, False),  # under 10K
    (10000, 40001, False),      # 24.99%
    (10000, 0, True),           # from $0
])
def test_large_swing_threshold(mom_amt, prior, large):
    assert mom.is_large_swing(D(mom_amt), D(prior), CFG) is large


def test_account_level_explanation_and_review_counts():
    # V1: new 15,000 accrual (large swing, reviewed). V2: 30,000 billed last month, 30,000 accrued now (flat).
    rows = [g(0, 0, 0, 0), {**g(30000, 0, 0, 0), "vendor_id": "V2", "vendor": "Vendor 2"}]
    current = {"V1|60100": {"accrual": D(15000), "vendor_name": "Vendor 1", "line": roster_line()},
               "V2|60100": {"accrual": D(30000), "vendor_name": "Vendor 2", "line": roster_line()}}
    res = mom.build(rows, current, CFG, {"V1|60100": {"user": "u", "at": "t"}}, {"60100": "Professional Services"})
    assert res["large_swings"] == 1 and res["large_swings_reviewed"] == 1
    assert res["accounts"][0]["why"].startswith("Up $15,000.00 (50%) vs last month, driven mainly by Vendor 1")
