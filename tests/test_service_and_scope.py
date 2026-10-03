"""Scope filter, service-month priority, prepaids and rollups."""
import pytest

from accrual_workbook.engine import model
from accrual_workbook.engine.period import Period
from accrual_workbook.engine.scope import apply_scope
from accrual_workbook.engine.service import assign_service_month, parse_memo_month, prepaid_split
from helpers import D, budget, config, gl, inputs, monthly_bills, roster


def line(result, key):
    return next(ln for ln in result["vendor_opex"]["lines"] if ln["key"] == key)


# ---------- service-month priority ----------

def test_service_month_priority_1_service_period_field_is_confirmed():
    row = gl(svc_from="2026-03-01", svc_to="2026-03-31", memo="April 2026 services", posted="2026-05-10")
    assert assign_service_month(row, config()) == ("2026-03", "Service period", "Confirmed")


def test_service_month_field_without_dates_counts_as_service_period():
    row = gl(svc_month="2026-02", posted="2026-05-10")
    assert assign_service_month(row, config()) == ("2026-02", "Service period", "Confirmed")


def test_service_month_priority_2_memo():
    row = gl(memo="Services for April 2026", posted="2026-05-10")
    assert assign_service_month(row, config()) == ("2026-04", "Memo", "Confirmed")


def test_service_month_priority_3_posting_month_is_estimated():
    row = gl(memo="Monthly services", posted="2026-05-10")
    assert assign_service_month(row, config()) == ("2026-05", "Posting month", "Estimated")


@pytest.mark.parametrize("memo,expected", [
    ("Inv 07/2026 localization", "2026-07"),
    ("Service on 03/15/2026", "2026-03"),
    ("Usage 2026-06", "2026-06"),
    ("Translation services - March 2026", "2026-03"),
    ("Sep '26 retainer", "2026-09"),
    ("FY2025 audit fieldwork - Dec 2025", "2025-12"),
    ("No date here", None),
])
def test_memo_month_formats(memo, expected):
    assert parse_memo_month(memo) == expected


def test_service_rule_forces_month_and_source_within_posting_window():
    cfg = config(service_rules=[{"vendor_id": "V1", "accounts": [62200], "posting_from": "2026-09-01",
                                 "posting_to": "2026-09-10", "service_month": "2026-08", "source": "Rule X"}])
    inside = gl("V1", 62200, 100, "2026-09-05")
    outside = gl("V1", 62200, 100, "2026-09-20")
    other_acct = gl("V1", 62100, 100, "2026-09-05")
    assert assign_service_month(inside, cfg) == ("2026-08", "Rule X", "Confirmed")
    assert assign_service_month(outside, cfg)[0] == "2026-09"
    assert assign_service_month(other_acct, cfg)[0] == "2026-09"


# ---------- scope ----------

def test_scope_exclusions_counted_with_reasons():
    cfg = config(scope={"removed_documents": ["DUP-1"], "excluded_accounts": [60510],
                        "corporate_card_vendor_ids": ["CARD"]},
                 legal={"vendor_ids": ["LAW1"], "accounts": [61500]})
    rows = [
        gl("V1", 60100, 100, "2026-09-10"),                      # in scope
        gl("V1", 60100, 100, "2026-10-01"),                      # after cutoff
        gl("V1", 60100, 100, "2026-10-02", journal="GJ"),        # after cutoff wins over journal
        gl("V1", 60100, 100, "2026-09-10", journal="GJ"),        # non-qualifying journal
        gl("V1", 60100, 100, "2026-09-10", journal="CCJ"),       # non-qualifying journal (card)
        gl("CARD", 60100, 100, "2026-09-10"),                    # corporate card vendor on AP
        gl("", 60100, 100, "2026-09-10"),                        # blank vendor
        gl("V1", 60510, 100, "2026-09-10"),                      # excluded commission account
        gl("V1", 70100, 100, "2026-09-10"),                      # out-of-scope account
        gl("LAW1", 61500, 100, "2026-09-10"),                    # legal vendor
        gl("V2", 61500, 100, "2026-09-10"),                      # legal account
        gl("V1", 60100, 100, "2026-09-10", doc="DUP-1"),         # removed document
        gl("V1", 13100, 100, "2026-09-10", journal="UNB"),       # in scope (prepaid, receipts journal)
    ]
    res = apply_scope(rows, cfg, Period.parse("2026-09"))
    assert res.counts == {"removed document": 1, "after cutoff": 2, "non-qualifying journal": 3,
                          "blank vendor": 1, "out-of-scope account": 2, "legal": 2}
    assert len(res.rows) == 2
    assert {r["kind"] for r in res.rows} == {"expense", "prepaid"}


def test_nothing_posted_after_cutoff_is_counted():
    rows = monthly_bills("V1", 60100, 1000, range(1, 9)) + [gl("V1", 60100, 1000, "2026-10-01", "2026-09-01",
                                                                 "2026-09-30")]
    r = model.run("2026-09", inputs(rows, [roster("V1", 60100)], [budget("V1", 60100, 12000)]), config())
    ln = line(r, "V1|60100")
    assert ln["spend_ytd"] == D("8000.00")
    assert ln["formula_accrual"] == D("1000.00")


# ---------- spend components ----------

def test_bills_for_service_after_cutoff_are_included_prior_year_excluded():
    rows = monthly_bills("V1", 60100, 1000, range(1, 9)) + [
        gl("V1", 60100, 4000, "2026-09-22", "2026-10-01", "2026-10-31"),   # billed ahead: included
        gl("V1", 60100, 700, "2026-01-05", "2025-12-01", "2025-12-31"),    # prior-year: excluded
    ]
    ln = line(model.run("2026-09", inputs(rows, [roster("V1", 60100)], [budget("V1", 60100, 12000)]), config()),
              "V1|60100")
    assert ln["after_cutoff"] == D("4000.00")
    assert ln["prior_year_service"] == D("700.00")
    assert ln["spend_ytd"] == D("12000.00")      # 8,000 + 4,000
    assert ln["gl_total_ytd"] == D("12700.00")   # every in-scope row on the line


# ---------- prepaids ----------

def test_prepaid_split_by_days_across_year_end():
    fy = Period(2026, 9)
    assert prepaid_split(D(36500), Period(2026, 7).start, Period(2027, 6).end, fy.fy_start, fy.fy_end) ==         (D(0), D("18400.00"), D("18100.00"))  # 184 of 365 days in 2026
    assert prepaid_split(D(1000), Period(2026, 10).start, Period(2027, 9).end, fy.fy_start, fy.fy_end) ==         (D(0), D("252.05"), D("747.95"))      # next year 273/365 = 747.945... -> 747.95


def test_prepaid_split_by_days_at_year_start():
    fy = Period(2026, 9)
    # 1,200 for 7/1/25-6/30/26: 184 of 365 days are prior-year (604.93, excluded); 595.07 is current
    assert prepaid_split(D(1200), Period(2025, 7).start, Period(2026, 6).end, fy.fy_start, fy.fy_end) ==         (D("604.93"), D("595.07"), D(0))
    # spanning both year-ends: 1,095 for 7/1/25-6/30/27 (730 days): 184 prior, 365 current, 181 next
    assert prepaid_split(D(1095), Period(2025, 7).start, Period(2027, 6).end, fy.fy_start, fy.fy_end) ==         (D("276.00"), D("547.50"), D("271.50"))


def test_prepaid_prior_year_share_is_excluded_from_spend():
    rows = [gl("V1", 13100, 1200, "2026-01-05", "2025-07-01", "2026-06-30")]
    ln = line(model.run("2026-09", inputs(rows, [roster("V1", 63100)], []), config()), "V1|63100")
    assert (ln["prior_year_service"], ln["prepaid_included"], ln["spend_ytd"]) ==         (D("604.93"), D("595.07"), D("595.07"))


def test_prepaid_counts_current_year_share_on_single_roster_line():
    rows = [gl("V1", 13100, 36500, "2026-07-03", "2026-07-01", "2027-06-30")]
    ln = line(model.run("2026-09", inputs(rows, [roster("V1", 63100)], [budget("V1", 63100, 40000)]), config()),
              "V1|63100")
    assert ln["prepaid_included"] == D("18400.00")
    assert ln["prepaid_next_year"] == D("18100.00")
    assert ln["spend_ytd"] == D("18400.00")
    assert ln["formula_accrual"] == D("11600.00")  # 30,000 - 18,400


def test_prepaid_within_the_year_counts_in_full():
    rows = [gl("V1", 13100, 1200, "2026-02-01", "2026-02-01", "2026-11-30")]
    ln = line(model.run("2026-09", inputs(rows, [roster("V1", 63100)], []), config()), "V1|63100")
    assert ln["prepaid_included"] == D("1200.00")
    assert ln["prepaid_next_year"] == D("0")


def test_prepaid_ignored_when_vendor_has_more_than_one_roster_line():
    rows = [gl("V1", 13101, 24000, "2026-02-03", "2026-02-01", "2027-01-31")]
    r = model.run("2026-09", inputs(rows, [roster("V1", 61100), roster("V1", 65300)], []), config())
    assert line(r, "V1|61100")["prepaid_included"] == D("0")
    assert line(r, "V1|65300")["prepaid_included"] == D("0")
    assert [p["amount"] for p in r["vendor_opex"]["prepaid_ignored"]] == [D("24000.00")]
    assert any(a["category"] == "Prepaid" for a in r["attention_candidates"])


# ---------- rollups ----------

def test_account_rollup_moves_spend_and_budget_to_target_line():
    cfg = config(rollups={"account": [{"vendor_id": "V1", "from_account": 61100, "to_account": 61200}]})
    rows = monthly_bills("V1", 61200, 7000, range(1, 9)) + monthly_bills("V1", 61100, 1000, range(1, 9))
    r = model.run("2026-09", inputs(rows, [roster("V1", 61200)],
                                    [budget("V1", 61200, 96000), budget("V1", 61100, 6000)]), cfg)
    ln = line(r, "V1|61200")
    assert ln["annual_budget"] == D("102000")            # 96,000 + 6,000
    assert ln["budget_ytd"] == D("76500.00")              # 102,000 x 9 / 12
    assert ln["spend_ytd"] == D("64000.00")               # 8 x (7,000 + 1,000)
    assert ln["formula_accrual"] == D("12500.00")


def test_account_rollup_only_applies_to_its_vendor():
    cfg = config(rollups={"account": [{"vendor_id": "V1", "from_account": 61100, "to_account": 61200}]})
    rows = monthly_bills("V2", 61100, 1000, range(1, 4))
    r = model.run("2026-09", inputs(rows, [roster("V2", 61200), roster("V2", 61100)], []), cfg)
    assert line(r, "V2|61100")["spend_ytd"] == D("3000.00")
    assert line(r, "V2|61200")["spend_ytd"] == D("0")


def test_vendor_rollup_moves_spend_and_budget_to_target_vendor():
    cfg = config(rollups={"vendor": [{"from_vendor_id": "V9", "to_vendor_id": "V1", "gl_account": 64100}]})
    rows = monthly_bills("V1", 64100, 4000, range(1, 9)) + monthly_bills("V9", 64100, 500, range(1, 10))
    r = model.run("2026-09", inputs(rows, [roster("V1", 64100)],
                                    [budget("V1", 64100, 48000), budget("V9", 64100, 12000)]), cfg)
    ln = line(r, "V1|64100")
    assert ln["annual_budget"] == D("60000")              # 48,000 + 12,000
    assert ln["budget_ytd"] == D("45000.00")
    assert ln["spend_ytd"] == D("36500.00")               # 32,000 + 4,500
    assert ln["formula_accrual"] == D("8500.00")
