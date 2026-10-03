"""Journal entry: lines, dimensions, ordering, tie-out checks and exports."""
import csv
import io
from datetime import date

from accrual_workbook.engine import journal, model
from accrual_workbook.engine.model import State
from helpers import D, budget, capex_row, config, dims_row, gl, inputs, monthly_bills, roster

LEGAL = [{"vendor": "Firm A", "vendor_id": "LA", "amount": D(5000), "customer": "C1", "project": "P1",
          "dept": "D1", "location": "L1", "item": "I-LEGAL"}]
TRACKER = [capex_row("Deal A", "P1", "VC1", "Framing", 100000, 100000, 50, 20000)]  # 30,000


def scenario(cfg=None, state=None):
    rows = (monthly_bills("V1", 60100, 1000, range(1, 7))      # V1 formula 3,000
            + monthly_bills("V2", 62100, 500, range(1, 8))     # V2 formula 12,000 - ... see below
            + [gl("V3", 60200, 100, "2026-03-10", "2026-03-01", "2026-03-31", dept="Finance", loc="Main Office")])
    inp = inputs(rows, [roster("V1", 60100), roster("V2", 62100), roster("V3", 60200)],
                 [budget("V1", 60100, 12000), budget("V2", 62100, 24000), budget("V3", 60200, 1200)],
                 legal_rows=LEGAL, capex_rows=TRACKER,
                 je_dims=[dims_row("V1", 60100, "D1", "L1", "I1", "prior_je"),
                          dims_row("V1", 60100, "D9", "L9", "I9", "latest_bill"),
                          dims_row("V2", 62100, "D2", "L1", "I2", "latest_bill")])
    inp.dim_names = {"dept": {"D1": "Finance", "D2": "Ops"}, "location": {"L1": "Main Office"},
                     "account": {"60100": "Professional Services", "20500": "Accrued Expenses"}}
    return model.run("2026-09", inp, cfg or config(), state)


def test_je_balances_and_header():
    je = scenario()["je"]
    assert je["total_debits"] == je["total_credits"]
    assert je["header"]["memo"] == "OPEX - Accruals - Sep2026"
    assert je["header"]["date"] == date(2026, 9, 30)
    assert je["header"]["reverse_date"] == date(2026, 10, 1)


def test_je_amounts_by_section():
    r = scenario()
    je = r["je"]
    # V1: 9,000 - 6,000 = 3,000. V2: 18,000 - 3,500 = 14,500. V3: 900 - 100 = 800.
    opex = sorted(ln["debit"] for ln in je["lines"] if ln["section"] == "Vendor OpEx" and ln["side"] == "debit")
    assert opex == [D("800.00"), D("3000.00"), D("14500.00")]
    assert journal.section_debits(je["lines"], "Legal") == D("5000.00")
    assert journal.section_debits(je["lines"], "Capex Projects") == D("30000.00")


def test_every_debit_has_matching_credit_with_identical_dimensions():
    je = scenario()["je"]
    assert journal.debit_credit_pairs_match(je["lines"])
    assert all(ln["acct"] == 20500 for ln in je["lines"] if ln["side"] == "credit")


def test_layout_debits_ascending_then_credits_in_same_order_per_section():
    lines = scenario()["je"]["lines"]
    opex = [ln for ln in lines if ln["section"] == "Vendor OpEx"]
    sides = [ln["side"] for ln in opex]
    assert sides == ["debit"] * 3 + ["credit"] * 3
    debits = [ln["debit"] for ln in opex[:3]]
    assert debits == sorted(debits)
    assert [ln["credit"] for ln in opex[3:]] == debits
    assert [ln["line_no"] for ln in lines] == list(range(1, len(lines) + 1))


def test_dimensions_prior_je_beats_latest_bill_then_gl_fallback_then_missing():
    lines = {ln["vendor_id"]: ln for ln in scenario()["je"]["lines"] if ln["side"] == "debit"}
    assert (lines["V1"]["dept"], lines["V1"]["dims_source"]) == ("D1", "prior_je")
    assert (lines["V2"]["dept"], lines["V2"]["dims_source"]) == ("D2", "latest_bill")
    # V3 has no je_dims row: names from its latest bill mapped back to IDs
    assert (lines["V3"]["dept"], lines["V3"]["location"], lines["V3"]["dims_source"]) == ("D1", "L1", "latest_bill")


def test_missing_dimensions_are_flagged():
    rows = monthly_bills("V4", 60100, 100, range(1, 3))
    for r in rows:
        r["department_name"] = r["location_name"] = ""
    res = model.run("2026-09", inputs(rows, [roster("V4", 60100)], [budget("V4", 60100, 12000)]), config())
    debit = next(ln for ln in res["je"]["lines"] if ln["side"] == "debit")
    assert debit["missing_dims"] == ["dept", "location"]
    assert any(a["key"] == "dims|V4|60100" for a in res["attention_candidates"])


def test_all_four_tie_out_checks_pass():
    checks = {c["name"]: c["ok"] for c in scenario()["je"]["checks"]}
    assert checks == {"Debits = Credits": True, "Vendor OpEx = Tab 2": True, "Legal = Tab 3": True,
                      "Capex = Tab 4": True}


def test_dept_split_rounding_difference_goes_to_first_part():
    shares = [{"dept": "A", "share": 0.5}, {"dept": "B", "share": 0.25}, {"dept": "C", "share": 0.25}]
    # 10,000.02 -> 5,000.01 + 2,500.01 + 2,500.01 = 10,000.03; the -0.01 goes to A
    assert journal.dept_split(D("10000.02"), shares) == [("A", D("5000.00")), ("B", D("2500.01")),
                                                         ("C", D("2500.01"))]


def test_dept_split_in_je_ties_out():
    cfg = config(je={"dept_splits": [{"vendor_id": "V2", "gl_account": 62100,
                                      "shares": [{"dept": "D1", "share": 0.6}, {"dept": "D2", "share": 0.4}]}]})
    je = scenario(cfg)["je"]
    v2 = [ln for ln in je["lines"] if ln["vendor_id"] == "V2" and ln["side"] == "debit"]
    assert sorted((ln["dept"], ln["debit"]) for ln in v2) == [("D1", D("8700.00")), ("D2", D("5800.00"))]
    assert je["ok"]


def test_broken_dept_split_makes_tie_out_fail():
    """Deliberately broken input: shares add to 90%, so the JE no longer ties to the Vendor OpEx tab."""
    cfg = config(je={"dept_splits": [{"vendor_id": "V2", "gl_account": 62100,
                                      "shares": [{"dept": "D1", "share": 0.5}, {"dept": "D2", "share": 0.4}]}]})
    je = scenario(cfg)["je"]
    checks = {c["name"]: c for c in je["checks"]}
    assert checks["Vendor OpEx = Tab 2"]["ok"] is False
    assert checks["Vendor OpEx = Tab 2"]["difference"] == D("-1450.00")  # 10% of 14,500 missing
    assert je["ok"] is False


def test_override_flows_through_to_je():
    state = State(overrides={"V1|60100": {"amount": D("4321.00"), "explanation": "Vendor estimate", "user": "u"}})
    r = scenario(state=state)
    v1 = next(ln for ln in r["vendor_opex"]["lines"] if ln["key"] == "V1|60100")
    assert (v1["formula_accrual"], v1["final_accrual"]) == (D("3000.00"), D("4321.00"))
    debit = next(ln for ln in r["je"]["lines"] if ln["vendor_id"] == "V1" and ln["side"] == "debit")
    assert debit["debit"] == D("4321.00")
    assert r["je"]["ok"]


def test_override_to_zero_removes_je_line():
    state = State(overrides={"V1|60100": {"amount": D(0), "explanation": "Billed in full", "user": "u"}})
    r = scenario(state=state)
    assert not any(ln["vendor_id"] == "V1" for ln in r["je"]["lines"])


def test_manual_add_flows_through_to_je_with_its_dimensions():
    state = State(manual_adds=[{"id": 1, "period": "2026-09", "vendor": "New Vendor", "vendor_id": "V8",
                                "gl_account": 65100, "amount": D("2500"), "dept": "D2", "location": "L1",
                                "item": "I8", "explanation": "Offsite deposit", "user": "u"}])
    r = scenario(state=state)
    debit = next(ln for ln in r["je"]["lines"] if ln["vendor_id"] == "V8" and ln["side"] == "debit")
    assert (debit["acct"], debit["debit"], debit["dept"], debit["item"], debit["dims_source"]) == \
        (65100, D("2500.00"), "D2", "I8", "manual add")
    assert r["je"]["ok"]


def test_upload_csv_columns_and_rows():
    je = scenario()["je"]
    rows = list(csv.DictReader(io.StringIO(journal.upload_csv(je))))
    assert list(rows[0].keys()) == journal.UPLOAD_COLUMNS
    assert len(rows) == len(je["lines"])
    assert rows[0]["DATE"] == "09/30/2026" and rows[0]["REVERSEDATE"] == "10/01/2026"
    debits = sum(D(r["DEBIT"] or 0) for r in rows)
    credits = sum(D(r["CREDIT"] or 0) for r in rows)
    assert debits == credits == je["total_debits"]
