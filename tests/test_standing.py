"""Standing rules: each type, paid-through, unbilled months and every flag threshold."""
from datetime import date

import pytest

from accrual_workbook.engine import model
from accrual_workbook.engine.model import State
from accrual_workbook.engine.period import Period
from accrual_workbook.engine.standing import unbilled_months
from helpers import D, budget, config, gl, inputs, monthly_bills, roster

SEP = Period.parse("2026-09")


def cfg_with(*rules, carried=(), **extra):
    return config(standing={"baseline_month": "2026-08", "rules": list(rules), "carried_manual_adds": list(carried)},
                  **extra)


def run(rows, rules=(), budgets=None, period="2026-09", state=None, carried=(), roster_rows=None):
    budgets = budgets if budgets is not None else [budget("V1", 60100, 12000)]
    return model.run(period, inputs(rows, roster_rows or [roster("V1", 60100)], budgets),
                     cfg_with(*rules, carried=carried), state)


def line(result, key="V1|60100"):
    return next(ln for ln in result["vendor_opex"]["lines"] if ln["key"] == key)


def flags(ln):
    return [f["code"] for f in (ln["standing"] or {}).get("flags", [])]


def rule(**kw):
    return {"vendor_id": "V1", "gl_account": 60100, **kw}


# ---------- unbilled months ----------

@pytest.mark.parametrize("paid_through,granularity,expected", [
    (date(2026, 7, 31), "monthly", "2"),       # Aug + Sep
    (date(2026, 8, 15), "monthly", "1"),       # whole months only
    (date(2026, 8, 15), "half_month", "1.5"),  # on/before the 15th -> +0.5
    (date(2026, 8, 16), "half_month", "1"),    # after the 15th -> no half
    (date(2026, 2, 28), "half_month", "7"),    # last day of month -> no half
    (date(2026, 9, 10), "half_month", "0.5"),  # within the cutoff month
    (date(2026, 9, 30), "half_month", "0"),    # paid through month-end
    (date(2026, 10, 31), "monthly", "0"),      # billed ahead
])
def test_unbilled_months(paid_through, granularity, expected):
    assert unbilled_months(paid_through, SEP, granularity) == D(expected)


def test_unbilled_months_none_without_dated_bill():
    assert unbilled_months(None, SEP) is None


# ---------- rule types ----------

def test_zero_rule_sets_zero_and_auto_applies_without_flags():
    ln = line(run(monthly_bills("V1", 60100, 500, range(1, 9)), [rule(type="zero", reason="receipts")]))
    assert ln["formula_accrual"] == D("5000.00")
    assert ln["final_accrual"] == D("0.00")
    assert ln["standing"]["status"] == "Auto-applied"


def test_unbilled_monthly_rate_times_months_after_paid_through():
    rows = monthly_bills("V1", 60100, 1000, range(1, 8))  # paid through 7/31
    ln = line(run(rows, [rule(type="unbilled", rate=1000)]))
    assert ln["final_accrual"] == D("2000.00")


def test_unbilled_half_month():
    rows = monthly_bills("V1", 60100, 2000, range(1, 8)) + [gl("V1", 60100, 1000, "2026-08-20", "2026-08-01",
                                                               "2026-08-15")]
    ln = line(run(rows, [rule(type="unbilled", rate=2000, granularity="half_month")]))
    assert ln["final_accrual"] == D("3000.00")  # 1.5 x 2,000


def test_unbilled_without_dated_bill_accrues_one_month_and_flags():
    ln = line(run([], [rule(type="unbilled", rate=750)]))
    assert ln["final_accrual"] == D("750.00")
    assert "no_dated_bill" in flags(ln)
    assert ln["standing"]["status"] == "Review"


def test_paid_through_ignores_bills_spanning_more_than_100_days():
    rows = monthly_bills("V1", 60100, 1000, range(1, 8)) + [
        gl("V1", 60100, 9000, "2026-08-05", "2026-02-01", "2026-10-31")]  # 272 days -> ignored
    ln = line(run(rows, [rule(type="unbilled", rate=1000)]))
    assert ln["standing"]["paid_through"] == date(2026, 7, 31)
    assert ln["final_accrual"] == D("2000.00")


def test_paid_through_uses_end_of_service_month_for_undated_bill():
    rows = [gl("V1", 60100, 1000, "2026-08-05", memo="Services July 2026")]
    ln = line(run(rows, [rule(type="unbilled", rate=1000)]))
    assert ln["standing"]["paid_through"] == date(2026, 7, 31)


def test_avg_less_billed():
    rows = monthly_bills("V1", 60100, 1075, range(1, 9)) + [gl("V1", 60100, 400, "2026-09-28", "2026-09-01",
                                                               "2026-09-15")]
    ln = line(run(rows, [rule(type="avg_less_billed")]))
    # spend 8,600 + 400 = 9,000; avg 1,000/month; less 400 billed for Sep = 600
    assert ln["final_accrual"] == D("600.00")


def test_avg_less_billed_zero_when_paid_through_month_end():
    rows = monthly_bills("V1", 60100, 1000, range(1, 10))
    assert line(run(rows, [rule(type="avg_less_billed")]))["final_accrual"] == D("0.00")


def test_rate_unless_billed():
    billed = monthly_bills("V1", 60100, 2100, range(1, 10))
    unbilled = monthly_bills("V1", 60100, 2100, range(1, 9))
    assert line(run(billed, [rule(type="rate_unless_billed", rate=2500)]))["final_accrual"] == D("0.00")
    assert line(run(unbilled, [rule(type="rate_unless_billed", rate=2500)]))["final_accrual"] == D("2500.00")


def test_budget_rule_uses_formula():
    ln = line(run(monthly_bills("V1", 60100, 500, range(1, 9)), [rule(type="budget")]))
    assert ln["final_accrual"] == ln["formula_accrual"] == D("5000.00")


def test_baseline_month_previews_only():
    ln = line(run([], [rule(type="zero", reason="receipts")], period="2026-08"))
    assert ln["standing"]["status"] == "Preview"
    assert ln["final_accrual"] == ln["formula_accrual"] == D("8000.00")


def test_current_month_override_beats_standing_rule():
    state = State(overrides={"V1|60100": {"amount": D(1234), "explanation": "Vendor confirmed", "user": "u"}})
    ln = line(run([], [rule(type="zero", reason="receipts")], state=state))
    assert ln["final_accrual"] == D("1234.00")
    assert ln["applied_by"] == "override"


# ---------- generic paid-through rule ----------

def test_generic_rule_zeroes_vendor_billed_through_month_end():
    rows = monthly_bills("V1", 60100, 500, range(1, 10))
    ln = line(run(rows))
    assert ln["formula_accrual"] == D("4500.00")
    assert ln["final_accrual"] == D("0.00")
    assert flags(ln) == []  # below 10K


def test_paid_through_ignores_bills_dated_only_by_posting_month():
    """An arrears bill posted in September with no dates or memo must not look 'billed through 9/30'."""
    rows = monthly_bills("V1", 60100, 1000, range(1, 8)) + [gl("V1", 60100, 1000, "2026-09-12", memo="Invoice")]
    ln = line(run(rows, [rule(type="unbilled", rate=1000)]))
    assert ln["standing"]["paid_through"] == date(2026, 7, 31)
    assert ln["final_accrual"] == D("2000.00")


def test_generic_rule_not_triggered_by_posting_month_bill():
    rows = monthly_bills("V1", 60100, 500, range(1, 9)) + [gl("V1", 60100, 500, "2026-09-12", memo="Invoice")]
    ln = line(run(rows))
    assert ln["standing"] is None
    assert ln["final_accrual"] == ln["formula_accrual"] == D("4500.00")  # 9,000 - 4,500


def test_generic_rule_keeps_unpaid_prior_year_liability():
    rows = monthly_bills("V1", 60100, 900, range(1, 10))
    cfg = cfg_with(prior_year_liability=[{"vendor_id": "V1", "gl_account": 60100, "opening": 3000}])
    r = model.run("2026-09", inputs(rows, [roster("V1", 60100)], [budget("V1", 60100, 12000)]), cfg)
    ln = line(r)
    assert ln["formula_accrual"] == D("3900.00")      # 9,000 + 3,000 - 8,100
    assert ln["final_accrual"] == D("3000.00")        # billed through 9/30: only the prior-year liability
    assert "prior-year liability" in ln["standing"]["basis"]


def test_generic_rule_flags_removing_formula_of_10k_or_more():
    rows = monthly_bills("V1", 60100, 1000, range(1, 10))
    ln = line(run(rows, budgets=[budget("V1", 60100, "25333.33")]))  # YTD 19,000.00 -> formula 10,000.00
    assert ln["formula_accrual"] == D("10000.00")
    assert flags(ln) == ["paid_through_removal"]
    ln = line(run(rows, budgets=[budget("V1", 60100, "25333.32")]))  # YTD 18,999.99 -> formula 9,999.99
    assert flags(ln) == []


# ---------- flags ----------

def test_flag_budget_change_needs_20_pct_and_5k():
    def f(current, baseline):
        r = rule(type="budget", baseline={"annual_budget": baseline})
        return flags(line(run([], [r], budgets=[budget("V1", 60100, current)])))
    assert "budget_change" in f(120000, 100000)       # +20%, +20K
    assert "budget_change" not in f(119999, 100000)   # 19.999%
    assert "budget_change" not in f(14000, 10000)     # +40% but only 4K


def test_flag_spend_change_needs_50_pct_and_5k_vs_expected():
    def f(spend_each):
        r = rule(type="budget", baseline={"monthly_spend": 2000})  # expected 9 x 2,000 = 18,000
        return flags(line(run(monthly_bills("V1", 60100, spend_each, range(1, 10)), [r],
                              budgets=[budget("V1", 60100, 30000)])))
    assert "spend_change" in f("3000.00")      # 27,000: +50%, +9,000
    assert "spend_change" not in f("2900.00")  # 26,100: +45%


def test_flag_spend_change_abs_threshold():
    r = rule(type="budget", baseline={"monthly_spend": 100})  # expected 900
    ln = line(run(monthly_bills("V1", 60100, 1000, range(1, 10)), [r], budgets=[budget("V1", 60100, 30000)]))
    assert "spend_change" in flags(ln)  # 9,000 vs 900: +900%, +8,100
    r = rule(type="budget", baseline={"monthly_spend": 10})  # expected 90 vs 900: +900% but only 810
    ln = line(run(monthly_bills("V1", 60100, 100, range(1, 10)), [r], budgets=[budget("V1", 60100, 30000)]))
    assert "spend_change" not in flags(ln)


def test_flag_new_bill_on_zero_vendor():
    sep_bill = [gl("V1", 60100, 450, "2026-09-10", "2026-09-01", "2026-09-30")]
    aug_bill = [gl("V1", 60100, 450, "2026-08-10", "2026-08-01", "2026-08-31")]
    z = rule(type="zero", reason="receipts")
    assert "new_bill_on_zero" in flags(line(run(sep_bill, [z])))
    assert "new_bill_on_zero" not in flags(line(run(aug_bill, [z])))


def test_flag_billed_in_full_term_ending():
    ending = rule(type="zero", reason="billed_in_full", billed_through="2026-10-31")
    later = rule(type="zero", reason="billed_in_full", billed_through="2026-11-30")
    assert "term_ending" in flags(line(run([], [ending])))
    assert "term_ending" not in flags(line(run([], [later])))


def test_confirming_a_flagged_line_marks_it_reviewed():
    r = rule(type="unbilled", rate=750)
    assert line(run([], [r]))["standing"]["status"] == "Review"
    ln = line(run([], [r], state=State(standing_confirmed={"V1|60100"})))
    assert ln["standing"]["status"] == "Reviewed"


# ---------- carried-forward manual adds ----------

CARRIED = {"vendor": "Shuttle Co", "vendor_id": "V7", "gl_account": 65100, "type": "fixed", "amount": 1800,
           "dept": "D1", "location": "L1", "item": "I1", "explanation": "Quarterly invoices"}


def test_carried_manual_add_applies_after_baseline_with_flag_on_new_bill():
    rows = [gl("V7", 65100, 5400, "2026-09-15", "2026-07-01", "2026-09-30")]
    r = run(rows, carried=[CARRIED])
    ln = line(r, "V7|65100")
    assert ln["final_accrual"] == D("1800.00")
    assert flags(ln) == ["new_bill"]


def test_carried_manual_add_previews_in_baseline_month():
    r = run([], carried=[CARRIED], period="2026-08")
    assert all(ln["key"] != "V7|65100" for ln in r["vendor_opex"]["lines"])
    assert any(t["key"] == "V7|65100" and t["status"] == "Preview" for t in r["standing"]["table"])


def test_current_manual_add_beats_carried_manual_add():
    state = State(manual_adds=[{"period": "2026-09", "vendor": "Shuttle Co", "vendor_id": "V7", "gl_account": 65100,
                                "amount": D(900), "dept": "D1", "location": "L1", "item": "I1",
                                "explanation": "Revised estimate"}])
    r = run([], carried=[CARRIED], state=state)
    v7 = [ln for ln in r["vendor_opex"]["lines"] if ln["key"] == "V7|65100"]
    assert [(ln["line_type"], ln["final_accrual"]) for ln in v7] == [("manual", D("900.00"))]
