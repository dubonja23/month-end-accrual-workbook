"""Legal splits and Capex Projects netting."""
import pytest

from accrual_workbook.engine import capex, legal
from accrual_workbook.engine.model import State
from accrual_workbook.engine.vendor_opex import ValidationError
from helpers import D, capex_row, config

LEGAL_ROWS = [
    {"vendor": "Firm A", "vendor_id": "LA", "amount": D(42500), "customer": "C1", "project": "P1", "dept": "D1",
     "location": "L1", "item": "I-LEGAL"},
    {"vendor": "Firm B", "vendor_id": "LB", "amount": D(18750), "customer": "", "project": "", "dept": "D1",
     "location": "L1", "item": "I-LEGAL"},
]


def test_legal_total_is_sum_of_rows_with_default_gl():
    res = legal.build(LEGAL_ROWS, config(), State())
    assert res["total"] == D("61250.00")
    assert {r["gl"] for r in res["rows"]} == {61500}


def test_legal_split_firm_total_is_sum_of_lines_each_its_own_debit():
    state = State(legal_edits={"LA": {"splits": [
        {"amount": "30000", "gl": "61500", "item": "I-LEGAL", "note": "General"},
        {"amount": "12500.50", "gl": "61600", "item": "I-LIT", "note": "Litigation"},
    ]}})
    res = legal.build(LEGAL_ROWS, config(), state)
    a = res["rows"][0]
    assert a["total"] == D("42500.50")
    assert [(j["gl"], j["amount"]) for j in a["je_lines"]] == [(61500, D("30000.00")), (61600, D("12500.50"))]
    assert res["total"] == D("61250.50")


def test_legal_edit_overrides_fields():
    res = legal.build(LEGAL_ROWS, config(), State(legal_edits={"LB": {"amount": "20000", "project": "P9"}}))
    b = res["rows"][1]
    assert (b["amount"], b["project"], b["edited"]) == (D("20000"), "P9", True)


def test_legal_added_vendor_uses_given_values():
    state = State(legal_added=[{"vendor": "Firm C", "vendor_id": "LC", "amount": "5000", "gl": "61500",
                                "item": "I-LEGAL", "dept": "D1", "location": "L1"}])
    res = legal.build(LEGAL_ROWS, config(), state)
    assert res["rows"][-1]["added"] and res["total"] == D("66250.00")


def test_legal_split_validation():
    with pytest.raises(ValidationError):
        legal.validate_split([{"amount": "1", "gl": "61500"}])                       # one line
    with pytest.raises(ValidationError):
        legal.validate_split([{"amount": "1", "gl": "6150"}, {"amount": "1", "gl": "61500"}])  # 4-digit GL


# ---------- capex ----------

TRACKER = [
    capex_row("Deal A", "P1", "VC1", "Framing", 120000, 118000, 100, 100000),   # 18,000
    capex_row("Deal A", "P1", "VC1", "Ceilings", 40000, 42000, 50, 10000),      # 11,000
    capex_row("Deal B", "P2", "VC2", "Power", 90000, 95500, 40, 50000),         # -11,800
    capex_row("Deal B", "P2", "VC2", "Panel", 25000, 25000, 20, 0),             # 5,000
    capex_row("Deal B", "P2", "VC3", "Desk", None, None, None, 5000),           # blank -> 0
]


def test_capex_line_accrual():
    assert capex.line_accrual(D(118000), D(100), D(100000)) == D("18000.00")
    assert capex.line_accrual(D(95500), D(40), D(50000)) == D("-11800.00")
    assert capex.line_accrual(None, D(50), D(10)) == D(0)
    assert capex.line_accrual(D(1000), None, D(10)) == D(0)


def test_capex_netting_by_project_and_vendor_with_zero_floor():
    res = capex.build(TRACKER, {"unallocated_gl_total": "0"})
    groups = {(g["project_id"], g["vendor_id"]): g for g in res["groups"]}
    assert groups[("P1", "VC1")]["je_amount"] == D("29000.00")
    assert groups[("P2", "VC2")]["net"] == D("-6800.00")
    assert groups[("P2", "VC2")]["je_amount"] == D(0)
    assert [g["vendor_id"] for g in res["over_invoiced"]] == ["VC2"]
    assert groups[("P2", "VC3")]["je_amount"] == D(0)
    assert res["total"] == D("29000.00")
    assert res["not_final"] is False


def test_capex_deal_total_compares_cost_with_budget():
    deals = {d["deal"]: d for d in capex.build(TRACKER, {"unallocated_gl_total": "0"})["deals"]}
    assert deals["Deal A"]["status"] == "ties to budget"                 # 160,000 vs 160,000
    assert deals["Deal B"]["difference"] == D("5500.00")                 # 120,500 cost vs 115,000 budget
    assert deals["Deal B"]["status"] == "over by $5,500.00"


def test_capex_not_final_while_unallocated_gl_exists():
    assert capex.build(TRACKER, {"unallocated_gl_total": "4250"})["not_final"] is True
